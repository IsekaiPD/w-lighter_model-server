"""Relationship map 도메인 Pydantic 스키마.

`generate_relation_data(...)` + `build_relation_html(...)` 엔진 호출용.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RelationRequest(BaseModel):
    model_config = {"extra": "ignore"}

    workTitle: str = Field("", description="작품명")
    characters: list[dict[str, Any]] = Field(default_factory=list, description="캐릭터 설정집")
    limit: int = Field(12, ge=1, le=20, description="관계도 캐릭터 수(1~20)")
    includeHtml: bool = Field(True, description="true면 관계도 HTML도 함께 반환")


class RelationResponse(BaseModel):
    model_config = {"extra": "allow"}  # data(characters/relations/groups) + htmlReport 통과
