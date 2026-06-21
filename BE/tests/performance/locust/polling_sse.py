from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from locust import HttpUser, between, events, task


DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "users.local.json"
FALLBACK_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "users.example.json"


def _load_fixture() -> dict[str, Any]:
    fixture_path = Path(os.getenv("PERF_USERS_FILE", DEFAULT_FIXTURE))
    if not fixture_path.exists():
        fixture_path = FALLBACK_FIXTURE

    with fixture_path.open("r", encoding="utf-8") as fixture_file:
        data = json.load(fixture_file)

    if not data.get("users"):
        raise RuntimeError(f"{fixture_path} must contain a non-empty users array")

    return data


FIXTURE = _load_fixture()
WORKSPACE_ID = os.getenv("WORKSPACE_ID", str(FIXTURE.get("workspace_id", 1)))
TAB_ID = os.getenv("TAB_ID", str(FIXTURE.get("tab_id", 1)))
POLL_MIN_WAIT = float(os.getenv("POLL_MIN_WAIT", "1"))
POLL_MAX_WAIT = float(os.getenv("POLL_MAX_WAIT", "3"))
SSE_LISTEN_SECONDS = float(os.getenv("SSE_LISTEN_SECONDS", "30"))
SSE_READ_TIMEOUT_SECONDS = float(os.getenv("SSE_READ_TIMEOUT_SECONDS", str(max(SSE_LISTEN_SECONDS + 20, 30))))
SSE_READ_CHUNK_SIZE = int(os.getenv("SSE_READ_CHUNK_SIZE", "1"))
ENABLE_SSE_PUBLISH = os.getenv("ENABLE_SSE_PUBLISH", "false").lower() == "true"
SSE_PUBLISHER_USERS = max(0, int(os.getenv("SSE_PUBLISHER_USERS", "1")))
POLL_BEFORE_ID = os.getenv("POLL_BEFORE_ID", "").strip()
POLL_BEFORE_RATIO = float(os.getenv("POLL_BEFORE_RATIO", "1" if POLL_BEFORE_ID else "0"))
POLL_BEFORE_RATIO = max(0.0, min(POLL_BEFORE_RATIO, 1.0))
PUSH_CONTENT = os.getenv("PUSH_CONTENT", "<p>performance push notification</p>")
PUSH_PROVIDER_MODE = os.getenv("PUSH_PROVIDER_MODE", "fake")
PUSH_FAKE_PROVIDER_DELAY_MS = os.getenv("PUSH_FAKE_PROVIDER_DELAY_MS", "0")
_DELIVERY_LOCK = threading.Lock()
_PUBLISHED_EVENTS: dict[str, float] = {}
_RECEIVED_EVENT_IDS: set[str] = set()
_ACKED_EVENT_IDS: set[str] = set()
_REPLAYED_EVENT_IDS: set[str] = set()
_DUPLICATE_EVENT_IDS: set[str] = set()
_RECEIVED_EVENT_IDS_BY_LISTENER: dict[str, set[str]] = {}
_LISTENER_STARTED_AT: dict[str, float] = {}


def _pick_user() -> dict[str, Any]:
    return random.choice(FIXTURE["users"])


