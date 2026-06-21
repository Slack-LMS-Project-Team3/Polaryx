import json
import logging
import time
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
from datetime import datetime
import pytz

from app.service.websocket_manager import ConnectionManager
from app.service.realtime_observability import realtime_observability
from app.service.message import MessageService
from app.service.message_persistence import message_persistence_service
from app.service.workspace_member import WorkspaceMemberService

from app.service.tab import TabService

import uuid

router = APIRouter()
logger = logging.getLogger(__name__)

REALTIME_SOCKET_TYPE = "realtime"
realtime_connection = ConnectionManager()

# Temporary compatibility aliases for older imports/tests during the route migration.
message_connection = realtime_connection
like_connection = realtime_connection
profile_connection = realtime_connection

message_service = MessageService()
workspace_member_service = WorkspaceMemberService()

tab_service = TabService()

# 사용자 정보 캐시 (메모리 캐시)
user_cache = {}


def _target_tab_id(tab_row):
    if isinstance(tab_row, (list, tuple)):
        return tab_row[0]
    return tab_row


def _resolve_message_type(data: dict, *, legacy_profile_payload: bool = False) -> str:
    message_type = data.get("type")
    if message_type:
        return message_type
    if legacy_profile_payload and {"sender_id", "nickname", "image"}.issubset(data):
        return "profile"
    raise ValueError("missing realtime payload type")


def _extract_perf_id(content: str) -> str | None:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("perf_id"):
        return None
    return str(payload["perf_id"])


async def _send_persistence_error(
    websocket: WebSocket,
    *,
    temp_message_id: str,
    code: str,
    retryable: bool = True,
) -> None:
    await websocket.send_text(
        json.dumps(
            {
                "type": "send_error",
                "temp_message_id": temp_message_id,
                "code": code,
                "retryable": retryable,
            }
        )
    )


async def _handle_send(workspace_id: int, tab_id: int, data: dict, websocket: WebSocket):
    sender_id = data["sender_id"]
    content = data["content"]
    file_data = data.get("file_url")

    # 사용자 정보 캐시 확인 (DB 조회 최소화)
    if sender_id not in user_cache:
        workspace_member = workspace_member_service.get_member_by_user_id(uuid.UUID(sender_id).bytes)
        user_cache[sender_id] = {
            "nickname": workspace_member[0][2],
            "image": workspace_member[0][4],
        }

    user_info = user_cache[sender_id]
    nickname = user_info["nickname"]
    image = user_info["image"]

    # 임시 ID로 즉시 응답, 실제 저장은 백그라운드에서 처리
    temp_message_id = f"temp_{int(datetime.now().timestamp() * 1000)}"
    accepted_at = time.perf_counter()
    perf_id = _extract_perf_id(content)

    try:
        enqueue_result = await message_persistence_service.enqueue(
            workspace_id=workspace_id,
            tab_id=tab_id,
            sender_id=sender_id,
            content=content,
            file_url=file_data,
            temp_message_id=temp_message_id,
            accepted_at=accepted_at,
            perf_id=perf_id,
        )
    except Exception as e:
        realtime_observability.record_message_persistence_enqueue(success=False)
        logger.warning(
            "message_persistence_enqueue_failed",
            extra={
                "workspace_id": workspace_id,
                "tab_id": tab_id,
                "temp_message_id": temp_message_id,
                "exception_type": e.__class__.__name__,
            },
        )
        await _send_persistence_error(
            websocket,
            temp_message_id=temp_message_id,
            code="persistence_enqueue_failed",
            retryable=True,
        )
        return

    if not enqueue_result.accepted:
        await _send_persistence_error(
            websocket,
            temp_message_id=temp_message_id,
            code=enqueue_result.code or "persistence_enqueue_failed",
            retryable=enqueue_result.retryable,
        )
        return

    payload = {
        "type": "send",
        "file_url": file_data,
        "content": content,
        "nickname": nickname,
        "image": image,
        "created_at": str(datetime.now(pytz.timezone("Asia/Seoul")).isoformat()),    # 하드코딩으로 진행, 나중에 수정해주세요
        "message_id": temp_message_id,
        "sender_id": sender_id,
    }

    await realtime_connection.broadcast(workspace_id, tab_id, json.dumps(payload))


