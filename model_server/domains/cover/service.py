"""Cover 도메인 서비스 — 표지 프롬프트/이미지 생성 엔진 오케스트레이션.

엔진(`cover_generate.generate_cover_image`)은 재사용(재작성 X). dry_run으로 프롬프트만 받을 수 있다.
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
