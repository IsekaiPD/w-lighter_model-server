"""Guide 도메인 서비스 — 현지화 가이드 엔진 오케스트레이션."""
from __future__ import annotations

from typing import Any

from .guide_pipeline import generate_guide


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """현지화 가이드 생성. payload는 title/genre/synopsis/targetCountry 등."""
    return generate_guide(payload)


def status() -> dict:
    return {"domain": "guide", "status": "wired", "endpoint": "POST /api/v1/guide"}
