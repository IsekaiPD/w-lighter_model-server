"""Translation 도메인 서비스 — translate()/inspect_chat() 오케스트레이션.

- 엔진은 같은 패키지의 것을 import해 재사용한다.
- glossary hydrate / 결과 영속화는 db.repository 스텁(TODO: RDB 연동).
- 파이프라인은 (locale, mock)별 프로세스 캐시. warm-up은 lifespan에서 트리거.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from db import repository as db_repo

from . import (
    ChatbotAgent,
    ChatMessage,
    PipelineConfig,
    TranslationMode,
    TranslationPipeline,
)
from .infra.locale_utils import normalize_target_fields
from .infra.runtime import is_mock_mode
from .text_processing.korean_output import is_korean_source

_ALL_LOCALES = ["ko_ja", "ko_en_us", "ko_zh_cn", "ko_th_th"]
_pipeline_cache: dict[tuple[str, bool], TranslationPipeline] = {}


# ------------------------------------------------------------------ #
# 파이프라인 캐시 / warm-up
# ------------------------------------------------------------------ #
def get_translation_pipeline(
    locale: str, *, model_override: str | None = None
) -> TranslationPipeline:
    mock = is_mock_mode()
    key = (locale, mock)
    pipe = _pipeline_cache.get(key)
    if pipe is None:
        pipe = TranslationPipeline(
            PipelineConfig(
                locale=locale,
                mode=TranslationMode.V3_LITERARY_PACKAGE,
                mock=mock,
                model_override=model_override,
            )
        )
        _pipeline_cache[key] = pipe
    return pipe


def warmup(locales: list[str] | None = None) -> None:
    """무거운 파이프라인(KURE/qdrant)을 미리 적재. lifespan에서 호출."""
    for loc in locales or _ALL_LOCALES:
        get_translation_pipeline(loc)


def _chatbot(locale: str) -> ChatbotAgent:
    return ChatbotAgent(PipelineConfig(locale=locale, mock=is_mock_mode()))


# ------------------------------------------------------------------ #
# 헬퍼
# ------------------------------------------------------------------ #
def _payload_value(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _delivery_block_message(delivery_status: str) -> str:
    if delivery_status == "blocked_translation_safety":
        return "Translation safety validation failed. Please try again."
    if delivery_status == "blocked_translation_integrity":
        return "Translation target-language integrity validation failed. Please try again."
    return ""


def _normalize_delivery(
    *, final_translation: str, delivery_status: str, user_visible_error_code: str | None, metadata: dict[str, Any]
) -> tuple[str, str, str | None, dict[str, Any]]:
    md = dict(metadata or {})
    ft, ds, ec = final_translation, delivery_status, user_visible_error_code
    if ds == "deliverable" and not ft.strip():
        ft, ds, ec = "", "blocked_translation_integrity", "translation_integrity_failed"
    if ds == "blocked_translation_safety":
        ft, ec = "", "translation_safety_failed"
    elif ds == "blocked_translation_integrity":
        ft, ec = "", "translation_integrity_failed"
    if ds != "deliverable":
        md["delivery_status"] = ds
        md["user_visible_error_code"] = ec
    return ft, ds, ec, md


_BLOCK_MESSAGES = {
    "non_korean_source": "현재 한국어 원문만 지원하고 있어요. 한국어로 작성된 원문을 입력해 주세요.",
}


def _blocked_response(*, country: str, locale: str, block_reason: str) -> dict[str, Any]:
    message = _BLOCK_MESSAGES.get(block_reason, "입력을 처리할 수 없어요. 입력 내용을 다시 확인해 주세요.")
    return {
        "country": country,
        "locale": locale,
        "pipeline": "v3_literary_package",
        "finalTranslation": message,
        "deliveryStatus": "deliverable",
        "userVisibleErrorCode": None,
        "message": "",
        "translationRationale": {},
        "readerEndnotes": [],
        "authorReviewCards": [],
        "qaIssues": [],
        "metadata": {"blockReason": block_reason},
        "translationReport": {
            "translationRationale": {},
            "glossaryCandidates": [],
            "readerEndnotes": [],
            "culturalRiskResult": [],
        },
    }


# ------------------------------------------------------------------ #
# 공개 진입점
# ------------------------------------------------------------------ #
def translate(payload: dict[str, Any]) -> dict[str, Any]:
    source_text = str(_payload_value(payload, "sourceText", "source_text", default="") or "").strip()
    if not source_text:
        raise ValueError("sourceText is required")

    normalized = normalize_target_fields(payload)  # LocaleNormalizationError -> 400 (핸들러)
    country, locale = normalized["targetCountry"], normalized["targetLocale"]

    if not is_korean_source(source_text):
        return _blocked_response(country=country, locale=locale, block_reason="non_korean_source")

    model_override = payload.get("translationModel") or payload.get("model")
    genre = payload.get("genre") or payload.get("workGenre") or "Modern Korean web novel"
    max_iterations = int(payload.get("maxIterations") or 2)

    work_id = _payload_value(payload, "workId", "work_id", "canonicalWorkKey")
    request_wm = payload.get("workMemory") or payload.get("work_memory")
    work_memory = request_wm if isinstance(request_wm, dict) else None
    work_memory_source = "request_payload" if work_memory is not None else "none"
    work_memory_fallback = ""
    if work_memory is None and work_id is not None and locale:
        # TODO: db_repo.hydrate_work_memory 가 RDB 연동되면 승인 glossary로 hydrate.
        hydrated = db_repo.hydrate_work_memory(str(work_id), country)
        if hydrated is not None:
            work_memory = hydrated
            work_memory_source = "rdb_hydrated"

    pipeline = get_translation_pipeline(locale, model_override=model_override)
    result = asdict(
        pipeline.run_v3_literary_package(
            source_text,
            genre=genre,
            work_memory=work_memory,
            max_iterations=max_iterations,
            debug_capture_model_outputs=bool(
                payload.get("debugCaptureModelOutputs") or payload.get("debug_capture_model_outputs")
            ),
        )
    )

    final_translation = result.get("finalTranslation", "")
    delivery_status = result.get("deliveryStatus", "deliverable")
    user_visible_error_code = (result.get("internal") or {}).get("userVisibleErrorCode")
    final_translation, delivery_status, user_visible_error_code, metadata = _normalize_delivery(
        final_translation=final_translation,
        delivery_status=delivery_status,
        user_visible_error_code=user_visible_error_code,
        metadata={
            "mode": TranslationMode.V3_LITERARY_PACKAGE.value,
            "pipeline": result.get("pipeline"),
            "delivery_status": delivery_status,
            "qa_issue_count": len(result.get("qaIssues") or []),
            "reader_endnote_count": len(result.get("readerEndnotes") or []),
            "work_memory_source": work_memory_source,
            "work_memory_fallback_reason": work_memory_fallback,
        },
    )

    internal = dict(result.get("internal") or {})
    internal["userVisibleErrorCode"] = user_visible_error_code
    internal["workMemorySource"] = work_memory_source

    is_blocked = delivery_status.startswith("blocked_translation_")
    include_internal = bool(payload.get("includeInternal") or payload.get("debugCaptureModelOutputs"))
    response: dict[str, Any] = {
        "country": country,
        "locale": locale,
        "pipeline": result.get("pipeline"),
        "finalTranslation": final_translation,
        "deliveryStatus": delivery_status,
        "userVisibleErrorCode": user_visible_error_code,
        "message": _delivery_block_message(delivery_status),
        "translationRationale": {} if is_blocked else result.get("translationRationale", {}),
        "readerEndnotes": [] if is_blocked else result.get("readerEndnotes", []),
        "authorReviewCards": [] if is_blocked else result.get("authorReviewCards", []),
        "qaIssues": [] if is_blocked else result.get("qaIssues", []),
        "metadata": metadata,
    }
    # 화면설계서 번역 리포트 — 웹 4요소(summary·glossary_can·annotation_can·inspection_report) 실데이터 기반.
    internal_data = result.get("internal") or {}
    revisor_decisions = list(internal_data.get("revisorDecisions") or [])
    review_summaries = internal_data.get("reviewSummaries") or {}
    revisor_summary = str(internal_data.get("revisorSummary") or "")
    rationale_obj = dict(result.get("translationRationale") or {})
    # 각 용어 후보/주석에 UI 체크 상태용 applied 키(기본 0) 부여. 웹이 컨펌하면 1로 갱신.
    glossary_candidates = [] if is_blocked else [{**c, "applied": 0} for c in (internal_data.get("glossaryCandidates") or [])]
    reader_endnotes = [] if is_blocked else [{**e, "applied": 0} for e in (result.get("readerEndnotes") or [])]
    # inspection_report = 문화리스크 = 리바이저의 cultural 적용/보류 결정 리스트.
    cultural_risk = [] if is_blocked else [d for d in revisor_decisions if d.get("reviewerType") == "cultural"]
    # summary(text) = 번역가 overview + 검수자 3종 총평 + 최종 수정 총평(\n 묶음).
    summary_text = "" if is_blocked else "\n".join([
        f"번역가: {rationale_obj.get('overview', '')}",
        "",
        f"말투 검수자 : {review_summaries.get('voice', '')}",
        f"자연스러움 검수자 : {review_summaries.get('naturalness', '')}",
        f"문화권 리스크 검수자 : {review_summaries.get('cultural', '')}",
        "",
        f"최종 수정 : {revisor_summary}",
    ])
    response["readerEndnotes"] = reader_endnotes  # top-level도 applied 포함으로 동기화
    response["translationReport"] = {
        "summary": summary_text,
        "glossaryCandidates": glossary_candidates,
        "readerEndnotes": reader_endnotes,
        "culturalRiskResult": cultural_risk,
    }

    if include_internal:
        response["internal"] = internal

    # saveTranslationResult=true면 결과 영속화(rdb 백엔드 + episodeId 필요; 아니면 graceful no-op).
    # 영속화 실패가 번역 응답을 막지 않도록 best-effort.
    if payload.get("saveTranslationResult") or payload.get("save_translation_result"):
        episode_id = _payload_value(payload, "episodeId", "episode_id")
        try:
            saved = db_repo.save_translation_result(
                {
                    "episodeId": episode_id,
                    "targetCountry": country,
                    "translatedText": final_translation,
                    "summary": summary_text,                  # text
                    "glossaryCan": glossary_candidates,       # json (applied 포함)
                    "annotationCan": reader_endnotes,         # json (applied 포함)
                    "inspectionReport": cultural_risk,        # json = culturalRiskResult
                }
            )
            response["persisted"] = saved
        except Exception as exc:  # noqa: BLE001
            response["persisted"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return response


def _should_save_chat(payload: dict[str, Any]) -> bool:
    value = payload.get("saveChatMessages")
    if value is None:
        value = payload.get("save_chat_messages")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def inspect_chat(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(_payload_value(payload, "question", "question_text", default="") or "").strip()
    if not question:
        raise ValueError("question is required")
    normalized = normalize_target_fields(payload)
    locale = normalized["targetLocale"]

    workflow = payload.get("workflow") or {}
    draft = workflow.get("draft") or {}
    reviewed = (
        str(_payload_value(payload, "currentTranslation", "current_translation", default="") or "")
        or workflow.get("finalTranslation")
        or workflow.get("reviewed_translation")
        or draft.get("translation")
        or ""
    )
    source_text = str(_payload_value(payload, "sourceText", "source_text", default="") or "") or workflow.get("source_text") or ""

    chat_history: list[ChatMessage] = []
    for row in (payload.get("chatHistory") or [])[-8:]:
        if isinstance(row, dict) and str(row.get("content") or "").strip():
            role = str(row.get("role") or "").strip()
            chat_history.append(ChatMessage(role="assistant" if role in {"ai", "assistant"} else "user", content=str(row["content"]).strip()))

    reply = _chatbot(locale).reply(
        user_message=question,
        source_text=source_text,
        draft_translation=draft.get("translation", ""),
        reviewed_translation=reviewed,
        translation_rationale=str(workflow.get("translationRationale") or draft.get("rationale") or ""),
        used_references=[],
        inspection_report=workflow.get("qaIssues") or {},
        reader_endnotes=workflow.get("readerEndnotes") or [],
        work_title=str(payload.get("title") or ""),
        episode_id=str(_payload_value(payload, "episodeId", "episode_id", default="") or ""),
        translation_memory=[],
        chat_history=chat_history,
    )
    response = {
        "answer": reply.answer,
        "proposedTranslation": reply.proposed_translation,
        "changeSummary": reply.change_summary,
        "needsUserConfirmation": reply.needs_user_confirmation,
    }

    translation_id = _payload_value(payload, "translationId", "translation_id") or workflow.get("translationId") or workflow.get("translation_id")
    if translation_id is not None and _should_save_chat(payload):
        assistant_text = reply.answer or ""
        if reply.proposed_translation:
            assistant_text = f"{assistant_text}\n\n[수정 제안 번역문]\n{reply.proposed_translation}".strip()
        try:
            response["persistedChatMessages"] = db_repo.save_chat_messages(
                translation_id=int(translation_id),
                messages=[
                    {"senderType": "USER", "messageText": question},
                    {"senderType": "ASSISTANT", "messageText": assistant_text},
                ],
            )
        except Exception as exc:  # noqa: BLE001
            response["persistedChatMessages"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return response
