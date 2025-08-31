from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
import asyncio
from asyncio import CancelledError
import json
from typing import Dict, Set
from app.core.security import verify_token_and_get_token_data

router = APIRouter()

# workspaceId 별로 Queue 집합을 관리
subscribers: Dict[str, Set[asyncio.Queue]] = {}

async def event_generator(request: Request, workspace_id: str):
    queue = asyncio.Queue()
    subscribers.setdefault(workspace_id, set()).add(queue)

    try:
        while True:
            try:
                # 클라이언트가 연결을 끊으면 루프 종료
                if await request.is_disconnected():
                    print("연결 끊을게요")
                    break

                get_data_task = asyncio.create_task(queue.get())
                sleep_task = asyncio.create_task(asyncio.sleep(60))

                done, pending = await asyncio.wait(
                    [get_data_task, sleep_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if get_data_task in done: # sleep 태스크는 취소
                    sleep_task.cancel()
                    data = get_data_task.result()
                    yield f"event: {data['type']}\n"
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                else: # 60초 타임아웃
                    print("SSE ping")
                    get_data_task.cancel()
                    yield "event: ping\n"
                    yield "data: p\n\n"
            except CancelledError:
                print("클라이언트가 연결 끊음")
                raise
    finally:
        # 연결 종료 시 해당 워크스페이스의 큐에서 제거
        subscribers[workspace_id].remove(queue)
        # 만약 더 이상 구독자가 없으면 키 자체도 삭제
        if not subscribers[workspace_id]:
            del subscribers[workspace_id]

@router.get("/sse/notifications")
async def sse_notifications(request: Request, workspaceId: str, data = Depends(verify_token_and_get_token_data)):
    """
    클라이언트는 ?workspaceId=xxx 쿼리로 워크스페이스 구분해서 연결함
    """
    print("\n\n\n\nsse_notifications, user_id: ", data["user_id"])
    generator = event_generator(request, workspaceId)
    return StreamingResponse(generator, 
        media_type="text/event-stream", 
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # for Nginx
        })

async def send_sse_notification(workspace_id: str, payload: dict):
    """
    WebSocket 등에서 호출할 때 workspace_id 를 첫 인자로 넘겨줘야함
    payload['type'] 에 따라 event 이름(new_message, invited_to_tap)이 결정됨
    """
    queues = subscribers.get(workspace_id, set())
    for queue in list(queues):
        await queue.put(payload)

@router.post("/sse/notifications/{workspace_id}")
async def asdf(workspace_id: str, request: Request):
    print("\n\n\nin asdf")
    payload = await request.json()
    print(payload)
    await send_sse_notification(workspace_id, payload)