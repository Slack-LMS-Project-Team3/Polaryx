from __future__ import annotations

import asyncio
import unittest

from app.service.message_persistence import MessagePersistenceService
from app.service.realtime_observability import RealtimeObservabilityRegistry


class FakeMessageService:
    def __init__(self, *, result: int = 101, fail: Exception | None = None, delay: float = 0.0) -> None:
        self.result = result
        self.fail = fail
        self.delay = delay
        self.calls: list[tuple[int, str, str, str | None]] = []

    async def save_message(self, tab_id: int, sender_id: str, content: str, file_data: str | None) -> int:
        self.calls.append((tab_id, sender_id, content, file_data))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return self.result


class MessagePersistenceServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_success_is_bounded_and_worker_records_save_metrics(self) -> None:
        observability = RealtimeObservabilityRegistry()
        fake_service = FakeMessageService(result=2026)
        service = MessagePersistenceService(
            message_service=fake_service,
            observability=observability,
            queue_maxsize=2,
            worker_count=1,
            workers_enabled=True,
            shutdown_timeout_seconds=1.0,
        )

        await service.start_workers_if_enabled()
        try:
            result = await service.enqueue(
                workspace_id=1,
                tab_id=2,
                sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
                content="hello",
                file_url=None,
                temp_message_id="temp_1",
                perf_id="perf-1",
            )
            self.assertTrue(result.accepted)
            await asyncio.wait_for(service.join(), timeout=1)
        finally:
            await service.stop_workers()

        self.assertEqual(fake_service.calls, [(2, "05EA49CF-D91F-41A0-BE63-CACE1718DE71", "hello", None)])
        persistence = observability.snapshot()["persistence"]
        self.assertEqual(persistence["enqueue_attempts_total"], 1)
        self.assertEqual(persistence["enqueue_success_total"], 1)
        self.assertEqual(persistence["enqueue_failures_total"], 0)
        self.assertEqual(persistence["worker_saves_started_total"], 1)
        self.assertEqual(persistence["worker_save_success_total"], 1)
        self.assertEqual(persistence["message_save_success_total"], 1)
        self.assertEqual(persistence["message_save_failure_total"], 0)
        self.assertEqual(persistence["queue_wait_seconds"]["count"], 1)
        self.assertEqual(persistence["db_save_duration_seconds"]["count"], 1)
        self.assertEqual(persistence["db_visibility_lag_seconds"]["count"], 1)
        self.assertEqual(persistence["current_queue_depth"], 0)
        self.assertEqual(persistence["active_worker_count"], 0)

    async def test_queue_full_rejects_without_unbounded_task_fallback(self) -> None:
        observability = RealtimeObservabilityRegistry()
        service = MessagePersistenceService(
            message_service=FakeMessageService(),
            observability=observability,
            queue_maxsize=1,
            worker_count=1,
            workers_enabled=True,
        )
        worker_placeholder = asyncio.create_task(asyncio.Event().wait())
        service._tasks.append(worker_placeholder)

        try:
            first = await service.enqueue(
                workspace_id=1,
                tab_id=2,
                sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
                content="first",
                file_url=None,
                temp_message_id="temp_1",
            )
            second = await service.enqueue(
                workspace_id=1,
                tab_id=2,
                sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
                content="second",
                file_url=None,
                temp_message_id="temp_2",
            )
        finally:
            worker_placeholder.cancel()
            await asyncio.gather(worker_placeholder, return_exceptions=True)
            service._tasks.clear()

        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.code, "persistence_queue_full")
        self.assertTrue(second.retryable)
        persistence = observability.snapshot()["persistence"]
        self.assertEqual(persistence["enqueue_attempts_total"], 2)
        self.assertEqual(persistence["enqueue_success_total"], 1)
        self.assertEqual(persistence["enqueue_failures_total"], 1)
        self.assertEqual(persistence["queue_full_rejects_total"], 1)
        self.assertEqual(persistence["dropped_rejected_count_total"], 1)
        self.assertEqual(persistence["max_queue_depth"], 1)
        self.assertEqual(persistence["worker_saves_started_total"], 0)

    async def test_enqueue_rejects_when_workers_are_unavailable(self) -> None:
        observability = RealtimeObservabilityRegistry()
        service = MessagePersistenceService(
            message_service=FakeMessageService(),
            observability=observability,
            queue_maxsize=2,
            worker_count=1,
            workers_enabled=False,
        )

        result = await service.enqueue(
            workspace_id=1,
            tab_id=2,
            sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
            content="will not be persisted",
            file_url=None,
            temp_message_id="temp_unavailable",
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "persistence_workers_unavailable")
        persistence = observability.snapshot()["persistence"]
        self.assertEqual(persistence["enqueue_attempts_total"], 1)
        self.assertEqual(persistence["enqueue_success_total"], 0)
        self.assertEqual(persistence["enqueue_failures_total"], 1)
        self.assertEqual(persistence["queue_full_rejects_total"], 0)
        self.assertEqual(persistence["current_queue_depth"], 0)

    async def test_worker_save_failure_is_observable_without_logging_content(self) -> None:
        observability = RealtimeObservabilityRegistry()
        service = MessagePersistenceService(
            message_service=FakeMessageService(fail=RuntimeError("db unavailable")),
            observability=observability,
            queue_maxsize=2,
            worker_count=1,
            workers_enabled=True,
            shutdown_timeout_seconds=1.0,
        )

        await service.start_workers_if_enabled()
        try:
            result = await service.enqueue(
                workspace_id=1,
                tab_id=2,
                sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
                content="do not log this raw content",
                file_url=None,
                temp_message_id="temp_1",
            )
            self.assertTrue(result.accepted)
            await asyncio.wait_for(service.join(), timeout=1)
        finally:
            await service.stop_workers()

        persistence = observability.snapshot()["persistence"]
        self.assertEqual(persistence["worker_save_failure_total"], 1)
        self.assertEqual(persistence["message_save_failure_total"], 1)
        self.assertEqual(persistence["message_save_lag_seconds"]["count"], 1)
        self.assertEqual(persistence["db_visibility_lag_seconds"]["count"], 0)
        self.assertEqual(persistence["dropped_rejected_count_total"], 1)

    async def test_stop_workers_records_bounded_drain_timeout(self) -> None:
        observability = RealtimeObservabilityRegistry()
        service = MessagePersistenceService(
            message_service=FakeMessageService(delay=0.2),
            observability=observability,
            queue_maxsize=2,
            worker_count=1,
            workers_enabled=True,
            shutdown_timeout_seconds=0.01,
        )

        await service.start_workers_if_enabled()
        await service.enqueue(
            workspace_id=1,
            tab_id=2,
            sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
            content="slow",
            file_url=None,
            temp_message_id="temp_1",
        )
        await service.enqueue(
            workspace_id=1,
            tab_id=2,
            sender_id="05EA49CF-D91F-41A0-BE63-CACE1718DE71",
            content="queued during shutdown",
            file_url=None,
            temp_message_id="temp_2",
        )
        await service.stop_workers()

        persistence = observability.snapshot()["persistence"]
        self.assertEqual(persistence["shutdown_drain_timeout_total"], 1)
        self.assertEqual(persistence["dropped_rejected_count_total"], 2)
        self.assertEqual(persistence["current_queue_depth"], 0)
        self.assertEqual(persistence["active_worker_count"], 0)


if __name__ == "__main__":
    unittest.main()
