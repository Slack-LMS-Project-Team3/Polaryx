#!/usr/bin/env python3
"""Seed deterministic local rows for Story 2.1 DB index benchmarking."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import mysql.connector


DEFAULT_WORKSPACE_ID = 9901
DEFAULT_SECTION_ID = 9901
DEFAULT_TAB_ID = 9901001
DEFAULT_MESSAGES = 100_000
DEFAULT_USERS = 30
DEFAULT_NOTIFICATIONS = 3_000
FIXTURE_PREFIX = "db-index-fixture"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--section-id", type=int, default=DEFAULT_SECTION_ID)
    parser.add_argument("--tab-id", type=int, default=DEFAULT_TAB_ID)
    parser.add_argument("--messages", type=int, default=DEFAULT_MESSAGES)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--notifications", type=int, default=DEFAULT_NOTIFICATIONS)
    parser.add_argument("--emoji-every", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")
    return parser.parse_args()


def connection_config() -> dict[str, Any]:
    return {
        "host": os.getenv("RDB_HOST", "127.0.0.1"),
        "port": int(os.getenv("RDB_PORT", "3306")),
        "user": os.getenv("DB_USER", "polaryx"),
        "password": os.getenv("DB_PASSWORD", "polaryx"),
        "database": os.getenv("DB_NAME", "polaryx"),
        "connection_timeout": int(os.getenv("CONNECTION_TIMEOUT", "10")),
        "charset": "utf8mb4",
    }


def fixture_uuid(label: str) -> bytes:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"polaryx-{FIXTURE_PREFIX}-{label}").bytes


def user_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = []
    for index in range(args.users):
        user_id = fixture_uuid(f"user-{args.workspace_id}-{index}")
        member_id = fixture_uuid(f"workspace-member-{args.workspace_id}-{index}")
        rows.append(
            {
                "user_id": user_id,
                "member_id": member_id,
                "name": f"dbidx{index:03d}",
                "nickname": f"db-index-{index:03d}",
                "email": f"db-index-{args.workspace_id}-{index:03d}@example.invalid",
            }
        )
    return rows


def chunks(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def plan_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "workspace_id": args.workspace_id,
        "section_id": args.section_id,
        "tab_id": args.tab_id,
        "messages": args.messages,
        "users": args.users,
        "notifications": args.notifications,
        "emoji_every": args.emoji_every,
        "batch_size": args.batch_size,
        "safe_to_rerun": True,
        "cleanup": (
            "Deletes only fixture rows matching "
            f"{FIXTURE_PREFIX} content in the target tab/workspace before reseeding unless --skip-cleanup is used."
        ),
        "env": {
            "RDB_HOST": os.getenv("RDB_HOST", "127.0.0.1"),
            "RDB_PORT": os.getenv("RDB_PORT", "3306"),
            "DB_NAME": os.getenv("DB_NAME", "polaryx"),
            "DB_USER": os.getenv("DB_USER", "polaryx"),
        },
        "fixture_file": str(Path(__file__).resolve()),
    }


def cleanup_fixture(cursor: mysql.connector.cursor.MySQLCursor, args: argparse.Namespace) -> None:
    cursor.execute(
        """
        DELETE e
        FROM emoji e
        JOIN messages m ON m.id = e.msg_id
        WHERE m.tab_id = %s
          AND m.content LIKE %s
        """,
        (args.tab_id, f"{FIXTURE_PREFIX}-%"),
    )
    cursor.execute(
        """
        DELETE FROM notifications
        WHERE workspace_id = %s
          AND content LIKE %s
        """,
        (args.workspace_id, f"{FIXTURE_PREFIX}-%"),
    )
    cursor.execute(
        """
        DELETE FROM messages
        WHERE tab_id = %s
          AND content LIKE %s
        """,
        (args.tab_id, f"{FIXTURE_PREFIX}-%"),
    )


def seed_base_entities(cursor: mysql.connector.cursor.MySQLCursor, args: argparse.Namespace, users: list[dict[str, Any]]) -> None:
    cursor.execute(
        """
        INSERT INTO workspaces (id, name)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE name = VALUES(name), deleted_at = NULL
        """,
        (args.workspace_id, "DB Index Fixture"),
    )
    cursor.execute(
        """
        INSERT IGNORE INTO sections (id, workspace_id, name)
        VALUES (%s, %s, %s)
        """,
        (args.section_id, args.workspace_id, "DB Index Fixture"),
    )
    cursor.execute(
        """
        INSERT INTO tabs (id, name, workspace_id, section_id)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE name = VALUES(name), deleted_at = NULL
        """,
        (args.tab_id, "db-index-hot-tab", args.workspace_id, args.section_id),
    )

    cursor.executemany(
        """
        INSERT INTO users (id, name, email, provider, provider_id, workspace_id)
        VALUES (%(user_id)s, %(name)s, %(email)s, 'local-fixture', %(email)s, %(workspace_id)s)
        ON DUPLICATE KEY UPDATE name = VALUES(name), deleted_at = NULL
        """,
        [{**user, "workspace_id": args.workspace_id} for user in users],
    )
    cursor.executemany(
        """
        INSERT INTO workspace_members (id, user_id, workspace_id, nickname, email, image, github, blog)
        VALUES (%(member_id)s, %(user_id)s, %(workspace_id)s, %(nickname)s, %(email)s, NULL, NULL, NULL)
        ON DUPLICATE KEY UPDATE nickname = VALUES(nickname), deleted_at = NULL
        """,
        [{**user, "workspace_id": args.workspace_id} for user in users],
    )
    cursor.executemany(
        """
        INSERT INTO tab_members (workspace_id, user_id, tab_id, user_name)
        VALUES (%(workspace_id)s, %(user_id)s, %(tab_id)s, %(nickname)s)
        ON DUPLICATE KEY UPDATE user_name = VALUES(user_name)
        """,
        [{**user, "workspace_id": args.workspace_id, "tab_id": args.tab_id} for user in users],
    )


def seed_messages(
    cursor: mysql.connector.cursor.MySQLCursor,
    args: argparse.Namespace,
    users: list[dict[str, Any]],
) -> list[int]:
    started_at = datetime(2026, 1, 1, 0, 0, 0)

    def message_values() -> Iterable[tuple[Any, ...]]:
        for index in range(args.messages):
            user = users[index % len(users)]
            yield (
                args.tab_id,
                user["user_id"],
                f"{FIXTURE_PREFIX}-message-{index:06d}",
                user["nickname"],
                args.workspace_id,
                started_at + timedelta(seconds=index),
            )

    for batch in chunks(message_values(), args.batch_size):
        cursor.executemany(
            """
            INSERT INTO messages (tab_id, sender_id, content, sender_name, workspace_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            batch,
        )

    cursor.execute(
        """
        SELECT id
        FROM messages
        WHERE tab_id = %s
          AND content LIKE %s
        ORDER BY id
        """,
        (args.tab_id, f"{FIXTURE_PREFIX}-message-%"),
    )
    return [int(row[0]) for row in cursor.fetchall()]


