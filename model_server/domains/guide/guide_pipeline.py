"""Online localization guide pipeline composition."""

from __future__ import annotations

import json
import os
from typing import Any

from .agents.country_recommender import generate_country_recommendation
from .agents.guide_writer import generate_genre_signals, generate_llm_guide, llm_requested
from .engine.policy_analysis import build_policy_attention_payload
from .engine.recommendation import build_localization_advice
from .infra.country_recommendation_html import render_country_recommendation_html
from .retrieval.context_pack import build_context_pack_overlap_report, inspect_context_pack_source, resolve_context_market
from .retrieval.tavily_market import build_live_market_evidence


PIPELINE_MARKET_ALIASES = {
    "japan": "japan",
    "jp": "japan",
    "us": "english",
    "en": "english",
    "usa": "english",
    "english": "english",
    "global english": "english",
    "us/global english": "english",
    "china": "china",
    "cn": "china",
    "thailand": "thailand",
    "th": "thailand",
}


GUIDE_PUBLIC_KEYS = {
    "mode",
    "generationMode",
    "requiresSelection",
    "recommendationStatus",
    "title",
    "targetCountry",
    "targetCountryDisplay",
    "displayCountry",
    "country",
    "htmlReport",
    "llmGeneratedGuide",
    "message",
    "reportMode",
    "recommendedCountry",
    "recommendedCountryDisplay",
}

RECOMMENDATION_PUBLIC_KEYS = {
    "mode",
    "reportMode",
    "generationMode",
    "requiresSelection",
    "recommendationStatus",
    "title",
    "htmlReport",
    "genre",
    "synopsis",
    "message",
    "recommendedCountry",
    "recommendedCountryDisplay",
    "countryComparisons",
    "countryAnalyses",
    "availableCountries",
    "limitations",
    "limitation_notice",
    "confidence",
    "storyProfile",
    "recommendationMethod",
    "liveMarketUsed",
    "liveMarketEnabled",
    "liveMarketSkipReason",
    "liveMarketResultCount",
    "liveMarketInjectedCount",
    "createdAt",
}

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