def _auth_headers(user: dict[str, Any]) -> dict[str, str]:
    token = user.get("access_token") or os.getenv("ACCESS_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _poll_request_options() -> tuple[dict[str, str] | None, str]:
    if POLL_BEFORE_ID and random.random() < POLL_BEFORE_RATIO:
        return (
            {"before_id": POLL_BEFORE_ID},
            "GET /api/workspaces/:workspace_id/tabs/:tab_id/messages?before_id",
        )
    return None, "GET /api/workspaces/:workspace_id/tabs/:tab_id/messages"


def _is_read_timeout(exc: Exception | None) -> bool:
    if exc is None:
        return False
    class_name = exc.__class__.__name__.lower()
    return "readtimeout" in class_name or "read timed out" in str(exc).lower()


def _parse_sse_frame(frame: str) -> tuple[str | None, str | None, str | None]:
    event_id: str | None = None
    event_type: str | None = None
    data_lines: list[str] = []
    for raw_line in frame.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not event_type and not data_lines:
        return None, None, None
    return event_id, event_type, "\n".join(data_lines)


def _payload_latency_ms(payload: dict[str, Any]) -> float | None:
    raw_sent_at = payload.get("published_at_ms", payload.get("sent_at_ms"))
    try:
        sent_at_ms = float(raw_sent_at)
    except (TypeError, ValueError):
        return None
    return max(0.0, time.time() * 1000 - sent_at_ms)


def _reset_delivery_tracking() -> None:
    with _DELIVERY_LOCK:
        _PUBLISHED_EVENTS.clear()
        _RECEIVED_EVENT_IDS.clear()
        _ACKED_EVENT_IDS.clear()
        _REPLAYED_EVENT_IDS.clear()
        _DUPLICATE_EVENT_IDS.clear()
        _RECEIVED_EVENT_IDS_BY_LISTENER.clear()
        _LISTENER_STARTED_AT.clear()


def _register_listener(listener_id: str) -> None:
    with _DELIVERY_LOCK:
        _RECEIVED_EVENT_IDS_BY_LISTENER.setdefault(listener_id, set())
        _LISTENER_STARTED_AT.setdefault(listener_id, time.perf_counter())


def _record_published_event(event_id: str) -> None:
    with _DELIVERY_LOCK:
        _PUBLISHED_EVENTS[event_id] = time.perf_counter()


def _record_received_event(listener_id: str, event_id: str) -> None:
    with _DELIVERY_LOCK:
        _RECEIVED_EVENT_IDS.add(event_id)
        _RECEIVED_EVENT_IDS_BY_LISTENER.setdefault(listener_id, set()).add(event_id)


def _record_acked_event(event_id: str) -> None:
    with _DELIVERY_LOCK:
        _ACKED_EVENT_IDS.add(event_id)


def _record_replayed_event(event_id: str) -> None:
    with _DELIVERY_LOCK:
        _REPLAYED_EVENT_IDS.add(event_id)


def _record_duplicate_event(event_id: str) -> None:
    with _DELIVERY_LOCK:
        _DUPLICATE_EVENT_IDS.add(event_id)


def _publish_delivery_loss_events() -> None:
    if not ENABLE_SSE_PUBLISH:
        return
    with _DELIVERY_LOCK:
        published_event_ids = set(_PUBLISHED_EVENTS)
        missing_after_replay = sorted(published_event_ids - _ACKED_EVENT_IDS)

    if published_event_ids:
        events.request.fire(
            request_type="SSE",
            name="SSE missing after replay count",
            response_time=len(missing_after_replay),
            response_length=len(missing_after_replay),
            exception=(
                RuntimeError(f"{len(missing_after_replay)} published SSE events were not acked")
                if missing_after_replay
                else None
            ),
        )


def _register_delivery_summary_hooks() -> None:
    test_start = getattr(events, "test_start", None)
    test_stop = getattr(events, "test_stop", None)

    if hasattr(test_start, "add_listener"):
        @test_start.add_listener
        def on_test_start(environment: object, **kwargs: object) -> None:
            _reset_delivery_tracking()

    if hasattr(test_stop, "add_listener"):
        @test_stop.add_listener
        def on_test_stop(environment: object, **kwargs: object) -> None:
            _publish_delivery_loss_events()


_register_delivery_summary_hooks()


class PollingUser(HttpUser):
    wait_time = between(POLL_MIN_WAIT, POLL_MAX_WAIT)

    def on_start(self) -> None:
        self.user_fixture = _pick_user()
        self.headers = _auth_headers(self.user_fixture)

    @task
    def poll_messages(self) -> None:
        params, request_name = _poll_request_options()
        with self.client.get(
            f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/messages",
            params=params,
            headers=self.headers,
            name=request_name,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"unexpected status {response.status_code}: {response.text[:200]}")
                return

            try:
                payload = response.json()
            except ValueError as exc:
                response.failure(f"invalid json: {exc}")
                return

            if "messages" not in payload:
                response.failure("missing messages field")
                return

            response.success()


class PushNotificationUser(HttpUser):
    wait_time = between(POLL_MIN_WAIT, POLL_MAX_WAIT)

    def on_start(self) -> None:
        self.user_fixture = _pick_user()
        self.headers = _auth_headers(self.user_fixture)

    @task
    def enqueue_push_notification(self) -> None:
        perf_id = uuid.uuid4().hex
        with self.client.post(
            f"/api/notifications/{WORKSPACE_ID}/{TAB_ID}",
            headers={**self.headers, "Accept": "application/json"},
            json={
                "type": "new_message",
                "content": PUSH_CONTENT,
                "perf_id": perf_id,
            },
            name="POST /api/notifications enqueue",
            catch_response=True,
        ) as response:
            if response.status_code not in {200, 202}:
                response.failure(f"unexpected status {response.status_code}: {response.text[:200]}")
                return

            try:
                payload = response.json()
            except ValueError as exc:
                response.failure(f"invalid json: {exc}")
                return

            if payload.get("status") != "queued":
                response.failure(f"unexpected push status {payload.get('status')!r}")
                return
            if "job_id" not in payload:
                response.failure("missing job_id")
                return

            response.success()
            events.request.fire(
                request_type="PUSH",
                name="Web Push enqueue accepted",
                response_time=0,
                response_length=int(payload.get("recipient_count") or 0),
                exception=None,
            )


class SseListenerUser(HttpUser):
    wait_time = between(1, 2)

    def on_start(self) -> None:
        self.user_fixture = _pick_user()
        self.headers = _auth_headers(self.user_fixture)
        self.stream_attempts = 0
        self.listener_id = uuid.uuid4().hex
        self.last_event_id: str | None = None
        self.seen_event_ids: set[str] = set()
        _register_listener(self.listener_id)

    @task
    def listen_notifications(self) -> None:
        start = time.perf_counter()
        frames_seen = 0
        business_events_seen = 0
        exception: Exception | None = None
        stream_name = "GET /api/sse/notifications stream"

        if self.stream_attempts > 0:
            events.request.fire(
                request_type="SSE",
                name="SSE reconnect",
                response_time=0,
                response_length=0,
                exception=None,
            )
        self.stream_attempts += 1

        try:
            params = {"workspaceId": WORKSPACE_ID}
            if self.last_event_id:
                params["lastEventId"] = self.last_event_id
            with self.client.get(
                "/api/sse/notifications",
                params=params,
                headers={**self.headers, "Accept": "text/event-stream"},
                name="GET /api/sse/notifications",
                stream=True,
                timeout=SSE_READ_TIMEOUT_SECONDS,
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"unexpected status {response.status_code}: {response.text[:200]}")
                    return

                deadline = time.perf_counter() + SSE_LISTEN_SECONDS
                buffer = ""
                for raw_line in response.iter_lines(chunk_size=SSE_READ_CHUNK_SIZE):
                    if isinstance(raw_line, bytes):
                        line = raw_line.decode("utf-8", errors="replace")
                    else:
                        line = str(raw_line)
                    buffer += line + "\n"
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        frame_event_id, event_type, data = _parse_sse_frame(frame)
                        if not event_type and not data:
                            continue
                        frames_seen += 1
                        if data == "p" or event_type == "ping":
                            continue
                        if not data:
                            continue
                        try:
                            payload = json.loads(data)
                        except ValueError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        business_events_seen += 1
                        event_id = frame_event_id or payload.get("event_id")
                        if event_id:
                            event_id = str(event_id)
                            if event_id in self.seen_event_ids:
                                _record_duplicate_event(event_id)
                                events.request.fire(
                                    request_type="SSE",
                                    name="SSE duplicate event",
                                    response_time=0,
                                    response_length=1,
                                    exception=None,
                                )
                                continue
                            self.seen_event_ids.add(event_id)
                            self.last_event_id = event_id
                            _record_received_event(self.listener_id, event_id)
                            events.request.fire(
                                request_type="SSE",
                                name="SSE received unique event",
                                response_time=0,
                                response_length=1,
                                exception=None,
                            )
                            if payload.get("replayed"):
                                _record_replayed_event(event_id)
                                events.request.fire(
                                    request_type="SSE",
                                    name="SSE replayed event",
                                    response_time=0,
                                    response_length=1,
                                    exception=None,
                                )
                            ack_exception: Exception | None = None
                            try:
                                ack_response = self.client.post(
                                    "/api/sse/notifications/ack",
                                    headers={**self.headers, "Accept": "application/json"},
                                    json={"workspace_id": WORKSPACE_ID, "last_event_id": event_id},
                                    name="POST /api/sse/notifications/ack",
                                    catch_response=True,
                                )
                                with ack_response as response:
                                    if response.status_code != 200:
                                        ack_exception = RuntimeError(f"unexpected ack status {response.status_code}")
                                        response.failure(str(ack_exception))
                                    else:
                                        response.success()
                                        _record_acked_event(event_id)
                            except Exception as exc:  # noqa: BLE001 - report ack failure to Locust
                                ack_exception = exc
                            events.request.fire(
                                request_type="SSE",
                                name="SSE acked event",
                                response_time=0,
                                response_length=1 if ack_exception is None else 0,
                                exception=ack_exception,
                            )
                        latency_ms = _payload_latency_ms(payload)
                        if latency_ms is not None:
                            events.request.fire(
                                request_type="SSE",
                                name="SSE event latency",
                                response_time=latency_ms,
                                response_length=1,
                                exception=None,
                            )
                    if time.perf_counter() >= deadline:
                        break
        except Exception as exc:  # noqa: BLE001 - report the load-test failure to Locust
            exception = exc
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if exception is not None and ENABLE_SSE_PUBLISH and self.seen_event_ids:
                stream_name = "GET /api/sse/notifications reconnectable stream close"
                exception = None
            elif _is_read_timeout(exception) and (
                not ENABLE_SSE_PUBLISH or business_events_seen > 0 or bool(self.seen_event_ids)
            ):
                stream_name = (
                    "GET /api/sse/notifications published expected timeout"
                    if ENABLE_SSE_PUBLISH and (business_events_seen > 0 or self.seen_event_ids)
                    else "GET /api/sse/notifications idle expected timeout"
                )
                exception = None
            events.request.fire(
                request_type="SSE",
                name=stream_name,
                response_time=elapsed_ms,
                response_length=frames_seen,
                exception=exception,
            )
            if exception is not None:
                events.request.fire(
                    request_type="SSE",
                    name="SSE stream failure",
                    response_time=0,
                    response_length=0,
                    exception=exception,
                )
            if ENABLE_SSE_PUBLISH and business_events_seen == 0 and not self.seen_event_ids:
                events.request.fire(
                    request_type="SSE",
                    name="SSE zero-event listener window",
                    response_time=elapsed_ms,
                    response_length=0,
                    exception=RuntimeError("no published SSE event observed during listener window"),
                )


class SsePublisherUser(HttpUser):
    wait_time = between(2, 5)
    weight = 0
    fixed_count = SSE_PUBLISHER_USERS if ENABLE_SSE_PUBLISH else 0

    def on_start(self) -> None:
        self.user_fixture = _pick_user()
        self.headers = _auth_headers(self.user_fixture)

    @task
    def publish_notification(self) -> None:
        payload = {
            "event_id": uuid.uuid4().hex,
            "type": "new_message",
            "tab_id": TAB_ID,
            "message": "performance-test-notification",
            "sent_at_ms": int(time.time() * 1000),
            "sender_id": self.user_fixture["user_id"],
        }
        with self.client.post(
            f"/api/sse/notifications/{WORKSPACE_ID}",
            headers=self.headers,
            json=payload,
            name="POST /api/sse/notifications/:workspace_id",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"unexpected status {response.status_code}: {response.text[:200]}")
                return
            response.success()

        _record_published_event(payload["event_id"])
        events.request.fire(
            request_type="SSE",
            name="SSE published event",
            response_time=0,
            response_length=1,
            exception=None,
        )
