from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


PERF_ROOT = Path(__file__).resolve().parents[1]
BE_ROOT = PERF_ROOT.parents[1]
RESULTS_DIR = PERF_ROOT / "results"
DEFAULT_VUS = "100,300,500"
DEFAULT_CHAT_RATIOS = "0.01,0.05,0.10"
DEFAULT_CHAT_INTERVALS = "10,5,2,1"


@dataclass(frozen=True)
class ObservabilityConfig:
    url: str
    token: str | None
    auth_source: str


def parse_int_list(value: str) -> list[int]:
    parsed = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not parsed:
        raise argparse.ArgumentTypeError("must contain at least one integer")
    return parsed


def parse_float_list(value: str) -> list[float]:
    parsed = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not parsed:
        raise argparse.ArgumentTypeError("must contain at least one number")
    return parsed


def parse_scenario_list(value: str) -> set[str]:
    allowed = {"ws-hold", "ws-chat", "polling", "sse", "push"}
    selected = {item.strip() for item in value.split(",") if item.strip()}
    unknown = selected - allowed
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown scenario(s): {', '.join(sorted(unknown))}")
    return selected or allowed


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ratio_label(value: float) -> str:
    return f"{round(value * 100):g}pct"


def command_to_text(command: list[str]) -> str:
    return " ".join(command)


def completed_metadata(
    metadata: dict[str, object],
    command: list[str],
    exit_code: int,
    started_at: str,
    started_monotonic: float,
) -> dict[str, object]:
    return {
        **metadata,
        "started_at": started_at,
        "finished_at": now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started_monotonic, 3),
        "exit_code": exit_code,
        "command": command,
    }


