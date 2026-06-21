"""Character extract 도메인 Pydantic 스키마. 시놉시스 → 등장인물 목록."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from common.limits import MAX_CHARACTER_COUNT, MAX_GENRE, MAX_SYNOPSIS, MAX_WORK_TITLE


class CharacterExtractRequest(BaseModel):
    model_config = {"extra": "ignore"}

    workTitle: str = Field("", max_length=MAX_WORK_TITLE, description="작품명")
    genre: str = Field("", max_length=MAX_GENRE)
    synopsis: str = Field(..., min_length=1, max_length=MAX_SYNOPSIS, description="등장인물을 추출할 시놉시스(필수)")
    limit: int = Field(20, ge=1, le=MAX_CHARACTER_COUNT, description="추출 인물 수(1~20)")
    workId: int | None = Field(None, description="주면 추출 결과를 해당 작품의 CHARACTERS에 적재(rdb 백엔드일 때)")


class CharacterExtractResponse(BaseModel):
    model_config = {"extra": "allow"}

    work_title: str | None = None
    genre: str | None = None
    count: int | None = None
    characters: list[dict[str, Any]] = []
