"""Relationship map 도메인 서비스 — 인물 관계도 추출/렌더 엔진 오케스트레이션."""
from __future__ import annotations

from typing import Any

from core.logging import get_logger
from db import repository as db_repo

from .relationship_generate import generate_relation_data
from .relationship_html import build_relation_html

logger = get_logger("relationship_map.service")


def _should_save(payload: dict[str, Any]) -> bool:
    value = payload.get("saveRelationMap")
    if value is None:
        value = payload.get("save_relation_map")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def generate_relationship(payload: dict[str, Any]) -> dict[str, Any]:
    work_id = payload.get("workId") or payload.get("work_id")
    work = None
    if work_id is not None:
        try:
            work = db_repo.get_work(int(work_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("relationship_map work lookup failed: %r", exc)

    work_title = payload.get("workTitle") or payload.get("title") or (work or {}).get("title") or ""

    characters = payload.get("characters") or []
    if work_id is not None:
        try:
            db_characters = db_repo.get_characters(int(work_id))

            if characters:
                profile_by_name = {
                    str(item.get("char_name") or "").strip(): item.get("profile_label") or ""
                    for item in db_characters
                    if isinstance(item, dict)
                }

                characters = [
                    {
                        **item,
                        "profile_label": item.get("profile_label")
                        or profile_by_name.get(
                            str(item.get("char_name") or item.get("name") or "").strip(),
                            "",
                        ),
                    }
                    for item in characters
                    if isinstance(item, dict)
                ]
            else:
                characters = db_characters

        except Exception as exc:  # noqa: BLE001
            logger.warning("relationship_map character lookup failed: %r", exc)
            if not characters:
                characters = []

    data = generate_relation_data(
        work_title=work_title,
        characters=characters,
        limit=int(payload.get("limit") or 20),
    )

    result: dict[str, Any] = {"workTitle": work_title, "data": data}
    if payload.get("includeHtml", True):
        result["htmlReport"] = build_relation_html(work_title=work_title, relation_data=data)

    if work_id is not None and _should_save(payload):
        try:
            result["persistedRelationMap"] = db_repo.save_relation_map(
                work_id=int(work_id),
                map_content=result.get("htmlReport") or data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("relationship_map persistence failed: %r", exc)
            result["persistedRelationMap"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return result


def status() -> dict:
    return {"domain": "relationship_map", "status": "wired", "endpoint": "POST /api/v1/relationship-map"}
