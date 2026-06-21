"""Cover 도메인 서비스 — 표지 프롬프트/이미지 생성 엔진 오케스트레이션.

`cover_generate.generate_cover_image` 호출. dry_run이면 프롬프트만 반환한다.
workId가 있으면 DB의 작품/캐릭터를 보강하고, 생성 이미지(base64)는 로컬 파일로 저장한 뒤
covers.cover_url에는 짧은 공개 경로(`/generated/covers/...`)를 저장한다.
"""
from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.logging import get_logger
from db import repository as db_repo

from .cover_generate import generate_cover_image

logger = get_logger("cover.service")

_MODEL_SERVER_ROOT = Path(__file__).resolve().parents[2]
_COVER_DIR = _MODEL_SERVER_ROOT / "generated" / "covers"


def _should_save(payload: dict[str, Any]) -> bool:
    value = payload.get("saveCover")
    if value is None:
        value = payload.get("save_cover")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _main_cover_yn(payload: dict[str, Any]) -> Any:
    return payload.get("mainCoverYn") if "mainCoverYn" in payload else payload.get("main_cover_yn", False)


def _save_generated_cover_file(*, image_base64: str, work_id: int, target_country: str, output_format: str) -> str:
    """base64 이미지를 로컬 파일로 저장하고 FastAPI static 공개 경로를 반환한다."""
    fmt = (output_format or "png").strip().lower().lstrip(".") or "png"
    if fmt == "jpeg":
        fmt = "jpg"
    safe_country = (target_country or "KR").strip().upper()[:2] or "KR"
    date_part = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"work_{int(work_id)}_{safe_country}_{date_part}_{uuid4().hex[:8]}.{fmt}"
    _COVER_DIR.mkdir(parents=True, exist_ok=True)
    path = _COVER_DIR / filename
    path.write_bytes(base64.b64decode(image_base64))
    return f"/generated/covers/{filename}"


def generate_cover(payload: dict[str, Any]) -> dict[str, Any]:
    work_id = payload.get("workId") or payload.get("work_id")
    work = None
    if work_id is not None:
        try:
            work = db_repo.get_work(int(work_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover work lookup failed: %r", exc)

    characters = payload.get("characters") or []
    if not characters and work_id is not None:
        try:
            characters = db_repo.get_characters(int(work_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover character lookup failed: %r", exc)
            characters = []

    work_title = payload.get("workTitle") or payload.get("title") or (work or {}).get("title") or ""
    genre = payload.get("genre") or (work or {}).get("genre") or ""
    synopsis = payload.get("synopsis") or (work or {}).get("synopsis") or ""
    target_country = payload.get("targetCountry") or payload.get("target_country") or "KR"

    result = generate_cover_image(
        work_title=work_title,
        genre=genre,
        synopsis=synopsis,
        characters=characters,
        target_country=target_country,
        user_prompt=payload.get("userPrompt") or "",
        dry_run=bool(payload.get("dryRun", False)),
    )

    if work_id is not None and _should_save(payload):
        cover_url = (
            payload.get("coverUrl")
            or payload.get("cover_url")
            or payload.get("imageUrl")
            or payload.get("image_url")
            or result.get("coverUrl")
            or result.get("cover_url")
        )
        if not cover_url and result.get("image_base64"):
            try:
                cover_url = _save_generated_cover_file(
                    image_base64=str(result.get("image_base64") or ""),
                    work_id=int(work_id),
                    target_country=str(result.get("target_country") or target_country),
                    output_format=str(result.get("output_format") or "png"),
                )
                result["coverUrl"] = cover_url
            except Exception as exc:  # noqa: BLE001
                logger.warning("cover file save failed: %r", exc)
                result["persistedCover"] = {"saved": False, "reason": f"file_save_failed: {type(exc).__name__}: {exc}"}
                return result
        try:
            result["persistedCover"] = db_repo.save_cover(
                work_id=int(work_id),
                target_country=str(result.get("target_country") or target_country),
                cover_url=str(cover_url or ""),
                main_cover_yn=_main_cover_yn(payload),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover persistence failed: %r", exc)
            result["persistedCover"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return result


def status() -> dict:
    return {"domain": "cover", "status": "wired", "endpoint": "POST /api/v1/cover"}
