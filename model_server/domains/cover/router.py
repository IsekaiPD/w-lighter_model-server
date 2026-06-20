"""Cover 도메인 라우터 (스텁). TODO: /cover-prompt, /generate-cover-image."""
from __future__ import annotations

from fastapi import APIRouter

from . import service

router = APIRouter(prefix="/cover", tags=["cover"])


@router.get("/_status")
async def status() -> dict:
    return service.status()
