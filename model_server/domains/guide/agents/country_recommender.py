from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..engine.policy_analysis import build_policy_attention_report
from ..engine.recommendation import DEFAULT_INPUT, load_trend_data, rank_countries
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
                    "relativeFitScore": {"type": "number", "minimum": 1, "maximum": 100},
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

CREATIVE_BOUNDARY_RULES = [
    "작품의 플롯, 결말, 캐릭터 성격, 핵심 설정, 장르 방향을 바꾸라고 제안하지 마세요.",
    "국가 추천은 작품을 현재 방향 그대로 두고 어느 시장에서 먼저 전달/테스트하기 좋은지 판단하는 것입니다.",
    "strengths와 risks는 창작 수정이 아니라 제목, 소개문, 태그, 표지 브리프, 정책 검토, 독자 기대치 전달 관점으로 작성하세요.",
]


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


def _has_synopsis(payload: dict[str, Any]) -> bool:
    return bool(_text(payload.get("synopsis") or payload.get("desc")))


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


COUNTRY_NAME_TO_CODE = {
    "Japan": "JP",
    "China": "CN",
    "US/global English": "US",
    "Thailand": "TH",
}


def _support_signal_labels(reasons: list[str], evidence_count: int) -> list[str]:
    labels: list[str] = []
    joined = " ".join(reasons)
    if "장르" in joined:
        labels.append("입력 장르와 공개 장르·태그 겹침")
    if "시놉시스" in joined:
        labels.append("시놉시스와 공개 제목·소개문 신호 겹침")
    if evidence_count and not labels:
        labels.append("상위 공개 노출 사례")
    return labels


