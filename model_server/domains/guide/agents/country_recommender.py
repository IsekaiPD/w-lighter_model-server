from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..engine.policy_analysis import build_policy_attention_report
from ..infra.country_recommendation_html import COMPARISON_WITHHELD_MESSAGE, UNGROUNDED_MARKET_LIMITATION
from ..infra.output_language_guard import repair_user_facing_explanations
from ..retrieval.context_pack import build_context_pack_overlap_report, inspect_context_pack_source
from ..retrieval.tavily_market import build_multi_country_live_market_evidence
from .guide_writer import _client_and_model, llm_requested

LIVE_EVIDENCE_CATEGORY_LABELS = {
    "platform_reference": "플랫폼 정책·운영 기준",
    "genre_trend": "장르·태그 관측",
    "title_synopsis_style": "제목·소개문 관습",
    "reader_hook": "독자 훅·태그 표현",
}


COUNTRY_COMPARISON_TARGETS = [
    {"code": "JP", "targetCountry": "Japan", "market": "japan", "display": "일본"},
    {"code": "CN", "targetCountry": "China", "market": "china", "display": "중국"},
    {"code": "US", "targetCountry": "US/global English", "market": "english", "display": "미국/글로벌 영어"},
    {"code": "TH", "targetCountry": "Thailand", "market": "thailand", "display": "태국"},
]

STORY_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "genre": {"type": "string"},
        "coreSignals": {"type": "array", "items": {"type": "string"}, "minItems": 6, "maxItems": 10},
        "analysisSummary": {"type": "string"},
        "searchTermsByCountry": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "US": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
                "CN": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
                "JP": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
                "TH": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
            },
            "required": ["US", "CN", "JP", "TH"],
        },
    },
    "required": ["title", "genre", "coreSignals", "analysisSummary", "searchTermsByCountry"],
}


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
                "coreSignals": {"type": "array", "items": {"type": "string"}, "minItems": 6, "maxItems": 10},
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
                    "fitLevel": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
                    "risks": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
                    "evidenceSummary": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                    "localizationDifficulty": {"type": "string"},
                },
                "required": [
                    "country",
                    "rank",
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


COUNTRY_EVIDENCE_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "storyProfile": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "genre": {"type": "string"},
                "coreSignals": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 10},
                "analysisSummary": {"type": "string"},
            },
            "required": ["title", "genre", "coreSignals", "analysisSummary"],
        },
        "countryAnalyses": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "country": {"type": "string", "enum": ["US", "CN", "JP", "TH"]},
                    "fitLevel": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
                    "risks": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
                    "evidenceSummary": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                    "localizationDifficulty": {"type": "string"},
                },
                "required": [
                    "country",
                    "fitLevel",
                    "strengths",
                    "risks",
                    "evidenceSummary",
                    "localizationDifficulty",
                ],
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
    },
    "required": ["storyProfile", "countryAnalyses", "limitations"],
}

CREATIVE_BOUNDARY_RULES = [
    "작품 자체를 바꾸는 방향 제안이 아니라 제목, 소개문, 태그, 표지 브리프, 정책 검토 관점에서만 설명하세요.",
    "작품의 플롯, 결말, 캐릭터 성격, 핵심 설정, 장르 방향을 바꾸라고 제안하지 마세요.",
    "현재 시놉시스 기준으로 확인 가능한 정보만 평가하고, 시놉시스에 없는 설정, 장르 비중, 향후 전개, 독자 반응을 임의로 가정하지 마세요.",
    "국가 추천은 작품을 현재 방향 그대로 두고 어느 시장에서 먼저 전달/테스트하기 좋은지 판단하는 것입니다.",
    "strengths와 risks는 창작 수정이 아니라 제목, 소개문, 태그, 표지 브리프, 정책 검토, 독자 기대치 전달 관점으로 작성하세요.",
]

