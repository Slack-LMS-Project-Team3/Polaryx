from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import verify_token_and_get_token_data
from app.service.realtime_observability import realtime_observability


router = APIRouter()


@router.get("/observability/realtime")
async def realtime_snapshot(token_data: dict = Depends(verify_token_and_get_token_data)):
    return realtime_observability.snapshot()
