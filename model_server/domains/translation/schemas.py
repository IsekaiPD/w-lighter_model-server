"""Translation 도메인 Pydantic 스키마 (얇은 응답 계약).

중첩 구조(rationale/endnote/card 등)는 엔진 출력을 그대로 전달하도록 dict/list로 둔다.
요구사항 기준으로 OpenAI 호출 전 입력 길이를 제한한다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from common.limits import (
    MAX_CHAT_QUESTION,
    MAX_CURRENT_TRANSLATION,
    MAX_GENRE,
    MAX_SOURCE_TEXT,
    MAX_WORK_TITLE,
)


class TranslateRequest(BaseModel):
    model_config = {"extra": "ignore"}

    sourceText: str = Field(..., min_length=1, max_length=MAX_SOURCE_TEXT, description="번역할 한국어 원문")
    # 목표는 둘 중 하나(또는 둘 다 일치). 서비스가 normalize.
    targetLocale: str | None = Field(None, max_length=20, description="예: ko_en_us, ko_ja")
    targetCountry: str | None = Field(None, max_length=20, description="예: US, JP, CN, TH")
    sourceLocale: str | None = Field("ko", max_length=10)
    genre: str | None = Field(None, max_length=MAX_GENRE)
    workId: str | None = Field(None, max_length=20)
    episodeId: str | None = Field(None, max_length=20)
    workMemory: dict[str, Any] | None = None
    includeInternal: bool = False
    saveTranslationResult: bool = True   # 번역 완료 시 선제 저장(기본). 실제 저장엔 episodeId 필요(없으면 graceful no-op).


class TranslateResponse(BaseModel):
    model_config = {"extra": "allow"}

    country: str
    locale: str
    pipeline: str | None = None
    finalTranslation: str
    readerEndnotes: list[dict[str, Any]] = []
    authorReviewCards: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    # 화면설계서 번역 리포트 4종 묶음. 프론트가 분리/합성해 사용.
    translationReport: dict[str, Any] = {}
    internal: dict[str, Any] | None = None  # includeInternal=true 일 때만


class InspectChatRequest(BaseModel):
    model_config = {"extra": "ignore"}

    question: str = Field(..., min_length=1, max_length=MAX_CHAT_QUESTION)
    sourceText: str | None = Field("", max_length=MAX_SOURCE_TEXT)
    currentTranslation: str | None = Field("", max_length=MAX_CURRENT_TRANSLATION)
    targetLocale: str | None = Field(None, max_length=20)
    targetCountry: str | None = Field(None, max_length=20)
    workflow: dict[str, Any] | None = None
    chatHistory: list[dict[str, Any]] | None = None
    title: str | None = Field(None, max_length=MAX_WORK_TITLE)
    workId: str | None = Field(None, max_length=20, description="glossary 수정 시 필요")
    episodeId: str | None = Field(None, max_length=20)
    translationId: int | None = Field(None, description="주면 검수 챗봇 대화를 chat_messages에 저장")
    saveChatMessages: bool = Field(True, description="translationId가 있을 때 chat_messages에 저장")
    pendingAction: dict[str, Any] | None = Field(None, description="이전 턴에서 제안된 액션 — 확인/취소 판정에 사용")


class InspectChatResponse(BaseModel):
    model_config = {"extra": "allow"}

    answer: str
    edits: list[dict[str, Any]] | None = None
    changeSummary: str | None = None
    needsUserConfirmation: bool = False
    pendingAction: dict[str, Any] | None = None
    actionExecuted: dict[str, Any] | None = None
