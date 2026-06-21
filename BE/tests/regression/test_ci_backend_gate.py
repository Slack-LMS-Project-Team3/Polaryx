from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "cicd.yml"
README_PATH = REPO_ROOT / "README.md"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow_steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(_workflow_text())
    return workflow["jobs"]["ci-cd"]["steps"]


def _named_step_indexes(steps: list[dict[str, object]], name: str) -> list[int]:
    return [index for index, step in enumerate(steps) if step.get("name") == name]


def _unique_step(steps: list[dict[str, object]], name: str) -> tuple[int, dict[str, object]]:
    matches = _named_step_indexes(steps, name)
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one workflow step named {name!r}, found {len(matches)}")
    index = matches[0]
    return index, steps[index]


def _normalized_run(step: dict[str, object]) -> str:
    return re.sub(r"\s+", " ", str(step.get("run", "")).strip())


class CiQualityGateTest(unittest.TestCase):
    def assertStepIsFailClosed(self, step: dict[str, object]) -> None:
        run_command = _normalized_run(step)
        continue_on_error = str(step.get("continue-on-error", "false")).strip().lower()
        if_expression = str(step.get("if", "")).strip().lower()

        self.assertNotIn("true", continue_on_error)
        self.assertNotIn("always()", if_expression)
        self.assertNotIn("|| true", run_command)

    def test_backend_and_frontend_quality_gates_run_before_deploy_steps(self) -> None:
        steps = _workflow_steps()
        backend_install_index, _ = _unique_step(steps, "Install backend dependencies")
        backend_regression_index, _ = _unique_step(steps, "Run backend regression suite")
        frontend_install_index, _ = _unique_step(steps, "Install frontend dependencies")
        frontend_lint_index, _ = _unique_step(steps, "Run frontend lint")
        frontend_build_index, _ = _unique_step(steps, "Run frontend build")
        frontend_test_index, _ = _unique_step(steps, "Run frontend test suite")
        guard_index, _ = _unique_step(steps, "Run CI quality gate guard")

        self.assertLess(backend_install_index, backend_regression_index)
        self.assertLess(backend_regression_index, frontend_install_index)
        self.assertLess(frontend_install_index, frontend_lint_index)
        self.assertLess(frontend_lint_index, frontend_build_index)
        self.assertLess(frontend_build_index, frontend_test_index)
        self.assertLess(frontend_test_index, guard_index)

        gated_steps = [
            "Configure AWS credentials",
            "Login to Amazon ECR",
            "Build and push image to ECR",
            "Copy frontend docker-compose to Frontend Server",
            "Upload docker-compose to S3 (if changed)",
            "Download docker-compose from S3 to Backend Server 1",
            "Download docker-compose from S3 to Backend Server 2",
            "Deploy to Backend Server 1 via SSM",
            "Deploy to Backend Server 2 via SSM",
            "Deploy to Frontend Server",
        ]
        for step in gated_steps:
            with self.subTest(step=step):
                gated_index, gated_step = _unique_step(steps, step)
                self.assertLess(guard_index, gated_index)
                self.assertStepIsFailClosed(gated_step)

    def test_backend_regression_gate_uses_expected_commands(self) -> None:
        steps = _workflow_steps()
        _, install = _unique_step(steps, "Install backend dependencies")
        _, regression = _unique_step(steps, "Run backend regression suite")
        install_command = _normalized_run(install)
        regression_command = _normalized_run(regression)

        self.assertEqual(install_command, "python -m pip install -r BE/requirements.txt")
        self.assertEqual(regression.get("working-directory"), "BE")
        self.assertIn("python -m unittest", regression_command)
        self.assertIn("tests.regression.test_auth_realtime_regression", regression_command)
        self.assertIn("tests.regression.test_security_access_control_regression", regression_command)
        self.assertIn("tests.unit.test_service_business_rules", regression_command)
        self.assertStepIsFailClosed(install)
        self.assertStepIsFailClosed(regression)

    def test_frontend_quality_gates_use_expected_commands(self) -> None:
        steps = _workflow_steps()
        _, install = _unique_step(steps, "Install frontend dependencies")
        _, lint = _unique_step(steps, "Run frontend lint")
        _, build = _unique_step(steps, "Run frontend build")
        _, test = _unique_step(steps, "Run frontend test suite")
        _, guard = _unique_step(steps, "Run CI quality gate guard")
        frontend_steps = [install, lint, build, test, guard]

        self.assertEqual(install.get("working-directory"), "FE")
        self.assertEqual(lint.get("working-directory"), "FE")
        self.assertEqual(build.get("working-directory"), "FE")
        self.assertEqual(test.get("working-directory"), "FE")
        self.assertEqual(_normalized_run(install), "npm ci")
        self.assertEqual(_normalized_run(lint), "npm run lint")
        self.assertEqual(_normalized_run(build), "npm run build")
        self.assertEqual(_normalized_run(test), "npm run test")

        for step in frontend_steps:
            with self.subTest(step=step.get("name")):
                self.assertStepIsFailClosed(step)


class BackendRegressionDocumentationTest(unittest.TestCase):
    def test_readme_documents_local_and_ci_regression_commands(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")

        self.assertIn(
            ".venv/bin/python -m unittest tests.regression.test_auth_realtime_regression",
            readme,
        )
        self.assertIn("tests.regression.test_security_access_control_regression", readme)
        self.assertIn("tests.unit.test_service_business_rules", readme)
        self.assertIn("unittest.expectedFailure", readme)
        self.assertIn(
            "python -m unittest tests.regression.test_auth_realtime_regression",
            readme,
        )
        self.assertIn("npm run lint", readme)
        self.assertIn("npm run build", readme)
        self.assertIn("npm run test", readme)
        self.assertIn("Vitest + React Testing Library + jsdom", readme)

if __name__ == "__main__":
    unittest.main()
