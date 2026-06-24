from __future__ import annotations

from typing import Any

UNGROUNDED_MARKET_LIMITATION = (
    "현재 확보된 자료만으로는 국가별 독자 선호, 플랫폼 실적 등 "
    "실제 시장 성과를 직접 확인할 수 없어 해당 내용을 확정적으로 판단하지 않았습니다."
)

ALLOWED_ORIGINAL_FIELD_NAMES = {
    "workTitle",
    "targetCountry",
    "country",
    "displayCountry",
    "targetCountryDisplay",
    "recommendedCountry",
    "recommendedCountry",
    "recommendedCountryDisplay",
    "llmGuideModel",
    "llmGuideGeneratedAt",
    "llmRecommendationMethod",
    "llmCountryRecommendationModel",
    "llmCountryRecommendationError",
    "llmRecommendationEvidenceBytes",
    "llmRecommendationRequestHash",
    "llmGuideEvidenceBytes",
    "llmGuideContextPackEvidenceBytes",
    "llmGuideRequestHash",
}

USER_FACING_TEXT_KEYS = {
    "title",
    "message",
    "notice",
    "summary",
    "analysisSummary",
    "confidence",
    "limitations",
    "executiveSummary",
    "marketInterpretation",
    "culturalNotes",
    "platformPolicyChecks",
    "marketTagGuidance",
    "evidenceExplanation",
    "storyProfile",
    "strengths",
    "risks",
    "recommendationNotice",
    "limitation_notice",
    "fitLevel",
    "localizationDifficulty",
}

FOREIGN_SENTENCE_PATTERNS = ("[A-Za-z]", "http://", "https://")


def _has_korean(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


def _looks_like_foreign_explanation(text: str) -> bool:
    if not text.strip():
        return False
    if _has_korean(text):
        return False
    return any(ch.isalpha() for ch in text)


def _is_original_allowed_key(key: str | None) -> bool:
    return bool(key and key in ALLOWED_ORIGINAL_FIELD_NAMES)


def _walk_explanations(value: Any, *, key: str | None = None):
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            yield from _walk_explanations(nested_value, key=str(nested_key))
    elif isinstance(value, list):
        for item in value:
            yield from _walk_explanations(item, key=key)
    elif isinstance(value, str):
        yield key, value


def validate_user_facing_language(payload: dict[str, Any]) -> dict[str, Any]:
    invalid_paths: list[str] = []
    for key, value in _walk_explanations(payload):
        if _is_original_allowed_key(key):
            continue
        if key and key not in USER_FACING_TEXT_KEYS:
            continue
        if _looks_like_foreign_explanation(value):
            invalid_paths.append(key or "")
    return {"ok": not invalid_paths, "invalidPaths": [path for path in invalid_paths if path]}


def _safe_korean_fallback(key: str | None, value: str) -> str:
    fallback = {
        "title": "가이드",
        "message": "한국어 안내가 필요합니다.",
        "notice": "검토 필요",
        "summary": "요약을 확인해 주세요.",
        "analysisSummary": "분석 결과를 한국어로 정리합니다.",
        "confidence": "낮음",
        "limitations": UNGROUNDED_MARKET_LIMITATION,
        "recommendationNotice": "추천이 필요합니다.",
        "limitation_notice": "참고용 안내입니다.",
        "fitLevel": "적합",
        "localizationDifficulty": "보통",
    }
    if key in fallback:
        return fallback[key]
    if "limit" in (key or "").lower():
        return UNGROUNDED_MARKET_LIMITATION
    if "risk" in (key or "").lower():
        return "주의가 필요합니다."
    if "strength" in (key or "").lower():
        return "강점이 있습니다."
    if "summary" in (key or "").lower():
        return "요약이 필요합니다."
    return "한국어 안내"


def _repair_value(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {nested_key: _repair_value(nested_value, key=str(nested_key)) for nested_key, nested_value in value.items()}
    if isinstance(value, list):
        return [_repair_value(item, key=key) for item in value]
    if isinstance(value, str) and _looks_like_foreign_explanation(value) and not _is_original_allowed_key(key):
        return _safe_korean_fallback(key, value)
    return value


def repair_user_facing_explanations(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: _repair_value(value, key=str(key)) for key, value in payload.items()}


def sanitize_deterministic_explanations(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = repair_user_facing_explanations(payload)
    validation = validate_user_facing_language(repaired)
    return repaired if validation["ok"] else repaired


__all__ = [
    "ALLOWED_ORIGINAL_FIELD_NAMES",
    "FOREIGN_SENTENCE_PATTERNS",
    "USER_FACING_TEXT_KEYS",
    "repair_user_facing_explanations",
    "sanitize_deterministic_explanations",
    "validate_user_facing_language",
]
