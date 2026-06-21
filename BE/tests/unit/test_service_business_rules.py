from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException


def _set_required_env() -> None:
    defaults = {
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
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


class DummyMySQLConnectionPool:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def get_connection(self) -> object:
        raise AssertionError("Service unit tests must not open real DB connections")


_set_required_env()
_MYSQL_POOL_PATCHER = patch("mysql.connector.pooling.MySQLConnectionPool", DummyMySQLConnectionPool)
_MYSQL_POOL_PATCHER.start()


def tearDownModule() -> None:
    _MYSQL_POOL_PATCHER.stop()


from app.core.exceptions import DatabaseError, ResourceConflictError, ResourceNotFoundError
from app.domain.message import Emoji
from app.domain.role import PermissionType
from app.schema.message.messages_response import MessageSchema
from app.schema.workspace_members.request import UpdateWorkspaceMemberRequest
from app.service.message import MessageService
from app.service.notification import NotificationService
from app.service.role import RoleService
from app.service.workspace_member import WorkspaceMemberService
from app.service import workspace_member as workspace_member_module


WORKSPACE_ID = 7
TAB_ID = 11
MESSAGE_ID = 2026
USER_ID = uuid.UUID("05ea49cf-d91f-41a0-be63-cace1718de71")
SENDER_ID = uuid.UUID("c0ffee00-0000-4000-8000-000000000001")
RECEIVER_ID = uuid.UUID("c0ffee00-0000-4000-8000-000000000002")


class MessageServiceBusinessRulesTest(unittest.IsolatedAsyncioTestCase):
    def _service_with_repo(self, repo: Mock) -> MessageService:
        with (
            patch("app.service.message.MessageRepo", return_value=repo),
            patch("app.service.message.FilesRepo", return_value=Mock()),
        ):
            return MessageService()

    async def test_toggle_like_plus_creates_emoji_updates_count_and_returns_camel_case_counts(self) -> None:
        repo = Mock()
        repo.get_emoji_counts.return_value = [(1, 2, 3, 4, 5)]
        service = self._service_with_repo(repo)

        result = await service.toggle_like(TAB_ID, MESSAGE_ID, USER_ID, "clap", True)

        repo.plus_emoji.assert_called_once()
        emoji = repo.plus_emoji.call_args.args[0]
        self.assertIsInstance(emoji, Emoji)
        self.assertEqual(emoji.tab_id, TAB_ID)
        self.assertEqual(emoji.msg_id, MESSAGE_ID)
        self.assertEqual(emoji.user_id, USER_ID)
        self.assertEqual(emoji.emoji_type, "clap")
        repo.update_emoji_cnt.assert_called_once_with(emoji, True)
        repo.minus_emoji.assert_not_called()
        self.assertEqual(
            result,
            {
                "checkCnt": 1,
                "clapCnt": 2,
                "likeCnt": 3,
                "prayCnt": 4,
                "sparkleCnt": 5,
            },
        )

    async def test_toggle_like_minus_removes_emoji_updates_count_and_returns_same_key_shape(self) -> None:
        repo = Mock()
        repo.get_emoji_counts.return_value = [(5, 4, 3, 2, 1)]
        service = self._service_with_repo(repo)

        result = await service.toggle_like(TAB_ID, MESSAGE_ID, USER_ID, "sparkle", False)

        repo.minus_emoji.assert_called_once()
        emoji = repo.minus_emoji.call_args.args[0]
        repo.update_emoji_cnt.assert_called_once_with(emoji, False)
        repo.plus_emoji.assert_not_called()
        self.assertEqual(
            set(result),
            {"checkCnt", "clapCnt", "likeCnt", "prayCnt", "sparkleCnt"},
        )
        self.assertEqual(result["sparkleCnt"], 1)

    def test_get_emoji_counts_returns_zero_counts_when_repository_has_no_rows(self) -> None:
        repo = Mock()
        repo.get_emoji_counts.return_value = []
        service = self._service_with_repo(repo)

        self.assertEqual(
            service.get_emoji_counts(MESSAGE_ID),
            {
                "checkCnt": 0,
                "clapCnt": 0,
                "likeCnt": 0,
                "prayCnt": 0,
                "sparkleCnt": 0,
            },
        )

    async def test_save_message_builds_message_and_returns_lastrowid(self) -> None:
        repo = Mock()
        repo.insert.return_value = {"lastrowid": 1234}
        service = self._service_with_repo(repo)

        result = await service.save_message(TAB_ID, USER_ID, "hello", "https://files.example/a.png")

        inserted = repo.insert.call_args.args[0]
        self.assertEqual(inserted.tab_id, TAB_ID)
        self.assertEqual(inserted.sender_id, USER_ID)
        self.assertEqual(inserted.content, "hello")
        self.assertEqual(inserted.file_url, "https://files.example/a.png")
        self.assertEqual(result, 1234)

    def test_message_schema_from_row_shapes_response_fields(self) -> None:
        created_at = datetime(2026, 6, 18, 1, 0, tzinfo=UTC)
        row = (
            MESSAGE_ID,
            TAB_ID,
            USER_ID.bytes,
            "Lena",
            None,
            "status update",
            True,
            created_at,
            None,
            None,
            "",
            1,
            2,
            3,
            4,
            5,
            1,
            0,
            1,
            0,
            1,
        )

        schema = MessageSchema.from_row(row)

        self.assertEqual(schema.sender_id, USER_ID.hex)
        self.assertEqual(schema.image, "")
        self.assertIsNone(schema.file_url)
        self.assertEqual(schema.e_check_cnt, 1)
        self.assertEqual(schema.e_clap_cnt, 2)
        self.assertEqual(schema.e_like_cnt, 3)
        self.assertEqual(schema.e_pray_cnt, 4)
        self.assertEqual(schema.e_sparkle_cnt, 5)
        self.assertEqual(
            schema.my_toggle,
            {"check": True, "clap": False, "like": True, "pray": False, "sparkle": True},
        )

    async def test_modify_and_delete_message_propagate_actual_repository_success_and_http_errors(self) -> None:
        repo = Mock()
        repo.update_message_content.return_value = {"rowcount": 1}
        repo.delete_message_by_id.return_value = 1
        service = self._service_with_repo(repo)

        self.assertEqual(await service.modify_message(MESSAGE_ID, "edited", USER_ID.hex), {"rowcount": 1})
        self.assertEqual(await service.delete_message(MESSAGE_ID, USER_ID.hex), 1)

        repo.update_message_content.side_effect = HTTPException(status_code=403, detail="forbidden")
        with self.assertRaises(HTTPException):
            await service.modify_message(MESSAGE_ID, "missing", USER_ID.hex)

        repo.delete_message_by_id.side_effect = HTTPException(status_code=403, detail="forbidden")
        with self.assertRaises(HTTPException):
            await service.delete_message(MESSAGE_ID, USER_ID.hex)

    async def test_modify_and_delete_message_raise_value_error_when_collaborator_reports_zero(self) -> None:
        repo = Mock()
        repo.update_message_content.return_value = 0
        repo.delete_message_by_id.return_value = 0
        service = self._service_with_repo(repo)

        with self.assertRaises(ValueError):
            await service.modify_message(MESSAGE_ID, "missing", USER_ID.hex)
        with self.assertRaises(ValueError):
            await service.delete_message(MESSAGE_ID, USER_ID.hex)


class NotificationServiceBusinessRulesTest(unittest.IsolatedAsyncioTestCase):
    def _service_with_repo(self, repo: Mock) -> NotificationService:
        with patch("app.service.notification.NotificationRepo", return_value=repo):
            return NotificationService()

    async def test_create_notification_converts_uuid_strings_to_bytes_before_insert(self) -> None:
        repo = Mock()
        service = self._service_with_repo(repo)

        await service.create_notification(
            str(RECEIVER_ID),
            str(SENDER_ID),
            TAB_ID,
            MESSAGE_ID,
            2,
            "mentioned you",
        )

        payload = repo.insert.call_args.args[0]
        self.assertEqual(payload["receiver_id"], RECEIVER_ID.bytes)
        self.assertEqual(payload["sender_id"], SENDER_ID.bytes)
        self.assertEqual(payload["tab_id"], TAB_ID)
        self.assertEqual(payload["message_id"], MESSAGE_ID)
        self.assertEqual(payload["type"], 2)
        self.assertEqual(payload["content"], "mentioned you")

    def test_get_notifications_finds_by_uuid_and_maps_rows(self) -> None:
        created_at = datetime(2026, 6, 18, 1, 15, tzinfo=UTC)
        repo = Mock()
        repo.find_by_user.return_value = [
            (1, RECEIVER_ID.bytes, SENDER_ID.bytes, TAB_ID, MESSAGE_ID, 2, "ping", False, created_at, None)
        ]
        service = self._service_with_repo(repo)

        result = service.get_notifications(str(RECEIVER_ID))

        repo.find_by_user.assert_called_once_with(RECEIVER_ID)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].receiver_id, RECEIVER_ID)
        self.assertEqual(result[0].sender_id, SENDER_ID)
        self.assertEqual(result[0].content, "ping")


