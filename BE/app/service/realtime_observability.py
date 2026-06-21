from __future__ import annotations

import math
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque


class TimingSamples:
    def __init__(self, limit: int = 200) -> None:
        self._samples: Deque[float] = deque(maxlen=max(1, limit))
        self._count = 0
        self._latest: float | None = None
        self._max: float | None = None

    def observe(self, value: float) -> None:
        safe_value = max(0.0, float(value))
        self._samples.append(safe_value)
        self._count += 1
        self._latest = safe_value
        self._max = safe_value if self._max is None else max(self._max, safe_value)

    def snapshot(self) -> dict[str, float | int | None]:
        samples = list(self._samples)
        return {
            "count": self._count,
            "sample_count": len(samples),
            "latest": self._latest,
            "max": self._max,
            "p50": self._percentile(samples, 0.50),
            "p95": self._percentile(samples, 0.95),
            "p99": self._percentile(samples, 0.99),
        }

    def reset(self) -> None:
        self._samples.clear()
        self._count = 0
        self._latest = None
        self._max = None

    @staticmethod
    def _percentile(samples: list[float], percentile: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return ordered[index]


class RealtimeObservabilityRegistry:
    def __init__(self, sample_limit: int = 200) -> None:
        self._sample_limit = sample_limit
        self._lock = threading.RLock()
        self._server_ids: set[str] = set()
        self._websocket_active: dict[tuple[str, int, int], int] = {}
        self._sse_subscribers: dict[str, int] = {}
        self._websocket_redis_lag = TimingSamples(sample_limit)
        self._message_save_lag = TimingSamples(sample_limit)
        self._message_persistence_queue_wait = TimingSamples(sample_limit)
        self._message_persistence_save_duration = TimingSamples(sample_limit)
        self._message_persistence_visibility_lag = TimingSamples(sample_limit)
        self._push_queue_lag = TimingSamples(sample_limit)
        self._push_provider_latency = TimingSamples(sample_limit)
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._websocket_active.clear()
            self._sse_subscribers.clear()
            self._websocket_redis_lag.reset()
            self._message_save_lag.reset()
            self._message_persistence_queue_wait.reset()
            self._message_persistence_save_duration.reset()
            self._message_persistence_visibility_lag.reset()
            self._push_queue_lag.reset()
            self._push_provider_latency.reset()
            self._websocket_counters = {
                "broadcasts_total": 0,
                "broadcast_recipients_total": 0,
                "send_success_total": 0,
                "send_failures_total": 0,
                "dropped_connections_total": 0,
                "redis_publish_attempts_total": 0,
                "redis_publish_messages_total": 0,
                "redis_publish_failures_total": 0,
            }
            self._sse_counters = {
                "delivery_attempts_total": 0,
                "event_delivery_count_total": 0,
                "queue_put_failures_total": 0,
                "queue_drops_total": 0,
                "max_queue_depth": 0,
                "outbox_inserted_total": 0,
                "outbox_published_total": 0,
                "outbox_failed_total": 0,
                "pending_outbox_count": 0,
                "stream_xadd_attempts_total": 0,
                "stream_xadd_failures_total": 0,
                "stream_messages_received_total": 0,
                "replayed_events_total": 0,
                "ack_updates_total": 0,
                "duplicate_events_deduped_total": 0,
                "listener_starts_total": 0,
                "listener_restarts_total": 0,
                "listener_failures_total": 0,
            }
            self._persistence_counters = {
                "message_save_success_total": 0,
                "message_save_failure_total": 0,
                "enqueue_attempts_total": 0,
                "enqueue_success_total": 0,
                "enqueue_failures_total": 0,
                "queue_full_rejects_total": 0,
                "worker_saves_started_total": 0,
                "worker_save_success_total": 0,
                "worker_save_failure_total": 0,
                "retry_count_total": 0,
                "dropped_rejected_count_total": 0,
                "current_queue_depth": 0,
                "max_queue_depth": 0,
                "active_worker_count": 0,
                "shutdown_drain_timeout_total": 0,
            }
            self._push_counters = {
                "enqueue_attempts_total": 0,
                "enqueue_success_total": 0,
                "enqueue_failures_total": 0,
                "jobs_read_total": 0,
                "recipient_lookup_success_total": 0,
                "recipient_lookup_failures_total": 0,
                "recipient_count_total": 0,
                "external_send_attempts_total": 0,
                "external_send_success_total": 0,
                "external_send_failures_total": 0,
                "retry_count_total": 0,
                "dropped_count_total": 0,
                "dead_letter_count_total": 0,
                "max_queue_depth": 0,
                "stream_length": 0,
            }

    def register_server_id(self, server_id: str | None) -> None:
        if not server_id:
            return
        with self._lock:
            self._server_ids.add(str(server_id))

    def set_websocket_active(
        self,
        socket_type: str,
        workspace_id: int,
        tab_id: int,
        count: int,
    ) -> None:
        key = (str(socket_type), int(workspace_id), int(tab_id))
        with self._lock:
            if count <= 0:
                self._websocket_active.pop(key, None)
            else:
                self._websocket_active[key] = int(count)

    def record_websocket_broadcast(
        self,
        socket_type: str,
        workspace_id: int,
        tab_id: int,
        *,
        recipient_count: int,
        success_count: int,
        failure_count: int,
        dropped_count: int = 0,
    ) -> None:
        with self._lock:
            self._websocket_counters["broadcasts_total"] += 1
            self._websocket_counters["broadcast_recipients_total"] += max(0, recipient_count)
            self._websocket_counters["send_success_total"] += max(0, success_count)
            self._websocket_counters["send_failures_total"] += max(0, failure_count)
            self._websocket_counters["dropped_connections_total"] += max(0, dropped_count)

    def record_websocket_redis_publish(
        self,
        *,
        batch_size: int,
        latency_seconds: float,
        failed: bool = False,
    ) -> None:
        with self._lock:
            self._websocket_counters["redis_publish_attempts_total"] += 1
            self._websocket_counters["redis_publish_messages_total"] += max(0, batch_size)
            if failed:
                self._websocket_counters["redis_publish_failures_total"] += 1
            self._websocket_redis_lag.observe(latency_seconds)

    def set_sse_subscribers(self, workspace_id: str, count: int) -> None:
        key = str(workspace_id)
        with self._lock:
            if count <= 0:
                self._sse_subscribers.pop(key, None)
            else:
                self._sse_subscribers[key] = int(count)

    def record_sse_delivery(
        self,
        workspace_id: str,
        *,
        target_count: int,
        queue_put_failures: int = 0,
        max_queue_depth: int | None = None,
        queue_drops: int = 0,
    ) -> None:
        with self._lock:
            safe_target_count = max(0, target_count)
            safe_failures = max(0, queue_put_failures)
            self._sse_counters["delivery_attempts_total"] += safe_target_count
            self._sse_counters["event_delivery_count_total"] += max(0, safe_target_count - safe_failures)
            self._sse_counters["queue_put_failures_total"] += safe_failures
            self._sse_counters["queue_drops_total"] += max(0, queue_drops)
            if max_queue_depth is not None:
                self._sse_counters["max_queue_depth"] = max(
                    self._sse_counters["max_queue_depth"],
                    max(0, max_queue_depth),
                )

    def record_sse_stream_xadd(self, *, failed: bool = False) -> None:
        with self._lock:
            self._sse_counters["stream_xadd_attempts_total"] += 1
            if failed:
                self._sse_counters["stream_xadd_failures_total"] += 1

    def record_sse_stream_message(self) -> None:
        with self._lock:
            self._sse_counters["stream_messages_received_total"] += 1

    def record_sse_outbox_inserted(self) -> None:
        with self._lock:
            self._sse_counters["outbox_inserted_total"] += 1

    def record_sse_outbox_published(self) -> None:
        with self._lock:
            self._sse_counters["outbox_published_total"] += 1

    def record_sse_outbox_failed(self) -> None:
        with self._lock:
            self._sse_counters["outbox_failed_total"] += 1

    def set_sse_pending_outbox_count(self, count: int) -> None:
        with self._lock:
            self._sse_counters["pending_outbox_count"] = max(0, int(count))

    def record_sse_replayed_event(self) -> None:
        with self._lock:
            self._sse_counters["replayed_events_total"] += 1

    def record_sse_ack_update(self) -> None:
        with self._lock:
            self._sse_counters["ack_updates_total"] += 1

    def record_sse_duplicate_deduped(self) -> None:
        with self._lock:
            self._sse_counters["duplicate_events_deduped_total"] += 1

    def record_sse_listener_start(self, *, restart: bool = False) -> None:
        with self._lock:
            self._sse_counters["listener_starts_total"] += 1
            if restart:
                self._sse_counters["listener_restarts_total"] += 1

    def record_sse_listener_failure(self) -> None:
        with self._lock:
            self._sse_counters["listener_failures_total"] += 1

    def record_message_save_success(self, lag_seconds: float) -> None:
        with self._lock:
            self._persistence_counters["message_save_success_total"] += 1
            self._message_save_lag.observe(lag_seconds)

    def record_message_save_failure(self, lag_seconds: float) -> None:
        with self._lock:
            self._persistence_counters["message_save_failure_total"] += 1
            self._message_save_lag.observe(lag_seconds)

    def record_message_persistence_enqueue(
        self,
        *,
        success: bool,
        queue_depth: int | None = None,
        full: bool = False,
    ) -> None:
        with self._lock:
            self._persistence_counters["enqueue_attempts_total"] += 1
            if success:
                self._persistence_counters["enqueue_success_total"] += 1
            else:
                self._persistence_counters["enqueue_failures_total"] += 1
                self._persistence_counters["dropped_rejected_count_total"] += 1
                if full:
                    self._persistence_counters["queue_full_rejects_total"] += 1
            if queue_depth is not None:
                self.set_message_persistence_queue_depth(queue_depth)

    def set_message_persistence_queue_depth(self, queue_depth: int) -> None:
        safe_depth = max(0, int(queue_depth))
        with self._lock:
            self._persistence_counters["current_queue_depth"] = safe_depth
            self._persistence_counters["max_queue_depth"] = max(
                self._persistence_counters["max_queue_depth"],
                safe_depth,
            )

    def set_message_persistence_active_workers(self, active_worker_count: int) -> None:
        with self._lock:
            self._persistence_counters["active_worker_count"] = max(0, int(active_worker_count))

    def record_message_persistence_worker_save_started(self, *, queue_wait_seconds: float) -> None:
        with self._lock:
            self._persistence_counters["worker_saves_started_total"] += 1
            self._message_persistence_queue_wait.observe(queue_wait_seconds)

    def record_message_persistence_save_success(
        self,
        *,
        queue_wait_seconds: float | None = None,
        save_duration_seconds: float,
        visibility_lag_seconds: float,
    ) -> None:
        with self._lock:
            self._persistence_counters["worker_save_success_total"] += 1
            self._persistence_counters["message_save_success_total"] += 1
            self._message_persistence_save_duration.observe(save_duration_seconds)
            self._message_persistence_visibility_lag.observe(visibility_lag_seconds)
            self._message_save_lag.observe(visibility_lag_seconds)

    def record_message_persistence_save_failure(
        self,
        *,
        queue_wait_seconds: float | None = None,
        save_duration_seconds: float,
        visibility_lag_seconds: float,
    ) -> None:
        with self._lock:
            self._persistence_counters["worker_save_failure_total"] += 1
            self._persistence_counters["message_save_failure_total"] += 1
            self._persistence_counters["dropped_rejected_count_total"] += 1
            self._message_persistence_save_duration.observe(save_duration_seconds)
            self._message_save_lag.observe(visibility_lag_seconds)

    def record_message_persistence_retry(self) -> None:
        with self._lock:
            self._persistence_counters["retry_count_total"] += 1

    def record_message_persistence_dropped(self, count: int = 1) -> None:
        safe_count = max(0, int(count))
        if safe_count == 0:
            return
        with self._lock:
            self._persistence_counters["dropped_rejected_count_total"] += safe_count

    def record_message_persistence_shutdown_drain_timeout(self) -> None:
        with self._lock:
            self._persistence_counters["shutdown_drain_timeout_total"] += 1

    def record_push_enqueue(self, *, success: bool, stream_length: int | None = None) -> None:
        with self._lock:
            self._push_counters["enqueue_attempts_total"] += 1
            if success:
                self._push_counters["enqueue_success_total"] += 1
            else:
                self._push_counters["enqueue_failures_total"] += 1
            if stream_length is not None:
                self.set_push_queue_depth(stream_length)

    def record_push_job_read(self, *, lag_seconds: float | None = None) -> None:
        with self._lock:
            self._push_counters["jobs_read_total"] += 1
            if lag_seconds is not None:
                self._push_queue_lag.observe(lag_seconds)

    def record_push_recipient_lookup(self, *, success: bool, recipient_count: int = 0) -> None:
        with self._lock:
            if success:
                self._push_counters["recipient_lookup_success_total"] += 1
                self._push_counters["recipient_count_total"] += max(0, recipient_count)
            else:
                self._push_counters["recipient_lookup_failures_total"] += 1

    def record_push_provider_result(
        self,
        *,
        attempts: int,
        successes: int,
        failures: int,
        latency_seconds: float | None = None,
    ) -> None:
        with self._lock:
            self._push_counters["external_send_attempts_total"] += max(0, attempts)
            self._push_counters["external_send_success_total"] += max(0, successes)
            self._push_counters["external_send_failures_total"] += max(0, failures)
            if latency_seconds is not None:
                self._push_provider_latency.observe(latency_seconds)

    def record_push_retry(self) -> None:
        with self._lock:
            self._push_counters["retry_count_total"] += 1

    def record_push_drop(self) -> None:
        with self._lock:
            self._push_counters["dropped_count_total"] += 1

    def record_push_dead_letter(self) -> None:
        with self._lock:
            self._push_counters["dead_letter_count_total"] += 1

    def set_push_queue_depth(self, stream_length: int) -> None:
        safe_length = max(0, int(stream_length))
        with self._lock:
            self._push_counters["stream_length"] = safe_length
            self._push_counters["max_queue_depth"] = max(
                self._push_counters["max_queue_depth"],
                safe_length,
            )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            active_connections = [
                {
                    "socket_type": socket_type,
                    "workspace_id": workspace_id,
                    "tab_id": tab_id,
                    "count": count,
                }
                for (socket_type, workspace_id, tab_id), count in sorted(
                    self._websocket_active.items(),
                    key=lambda item: (item[0][0], item[0][1], item[0][2]),
                )
            ]
            sse_subscribers = [
                {"workspace_id": workspace_id, "count": count}
                for workspace_id, count in sorted(self._sse_subscribers.items())
            ]
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "process": {
                    "pid": os.getpid(),
                    "server_ids": sorted(self._server_ids),
                },
                "websocket": {
                    "active_connections": active_connections,
                    **self._websocket_counters,
                    "redis_publish_lag_seconds": self._websocket_redis_lag.snapshot(),
                },
                "sse": {
                    "subscribers": sse_subscribers,
                    **self._sse_counters,
                },
                "persistence": {
                    **self._persistence_counters,
                    "message_save_lag_seconds": self._message_save_lag.snapshot(),
                    "queue_wait_seconds": self._message_persistence_queue_wait.snapshot(),
                    "db_save_duration_seconds": self._message_persistence_save_duration.snapshot(),
                    "db_visibility_lag_seconds": self._message_persistence_visibility_lag.snapshot(),
                },
                "push": {
                    **self._push_counters,
                    "queue_lag_seconds": self._push_queue_lag.snapshot(),
                    "provider_latency_seconds": self._push_provider_latency.snapshot(),
                },
            }


realtime_observability = RealtimeObservabilityRegistry()
