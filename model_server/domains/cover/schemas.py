"""Cover 도메인 Pydantic 스키마."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from common.limits import (
    MAX_CHARACTER_COUNT,
    MAX_COVER_PROMPT,
    MAX_GENRE,
    MAX_SYNOPSIS,
    MAX_WORK_TITLE,
)
from common.validators import validate_character_dicts


class CoverRequest(BaseModel):
    model_config = {"extra": "ignore"}

    workTitle: str = Field("", max_length=MAX_WORK_TITLE, description="작품명")
    workId: int | None = Field(None, description="주면 DB의 작품/캐릭터를 조회하고 표지 URL을 저장")
    genre: str = Field("", max_length=MAX_GENRE)
    synopsis: str = Field("", max_length=MAX_SYNOPSIS)
    characters: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=MAX_CHARACTER_COUNT,
        description="캐릭터 설정집",
    )
    targetCountry: str = Field("KR", max_length=20, description="KR/US/CN/JP/TH")
    userPrompt: str = Field("", max_length=MAX_COVER_PROMPT, description="추가 요청 문구(최대 500자)")
    dryRun: bool = Field(False, description="true면 이미지 생성 없이 최종 프롬프트만 반환")
    coverUrl: str | None = Field(None, max_length=255, description="이미 저장된 표지 URL/S3 경로가 있으면 이 값을 covers.cover_url에 저장")
    mainCoverYn: bool = Field(False, description="대표 표지 여부")
    saveCover: bool = Field(True, description="workId가 있을 때 covers에 저장")

    @field_validator("characters")
    @classmethod
    def validate_characters(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_character_dicts(value, max_items=MAX_CHARACTER_COUNT)


class CoverResponse(BaseModel):
    model_config = {"extra": "allow"}  # 엔진 출력(status/final_prompt/image_base64 등) 통과

    status: str
