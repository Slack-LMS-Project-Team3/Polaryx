from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path


PERF_ROOT = Path(__file__).resolve().parent
BE_ROOT = PERF_ROOT.parents[1]
RUN_MATRIX = PERF_ROOT / "scripts" / "run_matrix.py"
SUMMARIZE_RESULTS = PERF_ROOT / "scripts" / "summarize_results.py"
SEED_DB_INDEX_FIXTURE = PERF_ROOT / "scripts" / "seed_db_index_fixture.py"
SCHEMA_SQL = BE_ROOT / "sql" / "init" / "ddl_create_tables.sql"


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


class PerformanceMatrixScriptTests(unittest.TestCase):
    def test_schema_declares_story_2_1_hot_path_indexes(self) -> None:
        schema = SCHEMA_SQL.read_text(encoding="utf-8")

        expected_indexes = [
            "KEY `idx_messages_tab_deleted_id_desc` (`tab_id`,`deleted_at`,`id` DESC)",
            "KEY `idx_emoji_msg_user` (`msg_id`,`user_id`)",
            "KEY `idx_notifications_receiver_created` (`receiver_id`,`created_at` DESC)",
            "KEY `idx_tab_members_workspace_tab_user` (`workspace_id`,`tab_id`,`user_id`)",
            "KEY `idx_workspace_members_workspace_deleted_user` (`workspace_id`,`deleted_at`,`user_id`)",
        ]

        for index_definition in expected_indexes:
            with self.subTest(index_definition=index_definition):
                self.assertIn(index_definition, schema)

        self.assertNotIn("UNIQUE KEY `idx_emoji_msg_user`", schema)
        self.assertNotIn("KEY `idx_tab_members_user_workspace_tab`", schema)

    def test_tab_member_queries_include_workspace_predicate_for_composite_index(self) -> None:
        tab_repository = (BE_ROOT / "app" / "repository" / "tab.py").read_text(encoding="utf-8")

        self.assertIn(
            "AND tm.workspace_id = %(workspace_id)s\n  AND tm.tab_id = %(tab_id)s",
            tab_repository,
        )
        self.assertIn(
            "FROM tab_members\n      WHERE workspace_id = %(workspace_id)s\n        AND tab_id = %(tab_id)s",
            tab_repository,
        )

    def test_db_index_fixture_script_dry_run_documents_deterministic_plan(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SEED_DB_INDEX_FIXTURE),
                "--messages",
                "100000",
                "--users",
                "30",
                "--notifications",
                "3000",
                "--dry-run",
            ],
            cwd=BE_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        plan = json.loads(completed.stdout)
        self.assertEqual(plan["workspace_id"], 9901)
        self.assertEqual(plan["tab_id"], 9901001)
        self.assertEqual(plan["messages"], 100000)
        self.assertEqual(plan["users"], 30)
        self.assertEqual(plan["notifications"], 3000)
        self.assertTrue(plan["safe_to_rerun"])
        self.assertIn("cleanup", plan)

    def test_run_matrix_adds_metadata_to_k6_and_locust_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "token"}],
                    }
                ),
                encoding="utf-8",
            )

            fake_k6 = temp / "fake_k6.py"
            write_executable(
                fake_k6,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json
                    import sys

                    output = sys.argv[sys.argv.index("--summary-export") + 1]
                    with open(output, "w", encoding="utf-8") as result:
                        json.dump({{
                            "metrics": {{
                                "ws_send_count": {{"values": {{"count": 7}}}},
                                "ws_errors": {{"values": {{"count": 0}}}},
                            }}
                        }}, result)
                    """
                ),
            )

            fake_locust = temp / "fake_locust.py"
            write_executable(
                fake_locust,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json

                    print(json.dumps({{
                        "stats": [{{
                            "name": "Aggregated",
                            "num_requests": 5,
                            "num_failures": 1,
                            "response_time_percentile_0.95": 123.4,
                        }}]
                    }}))
                    """
                ),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--vus",
                    "2",
                    "--scenarios",
                    "ws-hold,polling",
                    "--run-id",
                    "workers1-test",
                    "--runtime-label",
                    "workers=1",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--k6-bin",
                    str(fake_k6),
                    "--locust-bin",
                    str(fake_locust),
                    "--host",
                    "http://testserver",
                    "--ws-base-url",
                    "ws://testserver/api/ws",
                    "--ws-duration",
                    "1m",
                    "--locust-run-time",
                    "30s",
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)

            k6_result = json.loads((results_dir / "workers1-test-ws-hold-2u.json").read_text())
            self.assertIn("metrics", k6_result)
            self.assertEqual(k6_result["metrics"]["ws_send_count"]["values"]["count"], 7)
            self.assertEqual(k6_result["metadata"]["run_id"], "workers1-test")
            self.assertEqual(k6_result["metadata"]["runtime_label"], "workers=1")
            self.assertEqual(k6_result["metadata"]["scenario"], "ws-hold")
            self.assertEqual(k6_result["metadata"]["users"], 2)
            self.assertEqual(k6_result["metadata"]["vus"], 2)
            self.assertEqual(k6_result["metadata"]["exit_code"], 0)
            self.assertEqual(k6_result["metadata"]["ws_base_url"], "ws://testserver/api/ws")
            self.assertEqual(k6_result["metadata"]["run_duration"], "1m")
            self.assertIn("started_at", k6_result["metadata"])
            self.assertIn("finished_at", k6_result["metadata"])
            self.assertIn("elapsed_seconds", k6_result["metadata"])
            self.assertIsInstance(k6_result["metadata"]["command"], list)

            locust_result = json.loads((results_dir / "workers1-test-polling-2u.json").read_text())
            self.assertEqual(locust_result["metadata"]["runtime_label"], "workers=1")
            self.assertEqual(locust_result["metadata"]["scenario"], "polling")
            self.assertEqual(locust_result["metadata"]["host"], "http://testserver")
            self.assertEqual(locust_result["metadata"]["run_duration"], "30s")

    def test_run_matrix_can_configure_polling_before_id_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "token"}],
                    }
                ),
                encoding="utf-8",
            )

            fake_locust = temp / "fake_locust.py"
            write_executable(
                fake_locust,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json
                    import os

                    print(json.dumps({{
                        "env": {{
                            "POLL_BEFORE_ID": os.environ.get("POLL_BEFORE_ID"),
                            "POLL_BEFORE_RATIO": os.environ.get("POLL_BEFORE_RATIO"),
                        }},
                        "stats": [{{
                            "name": "Aggregated",
                            "num_requests": 5,
                            "num_failures": 0,
                            "response_time_percentile_0.95": 120,
                        }}],
                    }}))
                    """
                ),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--vus",
                    "2",
                    "--scenarios",
                    "polling",
                    "--run-id",
                    "db-index-before-test",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--locust-bin",
                    str(fake_locust),
                    "--poll-before-id",
                    "9900123",
                    "--poll-before-ratio",
                    "0.5",
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            locust_result = json.loads((results_dir / "db-index-before-test-polling-2u.json").read_text())
            self.assertEqual(locust_result["metadata"]["poll_before_id"], "9900123")
            self.assertEqual(locust_result["metadata"]["poll_before_ratio"], 0.5)
            self.assertEqual(locust_result["locust"]["env"]["POLL_BEFORE_ID"], "9900123")
            self.assertEqual(locust_result["locust"]["env"]["POLL_BEFORE_RATIO"], "0.5")

    def test_run_matrix_sse_publish_runs_listener_and_publisher_user_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "token"}],
                    }
                ),
                encoding="utf-8",
            )

            fake_locust = temp / "fake_locust.py"
            write_executable(
                fake_locust,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json
                    import os
                    import sys

                    print(json.dumps({{
                        "argv": sys.argv,
                        "env": {{
                            "ENABLE_SSE_PUBLISH": os.environ.get("ENABLE_SSE_PUBLISH"),
                            "SSE_PUBLISHER_USERS": os.environ.get("SSE_PUBLISHER_USERS"),
                        }},
                        "stats": [{{
                            "name": "Aggregated",
                            "num_requests": 5,
                            "num_failures": 0,
                            "response_time_percentile_0.95": 120,
                        }}],
                    }}))
                    """
                ),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--vus",
                    "2",
                    "--scenarios",
                    "sse",
                    "--run-id",
                    "sse-publish-test",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--locust-bin",
                    str(fake_locust),
                    "--sse-publish",
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            locust_result = json.loads((results_dir / "sse-publish-test-sse-2u.json").read_text())
            self.assertEqual(locust_result["metadata"]["sse_publish"], True)
            self.assertEqual(locust_result["metadata"]["listener_users"], 2)
            self.assertEqual(locust_result["metadata"]["publisher_users"], 1)
            self.assertEqual(locust_result["metadata"]["total_locust_users"], 3)
            self.assertEqual(locust_result["metadata"]["user_class"], "SseListenerUser,SsePublisherUser")
            self.assertEqual(locust_result["locust"]["env"]["ENABLE_SSE_PUBLISH"], "true")
            self.assertEqual(locust_result["locust"]["env"]["SSE_PUBLISHER_USERS"], "1")
            users_index = locust_result["locust"]["argv"].index("--users")
            self.assertEqual(locust_result["locust"]["argv"][users_index + 1], "3")
            self.assertIn("SseListenerUser", locust_result["locust"]["argv"])
            self.assertIn("SsePublisherUser", locust_result["locust"]["argv"])

    def test_run_matrix_push_scenario_dry_run_expands_locust_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "token"}],
                    }
                ),
                encoding="utf-8",
            )
            fake_locust = temp / "fake_locust.py"
            write_executable(fake_locust, f"#!{sys.executable}\n")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--dry-run",
                    "--vus",
                    "100,300,500",
                    "--scenarios",
                    "push",
                    "--run-id",
                    "web-push-async-dryrun",
                    "--runtime-label",
                    "push-async-dispatch",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--locust-bin",
                    str(fake_locust),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("PushNotificationUser", completed.stdout)
            self.assertIn("web-push-async-dryrun-push-100u.json", completed.stdout)
            self.assertIn("web-push-async-dryrun-push-300u.json", completed.stdout)
            self.assertIn("web-push-async-dryrun-push-500u.json", completed.stdout)

    def test_run_matrix_push_scenario_metadata_with_fake_locust(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "token"}],
                    }
                ),
                encoding="utf-8",
            )

            fake_locust = temp / "fake_locust.py"
            write_executable(
                fake_locust,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json
                    import os
                    import sys

                    print(json.dumps({{
                        "argv": sys.argv,
                        "env": {{
                            "PUSH_PROVIDER_MODE": os.environ.get("PUSH_PROVIDER_MODE"),
                            "PUSH_FAKE_PROVIDER_DELAY_MS": os.environ.get("PUSH_FAKE_PROVIDER_DELAY_MS"),
                        }},
                        "stats": [{{
                            "name": "Aggregated",
                            "num_requests": 5,
                            "num_failures": 0,
                            "response_time_percentile_0.95": 42,
                        }}],
                    }}))
                    """
                ),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--vus",
                    "2",
                    "--scenarios",
                    "push",
                    "--run-id",
                    "push-test",
                    "--runtime-label",
                    "push-async-dispatch",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--locust-bin",
                    str(fake_locust),
                    "--push-provider-mode",
                    "fake",
                    "--push-fake-provider-delay-ms",
                    "250",
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            locust_result = json.loads((results_dir / "push-test-push-2u.json").read_text())
            self.assertEqual(locust_result["metadata"]["scenario"], "push")
            self.assertEqual(locust_result["metadata"]["user_class"], "PushNotificationUser")
            self.assertEqual(locust_result["metadata"]["push_provider_mode"], "fake")
            self.assertEqual(locust_result["metadata"]["push_fake_provider_delay_ms"], "250")
            self.assertEqual(locust_result["locust"]["env"]["PUSH_PROVIDER_MODE"], "fake")
            self.assertEqual(locust_result["locust"]["env"]["PUSH_FAKE_PROVIDER_DELAY_MS"], "250")
            self.assertIn("PushNotificationUser", locust_result["locust"]["argv"])

    def test_polling_user_marks_valid_message_response_success(self) -> None:
        module_path = PERF_ROOT / "locust" / "polling_sse.py"
        spec = importlib.util.spec_from_file_location("polling_sse_for_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        polling_sse = importlib.util.module_from_spec(spec)

        locust_stub = types.SimpleNamespace(
            HttpUser=object,
            between=lambda *_args: None,
            events=types.SimpleNamespace(request=types.SimpleNamespace(fire=lambda **_kwargs: None)),
            task=lambda func: func,
        )
        original_locust = sys.modules.get("locust")
        sys.modules["locust"] = locust_stub
        try:
            spec.loader.exec_module(polling_sse)
        finally:
            if original_locust is None:
                sys.modules.pop("locust", None)
            else:
                sys.modules["locust"] = original_locust

        class FakeResponse:
            status_code = 200
            text = ""

            def __init__(self) -> None:
                self.success_called = False
                self.failure_message: str | None = None

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
                return False

            def json(self) -> dict[str, list[object]]:
                return {"messages": []}

            def success(self) -> None:
                self.success_called = True

            def failure(self, message: str) -> None:
                self.failure_message = message

        class FakeClient:
            def __init__(self, response: FakeResponse) -> None:
                self.response = response
                self.kwargs: dict[str, object] | None = None

            def get(self, url: str, **kwargs: object) -> FakeResponse:
                self.kwargs = kwargs
                return self.response

        response = FakeResponse()
        fake_client = FakeClient(response)
        fake_user = type("FakePollingUser", (), {"headers": {}, "client": fake_client})()

        original_options = polling_sse._poll_request_options
        polling_sse._poll_request_options = lambda: (None, "GET test")
        try:
            polling_sse.PollingUser.poll_messages(fake_user)
        finally:
            polling_sse._poll_request_options = original_options

        self.assertTrue(response.success_called)
        self.assertIsNone(response.failure_message)
        self.assertIsNotNone(fake_client.kwargs)
        self.assertTrue(fake_client.kwargs["catch_response"])

    def test_run_matrix_captures_observability_snapshots_with_fixture_token_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "fixture-token"}],
                    }
                ),
                encoding="utf-8",
            )
            snapshot_source = temp / "observability-source.json"
            snapshot_source.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-18T00:00:00+00:00",
                        "process": {"pid": 1001, "server_ids": ["file-server"]},
                        "websocket": {
                            "active_connections": [],
                            "broadcasts_total": 1,
                            "broadcast_recipients_total": 10,
                            "send_failures_total": 0,
                            "redis_publish_failures_total": 0,
                        },
                        "sse": {"subscribers": [], "delivery_attempts_total": 5, "queue_put_failures_total": 0},
                        "persistence": {
                            "message_save_success_total": 2,
                            "message_save_failure_total": 0,
                            "message_save_lag_seconds": {"count": 1, "latest": 0.1, "max": 0.1, "p95": 0.1},
                        },
                    }
                ),
                encoding="utf-8",
            )

            fake_k6 = temp / "fake_k6.py"
            write_executable(
                fake_k6,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json
                    import sys

                    output = sys.argv[sys.argv.index("--summary-export") + 1]
                    with open(output, "w", encoding="utf-8") as result:
                        json.dump({{"metrics": {{"ws_errors": {{"values": {{"count": 0}}}}}}}}, result)
                    """
                ),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--vus",
                    "2",
                    "--scenarios",
                    "ws-hold",
                    "--run-id",
                    "obs-test",
                    "--runtime-label",
                    "workers=1",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--k6-bin",
                    str(fake_k6),
                    "--observability-url",
                    snapshot_source.as_uri(),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads((results_dir / "obs-test-ws-hold-2u.json").read_text(encoding="utf-8"))
            observability = result["metadata"]["observability"]
            self.assertEqual(observability["auth_source"], "fixture")
            before_path = Path(observability["before"]["snapshot_file"])
            after_path = Path(observability["after"]["snapshot_file"])
            self.assertTrue(before_path.exists())
            self.assertTrue(after_path.exists())
            self.assertEqual(json.loads(before_path.read_text())["process"]["server_ids"], ["file-server"])
            self.assertEqual(json.loads(after_path.read_text())["process"]["server_ids"], ["file-server"])

    def test_failed_k6_run_does_not_reuse_stale_summary_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            fixtures_dir = temp / "fixtures"
            results_dir.mkdir()
            fixtures_dir.mkdir()
            users_file = fixtures_dir / "users.local.json"
            users_file.write_text(
                json.dumps(
                    {
                        "workspace_id": 1,
                        "tab_id": 1,
                        "users": [{"user_id": 1, "access_token": "token"}],
                    }
                ),
                encoding="utf-8",
            )

            stale_result = results_dir / "workers1-test-ws-hold-2u.json"
            stale_result.write_text(
                json.dumps(
                    {
                        "metrics": {
                            "ws_send_count": {"values": {"count": 999}},
                            "ws_errors": {"values": {"count": 0}},
                        }
                    }
                ),
                encoding="utf-8",
            )

            failing_k6 = temp / "failing_k6.py"
            write_executable(
                failing_k6,
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import sys

                    sys.exit(23)
                    """
                ),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUN_MATRIX),
                    "--vus",
                    "2",
                    "--scenarios",
                    "ws-hold",
                    "--run-id",
                    "workers1-test",
                    "--runtime-label",
                    "workers=1",
                    "--results-dir",
                    str(results_dir),
                    "--users-file",
                    str(users_file),
                    "--k6-bin",
                    str(failing_k6),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 1)
            k6_result = json.loads(stale_result.read_text(encoding="utf-8"))
            self.assertEqual(k6_result["metadata"]["exit_code"], 23)
            self.assertIn("summary_export_error", k6_result)
            self.assertNotIn("ws_send_count", k6_result["metrics"])

    def test_summarize_results_includes_metadata_and_filters_by_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()

            (results_dir / "workers1-test-ws-hold-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "workers1-test",
                            "runtime_label": "workers=1",
                            "scenario": "ws-hold",
                            "users": 2,
                            "vus": 2,
                            "exit_code": 0,
                        },
                        "metrics": {
                            "ws_connect_success": {"values": {"rate": 1.0}},
                            "ws_maintain_success": {"values": {"rate": 0.99}},
                            "ws_errors": {"values": {"count": 0}},
                            "ws_delivery_ms": {"values": {"p(95)": 42.5}},
                            "ws_send_count": {"values": {"count": 7}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (results_dir / "workers2-test-ws-hold-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "workers2-test",
                            "runtime_label": "workers=2",
                            "scenario": "ws-hold",
                            "users": 2,
                            "exit_code": 0,
                        },
                        "metrics": {"ws_send_count": {"values": {"count": 3}}},
                    }
                ),
                encoding="utf-8",
            )
            (results_dir / "legacy-polling-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "legacy",
                            "runtime_label": "workers=1",
                            "scenario": "polling",
                            "users": 2,
                        },
                        "locust": {
                            "stats": [
                                {
                                    "name": "Aggregated",
                                    "num_requests": 5,
                                    "num_failures": 1,
                                    "response_time_percentile_0.95": 123.4,
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary-workers1.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                    "--runtime-label",
                    "workers=1",
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("| Run ID | Runtime | Tool | Scenario | Users |", markdown)
            self.assertIn("p99 ms", markdown)
            self.assertIn("Max ms", markdown)
            self.assertIn("| workers1-test | workers=1 | k6 | ws-hold | 2 |", markdown)
            self.assertIn("| legacy | workers=1 | locust | polling | 2 |", markdown)
            self.assertIn("| legacy | workers=1 | locust | polling | 2 | - | - | 1 | 123.40 | - | - | 5 |", markdown)
            self.assertIn("workers1-test-ws-hold-2u.json", markdown)
            self.assertIn("Generated at:", markdown)
            self.assertNotIn("workers2-test", markdown)

    def test_summarize_results_includes_observability_deltas_when_snapshots_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()
            before = results_dir / "obs-before.json"
            after = results_dir / "obs-after.json"
            before.write_text(
                json.dumps(
                    {
                        "process": {"pid": 1001, "server_ids": ["worker-a"]},
                        "websocket": {
                            "broadcast_recipients_total": 3,
                            "send_failures_total": 0,
                            "redis_publish_failures_total": 0,
                        },
                        "sse": {
                            "delivery_attempts_total": 1,
                            "event_delivery_count_total": 1,
                            "queue_put_failures_total": 0,
                            "queue_drops_total": 0,
                            "outbox_inserted_total": 0,
                            "outbox_published_total": 0,
                            "outbox_failed_total": 0,
                            "stream_xadd_attempts_total": 0,
                            "stream_xadd_failures_total": 0,
                            "stream_messages_received_total": 0,
                            "replayed_events_total": 0,
                            "ack_updates_total": 0,
                            "duplicate_events_deduped_total": 0,
                        },
                        "persistence": {
                            "message_save_success_total": 1,
                            "message_save_failure_total": 0,
                            "message_save_lag_seconds": {"p95": 0.10},
                        },
                    }
                ),
                encoding="utf-8",
            )
            after.write_text(
                json.dumps(
                    {
                        "process": {"pid": 1001, "server_ids": ["worker-a"]},
                        "websocket": {
                            "broadcast_recipients_total": 10,
                            "send_failures_total": 2,
                            "redis_publish_failures_total": 1,
                        },
                        "sse": {
                            "delivery_attempts_total": 6,
                            "event_delivery_count_total": 5,
                            "queue_put_failures_total": 1,
                            "queue_drops_total": 1,
                            "outbox_inserted_total": 2,
                            "outbox_published_total": 1,
                            "outbox_failed_total": 1,
                            "stream_xadd_attempts_total": 2,
                            "stream_xadd_failures_total": 1,
                            "stream_messages_received_total": 3,
                            "replayed_events_total": 4,
                            "ack_updates_total": 5,
                            "duplicate_events_deduped_total": 1,
                        },
                        "persistence": {
                            "message_save_success_total": 4,
                            "message_save_failure_total": 1,
                            "message_save_lag_seconds": {"p95": 0.25},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (results_dir / "workers1-test-ws-hold-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "workers1-test",
                            "runtime_label": "workers=1",
                            "scenario": "ws-hold",
                            "users": 2,
                            "observability": {
                                "before": {"snapshot_file": str(before)},
                                "after": {"snapshot_file": str(after)},
                            },
                        },
                        "metrics": {"ws_errors": {"values": {"count": 0}}},
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("Observability", markdown)
            self.assertIn(
                "ws_recips +7; ws_fail +2; redis_fail +1; sse_attempts +5; sse_queue_fail +1; sse_queue_drop +1; sse_delivered +4; sse_outbox_insert +2; sse_outbox_pub +1; sse_outbox_fail +1; sse_stream_xadd +2; sse_stream_fail +1; sse_stream_recv +3; sse_replayed +4; sse_ack +5; sse_dedupe +1; db_save +3/+1; db_lag_p95 0.25s",
                markdown,
            )

    def test_summarize_results_includes_push_observability_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()
            before = results_dir / "push-before.json"
            after = results_dir / "push-after.json"
            before.write_text(
                json.dumps(
                    {
                        "process": {"pid": 1001, "server_ids": ["worker-a"]},
                        "websocket": {
                            "broadcast_recipients_total": 0,
                            "send_failures_total": 0,
                            "redis_publish_failures_total": 0,
                        },
                        "sse": {
                            "delivery_attempts_total": 0,
                            "event_delivery_count_total": 0,
                            "queue_put_failures_total": 0,
                            "queue_drops_total": 0,
                            "outbox_inserted_total": 0,
                            "outbox_published_total": 0,
                            "outbox_failed_total": 0,
                            "stream_xadd_attempts_total": 0,
                            "stream_xadd_failures_total": 0,
                            "stream_messages_received_total": 0,
                            "replayed_events_total": 0,
                            "ack_updates_total": 0,
                            "duplicate_events_deduped_total": 0,
                        },
                        "persistence": {
                            "message_save_success_total": 0,
                            "message_save_failure_total": 0,
                            "message_save_lag_seconds": {"p95": 0.0},
                        },
                        "push": {
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
                            "queue_lag_seconds": {"p95": 0.0, "max": 0.0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            after.write_text(
                json.dumps(
                    {
                        "process": {"pid": 1001, "server_ids": ["worker-a"]},
                        "websocket": {
                            "broadcast_recipients_total": 0,
                            "send_failures_total": 0,
                            "redis_publish_failures_total": 0,
                        },
                        "sse": {
                            "delivery_attempts_total": 0,
                            "event_delivery_count_total": 0,
                            "queue_put_failures_total": 0,
                            "queue_drops_total": 0,
                            "outbox_inserted_total": 0,
                            "outbox_published_total": 0,
                            "outbox_failed_total": 0,
                            "stream_xadd_attempts_total": 0,
                            "stream_xadd_failures_total": 0,
                            "stream_messages_received_total": 0,
                            "replayed_events_total": 0,
                            "ack_updates_total": 0,
                            "duplicate_events_deduped_total": 0,
                        },
                        "persistence": {
                            "message_save_success_total": 0,
                            "message_save_failure_total": 0,
                            "message_save_lag_seconds": {"p95": 0.0},
                        },
                        "push": {
                            "enqueue_success_total": 5,
                            "enqueue_failures_total": 1,
                            "jobs_read_total": 4,
                            "recipient_lookup_success_total": 4,
                            "recipient_lookup_failures_total": 1,
                            "recipient_count_total": 8,
                            "external_send_attempts_total": 8,
                            "external_send_success_total": 6,
                            "external_send_failures_total": 2,
                            "retry_count_total": 1,
                            "dropped_count_total": 1,
                            "dead_letter_count_total": 1,
                            "queue_lag_seconds": {"p95": 0.25, "max": 0.40},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (results_dir / "push-test-push-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "push-test",
                            "runtime_label": "push-async",
                            "scenario": "push",
                            "users": 2,
                            "observability": {
                                "before": {"snapshot_file": str(before)},
                                "after": {"snapshot_file": str(after)},
                            },
                        },
                        "locust": {
                            "stats": [
                                {
                                    "name": "Aggregated",
                                    "num_requests": 5,
                                    "num_failures": 1,
                                    "response_time_percentile_0.95": 50,
                                },
                                {
                                    "name": "POST /api/notifications enqueue",
                                    "num_requests": 5,
                                    "num_failures": 1,
                                    "response_time_percentile_0.95": 50,
                                },
                                {"name": "Web Push enqueue accepted", "num_requests": 4, "num_failures": 0},
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("| push-test | push-async | locust | push | 2 | - | - | 1 | 50 | - | - | 5 |", markdown)
            self.assertIn(
                "push_enqueue +5; push_enqueue_fail +1; push_jobs_read +4; push_recipient_lookup +4; push_recipient_lookup_fail +1; push_recipient_count +8; push_send_attempts +8; push_send_success +6; push_send_fail +2; push_retry +1; push_drop +1; push_dead +1; push_lag_p95 0.25s; push_lag_max 0.40s",
                markdown,
            )
            self.assertIn(
                "push_http_requests 5; push_http_failures 1; push_http_p95 50ms; push_accepted 4",
                markdown,
            )

    def test_summarize_results_includes_message_persistence_queue_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()
            before = results_dir / "message-persistence-before.json"
            after = results_dir / "message-persistence-after.json"
            base_sections = {
                "process": {"pid": 1001, "server_ids": ["worker-a"]},
                "websocket": {
                    "broadcast_recipients_total": 0,
                    "send_failures_total": 0,
                    "redis_publish_failures_total": 0,
                },
                "sse": {
                    "delivery_attempts_total": 0,
                    "event_delivery_count_total": 0,
                    "queue_put_failures_total": 0,
                    "queue_drops_total": 0,
                    "outbox_inserted_total": 0,
                    "outbox_published_total": 0,
                    "outbox_failed_total": 0,
                    "stream_xadd_attempts_total": 0,
                    "stream_xadd_failures_total": 0,
                    "stream_messages_received_total": 0,
                    "replayed_events_total": 0,
                    "ack_updates_total": 0,
                    "duplicate_events_deduped_total": 0,
                },
            }
            before.write_text(
                json.dumps(
                    {
                        **base_sections,
                        "persistence": {
                            "message_save_success_total": 0,
                            "message_save_failure_total": 0,
                            "message_save_lag_seconds": {"p95": 0.0},
                            "enqueue_attempts_total": 0,
                            "enqueue_success_total": 0,
                            "enqueue_failures_total": 0,
                            "queue_full_rejects_total": 0,
                            "worker_saves_started_total": 0,
                            "worker_save_success_total": 0,
                            "worker_save_failure_total": 0,
                            "retry_count_total": 0,
                            "dropped_rejected_count_total": 0,
                            "max_queue_depth": 0,
                            "shutdown_drain_timeout_total": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            after.write_text(
                json.dumps(
                    {
                        **base_sections,
                        "persistence": {
                            "message_save_success_total": 7,
                            "message_save_failure_total": 1,
                            "message_save_lag_seconds": {"p95": 0.20},
                            "enqueue_attempts_total": 10,
                            "enqueue_success_total": 8,
                            "enqueue_failures_total": 2,
                            "queue_full_rejects_total": 2,
                            "worker_saves_started_total": 8,
                            "worker_save_success_total": 7,
                            "worker_save_failure_total": 1,
                            "retry_count_total": 0,
                            "dropped_rejected_count_total": 3,
                            "max_queue_depth": 5,
                            "shutdown_drain_timeout_total": 1,
                            "queue_wait_seconds": {"p95": 0.05, "p99": 0.08, "max": 0.10},
                            "db_save_duration_seconds": {"p95": 0.12, "p99": 0.18},
                            "db_visibility_lag_seconds": {"p50": 0.08, "p95": 0.22, "p99": 0.30},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (results_dir / "message-persistence-test-ws-chat-2u-10pct-1s.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "message-persistence-test",
                            "runtime_label": "bounded-message-persistence",
                            "scenario": "ws-chat",
                            "users": 2,
                            "observability": {
                                "before": {"snapshot_file": str(before)},
                                "after": {"snapshot_file": str(after)},
                            },
                        },
                        "metrics": {"ws_errors": {"values": {"count": 0}}},
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn(
                "persist_enqueue +8/+2; persist_full +2; persist_worker_start +8; persist_worker_save +7/+1; persist_retry +0; persist_drop_reject +3; persist_qmax 5; persist_shutdown_timeout +1; queue_wait_p95 0.05s; queue_wait_p99 0.08s; db_save_p95 0.12s; db_save_p99 0.18s; db_visible_p50 0.08s; db_visible_p95 0.22s; db_visible_p99 0.30s",
                markdown,
            )

    def test_summarize_results_includes_sse_published_event_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()
            (results_dir / "sse-publish-test-sse-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "sse-publish-test",
                            "runtime_label": "workers=2",
                            "scenario": "sse",
                            "users": 2,
                        },
                        "locust": {
                            "stats": [
                                {
                                    "name": "Aggregated",
                                    "num_requests": 10,
                                    "num_failures": 1,
                                    "response_time_percentile_0.95": 5000,
                                },
                                {
                                    "name": "SSE event latency",
                                    "num_requests": 4,
                                    "num_failures": 0,
                                    "response_time_percentile_0.95": 42.0,
                                    "response_time_percentile_0.99": 55.0,
                                    "max_response_time": 60.0,
                                },
                                {"name": "SSE published event", "num_requests": 5, "num_failures": 0},
                                {"name": "SSE received unique event", "num_requests": 4, "num_failures": 0},
                                {"name": "SSE acked event", "num_requests": 4, "num_failures": 0},
                                {"name": "SSE replayed event", "num_requests": 2, "num_failures": 0},
                                {"name": "SSE duplicate event", "num_requests": 1, "num_failures": 0},
                                {"name": "SSE reconnect", "num_requests": 2, "num_failures": 0},
                                {"name": "SSE stream failure", "num_requests": 1, "num_failures": 1},
                                {"name": "SSE missing after replay count", "num_requests": 1, "num_failures": 1, "max_response_time": 1},
                                {"name": "SSE zero-event listener window", "num_requests": 1, "num_failures": 1},
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("| sse-publish-test | workers=2 | locust | sse | 2 | - | - | 1 | 42.00 | 55.00 | 60.00 | 10 |", markdown)
            self.assertIn(
                "sse_event_p95 42.00ms; sse_published 5; sse_received_unique 4; sse_acked 4; sse_replayed 2; sse_duplicate 1; sse_reconnects 2; sse_stream_failures 1; sse_missing_after_replay 1; sse_zero_windows 1",
                markdown,
            )

    def test_summarize_results_rejects_observability_deltas_from_different_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()
            before = results_dir / "obs-before.json"
            after = results_dir / "obs-after.json"
            before.write_text(
                json.dumps(
                    {
                        "process": {"pid": 1001, "server_ids": ["worker-a"]},
                        "websocket": {"broadcast_recipients_total": 3},
                        "sse": {"delivery_attempts_total": 1},
                        "persistence": {"message_save_success_total": 1, "message_save_failure_total": 0},
                    }
                ),
                encoding="utf-8",
            )
            after.write_text(
                json.dumps(
                    {
                        "process": {"pid": 1002, "server_ids": ["worker-b"]},
                        "websocket": {"broadcast_recipients_total": 10},
                        "sse": {"delivery_attempts_total": 6},
                        "persistence": {"message_save_success_total": 4, "message_save_failure_total": 1},
                    }
                ),
                encoding="utf-8",
            )
            (results_dir / "workers2-test-ws-hold-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "workers2-test",
                            "runtime_label": "workers=2",
                            "scenario": "ws-hold",
                            "users": 2,
                            "observability": {
                                "before": {"snapshot_file": str(before)},
                                "after": {"snapshot_file": str(after)},
                            },
                        },
                        "metrics": {"ws_errors": {"values": {"count": 0}}},
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn(
                "obs_error process changed before_pid=1001 before_servers=['worker-a'] after_pid=1002 after_servers=['worker-b']",
                markdown,
            )
            self.assertNotIn("ws_recips +7", markdown)

    def test_summarize_results_preserves_zero_delivery_p95(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            results_dir = temp / "results"
            results_dir.mkdir()
            (results_dir / "workers1-test-ws-hold-2u.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": "workers1-test",
                            "runtime_label": "workers=1",
                            "scenario": "ws-hold",
                            "users": 2,
                        },
                        "metrics": {
                            "ws_delivery_ms": {"values": {"p(95)": 0.0}},
                            "ws_session_duration_ms": {"values": {"p(95)": 1234.5}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            output = temp / "summary.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZE_RESULTS),
                    "--results-dir",
                    str(results_dir),
                    "--output",
                    str(output),
                ],
                cwd=BE_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("| workers1-test | workers=1 | k6 | ws-hold | 2 | - | - | - | 0.00 | - |", markdown)
            self.assertNotIn("1234.50", markdown)


if __name__ == "__main__":
    unittest.main()