def _target_market(payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    raw = (
        payload.get("target_market")
        or payload.get("targetMarket")
        or payload.get("country")
        or payload.get("targetCountry")
        or payload.get("target_country")
        or result.get("targetCountry")
        or result.get("country")
    )
    if not raw:
        return None
    text = str(raw).strip()
    return PIPELINE_MARKET_ALIASES.get(text.lower()) or PIPELINE_MARKET_ALIASES.get(text) or resolve_context_market(text)


def _list_field(payload: dict[str, Any], *keys: str) -> list[str]:
    raw = None
    for key in keys:
        if key in payload:
            raw = payload.get(key)
            break
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [part.strip() for chunk in raw.split("\n") for part in chunk.split(",")]
    else:
        items = [str(item).strip() for item in raw if item]
    return list(dict.fromkeys(item for item in items if item))


def _declared_signals(payload: dict[str, Any]) -> list[str]:
    return _list_field(payload, "declaredSignals", "declared_signals", "signals")


def _requested_target_country(payload: dict[str, Any], result: dict[str, Any] | None = None) -> str | None:
    result = result or {}
    raw = (
        payload.get("targetCountry")
        or payload.get("target_country")
        or payload.get("targetMarket")
        or payload.get("target_market")
        or payload.get("country")
        or result.get("targetCountry")
        or result.get("country")
    )
    return str(raw).strip() if raw else None


def _has_synopsis(payload: dict[str, Any]) -> bool:
    return bool(str(payload.get("synopsis") or payload.get("desc") or "").strip())


def _guide_report_mode(payload: dict[str, Any]) -> str:
    if _has_synopsis(payload):
        return "synopsis_country_recommendation"
    return "country_genre_guide"


def _attach_live_market_evidence(payload: dict[str, Any], result: dict[str, Any], *, report_mode: str) -> dict[str, Any]:
    evidence = build_live_market_evidence(payload, result, report_mode=report_mode)
    enriched = dict(result)
    if evidence.get("liveMarketEvidence"):
        enriched["liveMarketEvidence"] = evidence["liveMarketEvidence"]
    enriched["liveMarketRequested"] = evidence.get("liveMarketRequested")
    enriched["liveMarketEnabled"] = evidence.get("liveMarketEnabled")
    enriched["liveMarketUsed"] = evidence.get("liveMarketUsed")
    enriched["liveMarketCountry"] = evidence.get("liveMarketCountry")
    enriched["liveMarketResultCount"] = evidence.get("liveMarketResultCount")
    enriched["liveMarketInjectedCount"] = evidence.get("liveMarketInjectedCount")
    enriched["liveMarketSkipReason"] = evidence.get("liveMarketSkipReason")
    return enriched


def _include_context_pack(payload: dict[str, Any]) -> bool:
    if "includeContextPack" in payload:
        return _truthy_flag(payload.get("includeContextPack"), default=True)
    if "include_context_pack" in payload:
        return _truthy_flag(payload.get("include_context_pack"), default=True)
    return _truthy_flag(os.getenv("WLIGHTER_GUIDE_CONTEXT_PACK"), default=True)


def _include_internal(_payload: dict[str, Any]) -> bool:
    return _truthy_flag(os.getenv("WLIGHTER_GUIDE_INCLUDE_INTERNAL"), default=False)


def _html_report(result: dict[str, Any]) -> Any:
    return result.get("htmlReport")


def _shape_guide_response(_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    public = {key: result[key] for key in GUIDE_PUBLIC_KEYS if key in result and result[key] is not None}
    html_report = _html_report(result)
    if html_report:
        public["htmlReport"] = html_report
    public.setdefault("requiresSelection", bool(result.get("requiresSelection", False)))
    public.setdefault("generationMode", result.get("generationMode") or "deterministic_guide")
    return public


def _shape_recommendation_response(_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    nullable_public_keys = {"recommendedCountry", "recommendedCountryDisplay"}
    public = {
        key: result[key]
        for key in RECOMMENDATION_PUBLIC_KEYS
        if key in result and (result[key] is not None or key in nullable_public_keys)
    }
    public.setdefault("requiresSelection", bool(result.get("requiresSelection", True)))
    public.setdefault("generationMode", result.get("generationMode") or "recommendation_only")
    return public


def _context_pack_requested_signals(
    payload: dict[str, Any],
    title_elements: list[str],
    comparable_signals: list[str],
    legacy_signals: list[str],
) -> list[str]:
    genre = str(payload.get("genre") or "").strip()
    synopsis = str(payload.get("synopsis") or "").strip()
    signals = list(title_elements)
    if genre:
        signals.append(genre)
    signals.extend(comparable_signals)
    signals.extend(legacy_signals)
    if synopsis:
        signals.append("synopsis")
    return list(dict.fromkeys(signals))


def _context_pack_injected_bytes(report: dict[str, Any]) -> int:
    evidence = report.get("evidence") or {}
    payload = {
        "contextPackBriefing": report.get("ui_briefing_payload") or {},
        "contextPackEvidenceSummary": {
            "target_market_ko": evidence.get("target_market_ko"),
            "context_record_count": evidence.get("context_record_count"),
            "platforms": evidence.get("platforms"),
            "signal_types": evidence.get("signal_types"),
            "summary": evidence.get("summary"),
            "data_limits": evidence.get("data_limits"),
        },
    }
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def _context_pack_diagnostics(
    *,
    requested: bool,
    enabled: bool,
    market: str | None,
    requested_target_country: str | None,
    requested_signals: list[str],
    evidence: dict[str, Any] | None = None,
    injected_evidence_bytes: int = 0,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    evidence = evidence or {}
    summary = evidence.get("summary") or {}
    rows = evidence.get("direct_signal_rows") or []
    matched = [
        str(row.get("work_signal"))
        for row in rows
        if row.get("direct_observation") == "observed" and row.get("work_signal")
    ]
    unmatched = [
        str(row.get("work_signal"))
        for row in rows
        if row.get("direct_observation") != "observed" and row.get("work_signal")
    ]
    if not rows and enabled and evidence:
        unmatched = list(requested_signals)

    source = inspect_context_pack_source(market)
    source_count = int(source.get("contextPackSourceRecordCount") or 0)
    candidate_count = len(rows)
    matched_count = len(matched)
    injected_count = len(matched) if injected_evidence_bytes else 0
    reason = skip_reason or source.get("contextPackSkipReason")
    if not reason:
        if not enabled:
            reason = "disabled"
        elif not source.get("contextPackSourceFound"):
            reason = "source_not_found" if market else "unsupported_market"
        elif source_count <= 0:
            reason = "no_source_records"
        elif candidate_count <= 0:
            reason = "no_candidate_records"
        elif injected_evidence_bytes > 0:
            reason = "injected"
        elif matched_count <= 0:
            reason = "no_matched_signals"
        else:
            reason = "not_injected"

    return {
        "contextPackRequested": requested,
        "contextPackEnabled": enabled,
        "requestedTargetCountry": requested_target_country,
        "resolvedTargetMarket": source.get("resolvedTargetMarket") or market,
        "contextPackSourceFound": bool(source.get("contextPackSourceFound")),
        "contextPackSourceRecordCount": source_count,
        "contextPackCandidateRecordCount": candidate_count,
        "contextPackMatchedRecordCount": matched_count,
        "contextPackInjectedRecordCount": injected_count,
        "contextPackInjectedEvidenceBytes": injected_evidence_bytes,
        "contextPackSkipReason": reason,
        "contextPackUsed": enabled and bool(evidence),
        "targetMarket": source.get("resolvedTargetMarket") or market,
        "contextRecordCount": evidence.get("context_record_count") if enabled and evidence else 0,
        "declaredSignalCount": summary.get("declared_signal_count", len(requested_signals)),
        "observedSignalCount": summary.get("observed_signal_count", 0) if enabled and evidence else 0,
        "matchedSignals": matched,
        "unmatchedSignals": unmatched,
    }


def _attach_context_pack_briefing(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    market = _target_market(payload, result)
    requested_target_country = _requested_target_country(payload, result)
    title_elements = _list_field(payload, "titleElements", "title_elements")
    comparable_signals = _list_field(payload, "comparableSignals", "comparable_signals")
    legacy_signals = _declared_signals(payload)
    requested_signals = _context_pack_requested_signals(payload, title_elements, comparable_signals, legacy_signals)
    requested = "includeContextPack" in payload or "include_context_pack" in payload
    enabled = _include_context_pack(payload)

    if not enabled:
        if not _include_internal(payload):
            return result
        return {
            **result,
            **_context_pack_diagnostics(
                requested=requested,
                enabled=False,
                market=market,
                requested_target_country=requested_target_country,
                requested_signals=requested_signals,
                skip_reason="disabled",
            ),
        }

    if not market or not (title_elements or comparable_signals or legacy_signals or payload.get("genre") or result.get("genre")):
        if _include_internal(payload):
            return {
                **result,
                **_context_pack_diagnostics(
                    requested=requested,
                    enabled=True,
                    market=market,
                    requested_target_country=requested_target_country,
                    requested_signals=requested_signals,
                    skip_reason="unsupported_market" if not market else "no_candidate_records",
                ),
            }
        return result

    report = build_context_pack_overlap_report(
        {
            "title": payload.get("title") or payload.get("workTitle") or result.get("title") or "가이드 입력",
            "target_market": market,
            "genre": payload.get("genre") or result.get("genre") or "",
            "synopsis": payload.get("synopsis") or "",
            "title_elements": title_elements,
            "comparable_signals": comparable_signals,
            "declared_signals": legacy_signals,
        }
    )
    injected_bytes = _context_pack_injected_bytes(report)
    enriched = dict(result)
    enriched["contextPackBriefing"] = report["ui_briefing_payload"]
    enriched["contextPackEvidence"] = report["evidence"]
    if _include_internal(payload):
        enriched.update(
            _context_pack_diagnostics(
                requested=requested,
                enabled=True,
                market=market,
                requested_target_country=requested_target_country,
                requested_signals=requested_signals,
                evidence=report["evidence"],
                injected_evidence_bytes=injected_bytes,
            )
        )
    return enriched


def generate_guide(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate the online localization guide response used by /api/guide."""
    report_mode = _guide_report_mode(payload)

    # Synopsis requests always return a four-country analysis. Country-specific
    # synopsis deep guides are a later product enhancement, not an active mode.
    if report_mode == "synopsis_country_recommendation":
        recommendation = {**generate_country_recommendation(payload), "reportMode": report_mode}
        recommendation["countryAnalyses"] = recommendation.get("countryAnalyses") or []
        # Temporary response compatibility for existing consumers.
        recommendation["countryComparisons"] = recommendation["countryAnalyses"]
        # The public response layer owns the final report. Always render from
        # structured data here so lower-layer mocks or stale htmlReport values
        # cannot become the public artifact.
        html_report = render_country_recommendation_html(recommendation)
        return _shape_recommendation_response(
            payload,
            {**recommendation, "htmlReport": html_report},
        )

    result = build_localization_advice(payload)
    if result.get("requiresSelection"):
        return _shape_recommendation_response(
            payload,
            {**result, "generationMode": result.get("generationMode") or "recommendation_only"},
        )

    result = {**result, "reportMode": result.get("reportMode") or report_mode}
    enriched = _attach_context_pack_briefing(payload, result)
    enriched = _attach_live_market_evidence(payload, enriched, report_mode=report_mode)
    enriched = {**enriched, **build_policy_attention_payload(payload, enriched)}

    try:
        genre_signals = generate_genre_signals(payload)
        if genre_signals:
            enriched = {**enriched, "genreSignals": genre_signals}
    except Exception:
        pass

    # A generated guide is a paid, user-facing artifact. Keep deterministic data
    # only as grounding input and always use the LLM for the final guide prose.
    try:
        return _shape_guide_response(payload, {**enriched, **generate_llm_guide(payload, enriched)})
    except Exception as exc:
        failed = dict(enriched)
        failed.pop("htmlReport", None)
        failed["generationMode"] = "llm_guide_failed"
        failed["llmGeneratedGuide"] = False
        failed["message"] = "LLM 가이드 생성에 실패해 결과를 만들지 못했습니다. 서버 로그와 모델/API 설정을 확인해 주세요."
        failed["llmGuideError"] = str(exc)
        return _shape_guide_response(payload, failed)
