from __future__ import annotations

import os
import unittest
from datetime import datetime

from app.service.realtime_observability import RealtimeObservabilityRegistry


class RealtimeObservabilityRegistryTest(unittest.TestCase):
    def test_snapshot_contains_process_sections_and_sorted_server_ids(self) -> None:
        registry = RealtimeObservabilityRegistry()
        registry.register_server_id("worker-b")
        registry.register_server_id("worker-a")

        snapshot = registry.snapshot()

        datetime.fromisoformat(snapshot["generated_at"])
        self.assertEqual(snapshot["process"]["pid"], os.getpid())
        self.assertEqual(snapshot["process"]["server_ids"], ["worker-a", "worker-b"])
        self.assertIn("websocket", snapshot)
        self.assertIn("sse", snapshot)
        self.assertIn("persistence", snapshot)
        self.assertIn("push", snapshot)

    def test_websocket_metrics_track_active_counts_and_broadcast_counters(self) -> None:
        registry = RealtimeObservabilityRegistry()

        registry.set_websocket_active("message", 1, 2, 3)
        registry.record_websocket_broadcast(
            "message",
            1,
            2,
            recipient_count=3,
            success_count=2,
            failure_count=1,
            dropped_count=1,
        )
        registry.record_websocket_redis_publish(batch_size=4, latency_seconds=0.25)
        registry.record_websocket_redis_publish(batch_size=2, latency_seconds=0.5, failed=True)
        registry.set_websocket_active("message", 1, 2, 0)

        websocket = registry.snapshot()["websocket"]

        self.assertEqual(websocket["active_connections"], [])
        self.assertEqual(websocket["broadcasts_total"], 1)
        self.assertEqual(websocket["broadcast_recipients_total"], 3)
        self.assertEqual(websocket["send_success_total"], 2)
        self.assertEqual(websocket["send_failures_total"], 1)
        self.assertEqual(websocket["dropped_connections_total"], 1)
        self.assertEqual(websocket["redis_publish_attempts_total"], 2)
        self.assertEqual(websocket["redis_publish_messages_total"], 6)
        self.assertEqual(websocket["redis_publish_failures_total"], 1)
        self.assertEqual(websocket["redis_publish_lag_seconds"]["count"], 2)

    def test_sse_metrics_track_subscribers_delivery_attempts_and_queue_depth(self) -> None:
        registry = RealtimeObservabilityRegistry()

        registry.set_sse_subscribers("1", 2)
        registry.record_sse_delivery(
            "1",
            target_count=2,
            queue_put_failures=1,
            max_queue_depth=5,
            queue_drops=1,
        )
        registry.record_sse_outbox_inserted()
        registry.record_sse_outbox_published()
        registry.record_sse_outbox_failed()
        registry.set_sse_pending_outbox_count(7)
        registry.record_sse_stream_xadd()
        registry.record_sse_stream_xadd(failed=True)
        registry.record_sse_stream_message()
        registry.record_sse_replayed_event()
        registry.record_sse_ack_update()
        registry.record_sse_duplicate_deduped()
        registry.record_sse_listener_start()
        registry.record_sse_listener_start(restart=True)
        registry.record_sse_listener_failure()
        registry.set_sse_subscribers("2", 1)

        sse = registry.snapshot()["sse"]

        self.assertEqual(
            sse["subscribers"],
            [{"workspace_id": "1", "count": 2}, {"workspace_id": "2", "count": 1}],
        )
        self.assertEqual(sse["delivery_attempts_total"], 2)
        self.assertEqual(sse["event_delivery_count_total"], 1)
        self.assertEqual(sse["queue_put_failures_total"], 1)
        self.assertEqual(sse["queue_drops_total"], 1)
        self.assertEqual(sse["max_queue_depth"], 5)
        self.assertEqual(sse["outbox_inserted_total"], 1)
        self.assertEqual(sse["outbox_published_total"], 1)
        self.assertEqual(sse["outbox_failed_total"], 1)
        self.assertEqual(sse["pending_outbox_count"], 7)
        self.assertEqual(sse["stream_xadd_attempts_total"], 2)
        self.assertEqual(sse["stream_xadd_failures_total"], 1)
        self.assertEqual(sse["stream_messages_received_total"], 1)
        self.assertEqual(sse["replayed_events_total"], 1)
        self.assertEqual(sse["ack_updates_total"], 1)
        self.assertEqual(sse["duplicate_events_deduped_total"], 1)
        self.assertEqual(sse["listener_starts_total"], 2)
        self.assertEqual(sse["listener_restarts_total"], 1)
        self.assertEqual(sse["listener_failures_total"], 1)

    def test_persistence_timing_samples_are_bounded_and_resettable(self) -> None:
        registry = RealtimeObservabilityRegistry(sample_limit=3)

        registry.record_message_save_success(0.10)
        registry.record_message_save_failure(0.20)
        registry.record_message_save_success(0.30)
        registry.record_message_save_success(0.40)

        persistence = registry.snapshot()["persistence"]

        self.assertEqual(persistence["message_save_success_total"], 3)
        self.assertEqual(persistence["message_save_failure_total"], 1)
        self.assertEqual(persistence["message_save_lag_seconds"]["count"], 4)
        self.assertEqual(persistence["message_save_lag_seconds"]["latest"], 0.40)
        self.assertEqual(persistence["message_save_lag_seconds"]["max"], 0.40)
        self.assertEqual(persistence["message_save_lag_seconds"]["sample_count"], 3)
        self.assertGreaterEqual(persistence["message_save_lag_seconds"]["p50"], 0.30)
        self.assertGreaterEqual(persistence["message_save_lag_seconds"]["p95"], 0.30)
        self.assertGreaterEqual(persistence["message_save_lag_seconds"]["p99"], 0.30)

        registry.reset()

        reset_snapshot = registry.snapshot()
        self.assertEqual(reset_snapshot["persistence"]["message_save_success_total"], 0)
        self.assertEqual(reset_snapshot["persistence"]["message_save_lag_seconds"]["count"], 0)

    def test_persistence_queue_metrics_are_additive_and_resettable(self) -> None:
        registry = RealtimeObservabilityRegistry(sample_limit=3)

        registry.record_message_persistence_enqueue(success=True, queue_depth=1)
        registry.record_message_persistence_enqueue(
            success=False,
            queue_depth=3,
            full=True,
        )
        registry.record_message_persistence_worker_save_started(queue_wait_seconds=0.10)
        registry.record_message_persistence_save_success(
            queue_wait_seconds=0.10,
            save_duration_seconds=0.20,
            visibility_lag_seconds=0.30,
        )
        registry.record_message_persistence_save_failure(
            queue_wait_seconds=0.15,
            save_duration_seconds=0.25,
            visibility_lag_seconds=0.40,
        )
        registry.record_message_persistence_retry()
        registry.record_message_persistence_dropped(2)
        registry.record_message_persistence_shutdown_drain_timeout()
        registry.set_message_persistence_active_workers(2)

        persistence = registry.snapshot()["persistence"]

        self.assertEqual(persistence["message_save_success_total"], 1)
        self.assertEqual(persistence["message_save_failure_total"], 1)
        self.assertEqual(persistence["enqueue_attempts_total"], 2)
        self.assertEqual(persistence["enqueue_success_total"], 1)
        self.assertEqual(persistence["enqueue_failures_total"], 1)
        self.assertEqual(persistence["queue_full_rejects_total"], 1)
        self.assertEqual(persistence["worker_saves_started_total"], 1)
        self.assertEqual(persistence["worker_save_success_total"], 1)
        self.assertEqual(persistence["worker_save_failure_total"], 1)
        self.assertEqual(persistence["retry_count_total"], 1)
        self.assertEqual(persistence["dropped_rejected_count_total"], 4)
        self.assertEqual(persistence["current_queue_depth"], 3)
        self.assertEqual(persistence["max_queue_depth"], 3)
        self.assertEqual(persistence["active_worker_count"], 2)
        self.assertEqual(persistence["shutdown_drain_timeout_total"], 1)
        self.assertEqual(persistence["queue_wait_seconds"]["count"], 1)
        self.assertEqual(persistence["db_save_duration_seconds"]["count"], 2)
        self.assertEqual(persistence["db_visibility_lag_seconds"]["count"], 1)
        self.assertGreaterEqual(persistence["db_visibility_lag_seconds"]["p99"], 0.30)

        registry.reset()

        reset_persistence = registry.snapshot()["persistence"]
        self.assertEqual(reset_persistence["enqueue_attempts_total"], 0)
        self.assertEqual(reset_persistence["current_queue_depth"], 0)
        self.assertEqual(reset_persistence["queue_wait_seconds"]["count"], 0)

    def test_push_metrics_track_enqueue_provider_retry_drop_and_lag(self) -> None:
        registry = RealtimeObservabilityRegistry(sample_limit=3)

        registry.record_push_enqueue(success=True, stream_length=4)
        registry.record_push_enqueue(success=False)
        registry.record_push_job_read(lag_seconds=0.10)
        registry.record_push_job_read(lag_seconds=0.25)
        registry.record_push_recipient_lookup(success=True, recipient_count=3)
        registry.record_push_recipient_lookup(success=False)
        registry.record_push_provider_result(
            attempts=3,
            successes=2,
            failures=1,
            latency_seconds=0.40,
        )
        registry.record_push_retry()
        registry.record_push_drop()
        registry.record_push_dead_letter()
        registry.set_push_queue_depth(2)

        push = registry.snapshot()["push"]

        self.assertEqual(push["enqueue_attempts_total"], 2)
        self.assertEqual(push["enqueue_success_total"], 1)
        self.assertEqual(push["enqueue_failures_total"], 1)
        self.assertEqual(push["jobs_read_total"], 2)
        self.assertEqual(push["recipient_lookup_success_total"], 1)
        self.assertEqual(push["recipient_lookup_failures_total"], 1)
        self.assertEqual(push["recipient_count_total"], 3)
        self.assertEqual(push["external_send_attempts_total"], 3)
        self.assertEqual(push["external_send_success_total"], 2)
        self.assertEqual(push["external_send_failures_total"], 1)
        self.assertEqual(push["retry_count_total"], 1)
        self.assertEqual(push["dropped_count_total"], 1)
        self.assertEqual(push["dead_letter_count_total"], 1)
        self.assertEqual(push["stream_length"], 2)
        self.assertEqual(push["max_queue_depth"], 4)
        self.assertEqual(push["queue_lag_seconds"]["count"], 2)
        self.assertEqual(push["provider_latency_seconds"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
