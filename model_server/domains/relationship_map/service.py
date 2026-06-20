"""Relationship map 도메인 서비스 — 인물 관계도 추출/렌더 엔진 오케스트레이션.

엔진(`relationship_generate.generate_relation_data` + `relationship_html.build_relation_html`)은 재사용(재작성 X).
"""
from __future__ import annotations

from typing import Any

from .relationship_generate import generate_relation_data
from .relationship_html import build_relation_html


def generate_relationship(payload: dict[str, Any]) -> dict[str, Any]:
    work_title = payload.get("workTitle") or payload.get("title") or ""
    data = generate_relation_data(
        work_title=work_title,
        characters=payload.get("characters") or [],
        limit=int(payload.get("limit") or 12),
    )
    result: dict[str, Any] = {"workTitle": work_title, "data": data}
    if payload.get("includeHtml", True):
        result["htmlReport"] = build_relation_html(work_title=work_title, relation_data=data)
    return result


def status() -> dict:
    return {"domain": "relationship_map", "status": "wired", "endpoint": "POST /api/v1/relationship-map"}
