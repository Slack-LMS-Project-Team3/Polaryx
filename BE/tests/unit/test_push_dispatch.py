from __future__ import annotations

import asyncio
import json
import os
import unittest
import uuid
from unittest.mock import patch


for key, value in {
    "SECRET_KEY": "test-regression-secret",
    "GOOGLE_CLIENT_ID": "test-google-client",
    "GOOGLE_CLIENT_SECRET": "test-google-secret",
    "GOOGLE_REDIRECT_URI": "http://localhost/auth/callback",
    "CONNECTION_TIMEOUT": "1",
    "RDB_HOST": "127.0.0.1",
    "RDB_PORT": "3306",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_NAME": "polaryx_test",
    "NOSQL_HOST": "127.0.0.1",
    "NOSQL_PORT": "27017",
    "NOSQL_URL": "mongodb://127.0.0.1:27017",
    "GITHUBS_CLIENT_ID": "test-github-client",
    "GITHUBS_CLIENT_SECRET": "test-github-secret",
    "GITHUBS_REDIRECT_URI": "http://localhost/auth/github/callback",
    "AWS_REGION": "ap-northeast-2",
    "AWS_BUCKET_NAME": "test-bucket",
    "AWS_ACCESS_KEY_ID": "test-access-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret-key",
    "VAPID_PUBLIC_KEY": "test-public",
    "VAPID_PRIVATE_KEY": "test-private",
    "VAPID_EMAIL": "mailto:test@example.com",
    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "6379",
    "REDIS_PASSWORD": "",
    "REDIS_DB": "0",
    "PUSH_DISPATCH_WORKERS_ENABLED": "false",
}.items():
    os.environ.setdefault(key, value)

from app.service.push import PushSendSummary, PushService
from app.service.push_dispatch import PushDispatchEnqueueError, PushDispatchService
from app.service.realtime_observability import RealtimeObservabilityRegistry


class FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.acks: list[tuple[str, str, str]] = []
        self.deletes: list[tuple[str, str]] = []
        self.groups: list[tuple[str, str]] = []
        self.fail_xadd = False
        self.sequence = 0
        self.xlen_calls = 0

    async def xadd(self, stream: str, fields: dict[str, str], **kwargs: object) -> str:
        if self.fail_xadd:
            raise RuntimeError("redis unavailable")
        self.sequence += 1
        entry_id = f"{self.sequence}-0"
        self.streams.setdefault(stream, []).append((entry_id, dict(fields)))
        return entry_id

    async def xlen(self, stream: str) -> int:
        self.xlen_calls += 1
        return len(self.streams.get(stream, []))

    async def xack(self, stream: str, group: str, entry_id: str) -> int:
        self.acks.append((stream, group, entry_id))
        return 1

    async def xdel(self, stream: str, entry_id: str) -> int:
        self.deletes.append((stream, entry_id))
        entries = self.streams.get(stream, [])
        self.streams[stream] = [(item_id, fields) for item_id, fields in entries if item_id != entry_id]
        return 1

    async def xgroup_create(self, stream: str, group: str, **kwargs: object) -> bool:
        item = (stream, group)
        if item in self.groups:
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")
        self.groups.append(item)
        return True

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        **kwargs: object,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        await asyncio.sleep(0)
        return []


class FakePushService:
    def __init__(self, summaries: list[PushSendSummary]) -> None:
        self.summaries = list(summaries)
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    async def send_push_to(self, user_ids: list[str], data: dict[str, str]) -> PushSendSummary:
        self.calls.append((list(user_ids), dict(data)))
        if self.summaries:
            return self.summaries.pop(0)
        return PushSendSummary(attempted=len(user_ids), succeeded=len(user_ids), failed=0)


class FakePushRepo:
    def __init__(self, subscription: tuple[str, str, str] | None = None) -> None:
        self.subscription = subscription or ("https://push.example/sub/secret", "p256dh", "auth")
        self.find_user_calls = 0

    def find_user(self, user_id: bytes) -> list[tuple[str, str, str]]:
        self.find_user_calls += 1
        return [self.subscription]


class FakeTabService:
    def __init__(self, members: list[uuid.UUID], tab_name: str = "general") -> None:
        self.members = members
        self.tab_name = tab_name
        self.get_tab_members_calls: list[tuple[int, int]] = []
        self.find_tab_calls: list[tuple[int, int]] = []

    def get_tab_members(self, workspace_id: int, tab_id: int) -> list[tuple[bytes]]:
        self.get_tab_members_calls.append((workspace_id, tab_id))
        return [(member.bytes,) for member in self.members]

    def find_tab(self, workspace_id: int, tab_id: int) -> list[tuple[int, str]]:
        self.find_tab_calls.append((workspace_id, tab_id))
        return [(tab_id, self.tab_name)]


