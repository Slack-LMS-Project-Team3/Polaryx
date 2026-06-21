from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PERF_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PERF_ROOT / "results"
SCENARIO_RE = re.compile(r"^(?P<run_id>.+?)-(?P<scenario>ws-hold|ws-chat|polling|sse|push)-(?P<users>\d+)u")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def metric_value(metrics: dict[str, Any], metric_name: str, value_name: str) -> Any:
    metric = metrics.get(metric_name)
    if not isinstance(metric, dict):
        return None
    values = metric.get("values")
    if isinstance(values, dict) and value_name in values:
        return values.get(value_name)
    return metric.get(value_name)


def fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def fmt_signed(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number.is_integer():
        return f"{int(number):+d}"
    return f"{number:+.2f}"


def fmt_seconds(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.2f}s"
    except (TypeError, ValueError):
        return f"{value}s"


def pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def infer_from_name(path: Path) -> dict[str, Any]:
    match = SCENARIO_RE.search(path.name)
    if not match:
        return {"run_id": "-", "scenario": "unknown", "users": "-"}
    return {
        "run_id": match.group("run_id"),
        "scenario": match.group("scenario"),
        "users": int(match.group("users")),
    }


def metadata_for(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def runtime_label(metadata: dict[str, Any]) -> str:
    value = metadata.get("runtime_label") or metadata.get("worker_label")
    return str(value) if value else "-"


def base_row(path: Path, data: dict[str, Any], tool: str) -> dict[str, Any]:
    metadata = metadata_for(data)
    inferred = infer_from_name(path)
    return {
        "run_id": metadata.get("run_id", inferred["run_id"]),
        "runtime": runtime_label(metadata),
        "file": path.name,
        "tool": metadata.get("tool", tool),
        "scenario": metadata.get("scenario", inferred["scenario"]),
        "users": metadata.get("users", metadata.get("vus", inferred["users"])),
        "observability": summarize_observability(path, data),
    }


def resolve_snapshot_path(result_path: Path, value: Any) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value))
    if candidate.is_absolute():
        return candidate
    return result_path.parent / candidate


def load_observability_snapshot(result_path: Path, metadata: dict[str, Any], phase: str) -> dict[str, Any] | None:
    phase_metadata = metadata.get(phase)
    if not isinstance(phase_metadata, dict):
        return None
    snapshot_path = resolve_snapshot_path(result_path, phase_metadata.get("snapshot_file"))
    if snapshot_path is None:
        return None
    return load_json(snapshot_path)


def delta(after: dict[str, Any], before: dict[str, Any], *keys: str) -> Any:
    after_value = get_nested(after, *keys)
    before_value = get_nested(before, *keys)
    if after_value is None or before_value is None:
        return None
    try:
        return float(after_value) - float(before_value)
    except (TypeError, ValueError):
        return None


