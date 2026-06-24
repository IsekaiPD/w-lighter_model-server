"""Relationship map 도메인 Pydantic 스키마.

`generate_relation_data(...)` + `build_relation_html(...)` 엔진 호출용.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from common.limits import MAX_RELATION_CHARACTER_COUNT, MAX_WORK_TITLE
from common.validators import validate_character_dicts


class RelationRequest(BaseModel):
    model_config = {"extra": "ignore"}

    workTitle: str = Field("", max_length=MAX_WORK_TITLE, description="작품명")
    workId: int | None = Field(None, description="주면 DB의 작품/캐릭터를 조회하고 관계도 결과를 저장")
    characters: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=MAX_RELATION_CHARACTER_COUNT,
        description="캐릭터 설정집",
    )
    limit: int = Field(20, ge=1, le=MAX_RELATION_CHARACTER_COUNT, description="관계도 캐릭터 수(1~20)")
    includeHtml: bool = Field(True, description="true면 관계도 HTML도 함께 반환")
    saveRelationMap: bool = Field(True, description="workId가 있을 때 관계도 결과를 relation_maps에 저장")

    @field_validator("characters")
    @classmethod
    def validate_characters(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_character_dicts(value, max_items=MAX_RELATION_CHARACTER_COUNT)


class RelationResponse(BaseModel):
    model_config = {"extra": "allow"}  # data(characters/relations/groups) + htmlReport 통과