class FakeWorkspaceMemberService:
    def __init__(self, nickname: str = "QA Tester") -> None:
        self.nickname = nickname
        self.calls: list[tuple[uuid.UUID, int]] = []

    def get_member_by_user_id_simple(self, user_id: uuid.UUID, workspace_id: int) -> list[tuple[str]]:
        self.calls.append((user_id, workspace_id))
        return [(self.nickname,)]


class PushDispatchServiceTest(unittest.TestCase):
    def _service(
        self,
        redis_client: FakeRedis,
        push_service: FakePushService | None = None,
        registry: RealtimeObservabilityRegistry | None = None,
        tab_service: FakeTabService | None = None,
        workspace_member_service: FakeWorkspaceMemberService | None = None,
    ) -> tuple[PushDispatchService, RealtimeObservabilityRegistry]:
        async def redis_getter() -> FakeRedis:
            return redis_client

        observability = registry or RealtimeObservabilityRegistry()
        service = PushDispatchService(
            redis_getter=redis_getter,
            push_service=push_service or FakePushService([]),
            tab_service=tab_service,
            workspace_member_service=workspace_member_service,
            observability=observability,
            stream_name="push:notifications",
            dead_letter_stream="push:notifications:dead",
            group_name="polaryx-push-dispatchers",
        )
        return service, observability

    def test_enqueue_writes_stable_stream_payload_and_metrics(self) -> None:
        redis_client = FakeRedis()
        service, registry = self._service(redis_client)
        recipient_id = str(uuid.uuid4())

        result = asyncio.run(
            service.enqueue_notification(
                workspace_id=1,
                tab_id=2,
                sender_id=str(uuid.uuid4()),
                content="hello",
                url="/workspaces/1/tabs/2",
                perf_id="perf-1",
            )
        )

        self.assertEqual(result["status"], "queued")
        self.assertIsNone(result["recipient_count"])
        self.assertEqual(result["recipient_count_status"], "deferred")
        fields = redis_client.streams["push:notifications"][0][1]
        self.assertEqual(fields["workspace_id"], "1")
        self.assertEqual(fields["tab_id"], "2")
        self.assertEqual(fields["content"], "hello")
        self.assertEqual(fields["url"], "/workspaces/1/tabs/2")
        self.assertEqual(fields["attempt"], "1")
        self.assertEqual(fields["perf_id"], "perf-1")
        self.assertNotIn("recipient_ids", fields)
        self.assertNotIn("title", fields)
        self.assertNotIn("body", fields)
        self.assertEqual(redis_client.xlen_calls, 0)

        push = registry.snapshot()["push"]
        self.assertEqual(push["enqueue_attempts_total"], 1)
        self.assertEqual(push["enqueue_success_total"], 1)
        self.assertEqual(push["enqueue_failures_total"], 0)
        self.assertEqual(push["stream_length"], 0)
        self.assertEqual(push["max_queue_depth"], 0)

    def test_enqueue_can_sample_stream_depth_when_enabled(self) -> None:
        previous_sample_rate = os.environ.get("PUSH_QUEUE_DEPTH_SAMPLE_RATE")
        os.environ["PUSH_QUEUE_DEPTH_SAMPLE_RATE"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_QUEUE_DEPTH_SAMPLE_RATE", previous_sample_rate) if previous_sample_rate is not None else os.environ.pop("PUSH_QUEUE_DEPTH_SAMPLE_RATE", None))

        redis_client = FakeRedis()
        service, registry = self._service(redis_client)

        asyncio.run(
            service.enqueue_notification(
                workspace_id=1,
                tab_id=2,
                sender_id=str(uuid.uuid4()),
                content="hello",
                url="/workspaces/1/tabs/2",
            )
        )

        self.assertEqual(redis_client.xlen_calls, 1)
        push = registry.snapshot()["push"]
        self.assertEqual(push["stream_length"], 1)
        self.assertEqual(push["max_queue_depth"], 1)

    def test_enqueue_failure_is_controlled_and_observable(self) -> None:
        redis_client = FakeRedis()
        redis_client.fail_xadd = True
        service, registry = self._service(redis_client)

        with self.assertRaises(PushDispatchEnqueueError):
            asyncio.run(
                service.enqueue_notification(
                    workspace_id=1,
                    tab_id=2,
                    sender_id=str(uuid.uuid4()),
                    content="hello",
                    url="/workspaces/1/tabs/2",
                )
            )

        push = registry.snapshot()["push"]
        self.assertEqual(push["enqueue_attempts_total"], 1)
        self.assertEqual(push["enqueue_success_total"], 0)
        self.assertEqual(push["enqueue_failures_total"], 1)

    def test_worker_success_records_provider_and_ack_metrics(self) -> None:
        redis_client = FakeRedis()
        summary = PushSendSummary(attempted=2, succeeded=2, failed=0, elapsed_seconds=0.25)
        push_service = FakePushService([summary])
        sender_id = uuid.uuid4()
        recipient_ids = [uuid.uuid4(), uuid.uuid4()]
        tab_service = FakeTabService([sender_id, *recipient_ids])
        workspace_member_service = FakeWorkspaceMemberService("QA Tester")
        service, registry = self._service(
            redis_client,
            push_service,
            tab_service=tab_service,
            workspace_member_service=workspace_member_service,
        )

        enqueue_result = asyncio.run(
            service.enqueue_notification(
                workspace_id=1,
                tab_id=2,
                sender_id=str(sender_id),
                content="hello",
                url="/workspaces/1/tabs/2",
            )
        )
        entry_id, fields = redis_client.streams["push:notifications"][0]
        asyncio.run(service._process_entry(redis_client, entry_id, fields))

        expected_recipients = [str(recipient_id) for recipient_id in recipient_ids]
        self.assertEqual(
            push_service.calls,
            [(expected_recipients, {"title": "general", "body": "QA Tester: hello", "url": "/workspaces/1/tabs/2"})],
        )
        self.assertEqual(tab_service.get_tab_members_calls, [(1, 2)])
        self.assertEqual(tab_service.find_tab_calls, [(1, 2)])
        self.assertEqual(workspace_member_service.calls, [(sender_id, 1)])
        self.assertEqual(redis_client.acks, [("push:notifications", "polaryx-push-dispatchers", entry_id)])
        self.assertEqual(redis_client.deletes, [("push:notifications", entry_id)])
        self.assertIsNone(enqueue_result["recipient_count"])
        push = registry.snapshot()["push"]
        self.assertEqual(push["jobs_read_total"], 1)
        self.assertEqual(push["recipient_lookup_success_total"], 1)
        self.assertEqual(push["recipient_lookup_failures_total"], 0)
        self.assertEqual(push["recipient_count_total"], 2)
        self.assertEqual(push["external_send_attempts_total"], 2)
        self.assertEqual(push["external_send_success_total"], 2)
        self.assertEqual(push["external_send_failures_total"], 0)
        self.assertEqual(push["provider_latency_seconds"]["count"], 1)
        self.assertEqual(push["queue_lag_seconds"]["count"], 1)

    def test_worker_retries_then_dead_letters_after_max_attempts(self) -> None:
        previous_attempts = os.environ.get("PUSH_MAX_ATTEMPTS")
        previous_delay = os.environ.get("PUSH_RETRY_DELAY_SECONDS")
        os.environ["PUSH_MAX_ATTEMPTS"] = "2"
        os.environ["PUSH_RETRY_DELAY_SECONDS"] = "0"
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_MAX_ATTEMPTS", previous_attempts) if previous_attempts is not None else os.environ.pop("PUSH_MAX_ATTEMPTS", None))
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_RETRY_DELAY_SECONDS", previous_delay) if previous_delay is not None else os.environ.pop("PUSH_RETRY_DELAY_SECONDS", None))

        redis_client = FakeRedis()
        push_service = FakePushService(
            [
                PushSendSummary(attempted=1, succeeded=0, failed=1, elapsed_seconds=0.10),
                PushSendSummary(attempted=1, succeeded=0, failed=1, elapsed_seconds=0.20),
            ]
        )
        sender_id = uuid.uuid4()
        recipient_id = uuid.uuid4()
        service, registry = self._service(
            redis_client,
            push_service,
            tab_service=FakeTabService([sender_id, recipient_id]),
            workspace_member_service=FakeWorkspaceMemberService("QA Tester"),
        )

        asyncio.run(
            service.enqueue_notification(
                workspace_id=1,
                tab_id=2,
                sender_id=str(sender_id),
                content="hello",
                url="/workspaces/1/tabs/2",
            )
        )
        first_entry_id, first_fields = redis_client.streams["push:notifications"][0]
        asyncio.run(service._process_entry(redis_client, first_entry_id, first_fields))

        retry_entry_id, retry_fields = redis_client.streams["push:notifications"][-1]
        self.assertEqual(retry_fields["attempt"], "2")
        asyncio.run(service._process_entry(redis_client, retry_entry_id, retry_fields))

        dead_fields = redis_client.streams["push:notifications:dead"][0][1]
        self.assertEqual(dead_fields["drop_reason"], "max_attempts_exceeded")
        self.assertEqual(dead_fields["content"], "hello")
        self.assertNotIn("recipient_ids", dead_fields)
        push = registry.snapshot()["push"]
        self.assertEqual(push["retry_count_total"], 1)
        self.assertEqual(push["dropped_count_total"], 1)
        self.assertEqual(push["dead_letter_count_total"], 1)
        self.assertEqual(push["external_send_failures_total"], 2)

    def test_worker_lifecycle_creates_group_and_stops_cleanly(self) -> None:
        previous_enabled = os.environ.get("PUSH_DISPATCH_WORKERS_ENABLED")
        previous_count = os.environ.get("PUSH_WORKER_COUNT")
        previous_shutdown = os.environ.get("PUSH_WORKER_SHUTDOWN_TIMEOUT_SECONDS")
        os.environ["PUSH_DISPATCH_WORKERS_ENABLED"] = "true"
        os.environ["PUSH_WORKER_COUNT"] = "1"
        os.environ["PUSH_WORKER_SHUTDOWN_TIMEOUT_SECONDS"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_DISPATCH_WORKERS_ENABLED", previous_enabled) if previous_enabled is not None else os.environ.pop("PUSH_DISPATCH_WORKERS_ENABLED", None))
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_WORKER_COUNT", previous_count) if previous_count is not None else os.environ.pop("PUSH_WORKER_COUNT", None))
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_WORKER_SHUTDOWN_TIMEOUT_SECONDS", previous_shutdown) if previous_shutdown is not None else os.environ.pop("PUSH_WORKER_SHUTDOWN_TIMEOUT_SECONDS", None))

        redis_client = FakeRedis()
        service, _registry = self._service(redis_client)

        async def start_and_stop() -> None:
            await service.start_workers_if_enabled()
            self.assertEqual(redis_client.groups, [("push:notifications", "polaryx-push-dispatchers")])
            self.assertEqual(len(service._tasks), 1)
            await service.stop_workers()
            self.assertEqual(service._tasks, [])

        asyncio.run(start_and_stop())


class PushServiceProviderAdapterTest(unittest.TestCase):
    def test_pywebpush_timeout_is_passed_and_success_is_counted(self) -> None:
        captured: dict[str, object] = {}
        previous_timeout = os.environ.get("PUSH_PROVIDER_TIMEOUT_SECONDS")
        os.environ["PUSH_PROVIDER_TIMEOUT_SECONDS"] = "1.5"
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_PROVIDER_TIMEOUT_SECONDS", previous_timeout) if previous_timeout is not None else os.environ.pop("PUSH_PROVIDER_TIMEOUT_SECONDS", None))

        def fake_webpush(**kwargs: object) -> None:
            captured.update(kwargs)

        service = PushService()
        service.repo = FakePushRepo()
        with patch("app.service.push.webpush", side_effect=fake_webpush):
            summary = asyncio.run(service.send_push_to([str(uuid.uuid4())], {"title": "t", "body": "b", "url": "/"}))

        self.assertEqual(summary.attempted, 1)
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(captured["timeout"], 1.5)
        self.assertEqual(captured["data"], json.dumps({"title": "t", "body": "b", "url": "/"}))

    def test_provider_exception_is_counted_without_escaping_gather(self) -> None:
        service = PushService()
        service.repo = FakePushRepo()
        with patch("app.service.push.webpush", side_effect=RuntimeError("provider down")):
            summary = asyncio.run(service.send_push_to([str(uuid.uuid4())], {"title": "t", "body": "b", "url": "/"}))

        self.assertEqual(summary.attempted, 1)
        self.assertEqual(summary.succeeded, 0)
        self.assertEqual(summary.failed, 1)

    def test_noop_provider_mode_counts_success_without_subscription_lookup_or_pywebpush(self) -> None:
        previous_mode = os.environ.get("PUSH_PROVIDER_MODE")
        os.environ["PUSH_PROVIDER_MODE"] = "noop"
        self.addCleanup(lambda: os.environ.__setitem__("PUSH_PROVIDER_MODE", previous_mode) if previous_mode is not None else os.environ.pop("PUSH_PROVIDER_MODE", None))

        repo = FakePushRepo()
        service = PushService(repo=repo)
        with patch("app.service.push.webpush") as provider:
            summary = asyncio.run(
                service.send_push_to(
                    [str(uuid.uuid4()), str(uuid.uuid4())],
                    {"title": "t", "body": "b", "url": "/"},
                )
            )

        self.assertEqual(summary.attempted, 2)
        self.assertEqual(summary.succeeded, 2)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.skipped_no_subscription, 0)
        self.assertEqual(repo.find_user_calls, 0)
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
