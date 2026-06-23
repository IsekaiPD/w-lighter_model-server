"""Guide 도메인 Pydantic 스키마.

엔진이 추가 키를 직접 읽으므로 요청은 extra=allow로 받고 주요 키만 문서화한다.
응답은 프론트 표시용 HTML 중심 공개 필드만 통과시킨다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from common.limits import MAX_GENRE, MAX_SYNOPSIS, MAX_WORK_TITLE


class GuideRequest(BaseModel):
    model_config = {"extra": "allow"}  # generate_guide가 추가 키를 직접 사용

    workId: int | None = Field(None, description="주면 DB의 작품 정보를 보강하고 가이드 결과를 저장")
    title: str | None = Field(None, max_length=MAX_WORK_TITLE)
    genre: str | None = Field(None, max_length=MAX_GENRE)
    synopsis: str | None = Field(None, max_length=MAX_SYNOPSIS)
    targetCountry: str | None = Field(None, max_length=20, description="japan/english/china/thailand 또는 JP/US/CN/TH")
    targetMarket: str | None = Field(None, max_length=20)
    titleElements: list[str] | None = Field(None, max_length=20)
    comparableSignals: list[str] | None = Field(None, max_length=20)
    includeContextPack: bool | None = None
    includeLiveMarket: bool | None = None
    saveGuide: bool | None = Field(True, description="workId가 있을 때 localization_guides에 저장")


class GuideResponse(BaseModel):
    model_config = {"extra": "allow"}  # htmlReport 중심 공개 응답 + 저장 결과 등 부가 키 허용

    generationMode: str | None = None
