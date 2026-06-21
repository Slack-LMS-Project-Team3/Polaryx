from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.security import verify_token_and_get_token_data
from app.service.sse_notifications import (
    SSEAckError,
    SSEPayloadError,
    SSEPublishError,
    SSESubscriptionError,
    sse_notification_service,
)


router = APIRouter()
logger = logging.getLogger(__name__)

# Compatibility surface for existing tests and imports. The service owns the map.
subscribers = sse_notification_service.subscribers


async def event_generator(
    request: Request,
    workspace_id: str,
    user_id: str | None = None,
    last_event_id: str | None = None,
):
    generator = sse_notification_service.event_generator(
        request,
        str(workspace_id),
        user_id=user_id,
        last_event_id=last_event_id,
    )
    try:
        async for frame in generator:
            yield frame
    finally:
        await generator.aclose()


@router.get("/sse/notifications")
async def sse_notifications(
    request: Request,
    workspaceId: str,
    lastEventId: str | None = Query(default=None),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    data: dict = Depends(verify_token_and_get_token_data),
):
    try:
        queue = await sse_notification_service.subscribe(str(workspaceId))
    except SSESubscriptionError as exc:
        raise HTTPException(status_code=503, detail="SSE notification stream unavailable") from exc

    generator = sse_notification_service.stream(
        request,
        str(workspaceId),
        queue,
        user_id=data["user_id"],
        last_event_id=lastEventId or last_event_id_header,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def send_sse_notification(workspace_id: str, payload: dict):
    return await sse_notification_service.publish(str(workspace_id), payload)


def schedule_sse_notification(workspace_id: str, payload: dict) -> asyncio.Task[None]:
    workspace_key = str(workspace_id)

    async def publish_background() -> None:
        try:
            await send_sse_notification(workspace_key, payload)
        except SSEPublishError as exc:
            logger.warning(
                "sse_background_publish_failed",
                extra={"workspace_id": workspace_key, "exception_type": type(exc).__name__},
            )
        except Exception as exc:  # noqa: BLE001 - keep background task failures controlled.
            logger.warning(
                "sse_background_publish_unexpected_error",
                extra={"workspace_id": workspace_key, "exception_type": type(exc).__name__},
            )

    return asyncio.create_task(publish_background())


@router.post("/sse/notifications/ack")
async def ack_sse_notification(
    request: Request,
    token_data: dict = Depends(verify_token_and_get_token_data),
):
    payload = await request.json()
    workspace_id = payload.get("workspace_id")
    last_event_id = payload.get("last_event_id")
    if workspace_id is None or not last_event_id:
        raise HTTPException(status_code=422, detail="workspace_id and last_event_id are required")
    try:
        return await sse_notification_service.acknowledge(
            workspace_id=str(workspace_id),
            user_id=token_data["user_id"],
            last_event_id=str(last_event_id),
        )
    except SSEAckError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sse/notifications/{workspace_id}")
async def post_sse_notification(
    workspace_id: str,
    request: Request,
    token_data: dict = Depends(verify_token_and_get_token_data),
):
    payload = await request.json()
    try:
        published = await sse_notification_service.publish(
            workspace_id,
            payload,
            publisher_user_id=token_data["user_id"],
        )
    except SSEPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SSEPublishError as exc:
        raise HTTPException(status_code=503, detail="SSE notification publish failed") from exc
    return {
        "status": "published",
        "event_id": published.get("event_id"),
        "published_at_ms": published.get("published_at_ms"),
    }
