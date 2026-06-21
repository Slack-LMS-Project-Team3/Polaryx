from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from app.service.realtime_observability import RealtimeObservabilityRegistry, realtime_observability


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class MessagePersistenceItem:
    workspace_id: int
    tab_id: int
    sender_id: str
    content: str
    file_url: str | None
    temp_message_id: str
    accepted_at: float
    perf_id: str | None = None
    attempt: int = 1


@dataclass(frozen=True)
class MessagePersistenceEnqueueResult:
    accepted: bool
    code: str | None = None
    retryable: bool = True
    queue_depth: int = 0


class MessagePersistenceService:
    def __init__(
        self,
        *,
        message_service: Any | None = None,
        observability: RealtimeObservabilityRegistry = realtime_observability,
        queue_maxsize: int | None = None,
        worker_count: int | None = None,
        workers_enabled: bool | None = None,
        enqueue_timeout_seconds: float | None = None,
        shutdown_timeout_seconds: float | None = None,
    ) -> None:
        self._message_service = message_service
        self._observability = observability
        self._queue_maxsize = queue_maxsize
        self._worker_count = worker_count
        self._workers_enabled = workers_enabled
        self._enqueue_timeout_seconds = enqueue_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._queue: asyncio.Queue[MessagePersistenceItem] | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = False

    @property
    def queue_maxsize(self) -> int:
        if self._queue_maxsize is not None:
            return max(1, int(self._queue_maxsize))
        return _env_int("MESSAGE_PERSISTENCE_QUEUE_MAXSIZE", 1000, minimum=1)

    @property
    def worker_count(self) -> int:
        if self._worker_count is not None:
            return max(1, int(self._worker_count))
        return _env_int("MESSAGE_PERSISTENCE_WORKER_COUNT", 2, minimum=1)

    @property
    def workers_enabled(self) -> bool:
        if self._workers_enabled is not None:
            return bool(self._workers_enabled)
        return _env_bool("MESSAGE_PERSISTENCE_WORKERS_ENABLED", True)

    @property
    def enqueue_timeout_seconds(self) -> float:
        if self._enqueue_timeout_seconds is not None:
            return max(0.0, float(self._enqueue_timeout_seconds))
        return _env_float("MESSAGE_PERSISTENCE_ENQUEUE_TIMEOUT_SECONDS", 0.0)

    @property
    def shutdown_timeout_seconds(self) -> float:
        if self._shutdown_timeout_seconds is not None:
            return max(0.0, float(self._shutdown_timeout_seconds))
        return _env_float("MESSAGE_PERSISTENCE_SHUTDOWN_TIMEOUT_SECONDS", 10.0)

    def _ensure_queue(self) -> asyncio.Queue[MessagePersistenceItem]:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.queue_maxsize)
            self._observability.set_message_persistence_queue_depth(0)
        return self._queue

    def _message_service_instance(self) -> Any:
        if self._message_service is None:
            from app.service.message import MessageService

            self._message_service = MessageService()
        return self._message_service

    def _live_tasks(self) -> list[asyncio.Task[None]]:
        return [task for task in self._tasks if not task.done()]

    def _workers_available(self) -> bool:
        if not self.workers_enabled:
            return False
        self._tasks = self._live_tasks()
        return bool(self._tasks)

    async def enqueue(
        self,
        *,
        workspace_id: int,
        tab_id: int,
        sender_id: str,
        content: str,
        file_url: str | None,
        temp_message_id: str,
        accepted_at: float | None = None,
        perf_id: str | None = None,
    ) -> MessagePersistenceEnqueueResult:
        queue = self._ensure_queue()
        if self._stopping:
            queue_depth = queue.qsize()
            self._observability.record_message_persistence_enqueue(success=False, queue_depth=queue_depth)
            return MessagePersistenceEnqueueResult(
                accepted=False,
                code="persistence_service_stopping",
                retryable=True,
                queue_depth=queue_depth,
            )
        if not self._workers_available():
            queue_depth = queue.qsize()
            self._observability.record_message_persistence_enqueue(success=False, queue_depth=queue_depth)
            logger.warning(
                "message_persistence_workers_unavailable",
                extra={
                    "workspace_id": int(workspace_id),
                    "tab_id": int(tab_id),
                    "temp_message_id": str(temp_message_id),
                    "queue_depth": queue_depth,
                },
            )
            return MessagePersistenceEnqueueResult(
                accepted=False,
                code="persistence_workers_unavailable",
                retryable=True,
                queue_depth=queue_depth,
            )

        item = MessagePersistenceItem(
            workspace_id=int(workspace_id),
            tab_id=int(tab_id),
            sender_id=str(sender_id),
            content=str(content),
            file_url=file_url,
            temp_message_id=str(temp_message_id),
            accepted_at=time.perf_counter() if accepted_at is None else float(accepted_at),
            perf_id=str(perf_id) if perf_id else None,
        )

        try:
            timeout = self.enqueue_timeout_seconds
            if timeout > 0:
                await asyncio.wait_for(queue.put(item), timeout=timeout)
            else:
                queue.put_nowait(item)
        except (asyncio.QueueFull, asyncio.TimeoutError):
            queue_depth = queue.qsize()
            self._observability.record_message_persistence_enqueue(
                success=False,
                queue_depth=queue_depth,
                full=True,
            )
            logger.warning(
                "message_persistence_queue_full",
                extra={
                    "workspace_id": int(workspace_id),
                    "tab_id": int(tab_id),
                    "temp_message_id": str(temp_message_id),
                    "queue_depth": queue_depth,
                    "queue_maxsize": queue.maxsize,
                },
            )
            return MessagePersistenceEnqueueResult(
                accepted=False,
                code="persistence_queue_full",
                retryable=True,
                queue_depth=queue_depth,
            )

        queue_depth = queue.qsize()
        self._observability.record_message_persistence_enqueue(success=True, queue_depth=queue_depth)
        return MessagePersistenceEnqueueResult(accepted=True, queue_depth=queue_depth)

    async def start_workers_if_enabled(self) -> None:
        self._tasks = self._live_tasks()
        if not self.workers_enabled or self._tasks:
            self._observability.set_message_persistence_active_workers(len(self._tasks))
            return
        self._stopping = False
        self._ensure_queue()
        for index in range(self.worker_count):
            self._tasks.append(asyncio.create_task(self._worker_loop(index + 1)))
        self._observability.set_message_persistence_active_workers(len(self._tasks))

    async def stop_workers(self) -> None:
        if not self._tasks:
            self._observability.set_message_persistence_active_workers(0)
            return
        self._stopping = True
        tasks = list(self._tasks)
        drain_timed_out = False
        try:
            await asyncio.wait_for(self.join(), timeout=self.shutdown_timeout_seconds)
        except asyncio.TimeoutError:
            drain_timed_out = True
            self._observability.record_message_persistence_shutdown_drain_timeout()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if drain_timed_out:
                self._drain_pending_items(reason="shutdown_drain_timeout")
            self._tasks.clear()
            self._observability.set_message_persistence_active_workers(0)
            queue = self._ensure_queue()
            self._observability.set_message_persistence_queue_depth(queue.qsize())
            self._stopping = False

    async def reset_for_test(self) -> None:
        await self.stop_workers()
        self._queue = asyncio.Queue(maxsize=self.queue_maxsize)
        self._observability.set_message_persistence_queue_depth(0)

    async def join(self) -> None:
        queue = self._ensure_queue()
        await queue.join()

    def _drain_pending_items(self, *, reason: str) -> int:
        queue = self._ensure_queue()
        dropped = 0
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            dropped += 1
            logger.warning(
                "message_persistence_item_dropped",
                extra={
                    "workspace_id": item.workspace_id,
                    "tab_id": item.tab_id,
                    "temp_message_id": item.temp_message_id,
                    "reason": reason,
                    "perf_id": item.perf_id,
                },
            )
            queue.task_done()
        if dropped:
            self._observability.record_message_persistence_dropped(dropped)
            self._observability.set_message_persistence_queue_depth(queue.qsize())
        return dropped

    async def _worker_loop(self, worker_index: int) -> None:
        queue = self._ensure_queue()
        while True:
            item: MessagePersistenceItem | None = None
            try:
                item = await queue.get()
                await self._process_item(item, worker_index)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if item is not None:
                    self._record_failed_item(item, exc, started_at=item.accepted_at)
            finally:
                if item is not None:
                    queue.task_done()
                    self._observability.set_message_persistence_queue_depth(queue.qsize())

    async def _process_item(self, item: MessagePersistenceItem, worker_index: int) -> None:
        queue_wait_seconds = time.perf_counter() - item.accepted_at
        self._observability.record_message_persistence_worker_save_started(
            queue_wait_seconds=queue_wait_seconds,
        )
        save_started_at = time.perf_counter()
        try:
            save_coro = self._message_service_instance().save_message(
                item.tab_id,
                item.sender_id,
                item.content,
                item.file_url,
            )
            real_message_id = await save_coro
            save_duration_seconds = time.perf_counter() - save_started_at
            visibility_lag_seconds = time.perf_counter() - item.accepted_at
            self._observability.record_message_persistence_save_success(
                queue_wait_seconds=queue_wait_seconds,
                save_duration_seconds=save_duration_seconds,
                visibility_lag_seconds=visibility_lag_seconds,
            )
            logger.info(
                "message_persistence_save_success",
                extra={
                    "workspace_id": item.workspace_id,
                    "tab_id": item.tab_id,
                    "temp_message_id": item.temp_message_id,
                    "real_message_id": real_message_id,
                    "worker_index": worker_index,
                    "queue_wait_seconds": queue_wait_seconds,
                    "save_duration_seconds": save_duration_seconds,
                    "visibility_lag_seconds": visibility_lag_seconds,
                    "perf_id": item.perf_id,
                },
            )
        except asyncio.CancelledError:
            save_duration_seconds = time.perf_counter() - save_started_at
            visibility_lag_seconds = time.perf_counter() - item.accepted_at
            self._observability.record_message_persistence_save_failure(
                queue_wait_seconds=queue_wait_seconds,
                save_duration_seconds=save_duration_seconds,
                visibility_lag_seconds=visibility_lag_seconds,
            )
            logger.warning(
                "message_persistence_worker_cancelled",
                extra={
                    "workspace_id": item.workspace_id,
                    "tab_id": item.tab_id,
                    "temp_message_id": item.temp_message_id,
                    "worker_index": worker_index,
                    "queue_wait_seconds": queue_wait_seconds,
                    "save_duration_seconds": save_duration_seconds,
                    "perf_id": item.perf_id,
                },
            )
            raise
        except Exception as exc:
            save_duration_seconds = time.perf_counter() - save_started_at
            visibility_lag_seconds = time.perf_counter() - item.accepted_at
            self._observability.record_message_persistence_save_failure(
                queue_wait_seconds=queue_wait_seconds,
                save_duration_seconds=save_duration_seconds,
                visibility_lag_seconds=visibility_lag_seconds,
            )
            logger.warning(
                "message_persistence_save_failed",
                extra={
                    "workspace_id": item.workspace_id,
                    "tab_id": item.tab_id,
                    "temp_message_id": item.temp_message_id,
                    "exception_type": type(exc).__name__,
                    "worker_index": worker_index,
                    "queue_wait_seconds": queue_wait_seconds,
                    "save_duration_seconds": save_duration_seconds,
                    "visibility_lag_seconds": visibility_lag_seconds,
                    "perf_id": item.perf_id,
                },
            )

    def _record_failed_item(self, item: MessagePersistenceItem, exc: Exception, *, started_at: float) -> None:
        visibility_lag_seconds = time.perf_counter() - item.accepted_at
        self._observability.record_message_persistence_save_failure(
            queue_wait_seconds=None,
            save_duration_seconds=max(0.0, time.perf_counter() - started_at),
            visibility_lag_seconds=visibility_lag_seconds,
        )
        logger.warning(
            "message_persistence_worker_loop_failed",
            extra={
                "workspace_id": item.workspace_id,
                "tab_id": item.tab_id,
                "temp_message_id": item.temp_message_id,
                "exception_type": type(exc).__name__,
                "perf_id": item.perf_id,
            },
        )


message_persistence_service = MessagePersistenceService()