def seed_emoji(
    cursor: mysql.connector.cursor.MySQLCursor,
    args: argparse.Namespace,
    users: list[dict[str, Any]],
    message_ids: list[int],
) -> int:
    if args.emoji_every <= 0:
        return 0

    rows = []
    for index, message_id in enumerate(message_ids):
        if index % args.emoji_every != 0:
            continue
        user = users[index % len(users)]
        rows.append((message_id, user["user_id"], args.workspace_id, 1))

    for batch in chunks(rows, args.batch_size):
        cursor.executemany(
            """
            INSERT INTO emoji (msg_id, user_id, workspace_id, e_like)
            VALUES (%s, %s, %s, %s)
            """,
            batch,
        )
    return len(rows)


def seed_notifications(
    cursor: mysql.connector.cursor.MySQLCursor,
    args: argparse.Namespace,
    users: list[dict[str, Any]],
    message_ids: list[int],
) -> int:
    if not message_ids:
        return 0

    rows = []
    for index in range(args.notifications):
        receiver = users[index % len(users)]
        sender = users[(index + 1) % len(users)]
        message_id = message_ids[index % len(message_ids)]
        rows.append(
            (
                receiver["user_id"],
                sender["user_id"],
                args.tab_id,
                message_id,
                1,
                f"{FIXTURE_PREFIX}-notification-{index:06d}",
                args.workspace_id,
            )
        )

    for batch in chunks(rows, args.batch_size):
        cursor.executemany(
            """
            INSERT INTO notifications (receiver_id, sender_id, tab_id, message_id, type, content, workspace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            batch,
        )
    return len(rows)


def main() -> int:
    args = parse_args()
    if args.messages < 0 or args.users <= 0 or args.notifications < 0:
        raise SystemExit("--messages and --notifications must be non-negative; --users must be positive")

    plan = plan_payload(args)
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    users = user_rows(args)
    connection = mysql.connector.connect(**connection_config())
    try:
        cursor = connection.cursor()
        if not args.skip_cleanup:
            cleanup_fixture(cursor, args)
        seed_base_entities(cursor, args, users)
        message_ids = seed_messages(cursor, args, users)
        emoji_rows = seed_emoji(cursor, args, users, message_ids)
        notification_rows = seed_notifications(cursor, args, users, message_ids)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    print(
        json.dumps(
            {
                **plan,
                "inserted": {
                    "messages": len(message_ids),
                    "emoji": emoji_rows,
                    "notifications": notification_rows,
                    "workspace_members": len(users),
                    "tab_members": len(users),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
