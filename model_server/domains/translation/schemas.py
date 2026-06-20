"""Translation 도메인 Pydantic 스키마.

요청/응답 계약은 통합초안 docs/translation_api_contract.md (v3 얇은 응답) 기반.
중첩 구조(rationale/endnote/card 등)는 현재 유연하게 dict/list로 둔다(엔진 출력 그대로 전달).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    model_config = {"extra": "ignore"}

    sourceText: str = Field(..., min_length=1, description="번역할 한국어 원문")
    # 목표는 둘 중 하나(또는 둘 다 일치). 서비스가 normalize.
    targetLocale: str | None = Field(None, description="예: ko_en_us, ko_ja")
    targetCountry: str | None = Field(None, description="예: US, JP, CN, TH")
    sourceLocale: str | None = "ko"
    genre: str | None = None
    qualityMode: str | None = None
    workId: str | None = None
    episodeId: str | None = None
    workMemory: dict[str, Any] | None = None
    includeInternal: bool = False
    saveTranslationResult: bool = False


class TranslateResponse(BaseModel):
    model_config = {"extra": "allow"}

    country: str
    locale: str
    pipeline: str | None = None
    finalTranslation: str
    deliveryStatus: str
    userVisibleErrorCode: str | None = None
    message: str = ""
    translationRationale: dict[str, Any] = {}
    readerEndnotes: list[dict[str, Any]] = []
    authorReviewCards: list[dict[str, Any]] = []
    qaIssues: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    internal: dict[str, Any] | None = None  # includeInternal=true 일 때만


class InspectChatRequest(BaseModel):
    model_config = {"extra": "ignore"}

    question: str = Field(..., min_length=1)
    sourceText: str | None = ""
    currentTranslation: str | None = ""
    targetLocale: str | None = None
    targetCountry: str | None = None
    workflow: dict[str, Any] | None = None
    chatHistory: list[dict[str, Any]] | None = None
    title: str | None = None
    episodeId: str | None = None


class InspectChatResponse(BaseModel):
    model_config = {"extra": "allow"}

    answer: str
    proposedTranslation: str | None = None
    changeSummary: str | None = None
    needsUserConfirmation: bool = False