def load_json_object(path: Path) -> tuple[dict[str, object], str | None]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"summary export missing: {exc}"

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return {"raw_summary": raw_text}, f"summary export invalid JSON: {exc}"

    if isinstance(payload, dict):
        return payload, None
    return {"raw_summary": payload}, "summary export was not a JSON object"


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture_observability_token(users_file: Path) -> str | None:
    try:
        payload = json.loads(users_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    users = payload.get("users")
    if not isinstance(users, list) or not users:
        return None
    first_user = users[0]
    if not isinstance(first_user, dict):
        return None
    token = first_user.get("access_token")
    return str(token) if token else None


def build_observability_config(
    observability_url: str | None,
    observability_token: str | None,
    users_file: Path,
) -> ObservabilityConfig | None:
    if not observability_url:
        return None
    if observability_token:
        return ObservabilityConfig(observability_url, observability_token, "explicit")
    fixture_token = fixture_observability_token(users_file)
    return ObservabilityConfig(observability_url, fixture_token, "fixture" if fixture_token else "missing")


def observability_snapshot_path(output_file: Path, phase: str) -> Path:
    return output_file.with_name(f"{output_file.stem}.observability-{phase}.json")


def capture_observability_snapshot(
    config: ObservabilityConfig,
    output_file: Path,
    phase: str,
) -> dict[str, object]:
    snapshot_path = observability_snapshot_path(output_file, phase)
    metadata: dict[str, object] = {
        "captured_at": now_iso(),
        "phase": phase,
        "snapshot_file": str(snapshot_path),
        "url": config.url,
    }
    parsed = urlparse(config.url)
    headers = {"Accept": "application/json"}
    if parsed.scheme in {"http", "https"}:
        if not config.token:
            metadata["error"] = "missing observability bearer token"
            return metadata
        headers["Authorization"] = f"Bearer {config.token}"

    try:
        request = urllib.request.Request(config.url, headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            raw_body = response.read().decode("utf-8")
            metadata["status_code"] = response.getcode()
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            payload = {"snapshot": payload}
        write_json(snapshot_path, payload)
    except Exception as exc:
        metadata["error"] = f"{exc.__class__.__name__}: {exc}"
    return metadata


def capture_observability_metadata(
    config: ObservabilityConfig | None,
    output_file: Path,
    phase: str,
    dry_run: bool,
) -> dict[str, object] | None:
    if config is None or dry_run:
        return None
    return capture_observability_snapshot(config, output_file, phase)


def run_k6_command(
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    output_file: Path,
    metadata: dict[str, object],
    dry_run: bool,
    observability_config: ObservabilityConfig | None = None,
) -> int:
    print(command_to_text(command))
    if dry_run:
        return 0

    if output_file.exists():
        output_file.unlink()

    started_at = now_iso()
    started_monotonic = time.perf_counter()
    observability_before = capture_observability_metadata(observability_config, output_file, "before", dry_run)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    observability_after = capture_observability_metadata(observability_config, output_file, "after", dry_run)
    payload, summary_error = load_json_object(output_file)
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        payload["metrics"] = {}
    if summary_error:
        payload["summary_export_error"] = summary_error
    if observability_config:
        metadata = {
            **metadata,
            "observability": {
                "auth_source": observability_config.auth_source,
                "before": observability_before,
                "after": observability_after,
            },
        }
    payload["metadata"] = completed_metadata(
        metadata,
        command,
        completed.returncode,
        started_at,
        started_monotonic,
    )
    write_json(output_file, payload)
    return completed.returncode


def run_locust_command(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    output_file: Path,
    metadata: dict[str, object],
    dry_run: bool,
    observability_config: ObservabilityConfig | None = None,
) -> int:
    print(f"{command_to_text(command)} > {output_file}")
    if dry_run:
        return 0

    started_at = now_iso()
    started_monotonic = time.perf_counter()
    observability_before = capture_observability_metadata(observability_config, output_file, "before", dry_run)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    observability_after = capture_observability_metadata(observability_config, output_file, "after", dry_run)

    payload: object
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"raw_stdout": completed.stdout}

    write_json(
        output_file,
        {
            "metadata": completed_metadata(
                {
                    **metadata,
                    **(
                        {
                            "observability": {
                                "auth_source": observability_config.auth_source,
                                "before": observability_before,
                                "after": observability_after,
                            }
                        }
                        if observability_config
                        else {}
                    ),
                },
                command,
                completed.returncode,
                started_at,
                started_monotonic,
            ),
            "locust": payload,
        },
    )

    if completed.stderr:
        output_file.with_suffix(".stderr.log").write_text(completed.stderr, encoding="utf-8")

    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Polaryx performance matrices and store machine-readable results."
    )
    parser.add_argument("--vus", type=parse_int_list, default=parse_int_list(DEFAULT_VUS))
    parser.add_argument("--scenarios", type=parse_scenario_list, default=parse_scenario_list("ws-hold,polling,sse"))
    parser.add_argument("--run-id", default=timestamp())
    parser.add_argument("--runtime-label", default=os.getenv("PERF_RUNTIME_LABEL", "unspecified"))
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--host", default=os.getenv("PERF_HOST", "http://localhost:8000"))
    parser.add_argument("--ws-base-url", default=os.getenv("WS_BASE_URL", "ws://localhost:8000/api/ws"))
    parser.add_argument("--users-file", default=str(PERF_ROOT / "fixtures" / "users.local.json"))
    parser.add_argument("--k6-bin", default=os.getenv("K6_BIN", "k6"))
    parser.add_argument("--locust-bin", default=os.getenv("LOCUST_BIN", str(BE_ROOT / ".venv" / "bin" / "locust")))
    parser.add_argument("--ws-duration", default=os.getenv("WS_DURATION", "10m"))
    parser.add_argument("--locust-run-time", default=os.getenv("LOCUST_RUN_TIME", "5m"))
    parser.add_argument("--spawn-rate", type=float, default=float(os.getenv("LOCUST_SPAWN_RATE", "25")))
    parser.add_argument("--chat-ratios", type=parse_float_list, default=parse_float_list(DEFAULT_CHAT_RATIOS))
    parser.add_argument("--chat-intervals", type=parse_int_list, default=parse_int_list(DEFAULT_CHAT_INTERVALS))
    parser.add_argument("--observability-url", default=os.getenv("PERF_OBSERVABILITY_URL"))
    parser.add_argument("--observability-token", default=os.getenv("PERF_OBSERVABILITY_TOKEN"))
    parser.add_argument("--poll-before-id", default=os.getenv("POLL_BEFORE_ID"))
    parser.add_argument(
        "--poll-before-ratio",
        type=float,
        default=float(os.getenv("POLL_BEFORE_RATIO")) if os.getenv("POLL_BEFORE_RATIO") else None,
    )
    parser.add_argument(
        "--sse-publish",
        action="store_true",
        help="Run SSE listeners together with SsePublisherUser for published-event delivery validation.",
    )
    parser.add_argument(
        "--sse-publisher-users",
        type=int,
        default=int(os.getenv("SSE_PUBLISHER_USERS", "1")),
        help="Number of fixed SsePublisherUser instances to add when --sse-publish is enabled.",
    )
    parser.add_argument("--push-provider-mode", default=os.getenv("PUSH_PROVIDER_MODE", "fake"))
    parser.add_argument("--push-fake-provider-delay-ms", default=os.getenv("PUSH_FAKE_PROVIDER_DELAY_MS", "0"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    users_file = Path(args.users_file)
    if not users_file.is_absolute():
        users_file = (Path.cwd() / users_file).resolve()

    if not args.results_dir.is_absolute():
        args.results_dir = (Path.cwd() / args.results_dir).resolve()
    args.results_dir.mkdir(parents=True, exist_ok=True)

    locust_bin = args.locust_bin
    if not Path(locust_bin).exists():
        locust_bin = shutil.which(locust_bin) or locust_bin

    failures: list[tuple[str, int]] = []
    selected = args.scenarios
    base_env = os.environ.copy()
    base_env["PERF_USERS_FILE"] = str(users_file)
    if args.poll_before_id:
        base_env["POLL_BEFORE_ID"] = str(args.poll_before_id)
    if args.poll_before_ratio is not None:
        base_env["POLL_BEFORE_RATIO"] = str(args.poll_before_ratio)
    if args.sse_publish:
        base_env["ENABLE_SSE_PUBLISH"] = "true"
        base_env["SSE_PUBLISHER_USERS"] = str(max(0, args.sse_publisher_users))
    base_env["PUSH_PROVIDER_MODE"] = str(args.push_provider_mode)
    base_env["PUSH_FAKE_PROVIDER_DELAY_MS"] = str(args.push_fake_provider_delay_ms)
    observability_config = build_observability_config(args.observability_url, args.observability_token, users_file)

    for vus in args.vus:
        if "ws-hold" in selected:
            output_file = args.results_dir / f"{args.run_id}-ws-hold-{vus}u.json"
            command = [
                args.k6_bin,
                "run",
                "--summary-export",
                str(output_file),
                "-e",
                f"USERS_FILE={users_file}",
                "-e",
                f"WS_BASE_URL={args.ws_base_url}",
                "-e",
                f"VUS={vus}",
                "-e",
                "SENDERS=0",
                "-e",
                f"DURATION={args.ws_duration}",
                str(PERF_ROOT / "k6" / "ws-chat.js"),
            ]
            metadata = {
                "run_id": args.run_id,
                "runtime_label": args.runtime_label,
                "tool": "k6",
                "scenario": "ws-hold",
                "users": vus,
                "vus": vus,
                "ws_base_url": args.ws_base_url,
                "run_duration": args.ws_duration,
            }
            exit_code = run_k6_command(
                command,
                PERF_ROOT / "k6",
                base_env,
                output_file,
                metadata,
                args.dry_run,
                observability_config,
            )
            if exit_code:
                failures.append((output_file.name, exit_code))
                if not args.keep_going:
                    break

        if "ws-chat" in selected:
            for ratio in args.chat_ratios:
                for interval in args.chat_intervals:
                    output_file = (
                        args.results_dir
                        / f"{args.run_id}-ws-chat-{vus}u-{ratio_label(ratio)}-{interval}s.json"
                    )
                    command = [
                        args.k6_bin,
                        "run",
                        "--summary-export",
                        str(output_file),
                        "-e",
                        f"USERS_FILE={users_file}",
                        "-e",
                        f"WS_BASE_URL={args.ws_base_url}",
                        "-e",
                        f"VUS={vus}",
                        "-e",
                        f"SENDER_RATIO={ratio}",
                        "-e",
                        f"SEND_EVERY_SECONDS={interval}",
                        "-e",
                        f"DURATION={args.ws_duration}",
                        str(PERF_ROOT / "k6" / "ws-chat.js"),
                    ]
                    metadata = {
                        "run_id": args.run_id,
                        "runtime_label": args.runtime_label,
                        "tool": "k6",
                        "scenario": "ws-chat",
                        "users": vus,
                        "vus": vus,
                        "ws_base_url": args.ws_base_url,
                        "run_duration": args.ws_duration,
                        "sender_ratio": ratio,
                        "send_every_seconds": interval,
                    }
                    exit_code = run_k6_command(
                        command,
                        PERF_ROOT / "k6",
                        base_env,
                        output_file,
                        metadata,
                        args.dry_run,
                        observability_config,
                    )
                    if exit_code:
                        failures.append((output_file.name, exit_code))
                        if not args.keep_going:
                            break
                if failures and not args.keep_going:
                    break

        if failures and not args.keep_going:
            break

        for scenario, user_class in (
            ("polling", "PollingUser"),
            ("sse", "SseListenerUser"),
            ("push", "PushNotificationUser"),
        ):
            if scenario not in selected:
                continue

            output_file = args.results_dir / f"{args.run_id}-{scenario}-{vus}u.json"
            user_classes = [user_class]
            publisher_users = 0
            total_locust_users = vus
            if scenario == "sse" and args.sse_publish:
                publisher_users = max(0, args.sse_publisher_users)
                total_locust_users += publisher_users
                user_classes.append("SsePublisherUser")
            command = [
                locust_bin,
                "-f",
                str(PERF_ROOT / "locust" / "polling_sse.py"),
                "--host",
                args.host,
                "--users",
                str(total_locust_users),
                "--spawn-rate",
                str(args.spawn_rate),
                "--run-time",
                args.locust_run_time,
                "--headless",
                "--only-summary",
                "--skip-log",
                "--json",
                *user_classes,
            ]
            metadata = {
                "run_id": args.run_id,
                "runtime_label": args.runtime_label,
                "tool": "locust",
                "scenario": scenario,
                "users": vus,
                "listener_users": vus if scenario == "sse" else None,
                "publisher_users": publisher_users if scenario == "sse" else None,
                "total_locust_users": total_locust_users,
                "spawn_rate": args.spawn_rate,
                "run_duration": args.locust_run_time,
                "run_time": args.locust_run_time,
                "host": args.host,
                "user_class": ",".join(user_classes),
                "sse_publish": bool(args.sse_publish) if scenario == "sse" else None,
                "poll_before_id": str(args.poll_before_id) if scenario == "polling" and args.poll_before_id else None,
                "poll_before_ratio": args.poll_before_ratio if scenario == "polling" else None,
                "push_provider_mode": str(args.push_provider_mode) if scenario == "push" else None,
                "push_fake_provider_delay_ms": str(args.push_fake_provider_delay_ms) if scenario == "push" else None,
            }
            exit_code = run_locust_command(
                command,
                BE_ROOT,
                base_env,
                output_file,
                metadata,
                args.dry_run,
                observability_config,
            )
            if exit_code:
                failures.append((output_file.name, exit_code))
                if not args.keep_going:
                    break

        if failures and not args.keep_going:
            break

    if failures:
        for name, exit_code in failures:
            print(f"failed: {name} exit_code={exit_code}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