def _recommendation_support_by_code(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build country-fit support from the same trend ranker used by legacy recommendations."""
    try:
        recommendations = rank_countries(
            load_trend_data(DEFAULT_INPUT),
            genre=payload.get("genre") or "",
            synopsis=payload.get("synopsis") or payload.get("desc") or "",
        )
    except Exception:
        return {}

    out: dict[str, dict[str, Any]] = {}
    positive_scores = [float(rec.score or 0) for rec in recommendations if float(rec.score or 0) > 0]
    max_score = max(positive_scores) if positive_scores else 0.0
    for index, rec in enumerate(recommendations, start=1):
        code = COUNTRY_NAME_TO_CODE.get(rec.country)
        if not code:
            continue
        reasons = [str(item) for item in rec.reasons[:4] if str(item).strip()]
        evidence_count = len(rec.evidence)
        out[code] = {
            "score": float(rec.score or 0),
            "normalizedScore": (float(rec.score or 0) / max_score) if max_score else 0.0,
            "rankIndex": index,
            "reasons": reasons,
            "signals": _support_signal_labels(reasons, evidence_count),
            "evidenceCount": evidence_count,
        }
    return out


def _score_from_support(target: dict[str, Any], support: dict[str, Any]) -> int:
    matched = len(target.get("matchedSignals") or [])
    platform = len(target.get("platformEvidence") or [])
    risk = int((target.get("policyRiskSummary") or {}).get("riskCount") or 0)
    normalized = float(support.get("normalizedScore") or 0)
    if normalized > 0:
        rank_penalty = max(0, int(support.get("rankIndex") or 1) - 1) * 4
        return max(18, min(95, int(round(34 + normalized * 56 + matched * 5 + min(platform, 5) * 2 - risk * 2 - rank_penalty))))
    return max(10, min(45, 24 + matched * 8 + min(platform, 5) * 2 - risk * 2))


def _country_strengths(target: dict[str, Any], support: dict[str, Any]) -> list[str]:
    display = target["displayCountry"]
    reasons = support.get("reasons") or []
    signals = support.get("signals") or []
    matched = target.get("matchedSignals") or []
    strengths: list[str] = []
    if reasons:
        strengths.append(f"{display} 공개 플랫폼 자료에서 {reasons[0]} 흐름이 확인됩니다.")
    if signals:
        strengths.append(f"참고 신호는 {', '.join(signals[:4])} 중심으로 잡혔습니다.")
    if matched:
        strengths.append(f"컨텍스트 팩에서 직접 겹친 입력 신호는 {', '.join(matched[:4])}입니다.")
    evidence_count = int(support.get("evidenceCount") or 0)
    if evidence_count:
        strengths.append(f"국가별 비교에는 관련 공개 노출 사례 {evidence_count}건을 보조 근거로 사용했습니다.")
    if not strengths:
        strengths.append(f"{display}은 직접 겹치는 신호가 약해 기본 시장 참고 자료만으로 비교했습니다.")
    return strengths[:4]


def _country_risks(target: dict[str, Any], support: dict[str, Any]) -> list[str]:
    policy = target.get("policyRiskSummary") or {}
    risks = [str(item.get("message") or item.get("title")) for item in policy.get("risks") or [] if item.get("message") or item.get("title")]
    out = risks[:2]
    if not support.get("signals"):
        out.append("시놉시스·장르와 직접 겹치는 공개 신호가 제한적이어서 추가 작품 정보로 재확인이 필요합니다.")
    out.append("이 비교는 배포 확정이 아니라 제목·소개문·태그·정책 검토 우선순위를 정하기 위한 참고입니다.")
    return list(dict.fromkeys(item for item in out if item))[:4]


def _evidence_summary(target: dict[str, Any], support: dict[str, Any]) -> list[str]:
    summary: list[str] = []
    if support.get("reasons"):
        summary.extend(support["reasons"][:2])
    if support.get("signals"):
        summary.append(f"참고 신호: {', '.join(support['signals'][:4])}")
    matched = target.get("matchedSignals") or []
    if matched:
        summary.append(f"직접 매칭 신호: {', '.join(matched[:4])}")
    else:
        summary.append("직접 매칭 신호: 없음 — 플랫폼 랭킹/태그 기반 보조 비교")
    summary.append(f"정책 점검 카드: {(target.get('policyRiskSummary') or {}).get('riskCount', 0)}개")
    return summary[:5]


def _story_core_signals(payload: dict[str, Any], evidence: dict[str, Any], supports: dict[str, dict[str, Any]]) -> list[str]:
    signals: list[str] = []
    genre = _text(evidence["story"].get("genre"))
    if genre:
        signals.append(f"입력 장르: {genre}")
    for support in supports.values():
        for signal in support.get("signals") or []:
            if signal and signal not in signals:
                signals.append(signal)
            if len(signals) >= 6:
                return signals
    if _text(payload.get("synopsis") or payload.get("desc")) and "시놉시스 기반 비교" not in signals:
        signals.append("시놉시스 기반 비교")
    return signals or ["입력 장르"]


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
        "comparisonRule": "시놉시스의 핵심 매력을 기준으로 4개국 적합도를 비교합니다.",
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


def _repair_relative_fit_scores(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair unhelpful LLM scores such as all-zero or all-equal ranked outputs."""
    scores: list[float] = []
    for item in comparisons:
        try:
            scores.append(float(item.get("relativeFitScore") or 0))
        except (TypeError, ValueError):
            scores.append(0.0)

    needs_repair = (
        any(score <= 0 for score in scores)
        or len({round(score, 2) for score in scores}) <= 1
        or any(score > 100 for score in scores)
    )
    if not needs_repair:
        return comparisons

    rank_scores = {1: 86, 2: 74, 3: 62, 4: 50}
    repaired: list[dict[str, Any]] = []
    for item in comparisons:
        rank = int(item.get("rank") or 99)
        score = rank_scores.get(rank, max(35, 90 - rank * 10))
        repaired.append({**item, "relativeFitScore": score})
    return repaired


def _country_evidence_by_code(evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not evidence:
        return {}
    return {
        str(country.get("country") or ""): country
        for country in evidence.get("countries") or []
        if country.get("country")
    }


def _has_direct_country_grounding(country_evidence: dict[str, Any]) -> bool:
    if country_evidence.get("matchedSignals"):
        return True
    if country_evidence.get("matchedContextEvidence"):
        return True
    for row in country_evidence.get("platformEvidence") or []:
        if str(row.get("status") or "").lower() not in {"", "missing", "none"}:
            return True
    return False


def _policy_risk_count(country_evidence: dict[str, Any]) -> int:
    try:
        return int((country_evidence.get("policyRiskSummary") or {}).get("riskCount") or 0)
    except (TypeError, ValueError):
        return 0


def _diagnostics_by_country(evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not evidence:
        return {}
    return {
        str(row.get("country") or ""): row
        for row in evidence.get("contextPackDiagnosticsByCountry") or []
        if row.get("country")
    }


def _ground_ungrounded_country_cards(
    result: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prevent LLM prose from presenting weak evidence as verified market facts."""
    if not evidence:
        return result

    countries = _country_evidence_by_code(evidence)
    diagnostics = _diagnostics_by_country(evidence)
    if not countries:
        return result

    grounded_count = sum(1 for item in countries.values() if _has_direct_country_grounding(item))
    all_weak = grounded_count == 0
    repaired_comparisons: list[dict[str, Any]] = []

    for item in result.get("countryComparisons") or []:
        code = str(item.get("country") or "")
        country_evidence = countries.get(code) or {}
        if not country_evidence or _has_direct_country_grounding(country_evidence):
            repaired_comparisons.append(item)
            continue

        display = _country_display(code)
        risk_count = _policy_risk_count(country_evidence)
        diagnostic = diagnostics.get(code) or {}
        source_count = int(diagnostic.get("contextPackSourceRecordCount") or 0)
        injected_count = int(diagnostic.get("contextPackInjectedRecordCount") or 0)
        repaired = {
            **item,
            "fitLevel": "근거 부족 예비 우선" if int(item.get("rank") or 99) == 1 else "근거 부족 비교 대상",
            "strengths": [
                f"{display}에서 이 작품 신호와 직접 매칭된 컨텍스트 근거는 아직 확인되지 않았습니다.",
                "따라서 이 카드는 국가별 독자 선호나 실적을 확인한 결론이 아니라, 입력 시놉시스와 점검 부담을 기준으로 한 예비 비교입니다.",
                "제목·소개문·태그 초안을 만든 뒤 실제 플랫폼 기준으로 다시 확인해야 합니다.",
            ],
            "risks": [
                "시장 반응, 독자 선호, 유사작 성과를 확인한 근거가 아니므로 확정 추천처럼 해석하면 안 됩니다.",
                "국가별 장르 친화도 표현은 현재 근거만으로 단정하지 않고, 현지화 문구 작성 후 재검토해야 합니다.",
            ],
            "evidenceSummary": [
                "확인된 직접 매칭: 0개",
                f"컨텍스트 직접 주입: {injected_count}건",
                f"정책 점검 후보: {risk_count}개",
                f"참고 컨텍스트 원천: {source_count}건 — 직접 매칭 근거로는 사용되지 않음",
                "해석 수준: 근거 부족 예비 비교",
            ],
        }
        repaired_comparisons.append(repaired)

    out = {**result, "countryComparisons": repaired_comparisons}
    if all_weak:
        story = dict(out.get("storyProfile") or {})
        story["analysisSummary"] = (
            "현재 입력에서는 4개국 모두 직접 매칭 근거가 확인되지 않았습니다. "
            "아래 결과는 국가별 시장 사실을 단정한 것이 아니라, 입력 시놉시스와 정책 점검 부담을 기준으로 한 예비 우선순위입니다."
        )
        out["storyProfile"] = story
        out["confidence"] = "낮음"
        limitations = [
            "국가별 독자 선호, 플랫폼 실적, 유사작 성과를 확인한 결과가 아닙니다.",
            "직접 매칭 근거가 0개이므로 시장 적합도 단정이 아니라 예비 우선순위로만 읽어야 합니다.",
            "제목·소개문·태그·표지 브리프를 만든 뒤 실제 플랫폼 정책과 현지 반응 기준으로 재검토해야 합니다.",
        ]
        for item in out.get("limitations") or []:
            if item not in limitations:
                limitations.append(item)
        out["limitations"] = limitations[:6]
    return out


def _canonicalize_result(
    result: dict[str, Any],
    *,
    evidence_size: int,
    evidence: dict[str, Any] | None = None,
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
    repaired = _ground_ungrounded_country_cards(repaired, evidence)
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
    comparisons = _repair_relative_fit_scores(comparisons)
    out = {
        "mode": "synopsis_country_recommendation",
        "requiresSelection": False,
        "title": "4개국 비교 추천",
        "recommendedCountry": recommended,
        "recommendedCountryDisplay": _country_display(recommended),
        "confidence": repaired["confidence"],
        "storyProfile": repaired["storyProfile"],
        "countryComparisons": comparisons,
        "limitations": repaired["limitations"],
        "recommendationMethod": "llm_country_comparison" if model else "deterministic_country_comparison",
        "llmCountryRecommendationModel": model,
        "llmRecommendationEvidenceBytes": evidence_size,
        "availableCountries": [
            {"country": target["code"], "targetCountry": target["targetCountry"], "displayCountry": target["display"]}
            for target in COUNTRY_COMPARISON_TARGETS
        ],
        "limitation_notice": "4개국 비교 결과입니다.",
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if internal_diagnostics:
        out.update(internal_diagnostics)
    if request_hash:
        out["llmRecommendationRequestHash"] = request_hash
    return out


def _deterministic_comparison(payload: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    supports = _recommendation_support_by_code(payload)
    rows = []
    for target in evidence["countries"]:
        support = supports.get(target["country"], {})
        score = _score_from_support(target, support)
        rows.append((score, target))
    ranked = sorted(rows, key=lambda item: item[0], reverse=True)
    comparisons = []
    for rank, (score, target) in enumerate(ranked, start=1):
        code = target["country"]
        support = supports.get(code, {})
        comparisons.append(
            {
                "country": code,
                "rank": rank,
                "relativeFitScore": score,
                "fitLevel": "상위 적합" if rank == 1 else "비교 적합",
                "strengths": _country_strengths(target, support),
                "risks": _country_risks(target, support),
                "evidenceSummary": _evidence_summary(target, support),
                "localizationDifficulty": "낮음" if score >= 70 else "보통" if score >= 40 else "추가 검토 필요",
            }
        )
    core_signals = _story_core_signals(payload, evidence, supports)
    result = {
        "storyProfile": {
            "title": evidence["story"]["title"],
            "genre": evidence["story"]["genre"],
            "coreSignals": core_signals,
            "analysisSummary": "입력 시놉시스와 장르를 국가별 공개 플랫폼 신호, 컨텍스트 팩, 정책 점검 항목과 대조해 4개국 적합도를 비교했습니다.",
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
        "requiresSelection": False,
        "title": "국가 비교를 완료하지 못했습니다",
        "message": "추천 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        "genre": payload.get("genre") or "",
        "synopsis": payload.get("synopsis") or payload.get("desc") or "",
        "availableCountries": [
            {"country": target["code"], "targetCountry": target["targetCountry"], "displayCountry": target["display"]}
            for target in COUNTRY_COMPARISON_TARGETS
        ],
        "recommendedCountry": None,
        "countryComparisons": [],
        "limitations": [
            "추천 LLM 호출이 실패했습니다.",
            "국가별 비교 결과를 만들지 못했습니다.",
        ],
        "recommendationMethod": "llm_country_comparison_failed",
        "llmCountryRecommendationError": error,
        "llmRecommendationEvidenceBytes": evidence_size,
        "limitation_notice": "추천 결과를 다시 생성해 주세요.",
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
    if not _has_synopsis(payload) and not llm_requested(payload):
        return _canonicalize_result(
            _deterministic_comparison(payload, evidence),
            evidence_size=evidence_size,
            evidence=evidence,
            internal_diagnostics=internal_diagnostics,
        )

    try:
        client, model = _client_and_model(payload)
        system = (
            "당신은 한국어로 국가 추천을 설명하는 도우미다. "
            "반드시 한국어 JSON 객체만 출력하고, 4개국 비교 결과를 균형 있게 제시한다. "
            "제공된 evidence에 없는 시장 선호, 독자 반응, 유사작 성과, 플랫폼 실적을 확인된 사실처럼 쓰면 안 됩니다."
        )
        user = {
            "task": "일본, 중국, 미국/글로벌 영어, 태국 중 적합한 국가를 비교 추천해 주세요.",
            "requirements": [
                "countryComparisons에는 US, CN, JP, TH를 각각 한 번씩 넣으세요.",
                "rank는 1~4를 중복 없이 사용하고, recommendedCountry는 rank 1과 일치해야 합니다.",
                "relativeFitScore는 40~95 사이의 상대 우선순위 점수로 작성하고, 0 또는 네 국가 동일 점수는 쓰지 마세요.",
                "rank 1은 rank 2보다, rank 2는 rank 3보다, rank 3은 rank 4보다 높은 점수를 주세요.",
                "작품 자체를 바꾸는 방향 제안이 아니라, 현재 시놉시스 기준 어느 국가에서 먼저 전달하기 좋은지 설명하세요.",
                "각 국가의 strengths에는 왜 그 국가가 맞거나 덜 맞는지 입력 장르, 시놉시스 신호, 플랫폼/정책 근거 중 최소 2가지를 연결해 구체적으로 쓰세요.",
                "각 국가의 evidenceSummary에는 점수의 근거가 된 신호를 요약하고, '근거를 확인했습니다'처럼 비어 있는 문장만 쓰지 마세요.",
                "직접 매칭이 0개인 경우에도 그대로 장점처럼 쓰지 말고, 어떤 보조 근거로 비교했는지 설명하세요.",
                "직접 매칭 0개 문구는 limitations에서 한 번만 설명하고, 각 국가 카드에서는 시장별 장점과 확인 지점을 중심으로 쓰세요.",
                "evidence에 직접 매칭, 컨텍스트 주입, 정책 점검 후보가 없으면 그 국가는 '근거 부족 예비 비교'로 쓰고 시장 적합을 단정하지 마세요.",
                "국가별 독자 선호, 시장 규모, 플랫폼 성과, 유사작 흥행은 evidence에 없으면 언급하지 마세요.",
                "추론이 필요한 문장은 '입력 시놉시스 기준으로는', '예비적으로는', '추가 확인이 필요합니다'처럼 추론임을 표시하세요.",
                *CREATIVE_BOUNDARY_RULES,
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
            evidence=evidence,
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
