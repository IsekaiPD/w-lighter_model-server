"""Character extract 도메인 Pydantic 스키마.

`extract_characters(...)` 엔진 호출용. 시놉시스 → 등장인물 목록(LLM).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CharacterExtractRequest(BaseModel):
    model_config = {"extra": "ignore"}

    workTitle: str = Field("", description="작품명")
    genre: str = ""
    synopsis: str = Field(..., min_length=1, description="등장인물을 추출할 시놉시스(필수)")
    limit: int = Field(20, ge=1, le=30, description="추출 인물 수(1~30)")


class CharacterExtractResponse(BaseModel):
    model_config = {"extra": "allow"}

    work_title: str | None = None
    genre: str | None = None
    count: int | None = None
    characters: list[dict[str, Any]] = []