class RoleServiceBusinessRulesTest(unittest.TestCase):
    def _role_row(self, role_id: int = 1, name: str = "Guest") -> tuple:
        return (
            role_id,
            name,
            WORKSPACE_ID,
            name == "Admin",
            False,
            False,
            False,
            datetime(2026, 6, 18, 1, 30, tzinfo=UTC),
            None,
            None,
        )

    def _service_with_repo(self, repo: Mock) -> RoleService:
        with patch("app.service.role.RolesRepo", return_value=repo):
            return RoleService()

    def test_find_all_find_create_modify_and_delete_map_repository_rows(self) -> None:
        repo = Mock()
        repo.find_all.return_value = [self._role_row(1, "Guest"), self._role_row(2, "Admin")]
        repo.find_by_user_id.return_value = self._role_row(2, "Admin")
        repo.find_by_name.return_value = self._role_row(3, "Operator")
        repo.find.return_value = self._role_row(3, "Renamed")
        repo.delete.return_value = True
        service = self._service_with_repo(repo)

        roles = service.find_all(WORKSPACE_ID)
        self.assertEqual([role.name for role in roles], ["Guest", "Admin"])
        self.assertEqual(service.find(WORKSPACE_ID, USER_ID.bytes).name, "Admin")
        self.assertEqual(service.create(WORKSPACE_ID, "Operator", [PermissionType.CHANNEL]).name, "Operator")
        self.assertEqual(service.modify(WORKSPACE_ID, 3, "Renamed", [PermissionType.ADMIN]).name, "Renamed")
        self.assertTrue(service.delete(WORKSPACE_ID, 3))

    def test_duplicate_role_creation_maps_to_resource_conflict(self) -> None:
        repo = Mock()
        repo.insert.side_effect = ValueError("이미 존재합니다: Admin")
        service = self._service_with_repo(repo)

        with self.assertRaises(ResourceConflictError):
            service.create(WORKSPACE_ID, "Admin", [PermissionType.ADMIN])

    def test_missing_role_operations_map_to_not_found_and_unexpected_errors_map_to_database_error(self) -> None:
        service = self._service_with_repo(Mock(find_by_user_id=Mock(side_effect=ValueError("missing"))))
        with self.assertRaises(ResourceNotFoundError):
            service.find(WORKSPACE_ID, USER_ID.bytes)

        service = self._service_with_repo(Mock(update=Mock(side_effect=ValueError("missing"))))
        with self.assertRaises(ResourceNotFoundError):
            service.modify(WORKSPACE_ID, 3, "Missing", [])

        service = self._service_with_repo(Mock(delete=Mock(side_effect=ValueError("missing"))))
        with self.assertRaises(ResourceNotFoundError):
            service.delete(WORKSPACE_ID, 3)

        service = self._service_with_repo(Mock(find_all=Mock(side_effect=RuntimeError("db down"))))
        with self.assertLogs(level="ERROR"), self.assertRaises(DatabaseError):
            service.find_all(WORKSPACE_ID)

    def test_insert_member_roles_bulk_defaults_imported_users_to_guest_only(self) -> None:
        repo = Mock()
        repo.get_all_roles.return_value = [(1, "Admin"), (2, "Guest")]
        repo.bulk_insert_member_roles.return_value = 2
        service = self._service_with_repo(repo)

        result = service.insert_member_roles_bulk(
            {
                "users": [
                    {"email": "admin@example.com", "name": "Ada", "role": "Admin"},
                    {"email": "guest@example.com", "name": "Grace", "role": "Owner"},
                ]
            }
        )

        self.assertEqual(result, 2)
        repo.bulk_insert_member_roles.assert_called_once_with(
            [
                {"email": "admin@example.com", "role_id": 2, "name": "Ada"},
                {"email": "guest@example.com", "role_id": 2, "name": "Grace"},
            ]
        )

    def test_delete_member_roles_converts_user_id_string_to_uuid_bytes(self) -> None:
        repo = Mock()
        repo.delete_mem_role.return_value = True
        service = self._service_with_repo(repo)

        self.assertTrue(service.delete_member_roles(str(USER_ID), WORKSPACE_ID))
        repo.delete_mem_role.assert_called_once_with(USER_ID.bytes, WORKSPACE_ID)


