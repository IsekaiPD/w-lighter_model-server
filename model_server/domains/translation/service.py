"""Translation 도메인 서비스 — translate()/inspect_chat() 오케스트레이션.

- 엔진은 같은 패키지의 것을 import해 재사용한다.
- glossary hydrate / 결과 영속화는 db.repository 스텁(TODO: RDB 연동).
- 파이프라인은 (locale, mock)별 프로세스 캐시. warm-up은 lifespan에서 트리거.
"""
from __future__ import annotations

import re as _re
from dataclasses import asdict
from typing import Any

from core.logging import get_logger
from db import repository as db_repo

from . import (
    ChatbotAgent,
    ChatIntentClassification,
    ChatIntentClassifier,
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
logger = get_logger("translation.service")


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
                mode=TranslationMode.LITERARY_PACKAGE,
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


def _chat_intent_classifier(locale: str) -> ChatIntentClassifier:
    return ChatIntentClassifier(PipelineConfig(locale=locale, mock=is_mock_mode()))


# ------------------------------------------------------------------ #
# 헬퍼
# ------------------------------------------------------------------ #
def _payload_value(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


_BLOCK_MESSAGES = {
    "non_korean_source": "현재 한국어 원문만 지원하고 있어요. 한국어로 작성된 원문을 입력해 주세요.",
}


def _blocked_response(*, country: str, locale: str, block_reason: str) -> dict[str, Any]:
    message = _BLOCK_MESSAGES.get(block_reason, "입력을 처리할 수 없어요. 입력 내용을 다시 확인해 주세요.")
    return {
        "country": country,
        "locale": locale,
        "pipeline": "literary_package",
        "finalTranslation": message,
        "readerEndnotes": [],
        "authorReviewCards": [],
        "metadata": {"blockReason": block_reason},
        "translationReport": {
            "summary": "",
            "glossaryCandidates": [],
            "readerEndnotes": [],
            "inspectionReport": [],
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
    # 번역 요청은 workId를 안 보낼 수 있음(django는 episodeId만 전송) → episode로 work_id 역추적.
    # 이게 없으면 아래 hydrate 조건(work_id is not None)이 거짓이라 hydrate가 호출조차 안 돼
    # 승인 glossary dedup이 전부 무력화된다(확정 용어 재추천 버그의 실제 원인). inspect_chat와 동일 패턴.
    if work_id is None:
        episode_id = _payload_value(payload, "episodeId", "episode_id")
        if episode_id is not None:
            try:
                derived = db_repo.get_work_id_by_episode(int(episode_id))
                if derived is not None:
                    work_id = derived
            except Exception as exc:  # noqa: BLE001 — 역추적 실패가 번역을 막지 않도록
                logger.warning("get_work_id_by_episode failed (episode_id=%s): %r", episode_id, exc)
    request_wm = payload.get("workMemory") or payload.get("work_memory")
    work_memory = request_wm if isinstance(request_wm, dict) else None
    work_memory_source = "request_payload" if work_memory is not None else "none"
    work_memory_fallback = ""
    if work_memory is None and work_id is not None and locale:
        hydrated = db_repo.hydrate_work_memory(str(work_id), country)
        if hydrated is not None:
            work_memory = hydrated
            work_memory_source = "rdb_hydrated"

    pipeline = get_translation_pipeline(locale, model_override=model_override)
    result = asdict(
        pipeline.run_literary_package(
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
    metadata = {
        "mode": TranslationMode.LITERARY_PACKAGE.value,
        "pipeline": result.get("pipeline"),
        "reader_endnote_count": len(result.get("readerEndnotes") or []),
        "work_memory_source": work_memory_source,
        "work_memory_fallback_reason": work_memory_fallback,
    }

    internal = dict(result.get("internal") or {})
    internal["workMemorySource"] = work_memory_source

    # deliveryStatus/blocked 폐지 — final_integrity_check 제거로 항상 deliver. 빈 입력 차단은 _blocked_response(상류).
    include_internal = bool(payload.get("includeInternal") or payload.get("debugCaptureModelOutputs"))
    response: dict[str, Any] = {
        "country": country,
        "locale": locale,
        "pipeline": result.get("pipeline"),
        "finalTranslation": final_translation,
        "readerEndnotes": result.get("readerEndnotes", []),
        "authorReviewCards": result.get("authorReviewCards", []),
        "metadata": metadata,
    }
    # 화면설계서 번역 리포트 — 웹 4요소(summary·glossary_can·annotation_can·inspection_report) 실데이터 기반.
    internal_data = result.get("internal") or {}
    revisor_decisions = list(internal_data.get("revisorDecisions") or [])
    revisor_summary = str(internal_data.get("revisorSummary") or "")
    # 각 용어 후보/주석에 UI 체크 상태용 applied 키(기본 0) 부여. 웹이 컨펌하면 1로 갱신.
    glossary_candidates = [{**c, "applied": 0} for c in (internal_data.get("glossaryCandidates") or [])]
    reader_endnotes = [{**e, "applied": 0} for e in (result.get("readerEndnotes") or [])]
    # inspectionReport = 리바이저 전체 적용/보류 결정(voice·naturalness·cultural·glossary).
    # 웹은 reviewerType=='cultural'만 필터해 "문화리스크"로 표시, 챗봇은 전체를 소비.
    inspection_report = list(revisor_decisions)
    # summary(text) = 최종 수정가(revisor)의 총평만 그대로. (초벌가·3종 리뷰어 총평 합본 폐지)
    summary_text = revisor_summary
    response["readerEndnotes"] = reader_endnotes  # top-level도 applied 포함으로 동기화
    response["translationReport"] = {
        "summary": summary_text,
        "glossaryCandidates": glossary_candidates,
        "readerEndnotes": reader_endnotes,
        "inspectionReport": inspection_report,
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
                    "inspectionReport": inspection_report,    # json = 전체 리바이저 decisions (웹은 cultural 필터)
                }
            )
            response["persisted"] = saved
        except Exception as exc:  # noqa: BLE001
            response["persisted"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return response


_PENDING_ACTION_FIELDS = {"type", "original_word", "new_value", "category", "description"}
_PENDING_ACTION_TYPES = {"update_glossary", "add_glossary", "delete_glossary"}
_PLACEHOLDER_VALUES = {"원어", "새 번역어", "번역어", "glossary_type", "proposed_translation"}

_CONFIRM_EXACT = {
    "네",
    "응",
    "ㅇ",
    "ㅇㅇ",
    "예",
    "좋아",
    "좋습니다",
    "ok",
    "yes",
    "적용",
    "적용해",
    "적용해줘",
    "반영",
    "반영해",
    "반영해줘",
    "저장",
    "저장해",
    "저장해줘",
    "진행",
    "진행해",
    "진행해줘",
    "바꿔줘",
    "수정해줘",
    "변경해줘",
    "고쳐줘",
    "그걸로",
    "그걸로 해",
    "그대로 해",
}
_CONFIRM_TOKENS = {"네", "응", "ㅇ", "ㅇㅇ", "예", "좋아", "ok", "yes"}
_CONFIRM_ACTION_PHRASES = {
    "적용",
    "적용해",
    "적용해줘",
    "반영",
    "반영해",
    "반영해줘",
    "저장",
    "저장해",
    "저장해줘",
    "진행",
    "진행해",
    "진행해줘",
}
_CONFIRM_PRONOUN_PHRASES = {"그걸로", "그대로", "이걸로", "저걸로"}
_CHANGE_VERB_PHRASES = {"바꿔줘", "수정해줘", "변경해줘", "고쳐줘"}

_CANCEL_EXACT = {
    "아니",
    "아뇨",
    "됐어",
    "취소",
    "취소해",
    "취소해줘",
    "no",
    "안해",
    "안 해",
    "하지마",
    "하지 마",
    "그냥둬",
    "그냥 둬",
    "ㄴㄴ",
    "괜찮아",
    "말아줘",
    "보류",
    "나중에",
}
_CANCEL_PHRASES = {
    "취소",
    "하지마",
    "하지 마",
    "안해",
    "안 해",
    "말아줘",
    "그냥둬",
    "그냥 둬",
    "저장하지마",
    "저장하지 마",
    "반영하지마",
    "반영하지 마",
    "적용하지마",
    "적용하지 마",
    "보류",
}
_QUESTION_CUES = {"?", "왜", "뭐", "무엇", "어떻게", "맞아", "맞나요", "되나", "될까", "괜찮을까"}
_EXPLANATION_QUESTION_CUES = {"왜", "뭐", "무엇", "어떻게", "어때", "맞아", "맞나요", "되나", "될까", "괜찮을까"}
_UNCLEAR_CUES = {"아직", "근데", "그런데", "하지만", "일단", "말고", "음", "흠", "보이긴", "긴 한데", "하는데"}
_ACTION_REQUEST_CUES = {
    "바꿔",
    "수정",
    "변경",
    "고쳐",
    "교정",
    "다시 써",
    "rewrite",
    "replace",
    "change",
    "fix",
    "correct",
    "자연스럽게",
    "다듬",
    "어색하지 않게",
    "말투",
    "톤",
    "날카롭게",
    "짧게",
    "줄여",
    "줄이",
    "압축",
    "간결",
    "담백",
    "건조",
    "용어집",
    "glossary",
    "앞으로",
    "항상",
    "계속",
    "통일",
    "추가",
    "삭제",
}


def _normalize_decision_text(message: str) -> tuple[str, set[str]]:
    text = _re.sub(r"\s+", " ", str(message or "").strip().lower())
    tokens = set(_re.sub(r"[^가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9]", " ", text).split())
    return text, tokens


def _classify_user_intent(message: str) -> str:
    """'confirm' | 'cancel' | 'unclear' | 'other' — pendingAction 처리 전 보수적 의도 판정."""
    text, tokens = _normalize_decision_text(message)
    if not text:
        return "unclear"

    compact = text.replace(" ", "")
    if text in _CANCEL_EXACT or compact in {v.replace(" ", "") for v in _CANCEL_EXACT}:
        return "cancel"
    if any(phrase.replace(" ", "") in compact for phrase in _CANCEL_PHRASES):
        return "cancel"

    if any(cue in text for cue in _QUESTION_CUES):
        return "other"

    if text in _CONFIRM_EXACT or compact in {v.replace(" ", "") for v in _CONFIRM_EXACT}:
        return "confirm"

    has_unclear_cue = any(cue in text for cue in _UNCLEAR_CUES)
    if has_unclear_cue:
        return "unclear"

    short_enough = len(text) <= 40 and len(tokens) <= 5
    has_affirmation = bool(tokens & _CONFIRM_TOKENS)
    has_action_phrase = any(phrase in text for phrase in _CONFIRM_ACTION_PHRASES)
    has_pronoun = any(phrase in text for phrase in _CONFIRM_PRONOUN_PHRASES)
    has_change_verb = any(phrase in text for phrase in _CHANGE_VERB_PHRASES)

    if short_enough and (has_affirmation or has_action_phrase):
        return "confirm"
    if short_enough and has_pronoun and (has_action_phrase or has_change_verb or "해" in tokens):
        return "confirm"

    if has_change_verb and not (has_affirmation or has_pronoun or has_action_phrase):
        return "other"
    if has_change_verb or has_action_phrase or has_affirmation:
        return "unclear"
    return "other"


def _looks_like_action_request(message: str) -> bool:
    """LLM이 DB 액션을 제안해도 되는 현재 사용자 요청인지 보수적으로 확인."""
    text, _tokens = _normalize_decision_text(message)
    if not text:
        return False
    if any(cue in text for cue in _EXPLANATION_QUESTION_CUES):
        return False
    return any(cue in text for cue in _ACTION_REQUEST_CUES)


def _fail_closed_intent(reason: str) -> ChatIntentClassification:
    return ChatIntentClassification(
        intent="ambiguous",
        edit_scope="unknown",
        source_grounding="unclear",
        allow_pending_action=False,
        allow_proposed_translation=False,
        answer_strategy="ask_clarification",
        reason=reason,
        raw_response={"error": reason},
    )


def _classify_chat_intent(
    *,
    locale: str,
    user_message: str,
    source_text: str,
    draft_translation: str,
    reviewed_translation: str,
    chat_history: list[ChatMessage],
    pending_action: dict[str, Any] | None,
    action_context: str,
) -> ChatIntentClassification:
    try:
        return _chat_intent_classifier(locale).classify(
            user_message=user_message,
            source_text=source_text,
            draft_translation=draft_translation,
            reviewed_translation=reviewed_translation,
            chat_history=chat_history,
            pending_action=pending_action,
            action_context=action_context,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat intent classification failed: %r", exc)
        return _fail_closed_intent(f"{type(exc).__name__}: {exc}")


def _intent_context(intent: ChatIntentClassification) -> str:
    return (
        "[시스템: chat_intent_classifier 결과입니다. "
        "이 분류를 우선 신뢰하세요. allow_pending_action=false이면 pending_action을 만들지 마세요. "
        "allow_proposed_translation=false이면 proposed_translation을 만들지 마세요. "
        f"결과={intent.to_context()}]"
    )


def _guardrail_answer(intent: ChatIntentClassification, fallback: str) -> str:
    if "error" in (intent.raw_response or {}):
        return "수정 의도를 안전하게 확인하지 못해 저장용 수정안은 만들지 않았습니다. 다시 한 번 구체적으로 요청해 주세요."
    if intent.answer_strategy == "ask_clarification":
        return "요청하신 내용이 현재 원문/번역에 근거한 수정인지 확인이 필요합니다. 원문에서 누락된 부분인지, 기존 번역의 어느 부분을 바꾸려는 것인지 알려주세요."
    if intent.answer_strategy == "refuse_unrelated":
        return "현재 챗봇은 번역, 원문, 용어, 현지화, 검수 결과와 관련된 질문만 처리할 수 있습니다."
    return fallback


def _sanitize_pending_action(pending_action: Any) -> dict[str, Any] | None:
    if not isinstance(pending_action, dict):
        return None
    return {key: pending_action.get(key, "") for key in _PENDING_ACTION_FIELDS}


def _is_placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text in _PLACEHOLDER_VALUES


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_pending_action(
    pending_action: dict[str, Any],
    *,
    work_id: str | None,
    translation_id: int | None,
) -> str | None:
    action_type = str(pending_action.get("type") or "").strip()
    if action_type not in _PENDING_ACTION_TYPES:
        return f"알 수 없는 action type입니다: {action_type or '(empty)'}"

    original_word = pending_action.get("original_word", "")
    new_value = pending_action.get("new_value", "")
    category = pending_action.get("category", "")

    if action_type in {"add_glossary", "update_glossary"}:
        if not work_id:
            return "workId가 없어 glossary를 수정할 수 없습니다."
        if _is_placeholder(original_word):
            return "glossary 원어가 비어 있거나 placeholder입니다."
        if _is_placeholder(new_value):
            return "glossary 번역어가 비어 있거나 placeholder입니다."
        if _is_placeholder(category):
            return "glossary category가 비어 있거나 placeholder입니다."
        return None

    if action_type == "delete_glossary":
        if not work_id:
            return "workId가 없어 glossary를 삭제할 수 없습니다."
        if _is_placeholder(original_word):
            return "삭제할 glossary 원어가 비어 있거나 placeholder입니다."
        return None

    return None


def _execute_pending_action(
    pending_action: dict[str, Any],
    *,
    work_id: str | None,
    target_country: str,
    translation_id: int | None,
) -> dict[str, Any]:
    """pendingAction을 실제 DB에 반영. {type, saved, ...} 반환."""
    action_type = pending_action.get("type", "")
    original_word = pending_action.get("original_word", "")
    new_value = pending_action.get("new_value", "")
    category = pending_action.get("category", "")

    if action_type in ("update_glossary", "add_glossary"):
        if not work_id:
            return {"type": action_type, "saved": False, "reason": "workId가 없어 glossary를 수정할 수 없습니다."}
        result = db_repo.upsert_glossary_entry(
            work_id=work_id,
            target_country=target_country,
            original_word=original_word,
            translated_word=new_value,
            glossary_type=category,
        )
        return {"type": action_type, **result}

    if action_type == "delete_glossary":
        if not work_id:
            return {"type": action_type, "saved": False, "reason": "workId가 없어 glossary를 삭제할 수 없습니다."}
        result = db_repo.delete_glossary_entry_by_word(
            work_id=work_id,
            target_country=target_country,
            original_word=original_word,
        )
        return {"type": action_type, **result}

    return {"type": action_type, "saved": False, "reason": f"알 수 없는 action type: {action_type}"}


def _should_save_chat(payload: dict[str, Any]) -> bool:
    value = payload.get("saveChatMessages")
    if value is None:
        value = payload.get("save_chat_messages")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _persist_chat_turn_if_needed(
    response: dict[str, Any],
    *,
    payload: dict[str, Any],
    translation_id: Any,
    question: str,
    assistant_text: str,
) -> None:
    if translation_id is None or not _should_save_chat(payload):
        return
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


def _chat_response(
    *,
    answer: str,
    change_summary: str = "",
    needs_user_confirmation: bool = False,
    pending_action: dict[str, Any] | None = None,
    action_executed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "answer": answer,
        "changeSummary": change_summary,
        "needsUserConfirmation": needs_user_confirmation,
        "pendingAction": pending_action,
    }
    if action_executed is not None:
        response["actionExecuted"] = action_executed
    return response


def inspect_chat(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(_payload_value(payload, "question", "question_text", default="") or "").strip()
    if not question:
        raise ValueError("question is required")
    normalized = normalize_target_fields(payload)
    locale = normalized["targetLocale"]
    target_country = normalized["targetCountry"]

    workflow = payload.get("workflow") or {}
    draft = workflow.get("draft") or {}

    # translationId 조기 추출 → DB에서 번역 결과 로드 (inspectionReport 주입용)
    translation_id = _payload_value(payload, "translationId", "translation_id") or workflow.get("translationId") or workflow.get("translation_id")
    db_translation: dict[str, Any] | None = None
    if translation_id is not None:
        try:
            db_translation = db_repo.get_translation_result(int(translation_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_translation_result failed (translation_id=%s): %r", translation_id, exc)

    # work_id 확보 — 페이로드 우선, 없으면 episode → work 역추적
    work_id: str | None = str(_payload_value(payload, "workId", "work_id") or "").strip() or None
    if work_id is None and db_translation is not None:
        ep_id = db_translation.get("episode_id")
        if ep_id:
            try:
                derived = db_repo.get_work_id_by_episode(int(ep_id))
                if derived is not None:
                    work_id = str(derived)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_work_id_by_episode failed: %r", exc)

    reviewed = (
        str(_payload_value(payload, "currentTranslation", "current_translation", default="") or "")
        or workflow.get("finalTranslation")
        or workflow.get("reviewed_translation")
        or (db_translation.get("translated_text") if db_translation else None)
        or draft.get("translation")
        or ""
    )
    source_text = str(_payload_value(payload, "sourceText", "source_text", default="") or "") or workflow.get("source_text") or ""

    chat_history: list[ChatMessage] = []
    for row in (payload.get("chatHistory") or [])[-8:]:
        if isinstance(row, dict) and str(row.get("content") or "").strip():
            role = str(row.get("role") or "").strip()
            chat_history.append(ChatMessage(role="assistant" if role in {"ai", "assistant"} else "user", content=str(row["content"]).strip()))

    # inspectionReport: DB 로드 우선(전체 리바이저 decisions), 없으면 페이로드 폴백
    inspection_report: list[dict[str, Any]] = (
        (db_translation.get("inspection_report") if db_translation else None)
        or workflow.get("inspectionReport")
        or []
    )
    draft_translation = str(draft.get("translation", "") or "")

    # pendingAction 처리 — 이전 턴에서 제안된 액션에 대한 사용자 응답 판정
    incoming_pending_action = _sanitize_pending_action(payload.get("pendingAction"))
    action_context = ""

    if incoming_pending_action:
        intent = _classify_user_intent(question)
        if intent == "confirm":
            safe_translation_id = _safe_int(translation_id)
            validation_error = _validate_pending_action(
                incoming_pending_action,
                work_id=work_id,
                translation_id=safe_translation_id,
            )
            if validation_error:
                action_executed = {
                    "type": incoming_pending_action.get("type", ""),
                    "saved": False,
                    "reason": validation_error,
                }
            else:
                action_executed = _execute_pending_action(
                    incoming_pending_action,
                    work_id=work_id,
                    target_country=target_country,
                    translation_id=safe_translation_id,
                )
            if action_executed.get("saved"):
                answer = "요청하신 변경을 적용했습니다."
            else:
                answer = f"변경을 적용하지 못했습니다: {action_executed.get('reason', '알 수 없는 오류')}"
            response = _chat_response(answer=answer, action_executed=action_executed)
            _persist_chat_turn_if_needed(
                response,
                payload=payload,
                translation_id=translation_id,
                question=question,
                assistant_text=answer,
            )
            return response
        elif intent == "cancel":
            desc = incoming_pending_action.get("description", "")
            answer = f"'{desc}' 변경 제안을 취소했습니다. 적용된 변경은 없습니다." if desc else "변경 제안을 취소했습니다. 적용된 변경은 없습니다."
            response = _chat_response(answer=answer)
            _persist_chat_turn_if_needed(
                response,
                payload=payload,
                translation_id=translation_id,
                question=question,
                assistant_text=answer,
            )
            return response
        elif intent == "unclear":
            answer = "이전 수정 제안을 적용할까요? 적용하려면 '적용해줘', 취소하려면 '취소'라고 답해주세요."
            response = _chat_response(
                answer=answer,
                needs_user_confirmation=True,
                pending_action=incoming_pending_action,
            )
            _persist_chat_turn_if_needed(
                response,
                payload=payload,
                translation_id=translation_id,
                question=question,
                assistant_text=answer,
            )
            return response
        else:
            action_context = (
                "[시스템: 이전 pendingAction이 있으나 현재 메시지는 명확한 확인/취소가 아닙니다. "
                "이전 액션을 실행하거나 재생성하지 말고 현재 메시지에만 답하세요.]"
            )

    intent = _classify_chat_intent(
        locale=locale,
        user_message=question,
        source_text=source_text,
        draft_translation=draft_translation,
        reviewed_translation=reviewed,
        chat_history=chat_history,
        pending_action=incoming_pending_action,
        action_context=action_context,
    )
    action_context = "\n".join(part for part in [action_context, _intent_context(intent)] if part)

    reply = _chatbot(locale).reply(
        user_message=question,
        source_text=source_text,
        draft_translation=draft_translation,
        reviewed_translation=reviewed,
        translation_rationale="",  # translationRationale 폐지 — 챗봇에 넘길 내용은 추후 재정의(팀원 협의).
        used_references=[],
        inspection_report=inspection_report,
        reader_endnotes=workflow.get("readerEndnotes") or [],
        work_title=str(payload.get("title") or ""),
        episode_id=str(_payload_value(payload, "episodeId", "episode_id", default="") or ""),
        translation_memory=[],
        chat_history=chat_history,
        action_context=action_context,
    )

    new_pending_action = reply.pending_action
    edits = reply.edits or []
    change_summary = reply.change_summary
    guardrail_removed_action = False
    if new_pending_action and not intent.allow_pending_action:
        new_pending_action = None
        guardrail_removed_action = True
    if edits and not intent.allow_proposed_translation:
        edits = []
        change_summary = ""
        guardrail_removed_action = True
    # 번역 수정은 edits(프론트 버튼 적용)로만 처리 → 확인이 필요한 것은 glossary pending_action뿐.
    needs_user_confirmation = bool(new_pending_action)
    answer = _guardrail_answer(intent, reply.answer) if guardrail_removed_action else reply.answer

    response: dict[str, Any] = {
        "answer": answer,
        "edits": edits,
        "changeSummary": change_summary,
        "needsUserConfirmation": needs_user_confirmation,
        "pendingAction": new_pending_action,
    }

    assistant_text = answer or ""
    if edits:
        assistant_text = f"{assistant_text}\n\n[수정 제안: {len(edits)}곳]".strip()
    _persist_chat_turn_if_needed(
        response,
        payload=payload,
        translation_id=translation_id,
        question=question,
        assistant_text=assistant_text,
    )

    return response
