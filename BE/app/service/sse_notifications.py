from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.repository.sse_notification import NotificationEventRepository
from app.service.realtime_observability import RealtimeObservabilityRegistry, realtime_observability
from app.util.database.redis import RedisManager


logger = logging.getLogger(__name__)


class SSEPublishError(RuntimeError):
    pass


class SSEPayloadError(ValueError):
    pass


class SSESubscriptionError(RuntimeError):
    pass


class SSEAckError(RuntimeError):
    pass


RedisGetter = Callable[[], Awaitable[Any]]


@dataclass
class WorkspaceListenerState:
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    failure: BaseException | None = None
    established: bool = False


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


class SseNotificationService:
    def __init__(
        self,
        *,
        redis_getter: RedisGetter | None = None,
        pubsub_getter: RedisGetter | None = None,
        repository: Any | None = None,
        observability: RealtimeObservabilityRegistry = realtime_observability,
        queue_maxsize: int | None = None,
        heartbeat_seconds: float | None = None,
        subscribe_ready_timeout: float | None = None,
        replay_limit: int | None = None,
    ) -> None:
        self.subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._listener_states: dict[str, WorkspaceListenerState] = {}
        self._lock = asyncio.Lock()
        self._redis_getter = redis_getter
        # Kept for test/backwards compatibility with the previous Pub/Sub implementation.
        self._pubsub_getter = pubsub_getter
        self._repository = repository if repository is not None else NotificationEventRepository()
        self._observability = observability
        self._queue_maxsize = queue_maxsize
        self._heartbeat_seconds = heartbeat_seconds
        self._subscribe_ready_timeout = subscribe_ready_timeout
        self._replay_limit = replay_limit

    @property
    def heartbeat_seconds(self) -> float:
        if self._heartbeat_seconds is not None:
            return max(0.1, self._heartbeat_seconds)
        return _env_float("SSE_HEARTBEAT_SECONDS", 15.0)

    @property
    def queue_maxsize(self) -> int:
        if self._queue_maxsize is not None:
            return max(1, self._queue_maxsize)
        return _env_int("SSE_QUEUE_MAXSIZE", 256)

    @property
    def subscribe_ready_timeout(self) -> float:
        if self._subscribe_ready_timeout is not None:
            return max(0.1, self._subscribe_ready_timeout)
        return _env_float("SSE_SUBSCRIBE_READY_TIMEOUT_SECONDS", 3.0)

    @property
    def replay_limit(self) -> int:
        if self._replay_limit is not None:
            return max(1, self._replay_limit)
        return _env_int("SSE_REPLAY_LIMIT", 500)

    @property
    def stream_block_ms(self) -> int:
        return max(100, int(_env_float("SSE_STREAM_BLOCK_SECONDS", 1.0) * 1000))

    def stream_for(self, workspace_id: str) -> str:
        return f"sse:notifications:{workspace_id}"

    def channel_for(self, workspace_id: str) -> str:
        return self.stream_for(workspace_id)

    async def _get_redis(self) -> Any:
        if self._redis_getter is not None:
            return await self._redis_getter()
        return await RedisManager.get_redis()

    async def subscribe(self, workspace_id: str) -> asyncio.Queue[dict[str, Any]]:
        workspace_key = str(workspace_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_maxsize)
        async with self._lock:
            queues = self.subscribers.setdefault(workspace_key, set())
            queues.add(queue)
            self._observability.set_sse_subscribers(workspace_key, len(queues))
            state = self._ensure_listener_locked(workspace_key)

        try:
            await asyncio.wait_for(state.ready.wait(), timeout=self.subscribe_ready_timeout)
        except asyncio.TimeoutError as exc:
            await self.unsubscribe(workspace_key, queue)
            self._observability.record_sse_listener_failure()
            raise SSESubscriptionError("SSE Redis Streams readiness timed out") from exc

        if state.failure is not None:
            await self.unsubscribe(workspace_key, queue)
            raise SSESubscriptionError("SSE Redis Streams listener failed") from state.failure
        return queue

    async def unsubscribe(self, workspace_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        workspace_key = str(workspace_id)
        task_to_cancel: asyncio.Task[None] | None = None
        async with self._lock:
            queues = self.subscribers.get(workspace_key)
            if queues is not None:
                queues.discard(queue)
                if not queues:
                    del self.subscribers[workspace_key]
                    state = self._listener_states.pop(workspace_key, None)
                    if state is not None:
                        task_to_cancel = state.task
                self._observability.set_sse_subscribers(
                    workspace_key,
                    len(self.subscribers.get(workspace_key, set())),
                )

        if task_to_cancel is not None:
            task_to_cancel.cancel()
            try:
                await task_to_cancel
            except asyncio.CancelledError:
                pass

    async def publish(
        self,
        workspace_id: str,
        payload: dict[str, Any],
        *,
        publisher_user_id: str | None = None,
    ) -> dict[str, Any]:
        workspace_key = str(workspace_id)
        event_payload = self._payload_with_measurement_fields(payload)
        event_id = str(event_payload["event_id"])
        event_type = str(event_payload["type"])
        tab_id = self._payload_tab_id(event_payload)
        recipient_user_id, recipient_scope = self._payload_recipient(event_payload)

        try:
            event_record, inserted = self._repository.insert_event(
                event_id=event_id,
                workspace_id=int(workspace_key),
                recipient_user_id=recipient_user_id,
                recipient_scope=recipient_scope,
                event_type=event_type,
                tab_id=tab_id,
                payload=event_payload,
            )
        except Exception as exc:
            logger.warning(
                "sse_outbox_insert_failed",
                extra={"workspace_id": workspace_key, "exception_type": type(exc).__name__},
            )
            raise SSEPublishError("SSE outbox insert failed") from exc

        if not inserted:
            self._observability.record_sse_duplicate_deduped()
            return dict(event_record["payload"])

        self._observability.record_sse_outbox_inserted()
        self._refresh_pending_outbox_count()

        try:
            await self._xadd_event(workspace_key, event_payload)
            self._repository.mark_published(event_id)
            self._observability.record_sse_stream_xadd(failed=False)
            self._observability.record_sse_outbox_published()
            self._refresh_pending_outbox_count()
            return event_payload
        except Exception as exc:
            self._observability.record_sse_stream_xadd(failed=True)
            try:
                self._repository.mark_failed(event_id)
            except Exception:
                logger.warning(
                    "sse_outbox_mark_failed_failed",
                    extra={"workspace_id": workspace_key, "event_id": event_id},
                )
            self._observability.record_sse_outbox_failed()
            self._refresh_pending_outbox_count()
            logger.warning(
                "sse_stream_xadd_failed",
                extra={"workspace_id": workspace_key, "exception_type": type(exc).__name__},
            )
            raise SSEPublishError("SSE Redis Streams XADD failed") from exc

    async def acknowledge(self, *, workspace_id: str, user_id: str, last_event_id: str) -> dict[str, Any]:
        if not last_event_id:
            raise SSEAckError("last_event_id is required")
        try:
            updated = self._repository.ack_event(
                user_id=user_id,
                workspace_id=int(workspace_id),
                event_id=str(last_event_id),
            )
        except Exception as exc:
            raise SSEAckError("SSE notification ack failed") from exc
        if updated:
            self._observability.record_sse_ack_update()
        return {
            "status": "acked",
            "workspace_id": int(workspace_id),
            "last_event_id": str(last_event_id),
            "updated": bool(updated),
        }

    async def event_generator(
        self,
        request: Any,
        workspace_id: str,
        *,
        user_id: str | None = None,
        last_event_id: str | None = None,
    ):
        queue = await self.subscribe(str(workspace_id))
        generator = self.stream(
            request,
            str(workspace_id),
            queue,
            user_id=user_id,
            last_event_id=last_event_id,
        )
        try:
            async for frame in generator:
                yield frame
        finally:
            await generator.aclose()

    async def stream(
        self,
        request: Any,
        workspace_id: str,
        queue: asyncio.Queue[dict[str, Any]],
        *,
        user_id: str | None = None,
        last_event_id: str | None = None,
    ):
        workspace_key = str(workspace_id)
        sent_event_ids: set[str] = set()
        try:
            if user_id:
                replay_cursor = last_event_id or self._repository.get_last_acked_event_id(
                    user_id=user_id,
                    workspace_id=int(workspace_key),
                )
                for event in self._repository.list_events_after(
                    workspace_id=int(workspace_key),
                    user_id=user_id,
                    after_event_id=replay_cursor,
                    limit=self.replay_limit,
                ):
                    payload = dict(event["payload"])
                    payload["replayed"] = True
                    event_id = str(payload.get("event_id") or event["event_id"])
                    sent_event_ids.add(event_id)
                    self._observability.record_sse_replayed_event()
                    yield self._format_sse_frame(payload)
                    await asyncio.sleep(0)

            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=self.heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield "event: ping\n"
                    yield "data: p\n\n"
                else:
                    event_id = payload.get("event_id")
                    if event_id and str(event_id) in sent_event_ids:
                        self._observability.record_sse_duplicate_deduped()
                        continue
                    if event_id:
                        sent_event_ids.add(str(event_id))
                    yield self._format_sse_frame(payload)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        finally:
            await self.unsubscribe(workspace_key, queue)

    async def deliver_local(self, workspace_id: str, payload: dict[str, Any]) -> None:
        workspace_key = str(workspace_id)
        queues = list(self.subscribers.get(workspace_key, set()))
        failures = 0
        queue_drops = 0
        max_queue_depth = 0
        for queue in queues:
            try:
                queue.put_nowait(payload)
                max_queue_depth = max(max_queue_depth, queue.qsize())
            except asyncio.QueueFull:
                failures += 1
                queue_drops += 1
            except Exception:
                failures += 1

        self._observability.record_sse_delivery(
            workspace_key,
            target_count=len(queues),
            queue_put_failures=failures,
            max_queue_depth=max_queue_depth,
            queue_drops=queue_drops,
        )

        if failures:
            logger.warning(
                "sse_local_delivery_failed",
                extra={
                    "workspace_id": workspace_key,
                    "target_count": len(queues),
                    "queue_put_failures": failures,
                    "queue_drops": queue_drops,
                },
            )

    def _payload_with_measurement_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SSEPayloadError("SSE notification payload must be a JSON object")
        event_payload = dict(payload)
        event_type = event_payload.get("type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise SSEPayloadError("SSE notification payload requires a string type")
        event_payload["type"] = event_type.strip()
        event_payload.setdefault("event_id", uuid.uuid4().hex)
        event_payload["event_id"] = str(event_payload["event_id"])
        event_payload.setdefault("published_at_ms", int(time.time() * 1000))
        self._payload_tab_id(event_payload)
        return event_payload

    def _payload_tab_id(self, payload: dict[str, Any]) -> int | None:
        raw_tab_id = payload.get("tab_id")
        if raw_tab_id in (None, ""):
            return None
        try:
            return int(raw_tab_id)
        except (TypeError, ValueError) as exc:
            raise SSEPayloadError("SSE notification tab_id must be numeric when present") from exc

    def _payload_recipient(self, payload: dict[str, Any]) -> tuple[str | None, str]:
        recipient_user_id = payload.get("recipient_user_id")
        if recipient_user_id:
            try:
                uuid.UUID(str(recipient_user_id))
            except (TypeError, ValueError) as exc:
                raise SSEPayloadError("SSE notification recipient_user_id must be a UUID") from exc
            return str(recipient_user_id), "user"
        recipient_scope = str(payload.get("recipient_scope") or "workspace")
        return None, recipient_scope

    async def _xadd_event(self, workspace_id: str, payload: dict[str, Any]) -> Any:
        redis_client = await self._get_redis()
        kwargs: dict[str, Any] = {}
        maxlen = int(os.getenv("SSE_STREAM_MAXLEN", "0") or "0")
        if maxlen > 0:
            kwargs = {"maxlen": maxlen, "approximate": True}
        return await redis_client.xadd(
            self.stream_for(workspace_id),
            {
                "event_id": str(payload["event_id"]),
                "data": json.dumps(payload, ensure_ascii=False),
            },
            **kwargs,
        )

    def _ensure_listener_locked(self, workspace_id: str) -> WorkspaceListenerState:
        existing = self._listener_states.get(workspace_id)
        if existing is not None and existing.task is not None and not existing.task.done():
            return existing

        state = WorkspaceListenerState()
        is_restart = existing is not None
        state.task = asyncio.create_task(self._redis_stream_listener(workspace_id, state))
        self._listener_states[workspace_id] = state
        self._observability.record_sse_listener_start(restart=is_restart)
        return state

    async def _redis_stream_listener(self, workspace_id: str, state: WorkspaceListenerState) -> None:
        stream_name = self.stream_for(workspace_id)
        last_id = "$"
        failed_after_ready = False
        try:
            redis_client = await self._get_redis()
            state.established = True
            state.ready.set()

            while True:
                messages = await redis_client.xread(
                    {stream_name: last_id},
                    count=100,
                    block=self.stream_block_ms,
                )
                for _stream, entries in messages or []:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        payload = self._decode_stream_fields(fields)
                        if payload is None:
                            continue
                        self._observability.record_sse_stream_message()
                        await self.deliver_local(workspace_id, payload)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.failure = exc
            failed_after_ready = state.established
            state.ready.set()
            self._observability.record_sse_listener_failure()
            logger.warning(
                "sse_redis_stream_listener_failed",
                extra={"workspace_id": workspace_id, "exception_type": type(exc).__name__},
            )
        finally:
            if failed_after_ready:
                await self._restart_listener_if_needed(workspace_id, state)
            else:
                async with self._lock:
                    if self._listener_states.get(workspace_id) is state:
                        self._listener_states.pop(workspace_id, None)

    async def _restart_listener_if_needed(
        self,
        workspace_id: str,
        failed_state: WorkspaceListenerState,
    ) -> None:
        await asyncio.sleep(_env_float("SSE_LISTENER_RESTART_DELAY_SECONDS", 1.0))
        async with self._lock:
            if self._listener_states.get(workspace_id) is not failed_state:
                return
            if not self.subscribers.get(workspace_id):
                self._listener_states.pop(workspace_id, None)
                return
            state = WorkspaceListenerState()
            state.task = asyncio.create_task(self._redis_stream_listener(workspace_id, state))
            self._listener_states[workspace_id] = state
            self._observability.record_sse_listener_start(restart=True)

    def _decode_stream_fields(self, fields: Any) -> dict[str, Any] | None:
        if not isinstance(fields, dict):
            return None
        normalized: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            normalized[str(key)] = value

        raw_data = normalized.get("data") or normalized.get("payload")
        if isinstance(raw_data, dict):
            return raw_data
        if raw_data is None:
            return normalized
        try:
            payload = json.loads(str(raw_data))
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _format_sse_frame(self, payload: dict[str, Any]) -> str:
        event_type = str(payload.get("type", "message"))
        event_id = payload.get("event_id")
        frame = ""
        if event_id:
            frame += f"id: {event_id}\n"
        frame += f"event: {event_type}\n"
        frame += f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        return frame

    def _refresh_pending_outbox_count(self) -> None:
        pending_count = None
        try:
            pending_count = self._repository.pending_count()
        except Exception:
            return
        if pending_count is not None:
            self._observability.set_sse_pending_outbox_count(int(pending_count))

    async def reset_for_test(self) -> None:
        async with self._lock:
            workspace_ids = list(self.subscribers.keys())
            states = list(self._listener_states.values())
            self.subscribers.clear()
            self._listener_states.clear()
            for workspace_id in workspace_ids:
                self._observability.set_sse_subscribers(workspace_id, 0)

        for state in states:
            if state.task is not None:
                state.task.cancel()
                try:
                    await state.task
                except asyncio.CancelledError:
                    pass


sse_notification_service = SseNotificationService()