EVIDENCE_ANALYSIS_BOUNDARY_RULES = [
    "작품 자체를 바꾸는 방향 제안이 아니라 제목, 소개문, 태그, 표지 브리프, 정책 검토 관점에서만 설명하세요.",
    "작품의 플롯, 결말, 캐릭터 성격, 핵심 설정, 장르 방향을 바꾸라고 제안하지 마세요.",
    "현재 시놉시스 기준으로 확인 가능한 정보만 평가하고, 시놉시스에 없는 설정, 장르 비중, 향후 전개, 독자 반응을 임의로 가정하지 마세요.",
    "국가별 카드는 추천이 아니라 관측 신호와 현지화 검토 지점을 설명하는 용도입니다.",
    "strengths와 risks는 창작 수정이 아니라 제목, 소개문, 태그, 표지 브리프, 정책 검토, 독자 기대치 전달 관점으로 작성하세요.",
]


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
        rows = [
            row
            for row in (report.get("evidence", {}).get("direct_signal_rows") or [])
            if row.get("match_status") == "direct"
        ]
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
            "inferredSignals": [],
            "matchedEvidence": [],
            "dataUseLimits": source.get("contextPackUseLimits") or [],
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
    direct_rows = [row for row in rows if row.get("match_status") == "direct"]
    inferred_rows = [row for row in rows if row.get("match_status") == "inferred"]
    matched_evidence = [
        {
            "signal": row.get("work_signal"),
            "matchStatus": row.get("match_status"),
            "observedLabel": row.get("observed_label"),
            "candidateLabels": [item.get("label_ko") for item in row.get("candidate_observations") or [] if item.get("label_ko")],
            "count": (row.get("aggregate") or {}).get("count"),
        }
        for row in direct_rows[:5]
    ]
    injected_bytes = _payload_size(matched_evidence) if matched_evidence else 0
    source_count = int(evidence.get("context_record_count") or source.get("contextPackSourceRecordCount") or 0)
    if not source.get("contextPackSourceFound"):
        skip_reason = "source_not_found"
    elif source_count <= 0:
        skip_reason = "no_source_records"
    elif not rows:
        skip_reason = "no_candidate_records"
    elif not direct_rows:
        skip_reason = "no_direct_matches"
    elif not matched_evidence:
        skip_reason = "not_injected"
    else:
        skip_reason = "injected"
    return {
        "contextRecordCount": evidence.get("context_record_count"),
        "matchedSignals": list(dict.fromkeys(row.get("work_signal") for row in direct_rows if row.get("work_signal"))),
        "inferredSignals": list(dict.fromkeys(row.get("work_signal") for row in inferred_rows if row.get("work_signal"))),
        "matchedEvidence": matched_evidence,
        "dataUseLimits": evidence.get("data_limits") or evidence.get("use_limits") or [],
        "diagnostics": {
            "country": target["code"],
            "contextPackRequested": True,
            "contextPackEnabled": True,
            "requestedTargetCountry": target["targetCountry"],
            "resolvedTargetMarket": source.get("resolvedTargetMarket") or evidence.get("target_market"),
            "contextPackSourceFound": bool(source.get("contextPackSourceFound")),
            "contextPackSourceRecordCount": source_count,
            "contextPackCandidateRecordCount": len(rows),
            "contextPackMatchedRecordCount": len(direct_rows),
            "contextPackInjectedRecordCount": len(matched_evidence),
            "contextPackInjectedEvidenceBytes": injected_bytes,
            "contextPackSkipReason": skip_reason,
        },
    }


GENERIC_POLICY_MATCHES = {
    "현대", "로맨스", "판타지", "드라마", "미스터리", "공포", "오컬트", "웹소설",
}

POLICY_STORY_TRIGGERS = {
    "성적": ("성관계", "성적 묘사", "노골적", "강간", "19금", "성인물", "임신"),
    "미성년": ("미성년", "아동", "소년", "소녀", "학생", "열두 살", "16세", "십대"),
    "폭력": ("폭력", "살인", "사망", "유혈", "전투", "재난", "죽음", "시체", "괴이"),
    "자해": ("자살", "자해", "극단적 선택"),
    "종교": ("신", "산신", "무당", "신령", "신당", "귀문", "제사", "종교", "민속"),
    "범죄": ("범죄", "비리", "불법", "사기", "살인", "실종", "납치", "수사"),
    "정치": ("정치", "정부", "국가", "시장 후보", "공공기관", "행정", "서울시"),
    "혐오": ("혐오", "차별", "인종", "민족"),
}


def _story_policy_text(payload: dict[str, Any], story_profile: dict[str, Any] | None) -> str:
    profile = story_profile or {}
    values = [
        payload.get("title"), payload.get("genre"), payload.get("synopsis") or payload.get("desc"),
        profile.get("genre"), profile.get("analysisSummary"), *(profile.get("coreSignals") or []),
    ]
    return " ".join(str(value) for value in values if value).lower()


POLICY_MESSAGE_TRIGGERS = {
    "성적": ("성적", "성관계", "노골적", "음란", "강간", "성인"),
    "미성년": ("미성년", "아동", "청소년", "학생", "연령"),
    "폭력": ("폭력", "살인", "유혈", "잔혹", "사망", "시체"),
    "자해": ("자해", "자살", "극단적 선택"),
    "종교": ("종교", "신앙", "무속", "신령", "제사", "민속"),
    "범죄": ("범죄", "불법", "사기", "납치", "수사", "모방"),
    "정치": ("정치", "국가", "정부", "공공기관", "역사", "지도자"),
    "혐오": ("혐오", "차별", "인종", "민족", "비하"),
}


POLICY_CATEGORY_LABELS = {
    "성적": "성적 콘텐츠",
    "미성년": "미성년자 보호",
    "폭력": "폭력·사망 묘사",
    "자해": "자해·자살 묘사",
    "종교": "종교·민속 표현",
    "범죄": "범죄·불법 행위",
    "정치": "정치·공공기관 표현",
    "혐오": "혐오·차별 표현",
}

