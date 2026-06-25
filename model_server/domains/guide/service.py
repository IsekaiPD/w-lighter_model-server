"""Guide 도메인 서비스 — 현지화 가이드 엔진 오케스트레이션."""
from __future__ import annotations

import json
from typing import Any

from core.logging import get_logger
from db import repository as db_repo

from .guide_pipeline import generate_guide

logger = get_logger("guide.service")


def _should_save(payload: dict[str, Any]) -> bool:
    value = payload.get("saveGuide")
    if value is None:
        value = payload.get("save_guide")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _target_country(payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    raw = (
        result.get("targetCountry")
        or result.get("country")
        or payload.get("targetCountry")
        or payload.get("target_country")
        or payload.get("targetMarket")
        or payload.get("target_market")
        or payload.get("country")
    )
    if not raw:
        return None
    text = str(raw).strip().lower()
    aliases = {
        "japan": "JP",
        "jp": "JP",
        "english": "US",
        "en": "US",
        "us": "US",
        "usa": "US",
        "global english": "US",
        "china": "CN",
        "cn": "CN",
        "thailand": "TH",
        "th": "TH",
    }
    return aliases.get(text, str(raw).strip().upper()[:2])


def _guide_content(result: dict[str, Any]) -> str:
    """DB TEXT에 넣을 대표 가이드 본문. 화면 재사용을 위해 HTML 우선."""
    value = result.get("htmlReport")
    if isinstance(value, str) and value.strip():
        return value
    return json.dumps(result, ensure_ascii=False, default=str)


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """현지화 가이드 생성. payload는 title/genre/synopsis/targetCountry 등."""
    work_id = payload.get("workId") or payload.get("work_id")
    enriched_payload = dict(payload)
    if work_id is not None:
        try:
            work = db_repo.get_work(int(work_id))
            if work:
                enriched_payload.setdefault("title", work.get("title") or "")
                enriched_payload.setdefault("genre", work.get("genre") or "")
                enriched_payload.setdefault("synopsis", work.get("synopsis") or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("guide work lookup failed: %r", exc)

    result = generate_guide(enriched_payload)

    if work_id is not None and _should_save(payload):
        try:
            is_multi_country = result.get("reportMode") == "synopsis_country_recommendation"
            result["persistedGuide"] = db_repo.save_localization_guide(
                work_id=int(work_id),
                target_country=None if is_multi_country else _target_country(enriched_payload, result),
                guide_content=_guide_content(result),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("guide persistence failed: %r", exc)
            result["persistedGuide"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return result


def status() -> dict:
    return {"domain": "guide", "status": "wired", "endpoint": "POST /api/v1/guide"}