async def _handle_edit(workspace_id: int, tab_id: int, data: dict):
    payload = {
        "type": "edit",
        "message_id": data["msg_id"],
        "content": data["content"],
    }
    await realtime_connection.broadcast(workspace_id, tab_id, json.dumps(payload))


async def _handle_emoji(workspace_id: int, tab_id: int, data: dict):
    user_id = data["userId"]
    message_id = data["messageId"]
    emoji_type = data["emojiType"]
    action = data["action"] == "like"

    if not user_id or not message_id:
        print(f"Invalid like data received: {data}")
        return

    counts = await message_service.toggle_like(tab_id, message_id, user_id, emoji_type, action)

    payload = {
        "type": "emoji_update",
        "messageId": message_id,
        **counts,
    }

    await realtime_connection.broadcast(workspace_id, tab_id, json.dumps(payload))


async def _handle_profile(workspace_id: int, data: dict):
    sender_id = data["sender_id"]
    nickname = data["nickname"]
    image = data["image"]

    payload = {
        "type": "profile_update",
        "sender_id": sender_id,
        "nickname": nickname,
        "image": image,
    }

    # 수정한 멤버가 속한 모든 탭 조회해서 다 뿌려주기.
    tab_ids = tab_service.find_tabs(workspace_id, sender_id)
    for target_tab in tab_ids:
        await realtime_connection.broadcast(workspace_id, _target_tab_id(target_tab), json.dumps(payload))


async def _dispatch_realtime_payload(
    workspace_id: int,
    tab_id: int,
    data: dict,
    *,
    allowed_types: set[str] | None = None,
    legacy_profile_payload: bool = False,
    websocket: WebSocket,
):
    message_type = _resolve_message_type(data, legacy_profile_payload=legacy_profile_payload)
    if allowed_types is not None and message_type not in allowed_types:
        raise ValueError(f"unsupported realtime payload type: {message_type}")

    if message_type == "send":
        await _handle_send(workspace_id, tab_id, data, websocket)
    elif message_type == "edit":
        await _handle_edit(workspace_id, tab_id, data)
    elif message_type == "emoji":
        await _handle_emoji(workspace_id, tab_id, data)
    elif message_type == "profile":
        await _handle_profile(workspace_id, data)
    else:
        raise ValueError(f"unsupported realtime payload type: {message_type}")


async def _realtime_websocket_loop(
    websocket: WebSocket,
    workspace_id: int,
    tab_id: int,
    *,
    allowed_types: set[str] | None = None,
    legacy_profile_payload: bool = False,
):
    await realtime_connection.connect(REALTIME_SOCKET_TYPE, workspace_id, tab_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            await _dispatch_realtime_payload(
                workspace_id,
                tab_id,
                data,
                allowed_types=allowed_types,
                legacy_profile_payload=legacy_profile_payload,
                websocket=websocket,
            )
    except WebSocketDisconnect:
        print("********* Realtime websocket disconnected *********")
        await realtime_connection.disconnect(workspace_id, tab_id, websocket)
    except Exception as e:
        print(f"An error occurred in realtime websocket: {e}")
        await realtime_connection.disconnect(workspace_id, tab_id, websocket)


@router.websocket("/{workspace_id}/{tab_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: int, tab_id: int):
    await _realtime_websocket_loop(websocket, workspace_id, tab_id)


@router.websocket("/like/{workspace_id}/{tab_id}")
async def websocket_endpoint_like(websocket: WebSocket, workspace_id: int, tab_id: int):
    await _realtime_websocket_loop(websocket, workspace_id, tab_id, allowed_types={"emoji"})


@router.websocket("/profile/{workspace_id}/{tab_id}")
async def websocket_endpoint_profile(websocket: WebSocket, workspace_id: int, tab_id: int):
    await _realtime_websocket_loop(
        websocket,
        workspace_id,
        tab_id,
        allowed_types={"profile"},
        legacy_profile_payload=True,
    )