POLICY_CATEGORY_MESSAGES = {
    "성적": "성적 표현의 수위와 연령 등급, 소개문·표지의 노골적 표현 여부를 확인하세요.",
    "미성년": "미성년 인물의 피해·사망·관계 묘사와 연령 등급 표시를 확인하세요.",
    "폭력": "실종·사망·괴이 사건의 폭력 수위와 표지·소개문에서의 자극적 표현을 확인하세요.",
    "자해": "자기희생이나 죽음 선택이 자해·자살을 미화하는 표현으로 읽히지 않는지 확인하세요.",
    "종교": "산신·무당·신당·귀문 같은 민속 요소가 특정 신앙을 비하하거나 사실로 단정되지 않는지 확인하세요.",
    "범죄": "범죄·비리·실종 사건을 홍보문에서 모방 가능한 절차로 지나치게 구체화하지 않는지 확인하세요.",
    "정치": "공공기관·도시개발 비리와 정치적 인물 묘사의 현지 민감도를 확인하세요.",
    "혐오": "특정 집단을 일반화하거나 비하하는 표현이 없는지 확인하세요.",
}


def _relevant_policy_categories(card: dict[str, Any], story_text: str) -> list[str]:
    title = str(card.get("card_title") or "")
    message_text = " ".join(
        str(card.get(key) or "")
        for key in ("guide_message_ko", "display_sentence", "rule_summary_ko")
    ).lower()
    matched = [str(item).strip() for item in card.get("matched_elements") or [] if str(item).strip()]
    meaningful = [item for item in matched if item not in GENERIC_POLICY_MATCHES]
    if not meaningful:
        return []
    if not any(term.lower() in message_text for term in meaningful):
        return []

    categories: list[str] = []
    for category, triggers in POLICY_STORY_TRIGGERS.items():
        if category not in title:
            continue
        if not any(trigger.lower() in story_text for trigger in triggers):
            continue
        message_triggers = POLICY_MESSAGE_TRIGGERS.get(category) or ()
        if not any(trigger.lower() in message_text for trigger in message_triggers):
            continue
        categories.append(category)
    return categories






