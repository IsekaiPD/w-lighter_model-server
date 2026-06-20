"""Character extract 도메인 서비스 — 시놉시스 → 등장인물 추출 엔진 오케스트레이션.

엔진(`character_extract.extract_characters`)은 재사용(재작성 X).
"""
from __future__ import annotations

from typing import Any

from core.logging import get_logger

from db import repository as db_repo

from .character_extract import extract_characters

logger = get_logger("character_extract.service")


def extract(payload: dict[str, Any]) -> dict[str, Any]:
    result = extract_characters(
        work_title=payload.get("workTitle") or payload.get("title") or "",
        genre=payload.get("genre") or "",
        synopsis=payload.get("synopsis") or "",
        limit=int(payload.get("limit") or 20),
    )

    # workId가 주어지면 추출 결과를 CHARACTERS에 적재(rdb 백엔드일 때만 실제 저장; 아니면 no-op).
    # 영속화 실패가 추출 응답을 막지 않도록 best-effort.
    work_id = payload.get("workId") or payload.get("work_id")
    if work_id is not None:
        try:
            persisted = db_repo.save_characters(int(work_id), result.get("characters") or [])
            result["persisted"] = persisted
        except Exception as exc:  # noqa: BLE001
            logger.warning("character persistence failed: %r", exc)
            result["persisted"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return result


def status() -> dict:
    return {"domain": "character_extract", "status": "wired", "endpoint": "POST /api/v1/character-extract"}
