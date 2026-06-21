from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import datetime, timezone
from typing import Any

from ..infra.report_html import build_guide_html_document

DEFAULT_MODEL = "gpt-5.4-mini"

GUIDE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "executiveSummary": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
        "inputReading": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "workTitle": {"type": "string"},
                "genre": {"type": "string"},
                "targetCountry": {"type": "string"},
                "coreAppeal": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "assumptions": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            },
            "required": ["workTitle", "genre", "targetCountry", "coreAppeal", "assumptions"],
        },
        "marketInterpretation": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
        "culturalNotes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "platformPolicyChecks": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "marketTagGuidance": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "evidenceExplanation": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "limitations": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
    },
    "required": [
        "executiveSummary",
        "inputReading",
        "marketInterpretation",
        "culturalNotes",
        "platformPolicyChecks",
        "marketTagGuidance",
        "evidenceExplanation",
        "limitations",
    ],
}


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _compact(value: Any, limit: int = 8000) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return {
        "truncated": True,
        "original_type": type(value).__name__,
        "preview_json": text[:limit],
    }


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv()


def llm_requested(payload: dict[str, Any]) -> bool:
    explicit = (
        payload.get("useLlm")
        if "useLlm" in payload
        else payload.get("use_llm")
        if "use_llm" in payload
        else payload.get("liveModel")
        if "liveModel" in payload
        else payload.get("live_model")
    )
    if explicit is not None:
        return str(explicit).strip().lower() not in {"0", "false", "no", "off", ""}
    return str(os.getenv("WLIGHTER_GUIDE_LLM", "")).strip().lower() in {"1", "true", "yes", "on", "live"}


def _client_and_model(payload: dict[str, Any]):
    _load_dotenv_if_available()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없어 LLM 가이드를 생성할 수 없습니다.")
    from openai import OpenAI

    model = str(
        payload.get("guideModel")
        or payload.get("guide_model")
        or os.getenv("WLIGHTER_GUIDE_MODEL")
        or os.getenv("OPENAI_GUIDE_MODEL")
        or DEFAULT_MODEL
    ).strip()
    return OpenAI(api_key=api_key), model