def same_process_snapshot(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_pid = get_nested(before, "process", "pid")
    after_pid = get_nested(after, "process", "pid")
    before_server_ids = get_nested(before, "process", "server_ids")
    after_server_ids = get_nested(after, "process", "server_ids")
    return before_pid == after_pid and before_server_ids == after_server_ids


def summarize_observability(result_path: Path, data: dict[str, Any]) -> str:
    metadata = metadata_for(data).get("observability")
    if not isinstance(metadata, dict):
        return "-"

    errors = []
    for phase in ("before", "after"):
        phase_metadata = metadata.get(phase)
        if isinstance(phase_metadata, dict) and phase_metadata.get("error"):
            errors.append(f"{phase}: {phase_metadata['error']}")
    if errors:
        return "obs_error " + "; ".join(errors)

    before = load_observability_snapshot(result_path, metadata, "before")
    after = load_observability_snapshot(result_path, metadata, "after")
    if before is None or after is None:
        before_file = get_nested(metadata, "before", "snapshot_file")
        after_file = get_nested(metadata, "after", "snapshot_file")
        if before_file or after_file:
            return f"snapshots: {Path(str(before_file)).name if before_file else '-'} -> {Path(str(after_file)).name if after_file else '-'}"
        return "-"
    if not same_process_snapshot(before, after):
        before_pid = get_nested(before, "process", "pid")
        after_pid = get_nested(after, "process", "pid")
        before_server_ids = get_nested(before, "process", "server_ids")
        after_server_ids = get_nested(after, "process", "server_ids")
        return (
            "obs_error process changed "
            f"before_pid={before_pid} before_servers={before_server_ids} "
            f"after_pid={after_pid} after_servers={after_server_ids}"
        )

    parts = [
        f"ws_recips {fmt_signed(delta(after, before, 'websocket', 'broadcast_recipients_total'))}",
        f"ws_fail {fmt_signed(delta(after, before, 'websocket', 'send_failures_total'))}",
        f"redis_fail {fmt_signed(delta(after, before, 'websocket', 'redis_publish_failures_total'))}",
        f"sse_attempts {fmt_signed(delta(after, before, 'sse', 'delivery_attempts_total'))}",
        f"sse_queue_fail {fmt_signed(delta(after, before, 'sse', 'queue_put_failures_total'))}",
        f"sse_queue_drop {fmt_signed(delta(after, before, 'sse', 'queue_drops_total'))}",
        f"sse_delivered {fmt_signed(delta(after, before, 'sse', 'event_delivery_count_total'))}",
        f"sse_outbox_insert {fmt_signed(delta(after, before, 'sse', 'outbox_inserted_total'))}",
        f"sse_outbox_pub {fmt_signed(delta(after, before, 'sse', 'outbox_published_total'))}",
        f"sse_outbox_fail {fmt_signed(delta(after, before, 'sse', 'outbox_failed_total'))}",
        f"sse_stream_xadd {fmt_signed(delta(after, before, 'sse', 'stream_xadd_attempts_total'))}",
        f"sse_stream_fail {fmt_signed(delta(after, before, 'sse', 'stream_xadd_failures_total'))}",
        f"sse_stream_recv {fmt_signed(delta(after, before, 'sse', 'stream_messages_received_total'))}",
        f"sse_replayed {fmt_signed(delta(after, before, 'sse', 'replayed_events_total'))}",
        f"sse_ack {fmt_signed(delta(after, before, 'sse', 'ack_updates_total'))}",
        f"sse_dedupe {fmt_signed(delta(after, before, 'sse', 'duplicate_events_deduped_total'))}",
        "db_save {}/{}".format(
            fmt_signed(delta(after, before, "persistence", "message_save_success_total")),
            fmt_signed(delta(after, before, "persistence", "message_save_failure_total")),
        ),
    ]
    if (
        get_nested(after, "persistence", "enqueue_attempts_total") is not None
        or get_nested(before, "persistence", "enqueue_attempts_total") is not None
    ):
        parts.extend(
            [
                "persist_enqueue {}/{}".format(
                    fmt_signed(delta(after, before, "persistence", "enqueue_success_total")),
                    fmt_signed(delta(after, before, "persistence", "enqueue_failures_total")),
                ),
                f"persist_full {fmt_signed(delta(after, before, 'persistence', 'queue_full_rejects_total'))}",
                f"persist_worker_start {fmt_signed(delta(after, before, 'persistence', 'worker_saves_started_total'))}",
                "persist_worker_save {}/{}".format(
                    fmt_signed(delta(after, before, "persistence", "worker_save_success_total")),
                    fmt_signed(delta(after, before, "persistence", "worker_save_failure_total")),
                ),
                f"persist_retry {fmt_signed(delta(after, before, 'persistence', 'retry_count_total'))}",
                f"persist_drop_reject {fmt_signed(delta(after, before, 'persistence', 'dropped_rejected_count_total'))}",
                f"persist_qmax {fmt_number(get_nested(after, 'persistence', 'max_queue_depth'), 0)}",
                f"persist_shutdown_timeout {fmt_signed(delta(after, before, 'persistence', 'shutdown_drain_timeout_total'))}",
            ]
        )
        for label, path in (
            ("queue_wait_p95", ("persistence", "queue_wait_seconds", "p95")),
            ("queue_wait_p99", ("persistence", "queue_wait_seconds", "p99")),
            ("db_save_p95", ("persistence", "db_save_duration_seconds", "p95")),
            ("db_save_p99", ("persistence", "db_save_duration_seconds", "p99")),
            ("db_visible_p50", ("persistence", "db_visibility_lag_seconds", "p50")),
            ("db_visible_p95", ("persistence", "db_visibility_lag_seconds", "p95")),
            ("db_visible_p99", ("persistence", "db_visibility_lag_seconds", "p99")),
        ):
            rendered = fmt_seconds(get_nested(after, *path))
            if rendered is not None:
                parts.append(f"{label} {rendered}")
    if isinstance(get_nested(after, "push"), dict) or isinstance(get_nested(before, "push"), dict):
        parts.extend(
            [
                f"push_enqueue {fmt_signed(delta(after, before, 'push', 'enqueue_success_total'))}",
                f"push_enqueue_fail {fmt_signed(delta(after, before, 'push', 'enqueue_failures_total'))}",
                f"push_jobs_read {fmt_signed(delta(after, before, 'push', 'jobs_read_total'))}",
                f"push_recipient_lookup {fmt_signed(delta(after, before, 'push', 'recipient_lookup_success_total'))}",
                f"push_recipient_lookup_fail {fmt_signed(delta(after, before, 'push', 'recipient_lookup_failures_total'))}",
                f"push_recipient_count {fmt_signed(delta(after, before, 'push', 'recipient_count_total'))}",
                f"push_send_attempts {fmt_signed(delta(after, before, 'push', 'external_send_attempts_total'))}",
                f"push_send_success {fmt_signed(delta(after, before, 'push', 'external_send_success_total'))}",
                f"push_send_fail {fmt_signed(delta(after, before, 'push', 'external_send_failures_total'))}",
                f"push_retry {fmt_signed(delta(after, before, 'push', 'retry_count_total'))}",
                f"push_drop {fmt_signed(delta(after, before, 'push', 'dropped_count_total'))}",
                f"push_dead {fmt_signed(delta(after, before, 'push', 'dead_letter_count_total'))}",
            ]
        )
        push_lag_p95 = get_nested(after, "push", "queue_lag_seconds", "p95")
        push_lag_max = get_nested(after, "push", "queue_lag_seconds", "max")
        if push_lag_p95 is not None:
            try:
                parts.append(f"push_lag_p95 {float(push_lag_p95):.2f}s")
            except (TypeError, ValueError):
                parts.append(f"push_lag_p95 {push_lag_p95}s")
        if push_lag_max is not None:
            try:
                parts.append(f"push_lag_max {float(push_lag_max):.2f}s")
            except (TypeError, ValueError):
                parts.append(f"push_lag_max {push_lag_max}s")
    lag_p95 = get_nested(after, "persistence", "message_save_lag_seconds", "p95")
    if lag_p95 is not None:
        try:
            parts.append(f"db_lag_p95 {float(lag_p95):.2f}s")
        except (TypeError, ValueError):
            parts.append(f"db_lag_p95 {lag_p95}s")
    return "; ".join(parts)


def summarize_k6(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    metrics = data.get("metrics", {})
    p95_value = metric_value(metrics, "ws_delivery_ms", "p(95)")
    p99_value = metric_value(metrics, "ws_delivery_ms", "p(99)")
    max_value = metric_value(metrics, "ws_delivery_ms", "max")
    if p95_value is None:
        p95_value = metric_value(metrics, "ws_session_duration_ms", "p(95)")
    if p99_value is None:
        p99_value = metric_value(metrics, "ws_session_duration_ms", "p(99)")
    if max_value is None:
        max_value = metric_value(metrics, "ws_session_duration_ms", "max")
    return {
        **base_row(path, data, "k6"),
        "connect": pct(metric_value(metrics, "ws_connect_success", "rate") or metric_value(metrics, "ws_connect_success", "value")),
        "maintain": pct(metric_value(metrics, "ws_maintain_success", "rate") or metric_value(metrics, "ws_maintain_success", "value")),
        "errors": fmt_number(metric_value(metrics, "ws_errors", "count"), 0),
        "p95_ms": fmt_number(p95_value),
        "p99_ms": fmt_number(p99_value),
        "max_ms": fmt_number(max_value),
        "requests": fmt_number(metric_value(metrics, "ws_send_count", "count"), 0),
    }


def locust_stats(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        stats = data
    elif isinstance(data, dict):
        stats = data.get("stats") if isinstance(data.get("stats"), list) else []
    else:
        stats = []
    for item in stats:
        if item.get("name") == "Aggregated":
            return item
    return stats[-1] if stats else {}


def locust_stats_named(data: Any, name: str) -> dict[str, Any]:
    if isinstance(data, list):
        stats = data
    elif isinstance(data, dict):
        stats = data.get("stats") if isinstance(data.get("stats"), list) else []
    else:
        stats = []
    for item in stats:
        if item.get("name") == name:
            return item
    return {}


def locust_percentile(stats: dict[str, Any], percentile: float) -> Any:
    for key in (
        f"response_time_percentile_{percentile}",
        f"response_time_percentile_{percentile:.2f}",
    ):
        if key in stats:
            return stats.get(key)

    response_times = stats.get("response_times")
    if not isinstance(response_times, dict):
        return None

    total = 0
    buckets: list[tuple[float, int]] = []
    for raw_time, raw_count in response_times.items():
        try:
            time_value = float(raw_time)
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        total += count
        buckets.append((time_value, count))
    if total <= 0:
        return None

    threshold = total * percentile
    seen = 0
    for time_value, count in sorted(buckets):
        seen += count
        if seen >= threshold:
            return time_value
    return buckets[-1][0] if buckets else None


def summarize_locust(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    locust = data.get("locust", {})
    stats = locust_stats(locust)
    base = base_row(path, data, "locust")
    sse_event_latency = locust_stats_named(locust, "SSE event latency")
    latency_stats = sse_event_latency or stats
    sse_extra = summarize_sse_locust_stats(locust)
    if sse_extra != "-":
        base["observability"] = (
            sse_extra
            if base["observability"] == "-"
            else f"{base['observability']}; {sse_extra}"
        )
    push_extra = summarize_push_locust_stats(locust)
    if push_extra != "-":
        base["observability"] = (
            push_extra
            if base["observability"] == "-"
            else f"{base['observability']}; {push_extra}"
        )
    return {
        **base,
        "connect": "-",
        "maintain": "-",
        "errors": fmt_number(stats.get("num_failures"), 0),
        "p95_ms": fmt_number(locust_percentile(latency_stats, 0.95)),
        "p99_ms": fmt_number(locust_percentile(latency_stats, 0.99)),
        "max_ms": fmt_number(latency_stats.get("max_response_time")),
        "requests": fmt_number(stats.get("num_requests"), 0),
    }


def summarize_sse_locust_stats(locust: Any) -> str:
    event_latency = locust_stats_named(locust, "SSE event latency")
    published_event = locust_stats_named(locust, "SSE published event")
    received_unique = locust_stats_named(locust, "SSE received unique event")
    acked_event = locust_stats_named(locust, "SSE acked event")
    replayed_event = locust_stats_named(locust, "SSE replayed event")
    duplicate_event = locust_stats_named(locust, "SSE duplicate event")
    reconnect = locust_stats_named(locust, "SSE reconnect")
    stream_failure = locust_stats_named(locust, "SSE stream failure")
    missing_after_replay = locust_stats_named(locust, "SSE missing after replay count")
    zero_window = locust_stats_named(locust, "SSE zero-event listener window")
    if not any(
        (
            event_latency,
            published_event,
            received_unique,
            acked_event,
            replayed_event,
            duplicate_event,
            reconnect,
            stream_failure,
            missing_after_replay,
            zero_window,
        )
    ):
        return "-"

    event_p95 = locust_percentile(event_latency, 0.95) if event_latency else None
    parts = [
        f"sse_event_p95 {fmt_number(event_p95)}ms",
        f"sse_published {fmt_number(published_event.get('num_requests'), 0)}",
        f"sse_received_unique {fmt_number(received_unique.get('num_requests'), 0)}",
        f"sse_acked {fmt_number(acked_event.get('num_requests'), 0)}",
        f"sse_replayed {fmt_number(replayed_event.get('num_requests'), 0)}",
        f"sse_duplicate {fmt_number(duplicate_event.get('num_requests'), 0)}",
        f"sse_reconnects {fmt_number(reconnect.get('num_requests'), 0)}",
        f"sse_stream_failures {fmt_number(stream_failure.get('num_failures'), 0)}",
        f"sse_missing_after_replay {fmt_number(missing_after_replay.get('max_response_time'), 0)}",
        f"sse_zero_windows {fmt_number(zero_window.get('num_failures'), 0)}",
    ]
    return "; ".join(parts)


def summarize_push_locust_stats(locust: Any) -> str:
    enqueue = locust_stats_named(locust, "POST /api/notifications enqueue")
    accepted = locust_stats_named(locust, "Web Push enqueue accepted")
    if not any((enqueue, accepted)):
        return "-"

    enqueue_p95 = locust_percentile(enqueue, 0.95) if enqueue else None
    parts = [
        f"push_http_requests {fmt_number(enqueue.get('num_requests'), 0)}",
        f"push_http_failures {fmt_number(enqueue.get('num_failures'), 0)}",
        f"push_http_p95 {fmt_number(enqueue_p95)}ms",
        f"push_accepted {fmt_number(accepted.get('num_requests'), 0)}",
    ]
    return "; ".join(parts)


def summarize_file(path: Path) -> dict[str, Any] | None:
    data = load_json(path)
    if data is None:
        return None
    if "locust" in data:
        return summarize_locust(path, data)
    if "metrics" in data:
        return summarize_k6(path, data)
    return None


def row_matches_filters(row: dict[str, Any], run_id: str | None, runtime: str | None) -> bool:
    if run_id and row["run_id"] != run_id:
        return False
    if runtime and row["runtime"] != runtime:
        return False
    return True


def build_markdown(
    rows: list[dict[str, Any]],
    source_dir: Path,
    run_id: str | None = None,
    runtime: str | None = None,
) -> str:
    filter_parts = []
    if run_id:
        filter_parts.append(f"run_id={run_id}")
    if runtime:
        filter_parts.append(f"runtime_label={runtime}")

    lines = [
        "# Performance Matrix Summary",
        "",
        f"- Generated at: {datetime.now(timezone.utc).isoformat()}",
        f"- Source directory: `{source_dir}`",
        f"- Filters: {', '.join(filter_parts) if filter_parts else 'none'}",
        "",
        "| Run ID | Runtime | Tool | Scenario | Users | Connect | Maintain | Errors | p95 ms | p99 ms | Max ms | Requests/Send Count | Observability | Source File |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {run_id} | {runtime} | {tool} | {scenario} | {users} | {connect} | {maintain} | {errors} | {p95_ms} | {p99_ms} | {max_ms} | {requests} | {observability} | {file} |".format(
                **row
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Markdown summary from k6 and Locust JSON results.")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "summary.md")
    parser.add_argument("--run-id")
    parser.add_argument("--runtime-label")
    args = parser.parse_args()

    rows = []
    for path in sorted(args.results_dir.glob("*.json")):
        row = summarize_file(path)
        if row and row_matches_filters(row, args.run_id, args.runtime_label):
            rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        build_markdown(rows, args.results_dir, args.run_id, args.runtime_label),
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
