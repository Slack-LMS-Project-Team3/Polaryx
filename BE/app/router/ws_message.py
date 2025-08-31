import json
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
from datetime import datetime
import pytz

from app.service.websocket_manager import ConnectionManager
from app.service.message import MessageService
from app.service.workspace_member import WorkspaceMemberService

from app.service.push import PushService
from app.service.tab import TabService

from app.service.notification import NotificationService
from app.router.sse import send_sse_notification

import uuid

router = APIRouter()

message_connection = ConnectionManager()
like_connection = ConnectionManager()
profile_connection = ConnectionManager()

message_service = MessageService()
workspace_member_service = WorkspaceMemberService()

tab_service = TabService()
push_service = PushService()
notification_service = NotificationService()

# 사용자 정보 캐시 (메모리 캐시)
user_cache = {}




@router.websocket("/{workspace_id}/{tab_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: int, tab_id: int):
    workspace_member = None
    socket_type = "message"
    await message_connection.connect(socket_type, workspace_id, tab_id, websocket)

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            type = data.get("type")
            if type == "send":
                sender_id = (data.get("sender_id"))
                content = data.get("content")
                file_data = data.get("file_url")

                # 사용자 정보 캐시 확인 (DB 조회 최소화)
                if sender_id not in user_cache:
                    workspace_member = workspace_member_service.get_member_by_user_id(uuid.UUID(sender_id).bytes)
                    user_cache[sender_id] = {
                        "nickname": workspace_member[0][2],
                        "image": workspace_member[0][4]
                    }
                
                user_info = user_cache[sender_id]
                nickname = user_info["nickname"]
                image = user_info["image"]

                # 임시 ID로 즉시 응답, 실제 저장은 백그라운드에서 처리
                temp_message_id = f"temp_{int(datetime.now().timestamp() * 1000)}"
                
                # 백그라운드에서 DB 저장 처리 (UI 블로킹 없음)
                async def save_message_background():
                    try:
                        real_message_id = await message_service.save_message(tab_id, sender_id, content, file_data)
                        # 필요시 실제 ID로 업데이트 브로드캐스트 가능
                    except Exception as e:
                        print(f"메시지 저장 에러: {e}")
                
                asyncio.create_task(save_message_background())
                message_id = temp_message_id
                payload = {
                    "type": "send",
                    "file_url": file_data,
                    "content": content,
                    "nickname": nickname,
                    "image": image,
                    "created_at": str(datetime.now(pytz.timezone("Asia/Seoul")).isoformat()),    # 하드코딩으로 진행, 나중에 수정해주세요
                    "message_id": message_id,
                    "sender_id": sender_id
                }


                await message_connection.broadcast(workspace_id, tab_id, json.dumps(payload))

                # for receiver in recipients:
                #     print("\n\nreceiver:\n", receiver)
                #     await notification_service.create_notification(
                #         receiver_id= receiver,
                #         sender_id=sender_id,
                #         tab_id=tab_id,
                #         message_id=message_id,
                #         type=1,
                #         content=clean_content,
                #     )
            else:  # 수정한 메세지 broadcast
                message_id = (data.get("msg_id"))
                content = data.get("content")

                payload = {
                    "type": "edit",
                    "message_id": message_id,
                    "content": content,
                }
                await message_connection.broadcast(workspace_id, tab_id, json.dumps(payload))

    except WebSocketDisconnect:
        print("********* Message websocket disconnected *********")
        await message_connection.disconnect(workspace_id, tab_id, websocket)

@router.websocket("/like/{workspace_id}/{tab_id}")
async def websocket_endpoint_like(websocket: WebSocket, workspace_id: int, tab_id: int):
    socket_type = "like"
    await like_connection.connect(socket_type, workspace_id, tab_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)

            user_id = data["userId"]
            message_id = data["messageId"]
            emoji_type = data["emojiType"]
            action = data["action"] == "like"           

            if not user_id or not message_id:
                print(f"Invalid like data received: {data}")
                continue

            counts = await message_service.toggle_like(tab_id, message_id, user_id, emoji_type, action)

            payload = {
                "type": "emoji_update",
                "messageId": message_id,
                **counts
            }

            await like_connection.broadcast(workspace_id, tab_id, json.dumps(payload))

    except WebSocketDisconnect:
        print("********* Like websocket disconnected *********")
        await like_connection.disconnect(workspace_id, tab_id, websocket)
    except Exception as e:
        print(f"An error occurred in like websocket: {e}")        
        await like_connection.disconnect(workspace_id, tab_id, websocket)

@router.websocket("/profile/{workspace_id}/{tab_id}")
async def websocket_endpoint_profile(websocket: WebSocket, workspace_id: int, tab_id: int):
    socket_type = "profile"
    await profile_connection.connect(socket_type, workspace_id, tab_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)

            sender_id = data["sender_id"]
            nickname = data["nickname"]
            image = data["image"]

            payload = {
                "sender_id": sender_id,
                "nickname": nickname,
                "image": image
            }

            # 수정한 멤버가 속한 모든 탭 조회해서 다 뿌려주기.
            tab_ids = tab_service.find_tabs(workspace_id, sender_id)
            for tab_id in tab_ids:
                await profile_connection.broadcast(workspace_id, tab_id[0], json.dumps(payload))

    except WebSocketDisconnect:
        print("********* Like websocket disconnected *********")
        await profile_connection.disconnect(workspace_id, tab_id, websocket)
    except Exception as e:
        print(f"An error occurred in like websocket: {e}")
        await profile_connection.disconnect(workspace_id, tab_id, websocket)
