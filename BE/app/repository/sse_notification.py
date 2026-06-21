from __future__ import annotations

import json
import uuid
from typing import Any

from app.util.database.db_factory import DBFactory


EVENT_COLUMNS = """
id,
event_id,
workspace_id,
LOWER(HEX(recipient_user_id)) AS recipient_user_id,
recipient_scope,
type,
tab_id,
payload_json,
created_at,
published_at,
status
"""

insert_notification_event = """
INSERT INTO notification_events (
  event_id,
  workspace_id,
  recipient_user_id,
  recipient_scope,
  type,
  tab_id,
  payload_json,
  status
) VALUES (
  %(event_id)s,
  %(workspace_id)s,
  %(recipient_user_id)s,
  %(recipient_scope)s,
  %(type)s,
  %(tab_id)s,
  %(payload_json)s,
  'pending'
)
ON DUPLICATE KEY UPDATE event_id = event_id;
"""

find_event_by_event_id = f"""
SELECT {EVENT_COLUMNS}
FROM notification_events
WHERE event_id = %(event_id)s;
"""

list_published_events_after = f"""
SELECT ne.id,
       ne.event_id,
       ne.workspace_id,
       LOWER(HEX(ne.recipient_user_id)) AS recipient_user_id,
       ne.recipient_scope,
       ne.type,
       ne.tab_id,
       ne.payload_json,
       ne.created_at,
       ne.published_at,
       ne.status
FROM notification_events ne
LEFT JOIN notification_events cursor_event
  ON cursor_event.event_id = %(after_event_id)s
WHERE ne.workspace_id = %(workspace_id)s
  AND ne.status = 'published'
  AND (%(after_event_id)s IS NULL OR ne.id > COALESCE(cursor_event.id, 0))
  AND (ne.recipient_user_id IS NULL OR ne.recipient_user_id = %(recipient_user_id)s)
ORDER BY ne.id ASC
LIMIT %(limit)s;
"""

mark_event_published = """
UPDATE notification_events
SET status = 'published',
    published_at = CURRENT_TIMESTAMP
WHERE event_id = %(event_id)s;
"""

mark_event_failed = """
UPDATE notification_events
SET status = 'failed'
WHERE event_id = %(event_id)s;
"""

find_event_position = """
SELECT id
FROM notification_events
WHERE event_id = %(event_id)s
  AND workspace_id = %(workspace_id)s;
"""

find_delivery_state = """
SELECT last_acked_event_id
FROM notification_delivery_state
WHERE user_id = %(user_id)s
  AND workspace_id = %(workspace_id)s;
"""

upsert_delivery_state = """
INSERT INTO notification_delivery_state (
  user_id,
  workspace_id,
  last_acked_event_id,
  last_acked_at
) VALUES (
  %(user_id)s,
  %(workspace_id)s,
  %(last_acked_event_id)s,
  CURRENT_TIMESTAMP
)
ON DUPLICATE KEY UPDATE
  last_acked_event_id = VALUES(last_acked_event_id),
  last_acked_at = CURRENT_TIMESTAMP;
"""

count_pending_events = """
SELECT COUNT(*)
FROM notification_events
WHERE status = 'pending';
"""


class NotificationEventRepository:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db if db is not None else DBFactory.get_db("MySQL")

    def insert_event(
        self,
        *,
        event_id: str,
        workspace_id: int,
        recipient_user_id: str | None,
        recipient_scope: str,
        event_type: str,
        tab_id: int | None,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        result = self.db.execute(
            insert_notification_event,
            {
                "event_id": event_id,
                "workspace_id": workspace_id,
                "recipient_user_id": _uuid_bytes_or_none(recipient_user_id),
                "recipient_scope": recipient_scope,
                "type": event_type,
                "tab_id": tab_id,
                "payload_json": json.dumps(payload, ensure_ascii=False),
            },
        )
        inserted = isinstance(result, dict) and int(result.get("rowcount") or 0) > 0
        event = self.find_event(event_id)
        if event is None:
            raise RuntimeError("notification event insert did not return a readable row")
        return event, inserted

    def find_event(self, event_id: str) -> dict[str, Any] | None:
        rows = self.db.execute(find_event_by_event_id, {"event_id": event_id})
        if not rows:
            return None
        return _event_from_row(rows[0])

    def list_events_after(
        self,
        *,
        workspace_id: int,
        user_id: str,
        after_event_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            list_published_events_after,
            {
                "workspace_id": workspace_id,
                "recipient_user_id": _uuid_bytes_or_none(user_id),
                "after_event_id": after_event_id,
                "limit": max(1, int(limit)),
            },
        )
        return [_event_from_row(row) for row in rows or []]

    def mark_published(self, event_id: str) -> None:
        self.db.execute(mark_event_published, {"event_id": event_id})

    def mark_failed(self, event_id: str) -> None:
        self.db.execute(mark_event_failed, {"event_id": event_id})

    def get_last_acked_event_id(self, *, user_id: str, workspace_id: int) -> str | None:
        rows = self.db.execute(
            find_delivery_state,
            {
                "user_id": _uuid_bytes_or_none(user_id),
                "workspace_id": workspace_id,
            },
        )
        if not rows:
            return None
        return rows[0][0]

    def ack_event(self, *, user_id: str, workspace_id: int, event_id: str) -> bool:
        new_position = self._event_position(workspace_id=workspace_id, event_id=event_id)
        if new_position is None:
            raise ValueError("cannot ack an unknown notification event")

        current_event_id = self.get_last_acked_event_id(user_id=user_id, workspace_id=workspace_id)
        if current_event_id == event_id:
            return False
        if current_event_id:
            current_position = self._event_position(workspace_id=workspace_id, event_id=current_event_id)
            if current_position is not None and current_position > new_position:
                return False

        self.db.execute(
            upsert_delivery_state,
            {
                "user_id": _uuid_bytes_or_none(user_id),
                "workspace_id": workspace_id,
                "last_acked_event_id": event_id,
            },
        )
        return True

    def pending_count(self) -> int | None:
        rows = self.db.execute(count_pending_events)
        if not rows:
            return 0
        return int(rows[0][0])

    def _event_position(self, *, workspace_id: int, event_id: str) -> int | None:
        rows = self.db.execute(
            find_event_position,
            {
                "workspace_id": workspace_id,
                "event_id": event_id,
            },
        )
        if not rows:
            return None
        return int(rows[0][0])


def _uuid_bytes_or_none(value: str | None) -> bytes | None:
    if not value:
        return None
    return uuid.UUID(str(value)).bytes


def _event_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    raw_payload = row[7]
    if isinstance(raw_payload, (bytes, bytearray)):
        raw_payload = raw_payload.decode("utf-8")
    payload = raw_payload if isinstance(raw_payload, dict) else json.loads(str(raw_payload))
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("event_id", row[1])
    payload.setdefault("type", row[5])
    if row[6] is not None:
        payload.setdefault("tab_id", row[6])
    return {
        "id": row[0],
        "event_id": row[1],
        "workspace_id": row[2],
        "recipient_user_id": row[3],
        "recipient_scope": row[4],
        "type": row[5],
        "tab_id": row[6],
        "payload": payload,
        "created_at": row[8],
        "published_at": row[9],
        "status": row[10],
    }
