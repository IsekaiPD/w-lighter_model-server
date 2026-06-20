"""Online localization guide pipeline composition."""

from __future__ import annotations

import os
from typing import Any

from domains.guide.agents.guide_writer import generate_llm_guide, llm_requested
from domains.guide.engine.policy_analysis import build_policy_attention_payload
from domains.guide.engine.recommendation import build_localization_advice
from domains.guide.retrieval.context_pack import build_context_pack_overlap_report


PIPELINE_MARKET_ALIASES = {
    "japan": "japan",
    "jp": "japan",
    "일본": "japan",
    "日本": "japan",
    "us": "english",
    "usa": "english",
    "english": "english",
    "영어권": "english",
    "미국": "english",
    "china": "china",
    "cn": "china",
    "중국": "china",
    "thailand": "thailand",
    "th": "thailand",
    "태국": "thailand",
}


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
    return PIPELINE_MARKET_ALIASES.get(str(raw).strip().lower()) or PIPELINE_MARKET_ALIASES.get(str(raw).strip())


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
    return _truthy_flag(os.getenv("WLIGHTER_GUIDE_CONTEXT_PACK"), default=True)


def _include_internal(payload: dict[str, Any]) -> bool:
    return _truthy_flag(payload.get("includeInternal") or payload.get("include_internal"), default=False)


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


def _context_pack_diagnostics(
    *,
    used: bool,
    market: str | None,
    requested_signals: list[str],
    evidence: dict[str, Any] | None = None,
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
    if not rows:
        unmatched = list(requested_signals) if used else []

    return {
        "contextPackUsed": used,
        "targetMarket": market,
        "contextRecordCount": evidence.get("context_record_count") if used else 0,
        "declaredSignalCount": summary.get("declared_signal_count", len(requested_signals) if used else len(requested_signals)),
        "observedSignalCount": summary.get("observed_signal_count", 0) if used else 0,
        "matchedSignals": matched,
        "unmatchedSignals": unmatched,
    }


def _attach_context_pack_briefing(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    market = _target_market(payload, result)
    title_elements = _list_field(payload, "titleElements", "title_elements")
    comparable_signals = _list_field(payload, "comparableSignals", "comparable_signals")
    legacy_signals = _declared_signals(payload)
    requested_signals = _context_pack_requested_signals(payload, title_elements, comparable_signals, legacy_signals)

    if not _include_context_pack(payload):
        if not _include_internal(payload):
            return result
        return {
            **result,
            **_context_pack_diagnostics(used=False, market=market, requested_signals=requested_signals),
        }

    if not market or not (title_elements or comparable_signals or legacy_signals or payload.get("genre") or result.get("genre")):
        if _include_internal(payload):
            return {
                **result,
                **_context_pack_diagnostics(used=False, market=market, requested_signals=requested_signals),
            }
        return result

    report = build_context_pack_overlap_report(
        {
            "title": payload.get("title") or payload.get("workTitle") or result.get("title") or "입력 작품",
            "target_market": market,
            "genre": payload.get("genre") or result.get("genre") or "",
            "synopsis": payload.get("synopsis") or "",
            "title_elements": title_elements,
            "comparable_signals": comparable_signals,
            "declared_signals": legacy_signals,
        }
    )
    enriched = dict(result)
    enriched["contextPackBriefing"] = report["ui_briefing_payload"]
    enriched["contextPackEvidence"] = report["evidence"]
    if _include_internal(payload):
        enriched.update(
            _context_pack_diagnostics(
                used=True,
                market=market,
                requested_signals=requested_signals,
                evidence=report["evidence"],
            )
        )
    return enriched


def _preserve_legacy_html_section_anchors(result: dict[str, Any]) -> dict[str, Any]:
    html_report = result.get("htmlReport")
    if not isinstance(html_report, str) or not html_report:
        return result
    required = ["제목/시놉시스", "문화", "플랫폼"]
    if all(anchor in html_report for anchor in required):
        return result
    enriched = dict(result)
    missing = " · ".join(anchor for anchor in required if anchor not in html_report)
    enriched["htmlReport"] = (
        html_report.replace(
            '<div class="guide-legacy-anchors">',
            f'<div class="guide-legacy-anchors">{missing} · ',
            1,
        )
        if '<div class="guide-legacy-anchors">' in html_report
        else html_report + f"\n<!-- legacy guide anchors: {missing} -->"
    )
    return enriched


def generate_guide(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate the online localization guide response used by /api/guide."""
    use_legacy = str(payload.get("legacyGuide") or payload.get("legacy_guide") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    result = build_localization_advice(payload)
    if result.get("requiresSelection"):
        if use_legacy:
            return result
        return {**result, "generationMode": result.get("generationMode") or "recommendation_only"}

    result = _preserve_legacy_html_section_anchors(result)
    enriched = _attach_context_pack_briefing(payload, result)
    enriched = {**enriched, **build_policy_attention_payload(payload, enriched)}

    deterministic_mode = "deterministic_rag_fallback" if use_legacy else "deterministic_guide"
    if not llm_requested(payload):
        return {**enriched, "generationMode": enriched.get("generationMode") or deterministic_mode}

    try:
        return {**enriched, **generate_llm_guide(payload, enriched)}
    except Exception as exc:
        fallback = dict(enriched)
        fallback["generationMode"] = deterministic_mode if not use_legacy else "deterministic_rag_fallback"
        fallback["llmGeneratedGuide"] = False
        fallback["llmGuideError"] = str(exc)
        return fallback
