"""Character extract 도메인 서비스 — 시놉시스 → 등장인물 추출 엔진 오케스트레이션.

엔진(`character_extract.extract_characters`)은 재사용(재작성 X).
"""
from __future__ import annotations

from typing import Any

from .character_extract import extract_characters


def extract(payload: dict[str, Any]) -> dict[str, Any]:
    return extract_characters(
        work_title=payload.get("workTitle") or payload.get("title") or "",
        genre=payload.get("genre") or "",
        synopsis=payload.get("synopsis") or "",
        limit=int(payload.get("limit") or 20),
    )


def status() -> dict:
    return {"domain": "character_extract", "status": "wired", "endpoint": "POST /api/v1/character-extract"}
