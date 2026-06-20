"""Relationship map 라우터 (스텁). TODO: /relation-prompt, /generate-relation-image."""
from __future__ import annotations

from fastapi import APIRouter

from . import service

router = APIRouter(prefix="/relationship-map", tags=["relationship_map"])


@router.get("/_status")
async def status() -> dict:
    return service.status()
