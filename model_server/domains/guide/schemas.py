"""Guide 도메인 Pydantic 스키마.

`generate_guide(payload)` 엔진이 다양한 키(titleElements/comparableSignals 등)를 직접 읽으므로
요청은 유연하게(extra=allow) 받되 주요 키를 문서화한다. 응답은 모드별 가변(~39키)이라 통과시킨다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GuideRequest(BaseModel):
    model_config = {"extra": "allow"}  # generate_guide가 추가 키를 직접 사용

    title: str | None = None
    genre: str | None = None
    synopsis: str | None = None
    targetCountry: str | None = Field(None, description="japan/english/china/thailand 또는 JP/US/CN/TH")
    targetMarket: str | None = None
    titleElements: list[str] | None = None
    comparableSignals: list[str] | None = None
    legacyGuide: bool | None = None
    includeContextPack: bool | None = None
    includeInternal: bool | None = None


class GuideResponse(BaseModel):
    model_config = {"extra": "allow"}  # 엔진 출력(모드별 ~39키)을 그대로 통과

    generationMode: str | None = None
