from __future__ import annotations

import base64
import asyncio
import hmac
import hashlib
import json
import os
import time
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch


TEST_SECRET = "test-regression-secret"
TEST_USER_ID = "05EA49CFD91F41A0BE63CACE1718DE71"
TEST_EMAIL = "qa-regression@example.com"
WORKSPACE_ID = 1
TAB_ID = 1
SECOND_TAB_ID = 2
_MISSING = object()


def _set_required_env() -> dict[str, str | None]:
    defaults = {
        "SECRET_KEY": TEST_SECRET,
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
        "MESSAGE_PERSISTENCE_WORKERS_ENABLED": "false",
    }
    previous_values = {key: os.environ.get(key) for key in defaults}
    for key, value in defaults.items():
        os.environ[key] = value
    return previous_values


def _restore_env(previous_values: dict[str, str | None]) -> None:
    for key, value in previous_values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _capture_instance_attr(obj: object, attr_name: str) -> tuple[object, str, object]:
    return obj, attr_name, getattr(obj, "__dict__", {}).get(attr_name, _MISSING)


def _restore_instance_attr(obj: object, attr_name: str, value: object) -> None:
    if value is _MISSING:
        getattr(obj, "__dict__", {}).pop(attr_name, None)
    else:
        setattr(obj, attr_name, value)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(expires_delta: timedelta = timedelta(minutes=10), **overrides: object) -> str:
    payload = {
        "user_id": TEST_USER_ID,
        "email": TEST_EMAIL,
        "exp": int((datetime.now(UTC) + expires_delta).timestamp()),
    }
    payload.update(overrides)
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode()),
            _b64url(json.dumps(payload, separators=(",", ":")).encode()),
        ]
    )
    signature = hmac.new(TEST_SECRET.encode(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _auth_headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or _token()}"}


class DummyMySQLConnectionPool:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def get_connection(self) -> object:
        raise AssertionError("Regression tests must stub service methods before DB access")


class DummySseRequest:
    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


class FakeSseRedisBus:
    def __init__(self) -> None:
        self.subscribers: dict[str, set[FakeSsePubSub]] = {}
        self.emit_subscribe_ack = True
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.sequence = 0
        self.condition = asyncio.Condition()
        self.fail_xadd = False
        self.xadd_log: list[str] = []

    def subscribe(self, channel: str, pubsub: "FakeSsePubSub") -> None:
        self.subscribers.setdefault(channel, set()).add(pubsub)

    def unsubscribe(self, channel: str, pubsub: "FakeSsePubSub") -> None:
        subscribers = self.subscribers.get(channel)
        if subscribers is None:
            return
        subscribers.discard(pubsub)
        if not subscribers:
            self.subscribers.pop(channel, None)

    async def publish(self, channel: str, data: str) -> int:
        subscribers = list(self.subscribers.get(channel, set()))
        for pubsub in subscribers:
            await pubsub.push(channel, data)
        return len(subscribers)

    async def acknowledge_subscriptions(self, channel: str) -> None:
        subscribers = list(self.subscribers.get(channel, set()))
        for pubsub in subscribers:
            await pubsub.push_subscribe_ack(channel)

    async def xadd(self, stream: str, fields: dict[str, str], **kwargs: object) -> str:
        if self.fail_xadd:
            raise RuntimeError("redis streams unavailable")
        async with self.condition:
            self.sequence += 1
            stream_id = f"{int(time.time() * 1000)}-{self.sequence}"
            self.streams.setdefault(stream, []).append((stream_id, dict(fields)))
            self.xadd_log.append(stream)
            self.condition.notify_all()
            return stream_id

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int = 100,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        effective_last_ids = {
            stream: self._tail_id(stream) if last_id == "$" else last_id
            for stream, last_id in streams.items()
        }
        timeout = (block or 0) / 1000
        deadline = time.monotonic() + timeout
        async with self.condition:
            while True:
                result = self._read_available(effective_last_ids, count)
                if result:
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                try:
                    await asyncio.wait_for(self.condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return []

    def _read_available(
        self,
        effective_last_ids: dict[str, str],
        count: int,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        result: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for stream, last_id in effective_last_ids.items():
            entries = [
                (entry_id, fields)
                for entry_id, fields in self.streams.get(stream, [])
                if self._id_greater(entry_id, last_id)
            ][:count]
            if entries:
                result.append((stream, entries))
        return result

    def _tail_id(self, stream: str) -> str:
        entries = self.streams.get(stream, [])
        return entries[-1][0] if entries else "0-0"

    @staticmethod
    def _id_greater(left: str, right: str) -> bool:
        def parse(value: str) -> tuple[int, int]:
            first, _, second = value.partition("-")
            return int(first or 0), int(second or 0)

        return parse(left) > parse(right)


class FakeSseRedis:
    def __init__(self, bus: FakeSseRedisBus) -> None:
        self.bus = bus

    def pubsub(self) -> "FakeSsePubSub":
        return FakeSsePubSub(self.bus)

    async def publish(self, channel: str, data: str) -> int:
        return await self.bus.publish(channel, data)

    async def xadd(self, stream: str, fields: dict[str, str], **kwargs: object) -> str:
        return await self.bus.xadd(stream, fields, **kwargs)

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int = 100,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        return await self.bus.xread(streams, count=count, block=block)


class FakeSsePubSub:
    def __init__(self, bus: FakeSseRedisBus) -> None:
        self.bus = bus
        self.channels: set[str] = set()
        self.queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channels.add(channel)
        self.bus.subscribe(channel, self)
        if self.bus.emit_subscribe_ack:
            await self.push_subscribe_ack(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.channels.discard(channel)
        self.bus.unsubscribe(channel, self)

    async def push(self, channel: str, data: str) -> None:
        if not self.closed:
            await self.queue.put({"type": "message", "channel": channel, "data": data})

    async def push_subscribe_ack(self, channel: str) -> None:
        if not self.closed:
            await self.queue.put({"type": "subscribe", "channel": channel, "data": 1})

    async def listen(self):
        while not self.closed:
            message = await self.queue.get()
            if message is None:
                break
            yield message

    async def aclose(self) -> None:
        self.closed = True
        for channel in list(self.channels):
            await self.unsubscribe(channel)
        await self.queue.put(None)


class FakeSseOutboxRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.acks: dict[tuple[str, int], str] = {}
        self.actions: list[str] = []

    def insert_event(
        self,
        *,
        event_id: str,
        workspace_id: int,
        recipient_user_id: str | None,
        recipient_scope: str,
        event_type: str,
        tab_id: int | None,
        payload: dict,
    ) -> tuple[dict, bool]:
        self.actions.append(f"insert:{event_id}")
        existing = self.find_event(event_id)
        if existing is not None:
            return existing, False
        event = {
            "id": len(self.events) + 1,
            "event_id": event_id,
            "workspace_id": workspace_id,
            "recipient_user_id": recipient_user_id,
            "recipient_scope": recipient_scope,
            "type": event_type,
            "tab_id": tab_id,
            "payload": dict(payload),
            "status": "pending",
        }
        self.events.append(event)
        return event, True

    def find_event(self, event_id: str) -> dict | None:
        for event in self.events:
            if event["event_id"] == event_id:
                return event
        return None

    def mark_published(self, event_id: str) -> None:
        self.actions.append(f"published:{event_id}")
        event = self.find_event(event_id)
        if event is None:
            raise RuntimeError("event not found")
        event["status"] = "published"

    def mark_failed(self, event_id: str) -> None:
        self.actions.append(f"failed:{event_id}")
        event = self.find_event(event_id)
        if event is None:
            raise RuntimeError("event not found")
        event["status"] = "failed"

    def list_events_after(
        self,
        *,
        workspace_id: int,
        user_id: str,
        after_event_id: str | None,
        limit: int,
    ) -> list[dict]:
        cursor_id = 0
        if after_event_id:
            cursor_event = self.find_event(after_event_id)
            cursor_id = int(cursor_event["id"]) if cursor_event else 0
        return [
            event
            for event in self.events
            if event["workspace_id"] == workspace_id
            and event["status"] == "published"
            and int(event["id"]) > cursor_id
            and (event["recipient_user_id"] is None or event["recipient_user_id"] == user_id)
        ][:limit]

    def get_last_acked_event_id(self, *, user_id: str, workspace_id: int) -> str | None:
        return self.acks.get((user_id, workspace_id))

    def ack_event(self, *, user_id: str, workspace_id: int, event_id: str) -> bool:
        event = self.find_event(event_id)
        if event is None:
            raise ValueError("unknown event")
        current_event_id = self.acks.get((user_id, workspace_id))
        if current_event_id == event_id:
            return False
        if current_event_id:
            current = self.find_event(current_event_id)
            if current is not None and int(current["id"]) > int(event["id"]):
                return False
        self.acks[(user_id, workspace_id)] = event_id
        return True

    def pending_count(self) -> int:
        return sum(1 for event in self.events if event["status"] == "pending")


class AuthRealtimeRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        original_env = _set_required_env()
        cls.addClassCleanup(_restore_env, original_env)

        import mysql.connector.pooling

        original_mysql_pool = mysql.connector.pooling.MySQLConnectionPool
        cls.addClassCleanup(
            setattr,
            mysql.connector.pooling,
            "MySQLConnectionPool",
            original_mysql_pool,
        )
        mysql.connector.pooling.MySQLConnectionPool = DummyMySQLConnectionPool

        from fastapi.testclient import TestClient
        from app.main import app
        from app.router import message, notification, sse, ws_message

        cls.TestClient = TestClient
        cls.app = app
        cls.message_router = message
        cls.notification_router = notification
        cls.sse_router = sse
        cls.ws_router = ws_message

    def setUp(self) -> None:
        self._attr_patches = [
            _capture_instance_attr(self.message_router.message_service, "find_recent_messages"),
            _capture_instance_attr(self.ws_router.workspace_member_service, "get_member_by_user_id"),
            _capture_instance_attr(self.ws_router.message_service, "save_message"),
            _capture_instance_attr(self.ws_router.message_service, "toggle_like"),
            _capture_instance_attr(self.ws_router.message_persistence_service, "enqueue"),
            _capture_instance_attr(self.ws_router.tab_service, "find_tabs"),
            _capture_instance_attr(self.notification_router.push_dispatch_service, "enqueue_notification"),
        ]
        self._manager_method_patches = []
        self.client = self.TestClient(self.app, raise_server_exceptions=False)
        self._patch_realtime_managers()
        self._patch_sse_service()

    def tearDown(self) -> None:
        asyncio.run(self.sse_router.sse_notification_service.reset_for_test())
        for manager in self._realtime_managers():
            manager.activate_connections.clear()
            manager.connection_metadata.clear()
            manager._pending_broadcasts.clear()
        self.ws_router.user_cache.clear()
        for obj, attr_name, value in reversed(getattr(self, "_manager_method_patches", [])):
            _restore_instance_attr(obj, attr_name, value)
        for obj, attr_name, value in reversed(getattr(self, "_attr_patches", [])):
            _restore_instance_attr(obj, attr_name, value)

    def _realtime_managers(self) -> tuple[object, ...]:
        return (self.ws_router.realtime_connection,)

    def _patch_realtime_managers(self) -> None:
        for manager in self._realtime_managers():
            for attr_name in (
                "_initialize_and_register_room",
                "_queue_redis_broadcast",
                "_unregister_room_from_redis",
            ):
                self._manager_method_patches.append(_capture_instance_attr(manager, attr_name))
                setattr(manager, attr_name, AsyncMock())
            manager._pending_broadcasts.clear()

    def _patch_sse_service(self) -> None:
        service = self.sse_router.sse_notification_service
        asyncio.run(service.reset_for_test())
        self.fake_sse_bus = FakeSseRedisBus()
        self.fake_sse_repo = FakeSseOutboxRepository()

        async def fake_redis_getter() -> FakeSseRedis:
            return FakeSseRedis(self.fake_sse_bus)

        for attr_name, value in (
            ("_redis_getter", fake_redis_getter),
            ("_pubsub_getter", fake_redis_getter),
            ("_repository", self.fake_sse_repo),
            ("_heartbeat_seconds", 0.05),
            ("_subscribe_ready_timeout", 1.0),
            ("_queue_maxsize", 2),
            ("_replay_limit", 50),
        ):
            self._attr_patches.append(_capture_instance_attr(service, attr_name))
            setattr(service, attr_name, value)

    def test_auth_check_rejects_missing_malformed_and_expired_tokens(self) -> None:
        missing = self.client.get("/api/auth/check")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["error"]["code"], "AUTH_FAILED")

        malformed = self.client.get("/api/auth/check", headers=_auth_headers("not-a-jwt"))
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(malformed.json()["error"]["code"], "INVALID_TOKEN")

        expired = self.client.get(
            "/api/auth/check",
            headers=_auth_headers(_token(expires_delta=timedelta(minutes=-1))),
        )
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.json()["error"]["code"], "TOKEN_EXPIRED")

    def test_auth_check_accepts_valid_bearer_token(self) -> None:
        response = self.client.get("/api/auth/check", headers=_auth_headers())

        self.assertEqual(response.status_code, 200)

    def test_notification_push_route_preserves_bearer_auth_boundaries(self) -> None:
        payload = {"type": "new_message", "content": "hello"}

        missing = self.client.post(f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}", json=payload)
        self.assertEqual(missing.status_code, 401)

        malformed = self.client.post(
            f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
            headers=_auth_headers("not-a-jwt"),
            json=payload,
        )
        self.assertEqual(malformed.status_code, 401)

        expired = self.client.post(
            f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
            headers=_auth_headers(_token(expires_delta=timedelta(minutes=-1))),
            json=payload,
        )
        self.assertEqual(expired.status_code, 401)

    def test_notification_push_route_enqueues_without_lookup_or_provider_call(self) -> None:
        enqueue_mock = AsyncMock(
            return_value={
                "status": "queued",
                "job_id": "job-regression",
                "recipient_count": None,
                "recipient_count_status": "deferred",
            }
        )
        self.notification_router.push_dispatch_service.enqueue_notification = enqueue_mock

        with patch("app.service.push.webpush") as provider:
            response = self.client.post(
                f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
                headers=_auth_headers(),
                json={"type": "new_message", "content": "<b>hello</b>"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        self.assertIsNone(response.json()["recipient_count"])
        self.assertEqual(response.json()["recipient_count_status"], "deferred")
        provider.assert_not_called()
        enqueue_mock.assert_awaited_once()
        kwargs = enqueue_mock.await_args.kwargs
        self.assertEqual(kwargs["workspace_id"], WORKSPACE_ID)
        self.assertEqual(kwargs["tab_id"], TAB_ID)
        self.assertEqual(kwargs["sender_id"], TEST_USER_ID)
        self.assertEqual(kwargs["content"], "hello")
        self.assertEqual(kwargs["url"], f"/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}")

    def test_notification_push_route_rejects_malformed_or_missing_content(self) -> None:
        malformed = self.client.post(
            f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            data="{not-json",
        )
        self.assertEqual(malformed.status_code, 400)

        missing_content = self.client.post(
            f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
            headers=_auth_headers(),
            json={"type": "new_message"},
        )
        self.assertEqual(missing_content.status_code, 422)

    def test_notification_push_route_returns_controlled_error_when_enqueue_fails(self) -> None:
        from app.service.push_dispatch import PushDispatchEnqueueError

        self.notification_router.push_dispatch_service.enqueue_notification = AsyncMock(
            side_effect=PushDispatchEnqueueError("redis unavailable")
        )

        response = self.client.post(
            f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
            headers=_auth_headers(),
            json={"type": "new_message", "content": "hello"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "HTTP_EXCEPTION")

    def test_lifespan_cleans_up_push_workers_when_persistence_start_fails(self) -> None:
        import app.main as main_module

        events: list[str] = []

        async def push_start() -> None:
            events.append("push_start")

        async def push_stop() -> None:
            events.append("push_stop")

        async def persistence_start() -> None:
            events.append("persistence_start")
            raise RuntimeError("persistence startup failed")

        async def persistence_stop() -> None:
            events.append("persistence_stop")

        patches = [
            _capture_instance_attr(main_module.push_dispatch_service, "start_workers_if_enabled"),
            _capture_instance_attr(main_module.push_dispatch_service, "stop_workers"),
            _capture_instance_attr(main_module.message_persistence_service, "start_workers_if_enabled"),
            _capture_instance_attr(main_module.message_persistence_service, "stop_workers"),
        ]
        main_module.push_dispatch_service.start_workers_if_enabled = push_start
        main_module.push_dispatch_service.stop_workers = push_stop
        main_module.message_persistence_service.start_workers_if_enabled = persistence_start
        main_module.message_persistence_service.stop_workers = persistence_stop

        async def run_lifespan() -> None:
            async with main_module.lifespan(main_module.app):
                pass

        try:
            with self.assertRaises(RuntimeError):
                asyncio.run(run_lifespan())
        finally:
            for obj, attr_name, value in reversed(patches):
                _restore_instance_attr(obj, attr_name, value)

        self.assertEqual(events, ["push_start", "persistence_start", "push_stop"])

    def test_realtime_observability_snapshot_requires_auth_and_returns_sections(self) -> None:
        from app.service.realtime_observability import realtime_observability

        realtime_observability.reset()
        realtime_observability.register_server_id("test-server")
        realtime_observability.set_websocket_active("realtime", WORKSPACE_ID, TAB_ID, 1)
        realtime_observability.set_sse_subscribers(str(WORKSPACE_ID), 1)
        realtime_observability.record_message_save_success(0.05)

        unauthenticated = self.client.get("/api/observability/realtime")
        self.assertEqual(unauthenticated.status_code, 401)

        response = self.client.get("/api/observability/realtime", headers=_auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("generated_at", payload)
        self.assertIn("test-server", payload["process"]["server_ids"])
        self.assertEqual(payload["websocket"]["active_connections"][0]["socket_type"], "realtime")
        self.assertEqual(payload["sse"]["subscribers"][0]["workspace_id"], str(WORKSPACE_ID))
        self.assertEqual(payload["persistence"]["message_save_success_total"], 1)
        self.assertIn("push", payload)

    def test_polling_messages_requires_auth_and_returns_message_shape(self) -> None:
        unauthenticated = self.client.get(f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/messages")
        self.assertEqual(unauthenticated.status_code, 401)

        created_at = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        self.message_router.message_service.find_recent_messages = AsyncMock(
            return_value=[
                (
                    101,
                    TAB_ID,
                    uuid.UUID(TEST_USER_ID).bytes,
                    "QA Tester",
                    "profile.png",
                    "polling regression message",
                    False,
                    created_at,
                    None,
                    None,
                    None,
                    0,
                    1,
                    2,
                    3,
                    4,
                    0,
                    1,
                    0,
                    0,
                    1,
                )
            ]
        )

        response = self.client.get(
            f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/messages",
            headers=_auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["messages"][0]["content"], "polling regression message")
        self.assertEqual(payload["messages"][0]["e_clap_cnt"], 1)
        self.assertEqual(payload["messages"][0]["my_toggle"]["clap"], True)

    def test_websocket_message_path_broadcasts_to_connected_client(self) -> None:
        from app.service.realtime_observability import realtime_observability
        from app.service.message_persistence import MessagePersistenceEnqueueResult

        realtime_observability.reset()
        self.ws_router.workspace_member_service.get_member_by_user_id = Mock(
            return_value=[
                (
                    uuid.UUID(TEST_USER_ID).bytes,
                    WORKSPACE_ID,
                    "QA Tester",
                    TEST_EMAIL,
                    "profile.png",
                )
            ]
        )
        self.ws_router.message_persistence_service.enqueue = AsyncMock(
            return_value=MessagePersistenceEnqueueResult(accepted=True, queue_depth=0)
        )

        with self.client.websocket_connect(f"/api/ws/{WORKSPACE_ID}/{TAB_ID}") as socket:
            socket.send_json(
                {
                    "type": "send",
                    "sender_id": TEST_USER_ID,
                    "content": "websocket regression message",
                    "file_url": None,
                }
            )

            payload = socket.receive_json()

            snapshot = realtime_observability.snapshot()
            self.assertEqual(snapshot["websocket"]["broadcasts_total"], 1)
            self.assertEqual(snapshot["websocket"]["broadcast_recipients_total"], 1)
            self.assertEqual(snapshot["websocket"]["send_success_total"], 1)
            self.assertEqual(snapshot["websocket"]["send_failures_total"], 0)
            self.assertEqual(
                snapshot["websocket"]["active_connections"],
                [
                    {
                        "socket_type": "realtime",
                        "workspace_id": WORKSPACE_ID,
                        "tab_id": TAB_ID,
                        "count": 1,
                    }
                ],
            )

        self.assertEqual(payload["type"], "send")
        self.assertEqual(payload["content"], "websocket regression message")
        self.assertEqual(payload["sender_id"], TEST_USER_ID)
        self.assertEqual(payload["nickname"], "QA Tester")
        self.assertTrue(str(payload["message_id"]).startswith("temp_"))
        self.ws_router.message_persistence_service.enqueue.assert_awaited_once()
        enqueue_kwargs = self.ws_router.message_persistence_service.enqueue.await_args.kwargs
        self.assertEqual(enqueue_kwargs["workspace_id"], WORKSPACE_ID)
        self.assertEqual(enqueue_kwargs["tab_id"], TAB_ID)
        self.assertEqual(enqueue_kwargs["sender_id"], TEST_USER_ID)
        self.assertEqual(enqueue_kwargs["content"], "websocket regression message")
        self.assertIsNone(enqueue_kwargs["file_url"])
        self.assertTrue(str(enqueue_kwargs["temp_message_id"]).startswith("temp_"))

    def test_websocket_redis_batch_publish_records_attempt_size_and_latency(self) -> None:
        from app.service.realtime_observability import realtime_observability
        from app.service.websocket_manager import ConnectionManager

        class FakePipeline:
            def __init__(self) -> None:
                self.published: list[tuple[str, str]] = []

            def publish(self, channel: str, message: str) -> None:
                self.published.append((channel, message))

            async def execute(self) -> None:
                return None

        class FakeRedis:
            def __init__(self) -> None:
                self.pipeline_instance = FakePipeline()

            def pipeline(self) -> FakePipeline:
                return self.pipeline_instance

        async def run_batch() -> None:
            manager = ConnectionManager()
            manager.socket_type = "realtime"
            manager._redis_client = FakeRedis()
            manager._pending_broadcasts = {
                "type:realtime:workspace:1:tab:1": [
                    {"message": "a", "sender_server": manager.server_id},
                    {"message": "b", "sender_server": manager.server_id},
                ]
            }
            await manager._process_batch_broadcasts()

        realtime_observability.reset()
        asyncio.run(run_batch())

        websocket = realtime_observability.snapshot()["websocket"]
        self.assertEqual(websocket["redis_publish_attempts_total"], 1)
        self.assertEqual(websocket["redis_publish_messages_total"], 2)
        self.assertEqual(websocket["redis_publish_failures_total"], 0)
        self.assertEqual(websocket["redis_publish_lag_seconds"]["count"], 1)

    def test_websocket_persistence_enqueue_failure_is_sender_only_and_does_not_broadcast(self) -> None:
        from app.service.realtime_observability import realtime_observability
        from app.service.message_persistence import MessagePersistenceEnqueueResult

        realtime_observability.reset()
        self.ws_router.workspace_member_service.get_member_by_user_id = Mock(
            return_value=[
                (
                    uuid.UUID(TEST_USER_ID).bytes,
                    WORKSPACE_ID,
                    "QA Tester",
                    TEST_EMAIL,
                    "profile.png",
                )
            ]
        )
        self.ws_router.message_persistence_service.enqueue = AsyncMock(
            return_value=MessagePersistenceEnqueueResult(
                accepted=False,
                code="persistence_queue_full",
                retryable=True,
                queue_depth=1,
            )
        )

        with self.client.websocket_connect(f"/api/ws/{WORKSPACE_ID}/{TAB_ID}") as socket:
            socket.send_json(
                {
                    "type": "send",
                    "sender_id": TEST_USER_ID,
                    "content": "do not log this content",
                    "file_url": None,
                }
            )

            payload = socket.receive_json()

        self.assertEqual(payload["type"], "send_error")
        self.assertEqual(payload["code"], "persistence_queue_full")
        self.assertTrue(payload["retryable"])
        self.assertTrue(str(payload["temp_message_id"]).startswith("temp_"))
        self.ws_router.message_persistence_service.enqueue.assert_awaited_once()
        persistence = realtime_observability.snapshot()["persistence"]
        self.assertEqual(persistence["message_save_success_total"], 0)
        self.assertEqual(persistence["message_save_failure_total"], 0)
        self.assertEqual(persistence["message_save_lag_seconds"]["count"], 0)

    def test_websocket_persistence_queue_full_uses_sender_only_error_and_no_room_broadcast(self) -> None:
        from app.service.message_persistence import MessagePersistenceEnqueueResult
        from app.service.realtime_observability import realtime_observability

        realtime_observability.reset()
        self.ws_router.workspace_member_service.get_member_by_user_id = Mock(
            return_value=[
                (
                    uuid.UUID(TEST_USER_ID).bytes,
                    WORKSPACE_ID,
                    "QA Tester",
                    TEST_EMAIL,
                    "profile.png",
                )
            ]
        )
        self.ws_router.message_persistence_service.enqueue = AsyncMock(
            return_value=MessagePersistenceEnqueueResult(
                accepted=False,
                code="persistence_queue_full",
                retryable=True,
                queue_depth=1,
            )
        )

        with self.client.websocket_connect(f"/api/ws/{WORKSPACE_ID}/{TAB_ID}") as socket:
            socket.send_json(
                {
                    "type": "send",
                    "sender_id": TEST_USER_ID,
                    "content": "overflow regression message",
                    "file_url": None,
                }
            )

            payload = socket.receive_json()

        self.assertEqual(payload["type"], "send_error")
        self.assertEqual(payload["code"], "persistence_queue_full")
        self.assertTrue(payload["retryable"])
        self.assertTrue(str(payload["temp_message_id"]).startswith("temp_"))
        websocket = realtime_observability.snapshot()["websocket"]
        self.assertEqual(websocket["broadcasts_total"], 0)
        self.assertEqual(websocket["broadcast_recipients_total"], 0)

    def test_websocket_unified_path_broadcasts_message_edit_to_connected_client(self) -> None:
        with self.client.websocket_connect(f"/api/ws/{WORKSPACE_ID}/{TAB_ID}") as socket:
            socket.send_json(
                {
                    "type": "edit",
                    "msg_id": 404,
                    "content": "edited websocket regression message",
                }
            )

            payload = socket.receive_json()

        self.assertEqual(payload["type"], "edit")
        self.assertEqual(payload["message_id"], 404)
        self.assertEqual(payload["content"], "edited websocket regression message")

    def test_websocket_unified_path_broadcasts_emoji_update_to_connected_client(self) -> None:
        message_id = 303
        counts = {
            "checkCnt": 1,
            "clapCnt": 2,
            "likeCnt": 3,
            "prayCnt": 4,
            "sparkleCnt": 5,
        }
        self.ws_router.message_service.toggle_like = AsyncMock(return_value=counts)
        self.assertIsInstance(self.ws_router.realtime_connection._initialize_and_register_room, AsyncMock)
        self.assertIsInstance(self.ws_router.realtime_connection._queue_redis_broadcast, AsyncMock)

        with self.client.websocket_connect(f"/api/ws/{WORKSPACE_ID}/{TAB_ID}") as socket:
            socket.send_json(
                {
                    "type": "emoji",
                    "messageId": message_id,
                    "userId": TEST_USER_ID,
                    "action": "like",
                    "emojiType": "clap",
                }
            )

            payload = socket.receive_json()

        self.assertEqual(payload["type"], "emoji_update")
        self.assertEqual(payload["messageId"], message_id)
        self.assertEqual(payload["checkCnt"], 1)
        self.assertEqual(payload["clapCnt"], 2)
        self.assertEqual(payload["likeCnt"], 3)
        self.assertEqual(payload["prayCnt"], 4)
        self.assertEqual(payload["sparkleCnt"], 5)
        self.ws_router.message_service.toggle_like.assert_awaited_once_with(
            TAB_ID,
            message_id,
            TEST_USER_ID,
            "clap",
            True,
        )

    def test_websocket_unified_path_broadcasts_profile_update_to_returned_tabs(self) -> None:
        self.ws_router.tab_service.find_tabs = Mock(return_value=[(TAB_ID,), (SECOND_TAB_ID,)])
        self.assertIsInstance(self.ws_router.realtime_connection._unregister_room_from_redis, AsyncMock)

        with (
            self.client.websocket_connect(f"/api/ws/{WORKSPACE_ID}/{TAB_ID}") as tab_one_socket,
            self.client.websocket_connect(
                f"/api/ws/{WORKSPACE_ID}/{SECOND_TAB_ID}"
            ) as tab_two_socket,
        ):
            tab_one_socket.send_json(
                {
                    "type": "profile",
                    "sender_id": TEST_USER_ID,
                    "nickname": "QA Profile",
                    "image": "profile-updated.png",
                }
            )

            first_payload = tab_one_socket.receive_json()
            second_payload = tab_two_socket.receive_json()

        self.assertEqual(first_payload, second_payload)
        self.assertEqual(first_payload["type"], "profile_update")
        self.assertEqual(first_payload["sender_id"], TEST_USER_ID)
        self.assertEqual(first_payload["nickname"], "QA Profile")
        self.assertEqual(first_payload["image"], "profile-updated.png")
        self.ws_router.tab_service.find_tabs.assert_called_once_with(WORKSPACE_ID, TEST_USER_ID)

    def test_websocket_unified_malformed_emoji_payload_missing_message_id_disconnects_currently(self) -> None:
        websocket = Mock()
        websocket.receive_text = AsyncMock(
            return_value=json.dumps(
                {
                    "type": "emoji",
                    "userId": TEST_USER_ID,
                    "action": "like",
                    "emojiType": "clap",
                }
            )
        )
        connect_mock = AsyncMock()
        disconnect_mock = AsyncMock()
        self.ws_router.message_service.toggle_like = AsyncMock()

        with (
            patch.object(self.ws_router.realtime_connection, "connect", connect_mock),
            patch.object(self.ws_router.realtime_connection, "disconnect", disconnect_mock),
        ):
            # Current route behavior is disconnect-only after a broad exception,
            # not a structured WebSocket error payload.
            asyncio.run(
                asyncio.wait_for(
                    self.ws_router.websocket_endpoint(websocket, WORKSPACE_ID, TAB_ID),
                    timeout=1,
                )
            )

        connect_mock.assert_awaited_once_with("realtime", WORKSPACE_ID, TAB_ID, websocket)
        disconnect_mock.assert_awaited_once_with(WORKSPACE_ID, TAB_ID, websocket)
        self.ws_router.message_service.toggle_like.assert_not_awaited()

    def test_websocket_unified_unsupported_payload_type_disconnects_currently(self) -> None:
        websocket = Mock()
        websocket.receive_text = AsyncMock(
            return_value=json.dumps(
                {
                    "type": "unknown",
                    "sender_id": TEST_USER_ID,
                }
            )
        )
        connect_mock = AsyncMock()
        disconnect_mock = AsyncMock()
        self.ws_router.tab_service.find_tabs = Mock()

        with (
            patch.object(self.ws_router.realtime_connection, "connect", connect_mock),
            patch.object(self.ws_router.realtime_connection, "disconnect", disconnect_mock),
        ):
            # Current route behavior is disconnect-only after a broad exception,
            # not a structured WebSocket error payload.
            asyncio.run(
                asyncio.wait_for(
                    self.ws_router.websocket_endpoint(websocket, WORKSPACE_ID, TAB_ID),
                    timeout=1,
                )
            )

        connect_mock.assert_awaited_once_with("realtime", WORKSPACE_ID, TAB_ID, websocket)
        disconnect_mock.assert_awaited_once_with(WORKSPACE_ID, TAB_ID, websocket)
        self.ws_router.tab_service.find_tabs.assert_not_called()

    def test_sse_notifications_require_auth_and_deliver_published_events(self) -> None:
        from app.service.realtime_observability import realtime_observability

        unauthenticated = self.client.get(f"/api/sse/notifications?workspaceId={WORKSPACE_ID}")
        self.assertEqual(unauthenticated.status_code, 401)
        unauthenticated_post = self.client.post(
            f"/api/sse/notifications/{WORKSPACE_ID}",
            json={"type": "new_message"},
        )
        self.assertEqual(unauthenticated_post.status_code, 401)
        unauthenticated_ack = self.client.post(
            "/api/sse/notifications/ack",
            json={"workspace_id": WORKSPACE_ID, "last_event_id": "evt-missing"},
        )
        self.assertEqual(unauthenticated_ack.status_code, 401)

        publish = self.client.post(
            f"/api/sse/notifications/{WORKSPACE_ID}",
            headers=_auth_headers(),
            json={"type": "new_message", "message": "sse-regression"},
        )
        self.assertEqual(publish.status_code, 200)
        realtime_observability.reset()

        async def receive_published_event() -> tuple[str, dict, dict, dict]:
            request = DummySseRequest()
            generator = self.sse_router.event_generator(request, str(WORKSPACE_ID))
            first_frame = asyncio.create_task(generator.__anext__())

            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if self.sse_router.subscribers.get(str(WORKSPACE_ID)):
                    break
                await asyncio.sleep(0.01)
            else:
                await generator.aclose()
                self.fail("SSE listener did not subscribe before timeout")

            subscribed_snapshot = realtime_observability.snapshot()
            await self.sse_router.send_sse_notification(
                str(WORKSPACE_ID),
                {"type": "new_message", "message": "sse-regression"},
            )
            frame = await asyncio.wait_for(first_frame, timeout=1)
            delivery_snapshot = realtime_observability.snapshot()
            await generator.aclose()
            closed_snapshot = realtime_observability.snapshot()
            return frame, subscribed_snapshot, delivery_snapshot, closed_snapshot

        frame, subscribed_snapshot, delivery_snapshot, closed_snapshot = asyncio.run(receive_published_event())

        self.assertIn("id: ", frame)
        self.assertIn("event: new_message", frame)
        self.assertIn("sse-regression", frame)
        self.assertEqual(
            subscribed_snapshot["sse"]["subscribers"],
            [{"workspace_id": str(WORKSPACE_ID), "count": 1}],
        )
        self.assertEqual(delivery_snapshot["sse"]["delivery_attempts_total"], 1)
        self.assertEqual(delivery_snapshot["sse"]["event_delivery_count_total"], 1)
        self.assertEqual(delivery_snapshot["sse"]["outbox_inserted_total"], 1)
        self.assertEqual(delivery_snapshot["sse"]["outbox_published_total"], 1)
        self.assertEqual(delivery_snapshot["sse"]["stream_xadd_attempts_total"], 1)
        self.assertEqual(delivery_snapshot["sse"]["stream_messages_received_total"], 1)
        self.assertEqual(delivery_snapshot["sse"]["queue_put_failures_total"], 0)
        self.assertEqual(closed_snapshot["sse"]["subscribers"], [])

    def test_sse_background_publish_failure_is_controlled_and_observable(self) -> None:
        from app.service.realtime_observability import realtime_observability

        async def run_background_publish_failure() -> dict:
            service = self.sse_router.sse_notification_service
            original_getter = service._redis_getter

            async def failing_redis_getter() -> object:
                raise RuntimeError("redis unavailable")

            realtime_observability.reset()
            service._redis_getter = failing_redis_getter
            try:
                task = self.sse_router.schedule_sse_notification(
                    str(WORKSPACE_ID),
                    {"type": "invited_to_tab", "tab_id": TAB_ID, "message": "do not log raw payload"},
                )
                await asyncio.wait_for(task, timeout=1)
                return realtime_observability.snapshot()
            finally:
                service._redis_getter = original_getter

        snapshot = asyncio.run(run_background_publish_failure())

        self.assertEqual(snapshot["sse"]["stream_xadd_attempts_total"], 1)
        self.assertEqual(snapshot["sse"]["stream_xadd_failures_total"], 1)
        self.assertEqual(snapshot["sse"]["outbox_failed_total"], 1)

    def test_sse_publish_inserts_db_outbox_before_redis_stream_xadd(self) -> None:
        async def publish_event() -> tuple[dict, list[str], list[str]]:
            service = self.sse_router.sse_notification_service
            published = await service.publish(
                str(WORKSPACE_ID),
                {"event_id": "evt-outbox-first", "type": "new_message", "tab_id": TAB_ID},
            )
            return published, list(self.fake_sse_repo.actions), list(self.fake_sse_bus.xadd_log)

        published, actions, xadd_log = asyncio.run(publish_event())

        self.assertEqual(published["event_id"], "evt-outbox-first")
        self.assertEqual(actions[:2], ["insert:evt-outbox-first", "published:evt-outbox-first"])
        self.assertEqual(xadd_log, [f"sse:notifications:{WORKSPACE_ID}"])
        event = self.fake_sse_repo.find_event("evt-outbox-first")
        self.assertIsNotNone(event)
        self.assertEqual(event["status"], "published")

    def test_sse_publish_stream_failure_leaves_outbox_failed_for_retry(self) -> None:
        async def publish_with_stream_failure() -> tuple[dict, dict]:
            from app.service.realtime_observability import realtime_observability

            realtime_observability.reset()
            self.fake_sse_bus.fail_xadd = True
            with self.assertRaises(self.sse_router.SSEPublishError):
                await self.sse_router.sse_notification_service.publish(
                    str(WORKSPACE_ID),
                    {"event_id": "evt-xadd-fails", "type": "new_message", "tab_id": TAB_ID},
                )
            return self.fake_sse_repo.find_event("evt-xadd-fails"), realtime_observability.snapshot()

        event, snapshot = asyncio.run(publish_with_stream_failure())

        self.assertIsNotNone(event)
        self.assertEqual(event["status"], "failed")
        self.assertEqual(snapshot["sse"]["outbox_inserted_total"], 1)
        self.assertEqual(snapshot["sse"]["outbox_failed_total"], 1)
        self.assertEqual(snapshot["sse"]["stream_xadd_failures_total"], 1)

    def test_sse_reconnect_replays_db_events_after_last_event_id(self) -> None:
        async def replay_after_cursor() -> tuple[str, dict]:
            from app.service.realtime_observability import realtime_observability

            realtime_observability.reset()
            repo = self.fake_sse_repo
            first, _ = repo.insert_event(
                event_id="evt-replay-1",
                workspace_id=WORKSPACE_ID,
                recipient_user_id=None,
                recipient_scope="workspace",
                event_type="new_message",
                tab_id=TAB_ID,
                payload={"event_id": "evt-replay-1", "type": "new_message", "tab_id": TAB_ID},
            )
            second, _ = repo.insert_event(
                event_id="evt-replay-2",
                workspace_id=WORKSPACE_ID,
                recipient_user_id=None,
                recipient_scope="workspace",
                event_type="invited_to_tab",
                tab_id=SECOND_TAB_ID,
                payload={"event_id": "evt-replay-2", "type": "invited_to_tab", "tab_id": SECOND_TAB_ID},
            )
            repo.mark_published(first["event_id"])
            repo.mark_published(second["event_id"])

            queue = await self.sse_router.sse_notification_service.subscribe(str(WORKSPACE_ID))
            generator = self.sse_router.sse_notification_service.stream(
                DummySseRequest(),
                str(WORKSPACE_ID),
                queue,
                user_id=TEST_USER_ID,
                last_event_id="evt-replay-1",
            )
            frame = await asyncio.wait_for(generator.__anext__(), timeout=1)
            snapshot = self.sse_router.sse_notification_service._observability.snapshot()
            await generator.aclose()
            return frame, snapshot

        frame, snapshot = asyncio.run(replay_after_cursor())

        self.assertIn("id: evt-replay-2", frame)
        self.assertIn("event: invited_to_tab", frame)
        self.assertIn('"replayed": true', frame)
        self.assertEqual(snapshot["sse"]["replayed_events_total"], 1)

    def test_sse_ack_endpoint_upserts_cursor_idempotently(self) -> None:
        event, _ = self.fake_sse_repo.insert_event(
            event_id="evt-ack-1",
            workspace_id=WORKSPACE_ID,
            recipient_user_id=None,
            recipient_scope="workspace",
            event_type="new_message",
            tab_id=TAB_ID,
            payload={"event_id": "evt-ack-1", "type": "new_message", "tab_id": TAB_ID},
        )
        self.fake_sse_repo.mark_published(event["event_id"])

        first = self.client.post(
            "/api/sse/notifications/ack",
            headers=_auth_headers(),
            json={"workspace_id": WORKSPACE_ID, "last_event_id": "evt-ack-1"},
        )
        second = self.client.post(
            "/api/sse/notifications/ack",
            headers=_auth_headers(),
            json={"workspace_id": WORKSPACE_ID, "last_event_id": "evt-ack-1"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["updated"])
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["updated"])
        self.assertEqual(self.fake_sse_repo.acks[(TEST_USER_ID, WORKSPACE_ID)], "evt-ack-1")

    def test_sse_duplicate_event_id_is_not_inserted_or_streamed_twice(self) -> None:
        async def publish_duplicate_twice() -> tuple[dict, dict, dict]:
            from app.service.realtime_observability import realtime_observability

            realtime_observability.reset()
            service = self.sse_router.sse_notification_service
            first = await service.publish(
                str(WORKSPACE_ID),
                {"event_id": "evt-duplicate-server", "type": "new_message", "tab_id": TAB_ID},
            )
            second = await service.publish(
                str(WORKSPACE_ID),
                {"event_id": "evt-duplicate-server", "type": "new_message", "tab_id": TAB_ID},
            )
            return first, second, realtime_observability.snapshot()

        first, second, snapshot = asyncio.run(publish_duplicate_twice())

        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(len([event for event in self.fake_sse_repo.events if event["event_id"] == "evt-duplicate-server"]), 1)
        self.assertEqual(len(self.fake_sse_bus.xadd_log), 1)
        self.assertEqual(snapshot["sse"]["duplicate_events_deduped_total"], 1)

    def test_sse_cross_worker_delivery_uses_shared_redis_pubsub_bus(self) -> None:
        from app.service.realtime_observability import RealtimeObservabilityRegistry
        from app.service.sse_notifications import SseNotificationService

        async def run_cross_worker_delivery() -> tuple[dict, dict, dict]:
            bus = FakeSseRedisBus()
            registry = RealtimeObservabilityRegistry()

            async def fake_redis_getter() -> FakeSseRedis:
                return FakeSseRedis(bus)

            subscriber_service = SseNotificationService(
                redis_getter=fake_redis_getter,
                repository=FakeSseOutboxRepository(),
                observability=registry,
                queue_maxsize=2,
                heartbeat_seconds=0.05,
                subscribe_ready_timeout=1.0,
            )
            publisher_service = SseNotificationService(
                redis_getter=fake_redis_getter,
                repository=FakeSseOutboxRepository(),
                observability=registry,
                queue_maxsize=2,
                heartbeat_seconds=0.05,
                subscribe_ready_timeout=1.0,
            )

            queue = await subscriber_service.subscribe(str(WORKSPACE_ID))
            published = await publisher_service.publish(
                str(WORKSPACE_ID),
                {"type": "new_message", "tab_id": TAB_ID, "sender_id": TEST_USER_ID},
            )
            delivered = await asyncio.wait_for(queue.get(), timeout=1)
            snapshot = registry.snapshot()
            await subscriber_service.unsubscribe(str(WORKSPACE_ID), queue)
            await subscriber_service.reset_for_test()
            await publisher_service.reset_for_test()
            return published, delivered, snapshot

        published, delivered, snapshot = asyncio.run(run_cross_worker_delivery())

        self.assertEqual(delivered["type"], "new_message")
        self.assertEqual(delivered["tab_id"], TAB_ID)
        self.assertEqual(delivered["sender_id"], TEST_USER_ID)
        self.assertEqual(delivered["event_id"], published["event_id"])
        self.assertIn("published_at_ms", delivered)
        self.assertEqual(snapshot["sse"]["stream_xadd_attempts_total"], 1)
        self.assertEqual(snapshot["sse"]["stream_xadd_failures_total"], 0)
        self.assertEqual(snapshot["sse"]["stream_messages_received_total"], 1)
        self.assertEqual(snapshot["sse"]["delivery_attempts_total"], 1)
        self.assertEqual(snapshot["sse"]["event_delivery_count_total"], 1)

    def test_sse_subscription_surfaces_stream_reader_start_failure(self) -> None:
        from app.service.realtime_observability import RealtimeObservabilityRegistry
        from app.service.sse_notifications import SSESubscriptionError
        from app.service.sse_notifications import SseNotificationService

        async def run_readiness_check() -> dict:
            registry = RealtimeObservabilityRegistry()

            async def failing_redis_getter() -> object:
                raise RuntimeError("redis unavailable")

            service = SseNotificationService(
                redis_getter=failing_redis_getter,
                repository=FakeSseOutboxRepository(),
                observability=registry,
                queue_maxsize=2,
                heartbeat_seconds=0.05,
                subscribe_ready_timeout=1.0,
            )

            with self.assertRaises(SSESubscriptionError):
                await service.subscribe(str(WORKSPACE_ID))
            snapshot = registry.snapshot()
            await service.reset_for_test()
            return snapshot

        snapshot = asyncio.run(run_readiness_check())

        self.assertEqual(snapshot["sse"]["subscribers"], [])
        self.assertEqual(snapshot["sse"]["listener_failures_total"], 1)

    def test_sse_heartbeat_emits_ping_before_read_timeout_window(self) -> None:
        async def receive_ping() -> list[str]:
            queue = await self.sse_router.sse_notification_service.subscribe(str(WORKSPACE_ID))
            generator = self.sse_router.sse_notification_service.stream(
                DummySseRequest(),
                str(WORKSPACE_ID),
                queue,
            )
            event_line = await asyncio.wait_for(generator.__anext__(), timeout=1)
            data_line = await asyncio.wait_for(generator.__anext__(), timeout=1)
            await generator.aclose()
            return [event_line, data_line]

        lines = asyncio.run(receive_ping())

        self.assertEqual([line.strip() for line in lines], ["event: ping", "data: p"])

    def test_sse_queue_full_records_put_failure_and_drop(self) -> None:
        from app.service.realtime_observability import RealtimeObservabilityRegistry
        from app.service.sse_notifications import SseNotificationService

        async def fill_queue() -> dict:
            bus = FakeSseRedisBus()
            registry = RealtimeObservabilityRegistry()

            async def fake_redis_getter() -> FakeSseRedis:
                return FakeSseRedis(bus)

            service = SseNotificationService(
                redis_getter=fake_redis_getter,
                repository=FakeSseOutboxRepository(),
                observability=registry,
                queue_maxsize=1,
                heartbeat_seconds=0.05,
                subscribe_ready_timeout=1.0,
            )
            queue = await service.subscribe(str(WORKSPACE_ID))
            await service.deliver_local(str(WORKSPACE_ID), {"type": "new_message", "tab_id": TAB_ID})
            await service.deliver_local(str(WORKSPACE_ID), {"type": "new_message", "tab_id": SECOND_TAB_ID})
            snapshot = registry.snapshot()
            await service.unsubscribe(str(WORKSPACE_ID), queue)
            await service.reset_for_test()
            return snapshot

        snapshot = asyncio.run(fill_queue())

        self.assertEqual(snapshot["sse"]["delivery_attempts_total"], 2)
        self.assertEqual(snapshot["sse"]["event_delivery_count_total"], 1)
        self.assertEqual(snapshot["sse"]["queue_put_failures_total"], 1)
        self.assertEqual(snapshot["sse"]["queue_drops_total"], 1)
        self.assertEqual(snapshot["sse"]["max_queue_depth"], 1)


if __name__ == "__main__":
    unittest.main()
