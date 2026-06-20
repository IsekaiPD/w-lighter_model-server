"""Cover 도메인 Pydantic 스키마.

`generate_cover_image(...)` 엔진 호출용. dryRun=true면 이미지 생성(OpenAI 호출) 없이 최종 프롬프트만 반환.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CoverRequest(BaseModel):
    model_config = {"extra": "ignore"}

    workTitle: str = Field("", description="작품명")
    genre: str = ""
    synopsis: str = ""
    characters: list[dict[str, Any]] = Field(default_factory=list, description="캐릭터 설정집")
    targetCountry: str = Field("KR", description="KR/US/CN/JP/TH")
    userPrompt: str = Field("", description="추가 요청 문구(최대 500자)")
    dryRun: bool = Field(False, description="true면 이미지 생성 없이 최종 프롬프트만 반환")


class CoverResponse(BaseModel):
    model_config = {"extra": "allow"}  # 엔진 출력(status/final_prompt/image_base64 등) 통과

    status: str