def _evidence_payload(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    briefing = result.get("contextPackBriefing") or {}
    evidence = result.get("contextPackEvidence") or {}
    return {
        "userInput": {
            "title": payload.get("title") or payload.get("workTitle"),
            "genre": payload.get("genre") or result.get("genre"),
            "synopsis": payload.get("synopsis") or result.get("synopsis"),
            "targetCountry": payload.get("targetCountry") or payload.get("country") or result.get("targetCountry"),
            "titleElements": payload.get("titleElements") or payload.get("title_elements") or [],
            "comparableSignals": payload.get("comparableSignals") or payload.get("comparable_signals") or [],
        },
        "selectedCountry": result.get("displayCountry")
        or result.get("targetCountryDisplay")
        or result.get("targetCountry")
        or result.get("country"),
        "countryDataMatches": _compact(result.get("recommendedCountries") or [], 7000),
        "trendSectionsFallback": _compact(result.get("sections") or {}, 9000),
        "evidenceUsed": _compact(result.get("evidenceUsed") or [], 9000),
        "contextPackBriefing": _compact(briefing, 10000),
        "contextPackEvidenceSummary": {
            "target_market_ko": evidence.get("target_market_ko"),
            "context_record_count": evidence.get("context_record_count"),
            "platforms": evidence.get("platforms"),
            "signal_types": evidence.get("signal_types"),
            "summary": evidence.get("summary"),
            "data_limits": evidence.get("data_limits"),
        },
        "policyAttentionCards": _compact(result.get("policyAttentionCards") or [], 9000),
        "policyLimitations": result.get("policyLimitations") or [],
    }


def _payload_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _stable_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _context_pack_evidence_size(evidence_payload: dict[str, Any]) -> int:
    context_part = {
        "contextPackBriefing": evidence_payload.get("contextPackBriefing") or {},
        "contextPackEvidenceSummary": evidence_payload.get("contextPackEvidenceSummary") or {},
    }
    if not context_part["contextPackBriefing"] and not any((context_part["contextPackEvidenceSummary"] or {}).values()):
        return 0
    return _payload_size(context_part)


def render_market_snapshot_html(result: dict[str, Any]) -> str:
    briefing = result.get("contextPackBriefing") or {}
    headline = briefing.get("headline_market_labels") or []
    evidence = result.get("contextPackEvidence") or {}
    platforms = evidence.get("platforms") or []
    record_count = evidence.get("context_record_count")
    platform_chips = "".join(f"<span class='chip'>{_esc(item)}</span>" for item in platforms)
    headline_rows = "".join(
        f"<li>{_esc(item.get('label_ko') or item.get('label') or '-')} ({_esc(item.get('count') or 0)})</li>"
        for item in headline[:8]
    )
    return f"""
<section class="section market-snapshot">
  <h2>컨텍스트 팩 참고 데이터</h2>
  <div class="work-summary">
    <div><small>레코드 수</small><strong>{_esc(record_count or '확인 불가')}</strong></div>
    <div><small>플랫폼</small><strong>{_esc(len(platforms))}</strong></div>
  </div>
  <div class="chips">{platform_chips or '<span class="chip">플랫폼 정보 없음</span>'}</div>
  <ul class="guide-list">{headline_rows or '<li>표시할 신호가 없습니다.</li>'}</ul>
</section>
"""


def render_llm_html(guide: dict[str, Any], result: dict[str, Any]) -> str:
    title = result.get("title") or "가이드"
    country = result.get("displayCountry") or result.get("targetCountryDisplay") or result.get("targetCountry") or result.get("country") or "대상국가"
    genre = result.get("genre") or "장르 미입력"

    def bullets(key: str) -> str:
        return "".join(f"<li>{_esc(item)}</li>" for item in guide.get(key) or [])

    market_items = guide.get("marketInterpretation") or guide.get("writingDirection") or []
    input_reading = guide.get("inputReading") or {}
    core = " · ".join(str(item) for item in input_reading.get("coreAppeal") or [])
    assumptions = "".join(f"<li>{_esc(item)}</li>" for item in input_reading.get("assumptions") or [])
    action_items = [
        f"{country}용 제목/소개문에서 핵심 포인트({core or '작품 강점'})가 초반에 보이는지 확인합니다.",
        "고유명사·호칭·스킬명은 작품 glossary에 먼저 고정한 뒤 번역에 반영합니다.",
        "플랫폼 정책 체크와 문화 메모는 게시 전 검수 항목으로 분리합니다.",
    ]
    for key in ("marketTagGuidance", "platformPolicyChecks", "limitations"):
        for item in guide.get(key) or []:
            text = str(item).strip()
            if text and text not in action_items:
                action_items.append(text)
                break
    action_html = "".join(f"<li>{_esc(item)}</li>" for item in action_items[:5])

    body_html = f"""
{render_market_snapshot_html(result)}
<section class="section summary-box">
  <h2>가이드 요약</h2>
  {''.join(f'<p>{_esc(item)}</p>' for item in guide.get('executiveSummary') or [])}
</section>
<section class="section">
  <h2>바로 적용할 체크리스트</h2>
  <ul class="guide-list">{action_html}</ul>
</section>
<section class="section">
  <h2>입력 해석</h2>
  <div class="work-summary">
    <div><small>작품 제목</small><strong>{_esc(input_reading.get('workTitle') or title)}</strong></div>
    <div><small>장르 / 대상</small><strong>{_esc(input_reading.get('genre') or genre)} · {_esc(input_reading.get('targetCountry') or country)}</strong></div>
  </div>
  <p><b>핵심 포인트:</b> {_esc(core or '입력 시놉시스가 부족합니다.')}</p>
  {('<div class="quiet-note"><strong>가정</strong><ul>' + assumptions + '</ul></div>') if assumptions else ''}
</section>
<section class="section"><h2>시장 해석</h2><ul class="guide-list">{''.join(f'<li>{_esc(item)}</li>' for item in market_items)}</ul></section>
<section class="section"><h2>문화 메모</h2><ul class="guide-list">{bullets('culturalNotes')}</ul></section>
<section class="section"><h2>플랫폼 정책 체크</h2><ul class="guide-list">{bullets('platformPolicyChecks')}</ul></section>
<section class="section"><h2>태그 가이드</h2><ul class="guide-list">{bullets('marketTagGuidance')}</ul></section>
<section class="section"><h2>증거 설명</h2><ul class="guide-list">{bullets('evidenceExplanation')}</ul></section>
<section class="section"><h2>한계</h2><ul class="guide-list">{bullets('limitations')}</ul></section>
"""
    return build_guide_html_document(title=f"{country} 현지화 가이드", body_html=body_html)


def generate_llm_guide(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    client, model = _client_and_model(payload)
    evidence_payload = _evidence_payload(payload, result)
    system = (
        "당신은 한국어로 쓰는 가이드 작성기다. "
        "출력은 반드시 JSON 객체여야 하며, 입력 근거(RAG/context/policy)만 사용하고 불확실한 단정은 하지 않는다. "
        "문장은 모두 한국어로 작성한다."
    )
    user = {
        "task": "입력 근거를 바탕으로 한국어 가이드를 작성해 주세요.",
        "requirements": [
            "시놉시스, 장르, 대상국가, 문화 주의사항, 플랫폼 정책 점검을 포함하세요.",
            "입력 해석은 '이렇게 보인다' 형식으로 자연스럽게 작성하세요.",
            "내부 근거를 재서술하지 말고, 사용자에게 도움이 되는 해석만 쓰세요.",
            "불필요한 영어 문장을 쓰지 마세요.",
        ],
        "evidence": evidence_payload,
    }
    request_hash = _stable_hash({"system": system, "user": user})
    evidence_bytes = _payload_size(evidence_payload)
    context_evidence_bytes = _context_pack_evidence_size(evidence_payload)

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "llm_localization_guide",
                "schema": GUIDE_JSON_SCHEMA,
                "strict": True,
            }
        },
    )
    guide = json.loads(response.output_text)
    html_report = render_llm_html(guide, result)
    action_checklist = [
        *(guide.get("marketTagGuidance") or [])[:1],
        *(guide.get("platformPolicyChecks") or [])[:2],
        *(guide.get("limitations") or [])[:1],
    ]
    out = {
        "generationMode": "llm_with_rag",
        "llmGeneratedGuide": True,
        "llmGuideModel": model,
        "llmGuideGeneratedAt": datetime.now(timezone.utc).isoformat(),
        "llmGuideEvidenceSummary": {
            "selectedCountry": evidence_payload["selectedCountry"],
            "contextRecordCount": evidence_payload["contextPackEvidenceSummary"].get("context_record_count"),
            "platforms": evidence_payload["contextPackEvidenceSummary"].get("platforms") or [],
            "policyCards": len(evidence_payload["policyAttentionCards"]),
            "countryDataMatchCount": len(evidence_payload["countryDataMatches"]),
        },
        "personalizedGuide": guide,
        "qualitySummary": guide.get("executiveSummary") or [],
        "actionChecklist": action_checklist,
        "htmlReport": html_report,
        "llmHtmlReport": html_report,
    }
    if _truthy_flag(payload.get("includeInternal") or payload.get("include_internal"), default=False):
        out["llmGuideEvidenceBytes"] = evidence_bytes
        out["llmGuideContextPackEvidenceBytes"] = context_evidence_bytes
        out["llmGuideRequestHash"] = request_hash
    return out


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


__all__ = [
    "DEFAULT_MODEL",
    "GUIDE_JSON_SCHEMA",
    "_client_and_model",
    "llm_requested",
    "generate_llm_guide",
    "render_llm_html",
]
