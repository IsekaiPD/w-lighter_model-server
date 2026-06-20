"""Cover 도메인 서비스 — 표지 프롬프트/이미지 생성 엔진 오케스트레이션.

`cover_generate.generate_cover_image` 호출. dry_run이면 프롬프트만 반환한다.
"""
from __future__ import annotations

from typing import Any

from .cover_generate import generate_cover_image


def generate_cover(payload: dict[str, Any]) -> dict[str, Any]:
    return generate_cover_image(
        work_title=payload.get("workTitle") or payload.get("title") or "",
        genre=payload.get("genre") or "",
        synopsis=payload.get("synopsis") or "",
        characters=payload.get("characters") or [],
        target_country=payload.get("targetCountry") or "KR",
        user_prompt=payload.get("userPrompt") or "",
        dry_run=bool(payload.get("dryRun", False)),
    )


def status() -> dict:
    return {"domain": "cover", "status": "wired", "endpoint": "POST /api/v1/cover"}