def _policy_summary(payload: dict[str, Any], target: dict[str, str], story_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    report = build_policy_attention_report({**payload, "targetCountry": target["code"]})
    raw_cards = report.get("policy_attention_cards") or []
    story_text = _story_policy_text(payload, story_profile)
    categories: dict[str, dict[str, Any]] = {}
    for card in raw_cards:
        for category in _relevant_policy_categories(card, story_text):
            row = categories.setdefault(
                category,
                {
                    "title": POLICY_CATEGORY_LABELS[category],
                    "status": card.get("status_label") or "게시 전 확인",
                    "message": POLICY_CATEGORY_MESSAGES[category],
                    "sources": [],
                },
            )
            for source in card.get("source_refs") or []:
                if source not in row["sources"]:
                    row["sources"].append(source)
    risks = list(categories.values())[:3]
    return {
        "riskCount": len(risks),
        "rawRiskCount": len(raw_cards),
        "risks": risks,
        "limitations": report.get("policy_limitations") or [],
    }


def build_country_recommendation_evidence(
    payload: dict[str, Any],
    *,
    story_profile: dict[str, Any] | None = None,
    live_market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    include_context_pack = _include_context_pack(payload)
    top_evidence = _top_evidence_by_country(payload) if include_context_pack else {}
    live_market = live_market or {}
    live_countries = live_market.get("countries") or {}
    countries = []
    diagnostics = []
    for target in COUNTRY_COMPARISON_TARGETS:
        context = _context_match_summary(payload, target, include_context_pack=include_context_pack)
        policy = _policy_summary(payload, target, story_profile)
        live = dict(live_countries.get(target["code"]) or {})
        diagnostics.append(context["diagnostics"])
        countries.append(
            {
                "country": target["code"],
                "targetCountry": target["targetCountry"],
                "displayCountry": target["display"],
                "liveMarketEvidence": live,
                "platformEvidence": top_evidence.get(target["code"], [])[:5],
                "matchedSignals": context["matchedSignals"],
                "inferredSignals": context.get("inferredSignals") or [],
                "matchedContextEvidence": context["matchedEvidence"],
                "dataUseLimits": context.get("dataUseLimits") or [],
                "policyRiskSummary": policy,
            }
        )
    profile = dict(story_profile or {})
    profile.setdefault("title", payload.get("title") or payload.get("workTitle") or "입력 작품")
    profile.setdefault("genre", payload.get("genre") or "장르 미입력")
    profile.setdefault("coreSignals", [])
    profile.setdefault("analysisSummary", "")
    return {
        "story": {
            "title": profile["title"],
            "genre": profile["genre"],
            "synopsis": payload.get("synopsis") or payload.get("desc") or "",
        },
        "storyProfile": profile,
        "countries": countries,
        "liveMarket": {
            "used": bool(live_market.get("liveMarketUsed")),
            "enabled": bool(live_market.get("liveMarketEnabled")),
            "skipReason": live_market.get("liveMarketSkipReason"),
            "resultCount": int(live_market.get("liveMarketResultCount") or 0),
            "injectedCount": int(live_market.get("liveMarketInjectedCount") or 0),
            "recommendationAllowed": bool(live_market.get("recommendationAllowed")),
            "limitations": live_market.get("limitations") or [],
        },
        "contextPackDiagnosticsByCountry": diagnostics,
        "comparisonRule": "context pack 기반으로 4개국을 항상 분석하며, Tavily 최신 근거가 있으면 보조로 활용합니다.",
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




def _score_from_support(target: dict[str, Any], support: dict[str, Any]) -> int:
    """Deprecated compatibility helper for legacy tests/imports.

    The Tavily-grounded production path does not call this helper and does not
    expose a numeric country-fit score. The old calculation remains available
    only so existing integrations can migrate without import errors.
    """
    matched = len(target.get("matchedSignals") or [])
    platform = len(target.get("platformEvidence") or [])
    try:
        risk = int((target.get("policyRiskSummary") or {}).get("riskCount") or 0)
    except (TypeError, ValueError):
        risk = 0
    try:
        normalized = float(support.get("normalizedScore") or 0)
    except (TypeError, ValueError):
        normalized = 0.0
    if normalized > 0:
        try:
            rank_index = int(support.get("rankIndex") or 1)
        except (TypeError, ValueError):
            rank_index = 1
        rank_penalty = max(0, rank_index - 1) * 4
        return max(18, min(95, int(round(34 + normalized * 56 + matched * 5 + min(platform, 5) * 2 - risk * 2 - rank_penalty))))
    return max(10, min(45, 24 + matched * 8 + min(platform, 5) * 2 - risk * 2))


def _repair_relative_fit_scores(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deprecated compatibility helper for legacy imports/tests.

    The current Tavily-grounded user flow never calls this function and never
    exposes ``relativeFitScore``. It retains the former deterministic repair
    semantics solely so downstream test modules and integrations do not fail at
    import time while migrating to the score-free contract.
    """
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
        try:
            rank = int(item.get("rank") or 99)
        except (TypeError, ValueError):
            rank = 99
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















def _normalize_country_analysis_model_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy rank/recommendation fixtures into the four-country analysis schema.

    The current model contract is countryAnalyses. countryComparisons is accepted
    only as an input compatibility shape and is never treated as the internal
    canonical representation.
    """
    if result.get("countryAnalyses"):
        return result

    legacy = result.get("countryComparisons") or []
    if not legacy:
        return result

    analyses: list[dict[str, Any]] = []
    legacy_ranking_terms = ("추천", "우선", "순위", "상위", "비교")
    for item in legacy:
        legacy_fit_level = str(item.get("fitLevel") or "").strip()
        neutral_fit_level = (
            "적합 요소와 주의 요소 확인"
            if any(term in legacy_fit_level for term in legacy_ranking_terms)
            else (legacy_fit_level or "추가 확인 필요")
        )
        analyses.append(
            {
                "country": item.get("country"),
                "fitLevel": neutral_fit_level,
                "strengths": list(item.get("strengths") or ["작품 신호와 공개 자료의 연결 여부를 추가 확인해야 합니다."])[:2],
                "risks": list(item.get("risks") or ["현지화 과정에서 문화적 전달 방식과 플랫폼 정책을 확인해야 합니다."])[:2],
                "evidenceSummary": list(item.get("evidenceSummary") or ["기존 비교 결과를 국가별 독립 분석 형식으로 변환했습니다."])[:3],
                "localizationDifficulty": item.get("localizationDifficulty") or "추가 확인 필요",
            }
        )

    return {
        "storyProfile": result.get("storyProfile") or {},
        "countryAnalyses": analyses,
        "limitations": list(result.get("limitations") or [UNGROUNDED_MARKET_LIMITATION]),
    }


def _validate_evidence_analysis_result(result: dict[str, Any]) -> None:
    analyses = result.get("countryAnalyses") or []
    countries = [item.get("country") for item in analyses]
    if sorted(countries) != ["CN", "JP", "TH", "US"]:
        raise ValueError("countryAnalyses must contain US, CN, JP, TH exactly once")


def _dedupe_texts(values: list[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


UNGROUNDED_MARKET_CLAIM_TERMS = (
    "독자",
    "선호",
    "플랫폼 실적",
    "시장 성과",
    "시장 적합",
    "시장 fit",
    "market fit",
    "흥행",
    "인기",
    "유리",
    "익숙",
    "성과",
    "prefer",
    "market",
)


def _has_market_claim(values: list[Any]) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(term.lower() in text for term in UNGROUNDED_MARKET_CLAIM_TERMS)


def _canonicalize_country_analysis_result(
    result: dict[str, Any],
    *,
    evidence_size: int,
    evidence: dict[str, Any],
    model: str,
    internal_diagnostics: dict[str, Any] | None = None,
    request_hash: str | None = None,
) -> dict[str, Any]:
    """Expose four independent, source-grounded country analyses without ranking or a winner."""
    result = _normalize_country_analysis_model_result(result)
    _validate_evidence_analysis_result(result)
    repaired = repair_user_facing_explanations(result)
    _validate_evidence_analysis_result(repaired)

    analyses = {str(item.get("country") or ""): item for item in repaired.get("countryAnalyses") or []}
    countries = _country_evidence_by_code(evidence)
    country_analyses: list[dict[str, Any]] = []

    for target in COUNTRY_COMPARISON_TARGETS:
        code = target["code"]
        model_item = analyses.get(code) or {}
        country = countries.get(code) or {}
        live = _live_country_payload(country)
        sources = _live_sources(country)
        evidence_level = str(live.get("evidenceLevel") or "없음")
        trusted = int(live.get("trustedCount") or 0)
        reference = int(live.get("referenceCount") or 0)
        categories = [
            LIVE_EVIDENCE_CATEGORY_LABELS.get(str(item), str(item))
            for item in live.get("categoriesCovered") or []
            if str(item).strip()
        ]

        strengths = _dedupe_texts(list(model_item.get("strengths") or []), limit=2)
        fit_level = str(model_item.get("fitLevel") or "분석 결과 참고")
        if sources:
            evidence_summary = [
                f"최신 공개 근거 {len(sources)}건 확인 (공식·플랫폼 {trusted}건, 참고 {reference}건)",
                f"확인 범위: {', '.join(categories) if categories else '플랫폼·장르 공개 자료'}",
            ]
        else:
            platform_count = len(country.get("platformEvidence") or [])
            matched_count = len(country.get("matchedSignals") or [])
            if platform_count or matched_count:
                evidence_summary = [
                    f"플랫폼 관측 자료 {platform_count}건 · 작품 신호 {matched_count}건 활용",
                    "Tavily 최신 웹 근거 없음 — context pack 기반 분석",
                ]
            else:
                evidence_summary = ["외부 검색 근거 없음 — 작품 프로필 및 장르 기반 분석"]

        policy_risks = [
            str(item.get("message") or item.get("title"))
            for item in (country.get("policyRiskSummary") or {}).get("risks") or []
            if item.get("message") or item.get("title")
        ]
        risks = _dedupe_texts([*(model_item.get("risks") or []), *policy_risks], limit=2)
        if not risks:
            risks = ["국가를 선택한 뒤 최신 플랫폼 정책과 문화적 전달 방식을 별도로 확인해야 합니다."]

        country_analyses.append(
            {
                "country": code,
                "displayCountry": target["display"],
                "targetCountry": target["targetCountry"],
                "rank": None,
                "assessment": "viable_with_cautions",
                "fitLevel": fit_level,
                "evidenceLevel": evidence_level,
                "strengths": strengths,
                "risks": risks,
                "evidenceSummary": evidence_summary,
                "liveEvidence": sources,
                "localizationDifficulty": str(model_item.get("localizationDifficulty") or "추가 확인 필요"),
            }
        )

    live = evidence.get("liveMarket") or {}
    skip_reason = str(live.get("skipReason") or "")
    if skip_reason == "missing_api_key":
        message = "Tavily API 키가 없어 최신 공개 근거를 수집하지 못했습니다. 작품 분석과 보유 자료를 기준으로 4개국의 확인점을 정리했습니다."
    elif skip_reason == "disabled":
        message = "실시간 시장 근거 수집이 비활성화되어 보유 자료를 기준으로 4개국의 적합 요소와 주의 요소를 정리했습니다."
    elif not live.get("used"):
        message = "신뢰 가능한 최신 공개 근거가 제한적이므로 국가별 판단 범위와 추가 확인점을 함께 표시했습니다."
    else:
        message = "현재 시놉시스와 국가별 공개 관측 자료를 바탕으로 4개국의 적합 요소와 주의 요소를 각각 분석했습니다."

    limitations = _dedupe_texts(
        [
            *(live.get("limitations") or []),
            *(repaired.get("limitations") or []),
            UNGROUNDED_MARKET_LIMITATION,
        ],
        limit=4,
    )
    out = {
        "mode": "synopsis_country_analysis",
        "requiresSelection": False,
        "analysisStatus": "completed",
        "recommendationStatus": "analyzed",
        "title": "4개국 현지화 적합성 분석",
        "message": message,
        "recommendedCountry": None,
        "recommendedCountryDisplay": None,
        "confidence": "국가별 근거 수준 참조",
        "storyProfile": _public_story_profile(evidence.get("storyProfile") or repaired.get("storyProfile") or {}),
        "countryAnalyses": country_analyses,
        # Temporary public compatibility alias. Internal code uses countryAnalyses.
        "countryComparisons": country_analyses,
        "limitations": limitations,
        "recommendationMethod": "llm_tavily_country_analysis",
        "llmCountryRecommendationModel": model,
        "llmRecommendationEvidenceBytes": evidence_size,
        "availableCountries": [
            {"country": target["code"], "targetCountry": target["targetCountry"], "displayCountry": target["display"]}
            for target in COUNTRY_COMPARISON_TARGETS
        ],
        "limitation_notice": "국가별 분석은 현재 시놉시스와 확인 가능한 공개 자료를 기준으로 한 참고 결과입니다.",
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        **_live_meta(evidence),
    }
    if internal_diagnostics:
        out.update(internal_diagnostics)
    if request_hash:
        out["llmRecommendationRequestHash"] = request_hash
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
    _validate_country_result(repaired)
    evidence = evidence or {}
    countries = _country_evidence_by_code(evidence)
    recommended = str(repaired["recommendedCountry"])
    comparisons: list[dict[str, Any]] = []
    source_comparisons = list(repaired["countryComparisons"])
    removed_ungrounded_market_claim = False
    # Legacy tests/integrations may still submit relativeFitScore. Repair it
    # internally for compatibility, but the current LLM schema never emits it
    # and public shaping/HTML do not expose it.
    if any("relativeFitScore" in item for item in source_comparisons):
        source_comparisons = _repair_relative_fit_scores(source_comparisons)

    for item in source_comparisons:
        code = str(item["country"])
        country = countries.get(code) or {}
        live = _live_country_payload(country)
        sources = _live_sources(country)
        trusted = int(live.get("trustedCount") or 0)
        reference = int(live.get("referenceCount") or 0)
        categories = [
            LIVE_EVIDENCE_CATEGORY_LABELS.get(str(value), str(value))
            for value in live.get("categoriesCovered") or []
            if str(value).strip()
        ]
        if sources:
            source_summary = [
                f"최신 공개 근거 {len(sources)}건 확인 (공식·플랫폼 {trusted}건, 참고 {reference}건)",
                f"확인 범위: {', '.join(categories) if categories else '플랫폼·장르 공개 자료'}",
            ]
            strengths = _dedupe_texts(item.get("strengths") or [], limit=2)
        else:
            display = _country_display(code)
            removed_ungrounded_market_claim = removed_ungrounded_market_claim or _has_market_claim(
                [
                    item.get("fitLevel"),
                    *(item.get("strengths") or []),
                    *(item.get("evidenceSummary") or []),
                ]
            )
            source_summary = [
                f"{display}에서 이 작품 신호와 직접 매칭된 컨텍스트 근거는 아직 확인되지 않았습니다.",
                "최신 공개 출처가 없어 독자 선호나 시장 적합도를 판단하지 않았습니다.",
                "해석 수준: 근거 부족 예비 비교",
            ]
            strengths = list(source_summary)
        policy_risks = [
            str(value.get("message") or value.get("title"))
            for value in (country.get("policyRiskSummary") or {}).get("risks") or []
            if value.get("message") or value.get("title")
        ]
        comparisons.append(
            {
                **item,
                "displayCountry": _country_display(code),
                "targetCountry": COUNTRY_COMPARISON_TARGETS[[t["code"] for t in COUNTRY_COMPARISON_TARGETS].index(code)]["targetCountry"],
                "evidenceLevel": str(live.get("evidenceLevel") or "제한적"),
                "strengths": strengths,
                "evidenceSummary": _dedupe_texts([*source_summary, *(item.get("evidenceSummary") or [])], limit=3),
                "risks": _dedupe_texts([*(item.get("risks") or []), *policy_risks], limit=2),
                "liveEvidence": sources,
            }
        )

    live = evidence.get("liveMarket") or {}
    limitation_values = [*(live.get("limitations") or []), *(repaired.get("limitations") or [])]
    if removed_ungrounded_market_claim and UNGROUNDED_MARKET_LIMITATION not in limitation_values:
        limitation_values = [UNGROUNDED_MARKET_LIMITATION, *limitation_values]
    limitations = _dedupe_texts(
        limitation_values,
        limit=4,
    )
    out = {
        "mode": "synopsis_country_recommendation",
        "requiresSelection": False,
        "recommendationStatus": "recommended",
        "title": "4개국 공개 근거 비교",
        "message": "작품 분석 후 4개국의 최신 공개 플랫폼·정책 근거를 검색하고, 확인된 범위에서 우선 검토 순서를 정리했습니다.",
        "recommendedCountry": recommended,
        "recommendedCountryDisplay": _country_display(recommended),
        "confidence": (
            "낮음"
            if comparisons and all(not item.get("liveEvidence") for item in comparisons)
            else repaired["confidence"]
        ),
        "storyProfile": _public_story_profile(evidence.get("storyProfile") or repaired["storyProfile"]),
        "countryComparisons": comparisons,
        "limitations": limitations,
        "recommendationMethod": "llm_tavily_country_comparison",
        "llmCountryRecommendationModel": model,
        "llmRecommendationEvidenceBytes": evidence_size,
        "availableCountries": [
            {"country": target["code"], "targetCountry": target["targetCountry"], "displayCountry": target["display"]}
            for target in COUNTRY_COMPARISON_TARGETS
        ],
        "limitation_notice": "우선 검토 순서는 최신 공개 근거를 바탕으로 한 편집 검토 결과이며 흥행 확률이 아닙니다.",
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        **_live_meta(evidence),
    }
    if internal_diagnostics:
        out.update(internal_diagnostics)
    if request_hash:
        out["llmRecommendationRequestHash"] = request_hash
    return out




def _manual_selection_fallback(
    payload: dict[str, Any],
    *,
    error: str,
    evidence_size: int,
    internal_diagnostics: dict[str, Any] | None = None,
    request_hash: str | None = None,
) -> dict[str, Any]:
    out = {
        "mode": "synopsis_country_analysis",
        "requiresSelection": False,
        "analysisStatus": "generation_failed",
        "recommendationStatus": "generation_failed",
        "title": "국가 비교를 완료하지 못했습니다",
        "message": "추천 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        "genre": payload.get("genre") or "",
        "synopsis": payload.get("synopsis") or payload.get("desc") or "",
        "availableCountries": [
            {"country": target["code"], "targetCountry": target["targetCountry"], "displayCountry": target["display"]}
            for target in COUNTRY_COMPARISON_TARGETS
        ],
        "recommendedCountry": None,
        "countryAnalyses": [],
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




def _generate_story_profile(
    payload: dict[str, Any],
    *,
    client: Any,
    model: str,
) -> tuple[dict[str, Any], str]:
    system = (
        "당신은 한국 웹소설 시놉시스를 정밀하게 분석하는 편집자다. "
        "반드시 한국어 JSON 객체만 출력하고, 입력에 없는 설정이나 시장 정보를 추가하지 않는다."
    )
    user = {
        "task": "국가별 웹 근거를 검색하기 전에 작품의 검색 가능한 핵심 프로필을 작성해 주세요.",
        "requirements": [
            "title은 입력 제목을 유지하세요.",
            "genre는 시놉시스 전체를 읽고 3~6개의 복합 장르를 한 줄로 정리하세요.",
            "coreSignals는 검색어로 사용할 수 있을 만큼 구체적인 관계·사건·문화·정서 신호 6~10개를 작성하세요.",
            "analysisSummary는 주인공, 핵심 갈등, 감정선, 차별점을 연결한 한 문단으로 작성하세요.",
            "searchTermsByCountry는 국가별 웹 검색용 핵심어를 작성하세요. US는 영어, JP는 일본어, CN은 중국어 간체, TH는 태국어를 사용하세요.",
            "검색어는 작품의 장르·관계·문화 소재를 나타내는 짧은 구문이어야 하며 인기나 흥행을 사실처럼 전제하지 마세요.",
            "국가 적합도, 독자 선호, 흥행 가능성은 아직 판단하지 마세요.",
        ],
        "input": {
            "title": payload.get("title") or payload.get("workTitle") or "입력 작품",
            "genre": payload.get("genre") or "",
            "synopsis": payload.get("synopsis") or payload.get("desc") or "",
        },
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
                "name": "guide_story_profile",
                "schema": STORY_PROFILE_SCHEMA,
                "strict": True,
            }
        },
    )
    profile = json.loads(response.output_text)
    profile["title"] = payload.get("title") or payload.get("workTitle") or profile.get("title") or "입력 작품"
    profile["coreSignals"] = _dedupe_texts(list(profile.get("coreSignals") or []), limit=10)
    search_terms = profile.get("searchTermsByCountry") or {}
    profile["searchTermsByCountry"] = {
        code: _dedupe_texts(list(search_terms.get(code) or []), limit=6)
        for code in ("US", "CN", "JP", "TH")
    }
    return profile, request_hash


def _public_story_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = profile or {}
    return {
        "title": profile.get("title") or "입력 작품",
        "genre": profile.get("genre") or "장르 미입력",
        "coreSignals": list(profile.get("coreSignals") or [])[:10],
        "analysisSummary": profile.get("analysisSummary") or "",
    }


def _live_country_payload(country_evidence: dict[str, Any]) -> dict[str, Any]:
    return dict(country_evidence.get("liveMarketEvidence") or {})


def _live_sources(country_evidence: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    live = _live_country_payload(country_evidence)
    return [dict(item) for item in (live.get("items") or [])[:limit]]


def _live_meta(evidence: dict[str, Any]) -> dict[str, Any]:
    live = evidence.get("liveMarket") or {}
    return {
        "liveMarketUsed": bool(live.get("used")),
        "liveMarketEnabled": bool(live.get("enabled")),
        "liveMarketSkipReason": live.get("skipReason"),
        "liveMarketResultCount": int(live.get("resultCount") or 0),
        "liveMarketInjectedCount": int(live.get("injectedCount") or 0),
    }


def generate_country_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze all four target countries without exposing scores, ranks, or a single winner."""
    request_hash: str | None = None
    evidence_size = 0
    internal_diagnostics: dict[str, Any] | None = None
    try:
        client, model = _client_and_model(payload)
        story_profile, profile_request_hash = _generate_story_profile(payload, client=client, model=model)
        live_market = build_multi_country_live_market_evidence(payload, story_profile)
        evidence = build_country_recommendation_evidence(
            payload,
            story_profile=story_profile,
            live_market=live_market,
        )
        evidence_size = _evidence_size(evidence)
        internal_diagnostics = _aggregate_context_pack_diagnostics(evidence, payload) if _include_internal(payload) else None

        system = (
            "당신은 한국 웹소설의 해외 현지화 적합성을 분석하는 편집자다. "
            "반드시 한국어 JSON 객체만 출력한다. 하나의 국가를 추천하거나 순위를 만들지 말고, "
            "미국/글로벌 영어, 중국, 일본, 태국을 각각 독립적으로 분석한다. "
            "platformEvidence·matchedSignals·matchedContextEvidence(context pack)를 주 근거로 사용하고, "
            "liveMarketEvidence(Tavily)가 있으면 보조 근거로 추가 활용한다. "
            "시장 규모, 흥행 확률, 독자 선호를 근거 없이 단정하지 않는다."
        )
        user = {
            "task": "현재 시놉시스를 기준으로 4개국 각각의 적합 요소, 주의 요소, 근거 범위와 현지화 난이도를 분석해 주세요.",
            "storyProfile": story_profile,
            "requirements": [
                "storyProfile은 제공된 값을 그대로 유지하세요.",
                "countryAnalyses에는 US, CN, JP, TH를 각각 한 번씩 넣으세요.",
                "국가 간 순위, 우승 국가, 추천 국가, 숫자 점수, 성공 확률을 만들지 마세요.",
                "fitLevel은 적합 신호가 뚜렷함, 가능성이 있으나 주의 필요, 적합 신호가 제한적임, 자료 부족으로 판단 보류 중 하나의 취지로 작성하세요.",
                "각 국가의 strengths는 작품의 핵심 소재 신호 중 구체적인 신호를 최소 1개 직접 언급하고, 그 신호가 장르·태그·제목·소개문 관측과 어떻게 연결되는지 최대 2개로 작성하세요.",
                "현대 판타지, 로맨스처럼 장르명만 반복하는 일반론은 피하고, 민원·공무원 조직·산신·무당·재개발·실종 가족 등 해당 작품에 실제로 있는 고유 소재를 중심으로 작성하세요.",
                "플랫폼 정책·운영 기준은 게시 가능 여부와 주의점의 근거일 뿐 작품 적합성의 근거로 사용하지 마세요.",
                "각 국가의 risks는 작품의 구체 문화·제도·민속 신호와 연결된 현지화 부담, 문화적 전달 문제, 관련 정책 확인점을 최대 2개로 작성하세요.",
                "플랫폼 관측 자료(platformEvidence)·작품 신호 매칭(matchedSignals·matchedContextEvidence)을 주 근거로 분석하고, 최신 웹 검색 결과(liveMarketEvidence)가 있으면 보조 근거로 추가 활용하세요. 이 필드명들은 분석 텍스트에 직접 노출하지 마세요.",
                "최신 웹 검색 결과가 없어도 플랫폼 관측 자료를 기반으로 각 국가의 적합 요소와 주의 요소를 반드시 작성하세요.",
                "근거 범위 요약에는 어떤 종류의 공개 자료를 확인했는지와 근거의 한계를 함께 적으세요.",
                "context pack은 플랫폼 순위·장르 관측 기반의 정제된 자료이며 주요 근거로 활용하되, 실제 흥행 확률이나 독자 반응의 단정적 표현은 피하세요.",
                *EVIDENCE_ANALYSIS_BOUNDARY_RULES,
                "설명은 모두 한국어로 작성하세요.",
            ],
            "evidence": evidence,
        }
        request_hash = _stable_hash({"profileRequestHash": profile_request_hash, "system": system, "user": user})
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "llm_tavily_country_analysis",
                    "schema": COUNTRY_EVIDENCE_ANALYSIS_SCHEMA,
                    "strict": True,
                }
            },
        )
        result = json.loads(response.output_text)
        result["storyProfile"] = story_profile
        return _canonicalize_country_analysis_result(
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
            request_hash=request_hash,
        )


__all__ = [
    "_repair_relative_fit_scores",
    "_score_from_support",
    "build_country_recommendation_evidence",
    "generate_country_recommendation",
    "llm_requested",
]
