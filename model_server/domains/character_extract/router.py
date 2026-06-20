"""Character extract 라우터 (스텁). TODO: /character-extract."""
from __future__ import annotations

from fastapi import APIRouter

from . import service

router = APIRouter(prefix="/character-extract", tags=["character_extract"])


@router.get("/_status")
async def status() -> dict:
    return service.status()
