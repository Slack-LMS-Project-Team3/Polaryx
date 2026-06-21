from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.service.push import PushSendSummary, PushService
from app.service.realtime_observability import RealtimeObservabilityRegistry, realtime_observability
from app.util.database.redis import RedisManager


logger = logging.getLogger(__name__)

RedisGetter = Callable[[], Awaitable[Any]]


class PushDispatchEnqueueError(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PushDispatchJob:
    job_id: str
    workspace_id: int
    tab_id: int
    sender_id: str
    content: str
    url: str
    created_at_ms: int
    attempt: int = 1
    perf_id: str | None = None

    def provider_payload(self, *, title: str, body: str) -> dict[str, str]:
        return {
            "title": title,
            "body": body,
            "url": self.url,
        }


@dataclass(frozen=True)
class PushRecipientContext:
    recipient_ids: list[str]
    title: str
    body: str


class PushDispatchService:
    def __init__(
        self,
        *,
        redis_getter: RedisGetter | None = None,
        push_service: PushService | None = None,
        tab_service: object | None = None,
        workspace_member_service: object | None = None,
        observability: RealtimeObservabilityRegistry = realtime_observability,
        stream_name: str | None = None,
        group_name: str | None = None,
        consumer_name_prefix: str | None = None,
        dead_letter_stream: str | None = None,
    ) -> None:
        self._redis_getter = redis_getter
        self._push_service = push_service if push_service is not None else PushService()
        self._tab_service = tab_service
        self._workspace_member_service = workspace_member_service
        self._observability = observability
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name_prefix = consumer_name_prefix
        self._dead_letter_stream = dead_letter_stream
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = False

    @property
    def stream_name(self) -> str:
        return self._stream_name or os.getenv("PUSH_STREAM_NAME", "push:notifications")

    @property
    def group_name(self) -> str:
        return self._group_name or os.getenv("PUSH_CONSUMER_GROUP", "polaryx-push-dispatchers")

    @property
    def dead_letter_stream(self) -> str:
        return self._dead_letter_stream or os.getenv("PUSH_DEAD_LETTER_STREAM", "push:notifications:dead")

    @property
    def maxlen(self) -> int:
        return _env_int("PUSH_STREAM_MAXLEN", 10000, minimum=1)

    @property
    def batch_size(self) -> int:
        return _env_int("PUSH_WORKER_BATCH_SIZE", 50, minimum=1)

    @property
    def stream_block_ms(self) -> int:
        return max(100, int(_env_float("PUSH_STREAM_BLOCK_SECONDS", 1.0) * 1000))

    @property
    def redis_timeout_seconds(self) -> float:
        return _env_float("PUSH_REDIS_TIMEOUT_SECONDS", 2.0)

    @property
    def max_attempts(self) -> int:
        return _env_int("PUSH_MAX_ATTEMPTS", 3, minimum=1)

    @property
    def retry_delay_seconds(self) -> float:
        return _env_float("PUSH_RETRY_DELAY_SECONDS", 1.0)

    @property
    def worker_count(self) -> int:
        return _env_int("PUSH_WORKER_COUNT", 1, minimum=1)

    @property
    def workers_enabled(self) -> bool:
        return _env_bool("PUSH_DISPATCH_WORKERS_ENABLED", True)

    @property
    def shutdown_timeout_seconds(self) -> float:
        return _env_float("PUSH_WORKER_SHUTDOWN_TIMEOUT_SECONDS", 10.0)

    @property
    def pending_idle_ms(self) -> int:
        return max(1000, int(_env_float("PUSH_PENDING_IDLE_SECONDS", 30.0) * 1000))

    @property
    def queue_depth_sample_rate(self) -> float:
        return min(1.0, _env_float("PUSH_QUEUE_DEPTH_SAMPLE_RATE", 0.0))

    @property
    def delete_after_ack(self) -> bool:
        return _env_bool("PUSH_DELETE_AFTER_ACK", True)

    async def _get_redis(self) -> Any:
        if self._redis_getter is not None:
            return await self._redis_getter()
        return await RedisManager.get_redis()

    async def enqueue_notification(
        self,
        *,
        workspace_id: int,
        tab_id: int,
        sender_id: str,
        content: str,
        url: str,
        perf_id: str | None = None,
    ) -> dict[str, Any]:
        job = PushDispatchJob(
            job_id=uuid.uuid4().hex,
            workspace_id=int(workspace_id),
            tab_id=int(tab_id),
            sender_id=str(sender_id),
            content=str(content),
            url=str(url),
            created_at_ms=int(time.time() * 1000),
            attempt=1,
            perf_id=str(perf_id) if perf_id else None,
        )
        fields = self._fields_for_job(job)

        try:
            redis_client = await self._get_redis()
            stream_id = await asyncio.wait_for(
                redis_client.xadd(
                    self.stream_name,
                    fields,
                    maxlen=self.maxlen,
                    approximate=True,
                ),
                timeout=self.redis_timeout_seconds,
            )
            stream_length = await self._sample_stream_length(redis_client)
            self._observability.record_push_enqueue(success=True, stream_length=stream_length)
            return {
                "status": "queued",
                "job_id": job.job_id,
                "stream_id": str(stream_id),
                "recipient_count": None,
                "recipient_count_status": "deferred",
            }
        except Exception as exc:
            self._observability.record_push_enqueue(success=False)
            logger.warning(
                "push_enqueue_failed",
                extra={
                    "workspace_id": int(workspace_id),
                    "tab_id": int(tab_id),
                    "exception_type": type(exc).__name__,
                },
            )
            raise PushDispatchEnqueueError("Web Push enqueue failed") from exc

    async def start_workers_if_enabled(self) -> None:
        if not self.workers_enabled or self._tasks:
            return
        redis_client = await self._get_redis()
        await self._ensure_group(redis_client)
        self._stopping = False
        prefix = self._consumer_name_prefix or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        for index in range(self.worker_count):
            consumer_name = f"{prefix}-{index + 1}"
            self._tasks.append(asyncio.create_task(self._worker_loop(consumer_name)))

    async def stop_workers(self) -> None:
        if not self._tasks:
            return
        self._stopping = True
        tasks = list(self._tasks)
        self._tasks.clear()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), self.shutdown_timeout_seconds)
        except asyncio.TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reset_for_test(self) -> None:
        await self.stop_workers()

    async def _worker_loop(self, consumer_name: str) -> None:
        redis_client = await self._get_redis()
        await self._ensure_group(redis_client)
        while not self._stopping:
            try:
                entries = await self._recover_pending(redis_client, consumer_name)
                if not entries:
                    entries = await self._read_group(redis_client, consumer_name, "0", block_ms=0)
                if not entries:
                    entries = await self._read_group(redis_client, consumer_name, ">", block_ms=self.stream_block_ms)
                for entry_id, fields in entries:
                    if self._stopping:
                        break
                    await self._process_entry(redis_client, entry_id, fields)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "push_worker_loop_failed",
                    extra={"consumer": consumer_name, "exception_type": type(exc).__name__},
                )
                await asyncio.sleep(1)

    async def _ensure_group(self, redis_client: Any) -> None:
        try:
            await redis_client.xgroup_create(
                self.stream_name,
                self.group_name,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _read_group(
        self,
        redis_client: Any,
        consumer_name: str,
        stream_id: str,
        *,
        block_ms: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        messages = await redis_client.xreadgroup(
            self.group_name,
            consumer_name,
            {self.stream_name: stream_id},
            count=self.batch_size,
            block=block_ms,
        )
        return self._flatten_stream_messages(messages)

    async def _recover_pending(self, redis_client: Any, consumer_name: str) -> list[tuple[str, dict[str, Any]]]:
        if not hasattr(redis_client, "xautoclaim"):
            return []
        try:
            result = await redis_client.xautoclaim(
                self.stream_name,
                self.group_name,
                consumer_name,
                min_idle_time=self.pending_idle_ms,
                start_id="0-0",
                count=self.batch_size,
            )
        except Exception as exc:
            logger.warning(
                "push_pending_recovery_failed",
                extra={"consumer": consumer_name, "exception_type": type(exc).__name__},
            )
            return []
        if not isinstance(result, (list, tuple)) or len(result) < 2:
            return []
        return [(str(entry_id), self._normalize_fields(fields)) for entry_id, fields in result[1]]

    async def _process_entry(self, redis_client: Any, entry_id: str, fields: dict[str, Any]) -> None:
        normalized = self._normalize_fields(fields)
        try:
            job = self._decode_job(normalized)
        except Exception as exc:
            self._observability.record_push_job_read()
            self._observability.record_push_drop()
            await self._drop_to_dead_letter(redis_client, entry_id, normalized, reason="decode_error")
            logger.warning(
                "push_job_decode_failed",
                extra={"entry_id": entry_id, "exception_type": type(exc).__name__},
            )
            return

        lag_seconds = max(0.0, (time.time() * 1000 - job.created_at_ms) / 1000)
        self._observability.record_push_job_read(lag_seconds=lag_seconds)

        try:
            recipient_context = await asyncio.to_thread(self._build_recipient_context, job)
            self._observability.record_push_recipient_lookup(
                success=True,
                recipient_count=len(recipient_context.recipient_ids),
            )
        except Exception as exc:
            self._observability.record_push_recipient_lookup(success=False)
            logger.warning(
                "push_recipient_lookup_failed",
                extra={
                    "job_id": job.job_id,
                    "workspace_id": job.workspace_id,
                    "tab_id": job.tab_id,
                    "attempt": job.attempt,
                    "exception_type": type(exc).__name__,
                },
            )
            await self._retry_or_drop(redis_client, entry_id, normalized, job)
            return

        try:
            summary = await self._push_service.send_push_to(
                recipient_context.recipient_ids,
                job.provider_payload(
                    title=recipient_context.title,
                    body=recipient_context.body,
                ),
            )
        except Exception as exc:
            summary = PushSendSummary(
                attempted=len(recipient_context.recipient_ids),
                succeeded=0,
                failed=len(recipient_context.recipient_ids),
            )
            logger.warning(
                "push_provider_batch_failed",
                extra={
                    "job_id": job.job_id,
                    "workspace_id": job.workspace_id,
                    "tab_id": job.tab_id,
                    "attempt": job.attempt,
                    "exception_type": type(exc).__name__,
                },
            )

        self._observability.record_push_provider_result(
            attempts=summary.attempted,
            successes=summary.succeeded,
            failures=summary.failed,
            latency_seconds=summary.elapsed_seconds,
        )

        if summary.has_failures:
            await self._retry_or_drop(redis_client, entry_id, normalized, job)
            return

        await self._ack(redis_client, entry_id)

    async def _retry_or_drop(
        self,
        redis_client: Any,
        entry_id: str,
        fields: dict[str, Any],
        job: PushDispatchJob,
    ) -> None:
        if job.attempt >= self.max_attempts:
            self._observability.record_push_drop()
            await self._drop_to_dead_letter(redis_client, entry_id, fields, reason="max_attempts_exceeded")
            return

        retry_fields = dict(fields)
        retry_fields["attempt"] = str(job.attempt + 1)
        retry_fields["retry_after_ms"] = str(int((time.time() + self.retry_delay_seconds) * 1000))
        if self.retry_delay_seconds:
            await asyncio.sleep(self.retry_delay_seconds)
        await redis_client.xadd(
            self.stream_name,
            retry_fields,
            maxlen=self.maxlen,
            approximate=True,
        )
        self._observability.record_push_retry()
        await self._ack(redis_client, entry_id)

    async def _drop_to_dead_letter(
        self,
        redis_client: Any,
        entry_id: str,
        fields: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        dead_fields = dict(fields)
        dead_fields["drop_reason"] = reason
        dead_fields["dropped_at_ms"] = str(int(time.time() * 1000))
        await redis_client.xadd(
            self.dead_letter_stream,
            dead_fields,
            maxlen=self.maxlen,
            approximate=True,
        )
        self._observability.record_push_dead_letter()
        await self._ack(redis_client, entry_id)

    async def _ack(self, redis_client: Any, entry_id: str) -> None:
        await redis_client.xack(self.stream_name, self.group_name, entry_id)
        if self.delete_after_ack and hasattr(redis_client, "xdel"):
            try:
                await redis_client.xdel(self.stream_name, entry_id)
            except Exception as exc:
                logger.warning(
                    "push_ack_delete_failed",
                    extra={"entry_id": entry_id, "exception_type": type(exc).__name__},
                )
        stream_length = await self._sample_stream_length(redis_client)
        if stream_length is not None:
            self._observability.set_push_queue_depth(stream_length)

    async def _sample_stream_length(self, redis_client: Any) -> int | None:
        rate = self.queue_depth_sample_rate
        if rate <= 0:
            return None
        if rate < 1.0 and random.random() >= rate:
            return None
        return await self._stream_length(redis_client)

    async def _stream_length(self, redis_client: Any) -> int | None:
        try:
            return int(await redis_client.xlen(self.stream_name))
        except Exception:
            return None

    def _build_recipient_context(self, job: PushDispatchJob) -> PushRecipientContext:
        sender_uuid = UUID(job.sender_id)
        members = self._tab_service_instance().get_tab_members(job.workspace_id, job.tab_id)
        tab_info = self._tab_service_instance().find_tab(job.workspace_id, job.tab_id)
        sender_info = self._workspace_member_service_instance().get_member_by_user_id_simple(
            sender_uuid,
            job.workspace_id,
        )

        tab_name = self._first_cell(tab_info, 1, default="Polaryx")
        nickname = self._first_cell(sender_info, 0, default="Someone")
        recipient_ids = [
            str(member_uuid)
            for member_uuid in (self._uuid_from_member_row(row) for row in members or [])
            if member_uuid != sender_uuid
        ]
        return PushRecipientContext(
            recipient_ids=recipient_ids,
            title=str(tab_name),
            body=f"{nickname}: {job.content}",
        )

    def _tab_service_instance(self) -> Any:
        if self._tab_service is None:
            from app.service.tab import TabService

            self._tab_service = TabService()
        return self._tab_service

    def _workspace_member_service_instance(self) -> Any:
        if self._workspace_member_service is None:
            from app.service.workspace_member import WorkspaceMemberService

            self._workspace_member_service = WorkspaceMemberService()
        return self._workspace_member_service

    @staticmethod
    def _uuid_from_member_row(row: Any) -> UUID:
        value = row[0] if isinstance(row, (list, tuple)) else row
        if isinstance(value, bytes):
            return UUID(bytes=value)
        return UUID(str(value))

    @staticmethod
    def _first_cell(rows: Any, index: int, *, default: str) -> Any:
        if not rows:
            return default
        first = rows[0]
        if isinstance(first, (list, tuple)) and len(first) > index:
            return first[index]
        return default

    def _fields_for_job(self, job: PushDispatchJob) -> dict[str, str]:
        fields = {
            "job_id": job.job_id,
            "workspace_id": str(job.workspace_id),
            "tab_id": str(job.tab_id),
            "sender_id": job.sender_id,
            "content": job.content,
            "url": job.url,
            "created_at_ms": str(job.created_at_ms),
            "attempt": str(job.attempt),
        }
        if job.perf_id:
            fields["perf_id"] = job.perf_id
        return fields

    def _decode_job(self, fields: dict[str, Any]) -> PushDispatchJob:
        return PushDispatchJob(
            job_id=str(fields["job_id"]),
            workspace_id=int(fields["workspace_id"]),
            tab_id=int(fields["tab_id"]),
            sender_id=str(fields["sender_id"]),
            content=str(fields.get("content") or fields.get("body") or ""),
            url=str(fields.get("url") or ""),
            created_at_ms=int(fields["created_at_ms"]),
            attempt=int(fields.get("attempt") or 1),
            perf_id=str(fields["perf_id"]) if fields.get("perf_id") else None,
        )

    def _flatten_stream_messages(self, messages: Any) -> list[tuple[str, dict[str, Any]]]:
        entries: list[tuple[str, dict[str, Any]]] = []
        for _stream, stream_entries in messages or []:
            for entry_id, fields in stream_entries:
                entries.append((str(entry_id), self._normalize_fields(fields)))
        return entries

    def _normalize_fields(self, fields: Any) -> dict[str, Any]:
        if not isinstance(fields, dict):
            return {}
        normalized: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            normalized[str(key)] = value
        return normalized


push_dispatch_service = PushDispatchService()
