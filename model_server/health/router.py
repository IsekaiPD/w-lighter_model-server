"""헬스체크 — Qdrant/KURE 없이도 항상 동작해야 한다(앱 부팅 확인용)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "ok": True,
        "app": settings.app_name,
        "mockMode": settings.wlighter_mock_mode,
        "qdrant": "url" if settings.qdrant_url else "embedded(TODO self-host url)",
        "warm": getattr(request.app.state, "warm", {}),
    }
