from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock


TEST_SECRET = "test-regression-secret"
TEST_USER_ID = "05EA49CFD91F41A0BE63CACE1718DE71"
OUTSIDER_USER_ID = "C0FFEE00000040008000000000000001"
TEST_EMAIL = "qa-regression@example.com"
OUTSIDER_EMAIL = "outsider-regression@example.com"
WORKSPACE_ID = 1
TAB_ID = 1
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


def _outsider_headers() -> dict[str, str]:
    return _auth_headers(_token(user_id=OUTSIDER_USER_ID, email=OUTSIDER_EMAIL))


class DummyMySQLConnectionPool:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def get_connection(self) -> object:
        raise AssertionError("Regression tests must stub service methods before DB access")


class SecurityAccessControlRegressionTest(unittest.TestCase):
    """Target tests for BFLA and BOLA gaps in sensitive backend routes."""

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
        from app.router import db, message, s3, tab

        cls.TestClient = TestClient
        cls.app = app
        cls.db_router = db
        cls.message_router = message
        cls.s3_router = s3
        cls.tab_router = tab

    def setUp(self) -> None:
        self._attr_patches = [
            _capture_instance_attr(self.db_router.db_service, "reset"),
            _capture_instance_attr(self.message_router.message_service, "find_recent_messages"),
            _capture_instance_attr(self.s3_router.boto3, "client"),
            _capture_instance_attr(self.tab_router.service, "exit_tab"),
            _capture_instance_attr(self.tab_router.service, "find_tab"),
            _capture_instance_attr(self.tab_router.service, "get_tab_members"),
            _capture_instance_attr(self.tab_router.wm_service, "get_member_by_user_id"),
        ]
        self.client = self.TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        for obj, attr_name, value in reversed(getattr(self, "_attr_patches", [])):
            _restore_instance_attr(obj, attr_name, value)

    def test_security_target_routes_are_registered(self) -> None:
        registered_routes = {
            (method, route.path)
            for route in self.app.routes
            for method in getattr(route, "methods", set())
            if method != "HEAD"
        }

        expected_routes = {
            ("GET", "/api/reset"),
            ("POST", "/api/s3/presigned-url"),
            ("POST", "/api/s3/presigned-url-get"),
            ("GET", "/api/workspaces/{workspace_id}/tabs/{tab_id}/members"),
            ("PATCH", "/api/workspaces/{workspace_id}/tabs/{tab_id}/out"),
            ("GET", "/api/workspaces/{workspace_id}/tabs/{tab_id}/messages"),
            ("GET", "/api/workspaces/{workspace_id}/tabs/{tab_id}/info"),
        }
        self.assertTrue(expected_routes.issubset(registered_routes))

    def test_security_harness_accepts_valid_token_on_protected_route(self) -> None:
        self.message_router.message_service.find_recent_messages = AsyncMock(return_value=[])

        response = self.client.get(
            f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/messages",
            headers=_auth_headers(),
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"messages": []})
        self.message_router.message_service.find_recent_messages.assert_awaited_once_with(
            TAB_ID,
            None,
            TEST_USER_ID,
        )

    @unittest.expectedFailure
    def test_db_reset_requires_auth_before_reset_service_is_called(self) -> None:
        self.db_router.db_service.reset = Mock(return_value=None)

        response = self.client.get("/api/reset")

        self.assertIn(response.status_code, {401, 403})
        self.db_router.db_service.reset.assert_not_called()

    @unittest.expectedFailure
    def test_s3_upload_presign_requires_auth_before_aws_client_is_created(self) -> None:
        fake_s3 = Mock()
        fake_s3.generate_presigned_url.return_value = "https://example.test/upload"
        self.s3_router.boto3.client = Mock(return_value=fake_s3)

        response = self.client.post(
            "/api/s3/presigned-url",
            json={"filename": "security.txt", "filetype": "text/plain"},
        )

        self.assertIn(response.status_code, {401, 403})
        self.s3_router.boto3.client.assert_not_called()

    @unittest.expectedFailure
    def test_s3_download_presign_requires_auth_before_aws_client_is_created(self) -> None:
        fake_s3 = Mock()
        fake_s3.generate_presigned_url.return_value = "https://example.test/download"
        self.s3_router.boto3.client = Mock(return_value=fake_s3)

        response = self.client.post(
            "/api/s3/presigned-url-get",
            json={"filename": "security.txt"},
        )

        self.assertIn(response.status_code, {401, 403})
        self.s3_router.boto3.client.assert_not_called()

    @unittest.expectedFailure
    def test_tab_members_requires_auth_before_member_list_service_is_called(self) -> None:
        self.tab_router.service.get_tab_members = Mock(return_value=[])

        response = self.client.get(f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/members")

        self.assertIn(response.status_code, {401, 403})
        self.tab_router.service.get_tab_members.assert_not_called()

    @unittest.expectedFailure
    def test_tab_exit_requires_auth_before_exit_service_is_awaited(self) -> None:
        self.tab_router.service.exit_tab = AsyncMock(return_value=None)

        response = self.client.patch(
            f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/out",
            json={"user_ids": [TEST_USER_ID]},
        )

        self.assertIn(response.status_code, {401, 403})
        self.tab_router.service.exit_tab.assert_not_awaited()

    @unittest.expectedFailure
    def test_outsider_cannot_read_tab_messages_before_membership_check(self) -> None:
        self.message_router.message_service.find_recent_messages = AsyncMock(return_value=[])

        response = self.client.get(
            f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/messages",
            headers=_outsider_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.message_router.message_service.find_recent_messages.assert_not_awaited()

    @unittest.expectedFailure
    def test_outsider_cannot_read_tab_info_before_membership_check(self) -> None:
        self.tab_router.wm_service.get_member_by_user_id = Mock(return_value=[])
        self.tab_router.service.find_tab = Mock(
            return_value=[(TAB_ID, "Security Tab", 1, "General")]
        )

        response = self.client.get(
            f"/api/workspaces/{WORKSPACE_ID}/tabs/{TAB_ID}/info",
            headers=_outsider_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.tab_router.service.find_tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
