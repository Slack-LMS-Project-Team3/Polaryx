from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


ADMIN_ROLE_NAMES = {"admin", "owner"}
MANAGE_ACTIONS = {
    "admin",
    "manage",
    "role:manage",
    "workspace:manage",
    "member:manage",
    "tab:manage",
}
ADMIN_ACTION_SUFFIXES = (":manage", ":delete", ":remove", ":update", ":create", ":invite")
MEMBER_SAFE_ACTIONS = {
    "read",
    "member:read",
    "workspace:read",
    "tab:read",
    "message:read",
    "notification:read",
}
MEMBERSHIP_ID_FIELDS = (
    "user_id",
    "userId",
    "member_id",
    "memberId",
    "workspace_member_id",
    "workspaceMemberId",
)


def _read_value(data: Any, *names: str) -> Any:
    if data is None:
        return None
    if isinstance(data, Mapping):
        for name in names:
            if name in data:
                return data[name]
        return None
    for name in names:
        if hasattr(data, name):
            return getattr(data, name)
    return None


def _iter_permissions(role_data: Any) -> Iterable[Any]:
    permissions = _read_value(role_data, "permissions", "permission")
    if permissions is None:
        return ()
    if isinstance(permissions, str):
        return (permissions,)
    return permissions


def _permission_value(permission: Any) -> Any:
    if isinstance(permission, Mapping):
        return _read_value(permission, "value", "name", "permission")
    return getattr(permission, "value", permission)


def _has_membership_identity(membership: Any) -> bool:
    if _read_value(membership, "workspace_id", "workspaceId") is None:
        return False
    return any(_read_value(membership, field) is not None for field in MEMBERSHIP_ID_FIELDS)


def _normalize_action(action: Any) -> str | None:
    if not isinstance(action, str):
        return None
    normalized = action.strip().lower()
    return normalized or None


def is_workspace_member(membership: Any) -> bool:
    if not membership:
        return False
    deleted_at = _read_value(membership, "deleted_at", "deletedAt")
    return deleted_at is None and _has_membership_identity(membership)


def has_admin_permission(membership: Any = None, role_data: Any = None) -> bool:
    for source in (membership, role_data):
        role_name = _read_value(source, "role_name", "role", "name")
        if isinstance(role_name, str) and role_name.lower() in ADMIN_ROLE_NAMES:
            return True
        for permission in _iter_permissions(source):
            value = _permission_value(permission)
            if isinstance(value, str) and value.lower() == "admin":
                return True
    return False


def can_access_member_resource(membership: Any, role_data: Any = None) -> bool:
    return is_workspace_member(membership)


def can_manage_workspace(membership: Any, role_data: Any = None) -> bool:
    return is_workspace_member(membership) and has_admin_permission(membership, role_data)


def can_perform_workspace_action(membership: Any, action: str, role_data: Any = None) -> bool:
    if not is_workspace_member(membership):
        return False
    normalized_action = _normalize_action(action)
    if normalized_action is None:
        return False
    if normalized_action in MANAGE_ACTIONS or normalized_action.endswith(ADMIN_ACTION_SUFFIXES):
        return has_admin_permission(membership, role_data)
    return normalized_action in MEMBER_SAFE_ACTIONS or normalized_action.endswith(":read")
