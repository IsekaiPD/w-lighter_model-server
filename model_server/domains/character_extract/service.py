"""Character extract 도메인 서비스 — 시놉시스 → 등장인물 추출 엔진 오케스트레이션."""
from __future__ import annotations

from typing import Any

from core.logging import get_logger

from db import repository as db_repo

from .character_extract import extract_characters

logger = get_logger("character_extract.service")


def display_gender(value: Any) -> str:
    """DB/LLM 성별 코드값(M/F/U) → 화면/API 응답용 한글 표시값."""
    token = str(value or "").strip().upper()
    if token == "M":
        return "남"
    if token == "F":
        return "여"
    return "미상"


def extract(payload: dict[str, Any]) -> dict[str, Any]:
    result = extract_characters(
        work_title=payload.get("workTitle") or payload.get("title") or "",
        genre=payload.get("genre") or "",
        synopsis=payload.get("synopsis") or "",
        limit=int(payload.get("limit") or 20),
    )

    # gender 단일 정규화(저장·응답 공용): 자유텍스트/남/male… → M/F/U 코드.
    # 이후 저장은 이 코드값을 그대로 쓰고(=CHECK 통과), 응답 직전에만 display_gender로 한글 변환한다.
    for character in result.get("characters") or []:
        if isinstance(character, dict):
            character["gender"] = db_repo.normalize_gender(character.get("gender"))

    # workId가 주어지면 CHARACTERS에 적재(rdb 백엔드일 때만 저장, 아니면 no-op).
    # 영속화 실패가 추출 응답을 막지 않도록 best-effort.
    work_id = payload.get("workId") or payload.get("work_id")
    if work_id is not None:
        try:
            persisted = db_repo.save_characters(int(work_id), result.get("characters") or [])
            result["persisted"] = persisted
        except Exception as exc:  # noqa: BLE001
            logger.warning("character persistence failed: %r", exc)
            result["persisted"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    # DB 저장은 M/F/U로 처리하고, 프론트/API 응답에서만 남/여/미상으로 변환한다.
    for character in result.get("characters") or []:
        if isinstance(character, dict):
            character["gender"] = display_gender(character.get("gender"))

    return result


def status() -> dict:
    return {"domain": "character_extract", "status": "wired", "endpoint": "POST /api/v1/character-extract"}