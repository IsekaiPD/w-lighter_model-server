from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..engine.policy_analysis import build_policy_attention_report
from ..infra.output_language_guard import repair_user_facing_explanations, sanitize_deterministic_explanations, validate_user_facing_language
from ..retrieval.context_pack import build_context_pack_overlap_report, inspect_context_pack_source
from .guide_writer import _client_and_model, llm_requested

COUNTRY_COMPARISON_TARGETS = [
    {"code": "JP", "targetCountry": "Japan", "market": "japan", "display": "일본"},
    {"code": "CN", "targetCountry": "China", "market": "china", "display": "중국"},
    {"code": "US", "targetCountry": "US/global English", "market": "english", "display": "미국/글로벌 영어"},
    {"code": "TH", "targetCountry": "Thailand", "market": "thailand", "display": "태국"},
]

COUNTRY_RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "storyProfile": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "genre": {"type": "string"},
                "coreSignals": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
                "analysisSummary": {"type": "string"},
            },
            "required": ["title", "genre", "coreSignals", "analysisSummary"],
        },
        "recommendedCountry": {"type": "string", "enum": ["US", "CN", "JP", "TH"]},
        "confidence": {"type": "string"},
        "countryComparisons": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "country": {"type": "string", "enum": ["US", "CN", "JP", "TH"]},
                    "rank": {"type": "integer", "minimum": 1, "maximum": 4},
                    "relativeFitScore": {"type": "number", "minimum": 0, "maximum": 100},
                    "fitLevel": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
                    "risks": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
                    "evidenceSummary": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
                    "localizationDifficulty": {"type": "string"},
                },
                "required": [
                    "country",
                    "rank",
                    "relativeFitScore",
                    "fitLevel",
                    "strengths",
                    "risks",
                    "evidenceSummary",
                    "localizationDifficulty",
                ],
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
    },
    "required": ["storyProfile", "recommendedCountry", "confidence", "countryComparisons", "limitations"],
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy_flag(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"", "0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return default


def _include_context_pack(payload: dict[str, Any]) -> bool:
    if "includeContextPack" in payload:
        return _truthy_flag(payload.get("includeContextPack"), default=True)
    if "include_context_pack" in payload:
        return _truthy_flag(payload.get("include_context_pack"), default=True)
    return _truthy_flag(payload.get("includeContextPackDefault"), default=True)


def _include_internal(payload: dict[str, Any]) -> bool:
    return _truthy_flag(payload.get("includeInternal") or payload.get("include_internal"), default=False)


def _stable_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _payload_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _target_market_for_code(code: str) -> str:
    for target in COUNTRY_COMPARISON_TARGETS:
        if target["code"] == code:
            return target["market"]
    return "japan"


def _country_display(code: str) -> str:
    for target in COUNTRY_COMPARISON_TARGETS:
        if target["code"] == code:
            return target["display"]
    return code


def _top_evidence_by_country(payload: dict[str, Any], *, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for target in COUNTRY_COMPARISON_TARGETS:
        report = build_context_pack_overlap_report(
            {
                "title": payload.get("title") or payload.get("workTitle") or "가이드 입력",
                "target_market": target["market"],
                "genre": payload.get("genre") or "",
                "synopsis": payload.get("synopsis") or payload.get("desc") or "",
                "title_elements": payload.get("titleElements") or payload.get("title_elements") or [],
                "comparable_signals": payload.get("comparableSignals") or payload.get("comparable_signals") or [],
                "declared_signals": payload.get("declaredSignals") or payload.get("declared_signals") or payload.get("signals") or [],
            }
        )
        rows = report.get("evidence", {}).get("direct_signal_rows") or []
        out[target["code"]] = [
            {
                "signal": row.get("work_signal"),
                "status": row.get("match_status"),
                "observedLabel": row.get("observed_label"),
                "source": row.get("source"),
            }
            for row in rows[:limit]
        ]
    return out


def _context_match_summary(payload: dict[str, Any], target: dict[str, str], *, include_context_pack: bool) -> dict[str, Any]:
    source = inspect_context_pack_source(target["market"])
    if not include_context_pack:
        return {
            "contextRecordCount": 0,
            "matchedSignals": [],
            "matchedEvidence": [],
            "diagnostics": {
                "country": target["code"],
                "contextPackRequested": False,
                "contextPackEnabled": False,
                "requestedTargetCountry": target["targetCountry"],
                "resolvedTargetMarket": source.get("resolvedTargetMarket"),
                "contextPackSourceFound": bool(source.get("contextPackSourceFound")),
                "contextPackSourceRecordCount": int(source.get("contextPackSourceRecordCount") or 0),
                "contextPackCandidateRecordCount": 0,
                "contextPackMatchedRecordCount": 0,
                "contextPackInjectedRecordCount": 0,
                "contextPackInjectedEvidenceBytes": 0,
                "contextPackSkipReason": "disabled",
            },
        }

    report = build_context_pack_overlap_report(
        {
            "title": payload.get("title") or payload.get("workTitle") or "가이드 입력",
            "target_market": target["market"],
            "genre": payload.get("genre") or "",
            "synopsis": payload.get("synopsis") or payload.get("desc") or "",
            "title_elements": payload.get("titleElements") or payload.get("title_elements") or [],
            "comparable_signals": payload.get("comparableSignals") or payload.get("comparable_signals") or [],
            "declared_signals": payload.get("declaredSignals") or payload.get("declared_signals") or payload.get("signals") or [],
        }
    )
    evidence = report["evidence"]
    rows = evidence.get("direct_signal_rows") or []
    matched_rows = [row for row in rows if row.get("direct_observation") == "observed"]
    matched_evidence = [
        {
            "signal": row.get("work_signal"),
            "matchStatus": row.get("match_status"),
            "observedLabel": row.get("observed_label"),
            "candidateLabels": [item.get("label_ko") for item in row.get("candidate_observations") or [] if item.get("label_ko")],
            "count": (row.get("aggregate") or {}).get("count"),
        }
        for row in matched_rows[:5]
    ]
    injected_bytes = _payload_size(matched_evidence) if matched_evidence else 0
    source_count = int(evidence.get("context_record_count") or source.get("contextPackSourceRecordCount") or 0)
    if not source.get("contextPackSourceFound"):
        skip_reason = "source_not_found"
    elif source_count <= 0:
        skip_reason = "no_source_records"
    elif not rows:
        skip_reason = "no_candidate_records"
    elif not matched_rows:
        skip_reason = "no_matched_signals"
    elif not matched_evidence:
        skip_reason = "not_injected"
    else:
        skip_reason = "injected"
    return {
        "contextRecordCount": evidence.get("context_record_count"),
        "matchedSignals": [row.get("work_signal") for row in matched_rows if row.get("work_signal")],
        "matchedEvidence": matched_evidence,
        "diagnostics": {
            "country": target["code"],
            "contextPackRequested": True,
            "contextPackEnabled": True,
            "requestedTargetCountry": target["targetCountry"],
            "resolvedTargetMarket": source.get("resolvedTargetMarket") or evidence.get("target_market"),
            "contextPackSourceFound": bool(source.get("contextPackSourceFound")),
            "contextPackSourceRecordCount": source_count,
            "contextPackCandidateRecordCount": len(rows),
            "contextPackMatchedRecordCount": len(matched_rows),
            "contextPackInjectedRecordCount": len(matched_evidence),
            "contextPackInjectedEvidenceBytes": injected_bytes,
            "contextPackSkipReason": skip_reason,
        },
    }


def _policy_summary(payload: dict[str, Any], target: dict[str, str]) -> dict[str, Any]:
    report = build_policy_attention_report({**payload, "targetCountry": target["code"]})
    cards = report.get("policy_attention_cards") or []
    return {
        "riskCount": len(cards),
        "risks": [
            {
                "title": card.get("card_title"),
                "status": card.get("status_label"),
                "message": card.get("guide_message_ko") or card.get("display_sentence"),
            }
            for card in cards[:4]
        ],
        "limitations": report.get("policy_limitations") or [],
    }


def build_country_recommendation_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    top_evidence = _top_evidence_by_country(payload)
    include_context_pack = _include_context_pack(payload)
    countries = []
    diagnostics = []
    for target in COUNTRY_COMPARISON_TARGETS:
        context = _context_match_summary(payload, target, include_context_pack=include_context_pack)
        policy = _policy_summary(payload, target)
        diagnostics.append(context["diagnostics"])
        countries.append(
            {
                "country": target["code"],
                "targetCountry": target["targetCountry"],
                "displayCountry": target["display"],
                "platformEvidence": top_evidence.get(target["code"], [])[:5],
                "matchedSignals": context["matchedSignals"],
                "matchedContextEvidence": context["matchedEvidence"],
                "policyRiskSummary": policy,
                "localizationDifficultyInputs": [
                    f"직접 매칭 {len(context['matchedSignals'])}개",
                    f"정책 점검 카드 {policy['riskCount']}개",
                    f"참고 컨텍스트 {context['contextRecordCount'] or 0}건",
                ],
            }
        )
    return {
        "story": {
            "title": payload.get("title") or payload.get("workTitle") or "입력 작품",
            "genre": payload.get("genre") or "장르 미입력",
            "synopsis": payload.get("synopsis") or payload.get("desc") or "",
        },
        "countries": countries,
        "contextPackDiagnosticsByCountry": diagnostics,
        "comparisonRule": "4개국 비교 후 사용자가 직접 선택할 수 있게 정리합니다.",
    }


def _evidence_size(evidence: dict[str, Any]) -> int:
    return _payload_size(evidence)


def _aggregate_context_pack_diagnostics(evidence: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    rows = evidence.get("contextPackDiagnosticsByCountry") or []
    enabled = _include_context_pack(payload)
    source_found = any(row.get("contextPackSourceFound") for row in rows)
    source_count = sum(int(row.get("contextPackSourceRecordCount") or 0) for row in rows)
    candidate_count = sum(int(row.get("contextPackCandidateRecordCount") or 0) for row in rows)
    matched_count = sum(int(row.get("contextPackMatchedRecordCount") or 0) for row in rows)
    injected_count = sum(int(row.get("contextPackInjectedRecordCount") or 0) for row in rows)
    injected_bytes = sum(int(row.get("contextPackInjectedEvidenceBytes") or 0) for row in rows)
    reasons = [str(row.get("contextPackSkipReason")) for row in rows if row.get("contextPackSkipReason")]
    if not enabled:
        reason = "disabled"
    elif injected_count:
        reason = "injected"
    elif "no_matched_signals" in reasons:
        reason = "no_matched_signals"
    elif reasons:
        reason = reasons[0]
    else:
        reason = "not_injected"
    return {
        "contextPackRequested": "includeContextPack" in payload or "include_context_pack" in payload,
        "contextPackEnabled": enabled,
        "requestedTargetCountry": None,
        "resolvedTargetMarket": "multi_country",
        "contextPackSourceFound": source_found,
        "contextPackSourceRecordCount": source_count,
        "contextPackCandidateRecordCount": candidate_count,
        "contextPackMatchedRecordCount": matched_count,
        "contextPackInjectedRecordCount": injected_count,
        "contextPackInjectedEvidenceBytes": injected_bytes,
        "contextPackSkipReason": reason,
        "contextPackDiagnosticsByCountry": rows,
    }


def _validate_country_result(result: dict[str, Any]) -> None:
    comparisons = result.get("countryComparisons") or []
    countries = [item.get("country") for item in comparisons]
    ranks = [item.get("rank") for item in comparisons]
    if sorted(countries) != ["CN", "JP", "TH", "US"]:
        raise ValueError("countryComparisons must contain US, CN, JP, TH exactly once")
    if sorted(ranks) != [1, 2, 3, 4]:
        raise ValueError("countryComparisons ranks must be 1..4 without duplicates")
    rank_one = next((item.get("country") for item in comparisons if item.get("rank") == 1), None)
    if result.get("recommendedCountry") != rank_one:
        raise ValueError("recommendedCountry must match rank 1 country")


def _canonicalize_result(
    result: dict[str, Any],
    *,
    evidence_size: int,
    model: str | None = None,
    internal_diagnostics: dict[str, Any] | None = None,
    request_hash: str | None = None,
) -> dict[str, Any]:
    _validate_country_result(result)
    repaired = repair_user_facing_explanations(result)
    validation = validate_user_facing_language(repaired)
    if not validation["ok"]:
        repaired = repair_user_facing_explanations(repaired)
    _validate_country_result(repaired)
    recommended = str(repaired["recommendedCountry"])
    comparisons = []
    for item in repaired["countryComparisons"]:
        code = str(item["country"])
        comparisons.append(
            {
                **item,
                "displayCountry": _country_display(code),
                "targetCountry": COUNTRY_COMPARISON_TARGETS[[t["code"] for t in COUNTRY_COMPARISON_TARGETS].index(code)]["targetCountry"],
            }
        )
    out = {
        "mode": "synopsis_country_recommendation",
        "requiresSelection": True,
        "title": "4개국 비교 추천",
        "recommendedCountry": recommended,
        "recommended_country": COUNTRY_COMPARISON_TARGETS[[t["code"] for t in COUNTRY_COMPARISON_TARGETS].index(recommended)]["targetCountry"],
        "recommended_country_display": _country_display(recommended),
        "confidence": repaired["confidence"],
        "storyProfile": repaired["storyProfile"],
        "countryComparisons": comparisons,
        "limitations": repaired["limitations"],
        "recommendationMethod": "llm_country_comparison" if model else "deterministic_country_comparison",
        "llmCountryRecommendationModel": model,
        "llmRecommendationEvidenceBytes": evidence_size,
        "available_countries": [target["display"] for target in COUNTRY_COMPARISON_TARGETS],
        "limitation_notice": "사용자 선택이 필요합니다.",
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if internal_diagnostics:
        out.update(internal_diagnostics)
    if request_hash:
        out["llmRecommendationRequestHash"] = request_hash
    return out


def _deterministic_comparison(payload: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for target in evidence["countries"]:
        matched = len(target.get("matchedSignals") or [])
        platform = len(target.get("platformEvidence") or [])
        risk = int((target.get("policyRiskSummary") or {}).get("riskCount") or 0)
        score = max(10, min(95, 45 + matched * 15 + min(platform, 5) * 4 - risk * 3))
        rows.append((score, target))
    ranked = sorted(rows, key=lambda item: item[0], reverse=True)
    comparisons = []
    for rank, (score, target) in enumerate(ranked, start=1):
        matched_signals = target.get("matchedSignals") or []
        code = target["country"]
        comparisons.append(
            {
                "country": code,
                "rank": rank,
                "relativeFitScore": score,
                "fitLevel": "상위 적합" if rank == 1 else "비교 적합",
                "strengths": [
                    f"{target['displayCountry']} 기준 직접 매칭 신호 {len(matched_signals)}개가 확인됩니다.",
                    "플랫폼 근거와 정책 근거를 함께 확인했습니다.",
                ],
                "risks": [
                    "정밀한 최종 판단은 추가 확인이 필요합니다.",
                    "문화 차이와 플랫폼 규정은 별도 검토가 필요합니다.",
                ],
                "evidenceSummary": [
                    f"직접 매칭 신호: {', '.join(matched_signals[:4]) if matched_signals else '없음'}",
                    f"정책 점검 카드: {target['policyRiskSummary']['riskCount']}개",
                ],
                "localizationDifficulty": "보통",
            }
        )
    result = {
        "storyProfile": {
            "title": evidence["story"]["title"],
            "genre": evidence["story"]["genre"],
            "coreSignals": [evidence["story"]["genre"]] if evidence["story"]["genre"] else ["입력 장르"],
            "analysisSummary": "입력 시놉시스와 컨텍스트 팩을 바탕으로 4개국 비교를 구성했습니다.",
        },
        "recommendedCountry": comparisons[0]["country"],
        "confidence": "중간",
        "countryComparisons": comparisons,
        "limitations": [
            "이 추천은 참고용이며 최종 선택은 사용자가 해야 합니다.",
            "추가 현지화 검토가 있으면 더 정확해집니다.",
        ],
    }
    return sanitize_deterministic_explanations(result)


def _manual_selection_fallback(
    payload: dict[str, Any],
    *,
    error: str,
    evidence_size: int,
    internal_diagnostics: dict[str, Any] | None = None,
    request_hash: str | None = None,
) -> dict[str, Any]:
    out = {
        "mode": "synopsis_country_recommendation",
        "requiresSelection": True,
        "title": "국가를 직접 선택해 주세요",
        "message": "추천 생성에 실패했습니다. 일본, 중국, 미국/글로벌 영어, 태국 중 하나를 직접 선택하면 상세 가이드를 이어갈 수 있습니다.",
        "genre": payload.get("genre") or "",
        "synopsis": payload.get("synopsis") or payload.get("desc") or "",
        "available_countries": [target["display"] for target in COUNTRY_COMPARISON_TARGETS],
        "recommended_country": None,
        "recommended_country_display": None,
        "recommendedCountry": None,
        "countryComparisons": [],
        "limitations": [
            "추천 LLM 호출이 실패했습니다.",
            "직접 국가를 선택하면 다음 단계로 진행할 수 있습니다.",
        ],
        "recommendationMethod": "llm_country_comparison_failed",
        "llmCountryRecommendationError": error,
        "llmRecommendationEvidenceBytes": evidence_size,
        "limitation_notice": "직접 선택이 필요합니다.",
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if internal_diagnostics:
        out.update(internal_diagnostics)
    if request_hash:
        out["llmRecommendationRequestHash"] = request_hash
    return out


def generate_country_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = build_country_recommendation_evidence(payload)
    evidence_size = _evidence_size(evidence)
    internal_diagnostics = _aggregate_context_pack_diagnostics(evidence, payload) if _include_internal(payload) else None
    if not llm_requested(payload):
        return _canonicalize_result(
            _deterministic_comparison(payload, evidence),
            evidence_size=evidence_size,
            internal_diagnostics=internal_diagnostics,
        )

    try:
        client, model = _client_and_model(payload)
        system = (
            "당신은 한국어로 국가 추천을 설명하는 도우미다. "
            "반드시 한국어 JSON 객체만 출력하고, 4개국 비교 결과를 균형 있게 제시한다."
        )
        user = {
            "task": "일본, 중국, 미국/글로벌 영어, 태국 중 적합한 국가를 비교 추천해 주세요.",
            "requirements": [
                "countryComparisons에는 US, CN, JP, TH를 각각 한 번씩 넣으세요.",
                "rank는 1~4를 중복 없이 사용하고, recommendedCountry는 rank 1과 일치해야 합니다.",
                "설명은 모두 한국어로 작성하세요.",
            ],
            "evidence": evidence,
        }
        request_hash = _stable_hash({"system": system, "user": user})
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "llm_country_recommendation",
                    "schema": COUNTRY_RECOMMENDATION_SCHEMA,
                    "strict": True,
                }
            },
        )
        result = json.loads(response.output_text)
        return _canonicalize_result(
            result,
            evidence_size=evidence_size,
            model=model,
            internal_diagnostics=internal_diagnostics,
            request_hash=request_hash,
        )
    except Exception as exc:
        return _manual_selection_fallback(
            payload,
            error=str(exc),
            evidence_size=evidence_size,
            internal_diagnostics=internal_diagnostics,
        )


__all__ = ["build_country_recommendation_evidence", "generate_country_recommendation"]
