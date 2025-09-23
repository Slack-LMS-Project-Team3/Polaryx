
from fastapi import APIRouter, Depends, Request
from typing import List

from app.core.security import verify_token_and_get_token_data
from app.core.exceptions import PermissionDeniedError
from app.service.notification import NotificationService
from app.schema.notification.response import NotificationSchema


from app.service.push import PushService
from app.service.tab import TabService
from app.service.workspace_member import WorkspaceMemberService
from uuid import UUID
import re

push_service = PushService()
tab_service = TabService()
wm_service = WorkspaceMemberService()

router = APIRouter(prefix="/notifications", tags=["Notifications"])
service = NotificationService()

# HTML 태그 제거 함수
def strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)

# 이미지 파일인지 확인하는 함수
def check_file_type(file_url: str) -> str:
    if not file_url:
        return "none"
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
    if any(file_url.lower().endswith(ext) for ext in image_extensions):
        return "image"
    else:
        return "file"

# 알림 메시지 생성 함수
def create_push_message(nickname: str, content: str, file_url: str) -> str:
    file_type = check_file_type(file_url)
    if file_type == "image":
        return f"{nickname}: 사진이 첨부되었습니다"
    elif file_type == "file":
        return f"{nickname}: 파일이 첨부되었습니다"
    else:
        clean_content = strip_tags(content)
        return f"{nickname}: {clean_content}"

@router.get("/{user_id}", response_model=List[NotificationSchema])
async def get_notifications(user_id: str, token_data = Depends(verify_token_and_get_token_data)):
    # 토큰의 user_id와 요청한 user_id가 일치하는지 확인
    if token_data["user_id"] != user_id:
        raise PermissionDeniedError("본인의 알림만 조회할 수 있습니다")

    notifications = service.get_notifications(user_id)
    return [NotificationSchema.from_domain(n) for n in notifications]

@router.post("/{workspace_id}/{tab_id}")
async def push_notifications(workspace_id: int, tab_id: int, request: Request, token_data = Depends(verify_token_and_get_token_data)):
    sender_id = token_data["user_id"]
    
    payload = await request.json()
    content = payload["content"]
    clean_content = strip_tags(content)
    sender_uuid = UUID(sender_id)
    user_data = wm_service.get_member_by_user_id_simple(sender_uuid, workspace_id)
    
    members = tab_service.get_tab_members(workspace_id, tab_id)
    tab_info = tab_service.find_tab(workspace_id, tab_id)
    tab_name = tab_info[0][1]
    nickname = user_data[0][0]
    
    recipients = [
    str(UUID(bytes=row[0]))
    for row in members
    if UUID(bytes=row[0]) != sender_uuid
    ]
    await push_service.send_push_to(recipients, {
        "title": tab_name,
        "body": f"{nickname}: {clean_content}",
        "url": f"/workspaces/{workspace_id}/tabs/{tab_id}"
    })

    return