class AccessControlHelperTest(unittest.TestCase):
    def _membership(self, role_name: str = "Guest") -> dict[str, object]:
        return {"workspace_id": WORKSPACE_ID, "user_id": USER_ID.hex, "role_name": role_name}

    def test_member_can_read_member_scoped_resources_and_non_member_is_denied(self) -> None:
        from app.service.access_control import can_access_member_resource

        self.assertTrue(can_access_member_resource(self._membership("Guest")))
        self.assertFalse(can_access_member_resource(None))
        self.assertFalse(can_access_member_resource({}))
        self.assertFalse(can_access_member_resource({"workspace_id": WORKSPACE_ID, "role_name": "Guest"}))
        self.assertFalse(can_access_member_resource({"user_id": USER_ID.hex, "role_name": "Guest"}))

    def test_admin_can_manage_sensitive_actions_but_guest_and_member_cannot(self) -> None:
        from app.service.access_control import can_manage_workspace, can_perform_workspace_action

        admin = self._membership("Admin")
        member = self._membership("Member")
        guest = self._membership("Guest")

        self.assertTrue(can_manage_workspace(admin))
        self.assertTrue(can_perform_workspace_action(admin, "role:manage"))
        self.assertTrue(can_perform_workspace_action(admin, " Workspace:Manage "))
        self.assertFalse(can_manage_workspace(guest))
        self.assertFalse(can_perform_workspace_action(member, "role:manage"))
        self.assertFalse(can_perform_workspace_action(member, "Workspace:Manage"))
        self.assertFalse(can_perform_workspace_action(member, "workspace:delete"))
        self.assertTrue(can_perform_workspace_action(member, "message:read"))
        self.assertFalse(can_perform_workspace_action(admin, "workspace:unknown"))
        self.assertFalse(can_perform_workspace_action(member, None))

    def test_admin_permission_accepts_mapping_permissions(self) -> None:
        from app.service.access_control import can_manage_workspace

        self.assertTrue(
            can_manage_workspace(
                self._membership("Member"),
                {"permissions": [{"value": "admin"}]},
            )
        )


class WorkspaceMemberServiceBusinessRulesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tab_service = workspace_member_module.tab_service
        self.original_role_service = workspace_member_module.role_service
        self.original_group_service = workspace_member_module.group_service
        self.addCleanup(setattr, workspace_member_module, "tab_service", self.original_tab_service)
        self.addCleanup(setattr, workspace_member_module, "role_service", self.original_role_service)
        self.addCleanup(setattr, workspace_member_module, "group_service", self.original_group_service)

    def _service_with_repo(self, repo: Mock) -> WorkspaceMemberService:
        with patch("app.service.workspace_member.WorkspaceMemberRepo", return_value=repo):
            return WorkspaceMemberService()

    def test_get_member_by_user_id_simple_converts_uuid_and_preserves_byte_input(self) -> None:
        repo = Mock()
        repo.find_by_user_id_simple.side_effect = [[("Lena",)], [("Byte Lena",)]]
        service = self._service_with_repo(repo)

        self.assertEqual(service.get_member_by_user_id_simple(USER_ID, WORKSPACE_ID), [("Lena",)])
        self.assertEqual(service.get_member_by_user_id_simple(USER_ID.bytes, WORKSPACE_ID), [("Byte Lena",)])
        repo.find_by_user_id_simple.assert_any_call(USER_ID.bytes, WORKSPACE_ID)

    def test_insert_workspace_member_builds_bulk_rows_with_generated_ids_and_optional_profiles(self) -> None:
        repo = Mock()
        repo.bulk_insert_workspace_member.return_value = 2
        service = self._service_with_repo(repo)

        result = service.insert_workspace_member(
            {
                "users": [
                    {
                        "name": "Ada",
                        "email": "ada@example.com",
                        "blog": "https://blog.example/ada",
                        "github": "ada",
                    },
                    {"name": "Grace", "email": "grace@example.com"},
                ]
            },
            WORKSPACE_ID,
        )

        self.assertEqual(result, 2)
        rows = repo.bulk_insert_workspace_member.call_args.args[0]
        self.assertEqual(rows[0]["nickname"], "Ada")
        self.assertEqual(rows[0]["email"], "ada@example.com")
        self.assertEqual(rows[0]["workspace_id"], WORKSPACE_ID)
        self.assertEqual(len(rows[0]["id"]), 16)
        self.assertEqual(rows[0]["blog"], "https://blog.example/ada")
        self.assertEqual(rows[0]["github"], "ada")
        self.assertIsNone(rows[1]["blog"])
        self.assertIsNone(rows[1]["github"])

    def test_update_profile_by_user_id_renames_dm_tabs_and_returns_updated_member(self) -> None:
        repo = Mock()
        repo.find_by_user_id.side_effect = [
            [(USER_ID.bytes, WORKSPACE_ID, "Old Nick", "old@example.com", "", "Member", "", None, None, b"wm-id")],
            [(USER_ID.bytes, WORKSPACE_ID, "New Nick", "old@example.com", "", "Member", "", "git", "blog", b"wm-id")],
        ]
        service = self._service_with_repo(repo)
        fake_tab_service = Mock()
        fake_tab_service.find_tabs.return_value = [
            (10, "Old Nick, Teammate", 4),
            (20, "general", 1),
        ]
        workspace_member_module.tab_service = fake_tab_service

        response = service.update_profile_by_user_id(
            WORKSPACE_ID,
            USER_ID,
            UpdateWorkspaceMemberRequest(nickname="New Nick", github="git", blog="blog", image=None),
        )

        fake_tab_service.modify_name.assert_called_once_with(WORKSPACE_ID, 10, "Teammate, New Nick")
        repo.update.assert_called_once()
        self.assertEqual(response.workspace_member.nickname, "New Nick")
        self.assertEqual(response.workspace_member.github, "git")
        self.assertEqual(response.workspace_member.blog, "blog")

    async def test_delete_member_exits_tabs_deletes_matching_workspace_member_and_combines_cleanup_results(self) -> None:
        repo = Mock()
        repo.find_by_user_id.return_value = [
            (USER_ID.bytes, 99, "Other", "other@example.com", "", "Member", "", None, None, b"other-wm"),
            (USER_ID.bytes, WORKSPACE_ID, "Lena", "lena@example.com", "", "Member", "", None, None, b"target-wm"),
        ]
        service = self._service_with_repo(repo)
        fake_tab_service = Mock()
        fake_tab_service.find_tabs.return_value = [(1,), (2,)]
        fake_tab_service.exit_tab = AsyncMock()
        fake_role_service = Mock()
        fake_role_service.delete_member_roles.return_value = True
        fake_group_service = Mock()
        fake_group_service.delete_grp_mem_by_ws_id.return_value = True
        workspace_member_module.tab_service = fake_tab_service
        workspace_member_module.role_service = fake_role_service
        workspace_member_module.group_service = fake_group_service

        with patch("builtins.print"):
            result = await service.delete_member(WORKSPACE_ID, str(USER_ID))

        fake_tab_service.exit_tab.assert_any_await(WORKSPACE_ID, 1, [str(USER_ID)])
        fake_tab_service.exit_tab.assert_any_await(WORKSPACE_ID, 2, [str(USER_ID)])
        repo.delete_wm_by_id.assert_called_once_with(b"target-wm")
        fake_role_service.delete_member_roles.assert_called_once_with(str(USER_ID), WORKSPACE_ID)
        fake_group_service.delete_grp_mem_by_ws_id.assert_called_once_with(str(USER_ID), WORKSPACE_ID)
        self.assertTrue(result)

    async def test_delete_member_returns_false_when_any_cleanup_result_is_false(self) -> None:
        for role_cleanup, group_cleanup in [(False, True), (True, False)]:
            with self.subTest(role_cleanup=role_cleanup, group_cleanup=group_cleanup):
                repo = Mock()
                repo.find_by_user_id.return_value = [
                    (USER_ID.bytes, WORKSPACE_ID, "Lena", "lena@example.com", "", "Member", "", None, None, b"target-wm"),
                ]
                service = self._service_with_repo(repo)
                fake_tab_service = Mock()
                fake_tab_service.find_tabs.return_value = []
                fake_role_service = Mock()
                fake_role_service.delete_member_roles.return_value = role_cleanup
                fake_group_service = Mock()
                fake_group_service.delete_grp_mem_by_ws_id.return_value = group_cleanup
                workspace_member_module.tab_service = fake_tab_service
                workspace_member_module.role_service = fake_role_service
                workspace_member_module.group_service = fake_group_service

                result = await service.delete_member(WORKSPACE_ID, str(USER_ID))

                repo.delete_wm_by_id.assert_called_once_with(b"target-wm")
                self.assertFalse(result)


class ServiceUnitIsolationTest(unittest.TestCase):
    def test_service_unit_module_does_not_need_app_sse_web_push_or_live_redis_state(self) -> None:
        script = """
import sys
import tests.unit.test_service_business_rules
from app.util.database.redis import RedisManager

assert "app.main" not in sys.modules, "unit import should not start the FastAPI app"
assert "app.router.sse" not in sys.modules, "unit import should not load SSE router state"
assert "app.router.push" not in sys.modules, "unit import should not load Web Push router state"
assert RedisManager._instance is None, "unit import should not create a Redis client"
assert RedisManager._pubsub_instance is None, "unit import should not create a Redis pubsub client"
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)


if __name__ == "__main__":
    unittest.main()
