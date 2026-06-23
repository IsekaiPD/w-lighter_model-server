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

CREATIVE_BOUNDARY_RULES = [
    "작품의 플롯, 결말, 캐릭터 성격, 핵심 설정, 장르 방향을 바꾸라고 제안하지 마세요.",
    "스토리 개선안, 플롯 수정안, 캐릭터 수정안, 시장 맞춤 리라이트처럼 보이는 표현을 쓰지 마세요.",
    "작품 자체를 고치는 대신 제목, 소개문, 태그, 표지 브리프, 플랫폼 정책, 독자 기대치 전달 방식에 한정하세요.",
    "'바꿔야 한다'보다 '전달할 때는', '소개문에서는', '태그에서는', '주의해서 설명하면 좋다'처럼 표현하세요.",
]

CREATIVE_BOUNDARY_NOTE = (
    "이 리포트는 작품을 바꾸는 컨설팅이 아니라, 작품을 현재 방향 그대로 두고 "
    "어느 국가에서 어떻게 전달하면 좋은지 정리하는 현지화 리포트입니다."
)


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
        "reportMode": result.get("reportMode") or ("synopsis_deep_guide" if payload.get("synopsis") else "country_genre_guide"),
        "countryRecommendation": _compact(result.get("countryRecommendation") or {}, 9000),
        "liveMarketEvidence": _compact(result.get("liveMarketEvidence") or {}, 12000),
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


def render_country_recommendation_html(result: dict[str, Any]) -> str:
    recommendation = result.get("countryRecommendation") or {}
    if not recommendation:
        return ""
    display = (
        recommendation.get("recommended_country_display")
        or recommendation.get("recommendedCountryDisplay")
        or result.get("recommendedCountryDisplay")
        or result.get("displayCountry")
        or result.get("targetCountryDisplay")
        or result.get("targetCountry")
        or "-"
    )
    confidence = recommendation.get("confidence") or "근거 기반 판단"
    story_profile = recommendation.get("storyProfile") or {}
    comparisons = sorted(
        recommendation.get("countryComparisons") or [],
        key=lambda item: int(item.get("rank") or 99),
    )
    cards = []
    for item in comparisons[:4]:
        score = max(0, min(100, int(float(item.get("relativeFitScore") or 0))))
        strengths = "".join(f"<li>{_esc(text)}</li>" for text in (item.get("strengths") or [])[:3])
        risks = "".join(f"<li>{_esc(text)}</li>" for text in (item.get("risks") or [])[:2])
        cards.append(
            f"""
<article class="mini-card">
  <div class="guide-section-header">
    <strong>{_esc(item.get('displayCountry') or item.get('country'))}</strong>
    <span class="badge ok">#{_esc(item.get('rank'))}</span>
  </div>
  <div class="chart-row">
    <div class="chart-label"><span>적합도</span><strong>{score}</strong></div>
    <div class="chart-track"><span style="width:{score}%"></span></div>
  </div>
  <p class="quiet-note">{_esc(item.get('fitLevel') or '')}</p>
  <h3>강점</h3><ul class="guide-list">{strengths or '<li>강점 근거 없음</li>'}</ul>
  <h3>주의</h3><ul class="guide-list">{risks or '<li>주의 근거 없음</li>'}</ul>
</article>
"""
        )
    signals = "".join(f"<span class='chip soft'>{_esc(item)}</span>" for item in story_profile.get("coreSignals") or [])
    return f"""
<section class="section recommendation-section">
  <p class="eyebrow">SYNOPSIS-BASED COUNTRY RECOMMENDATION</p>
  <h2>추천 국가: {_esc(display)}</h2>
  <p>{_esc(story_profile.get('analysisSummary') or '입력 시놉시스를 바탕으로 국가 적합도를 비교했습니다.')}</p>
  <div class="chips">{signals or '<span class="chip soft">시놉시스 분석</span>'}</div>
  <span class="badge ok">신뢰도: {_esc(confidence)}</span>
  <div class="cards">{''.join(cards)}</div>
</section>
"""


def render_live_market_evidence_html(result: dict[str, Any]) -> str:
    evidence = result.get("liveMarketEvidence") or {}
    if not evidence or not evidence.get("enabled"):
        return ""
    rows = []
    for country, items in (evidence.get("countryEvidence") or {}).items():
        links = "".join(
            f"<li><a href=\"{_esc(item.get('url'))}\" target=\"_blank\" rel=\"noreferrer\">{_esc(item.get('title') or item.get('url'))}</a><p>{_esc(item.get('content'))}</p></li>"
            for item in (items or [])[:3]
        )
        rows.append(f"<div class='mini-card'><h3>{_esc(country)}</h3><ul class='guide-list'>{links or '<li>검색 결과 없음</li>'}</ul></div>")
    return f"""
<section class="section live-market-section">
  <p class="eyebrow">LIVE MARKET EVIDENCE</p>
  <h2>실시간 웹 근거 참고</h2>
  <p class="quiet-note">아래 근거는 Tavily 웹 검색으로 수집한 참고 자료이며, LLM 판단의 보조 근거로만 사용합니다.</p>
  <div class="cards">{''.join(rows)}</div>
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
{render_country_recommendation_html(result)}
{render_live_market_evidence_html(result)}
<section class="section summary-box">
  <h2>가이드 요약</h2>
  {''.join(f'<p>{_esc(item)}</p>' for item in guide.get('executiveSummary') or [])}
</section>
<section class="section">
  <h2>출시 전 전달 체크리스트</h2>
  <ul class="guide-list">{action_html}</ul>
</section>
<section class="section">
  <h2>작품 입력 해석</h2>
  <div class="work-summary">
    <div><small>작품 제목</small><strong>{_esc(input_reading.get('workTitle') or title)}</strong></div>
    <div><small>장르 / 대상</small><strong>{_esc(input_reading.get('genre') or genre)} · {_esc(input_reading.get('targetCountry') or country)}</strong></div>
  </div>
  <p class="quiet-note">{_esc(CREATIVE_BOUNDARY_NOTE)}</p>
  <p><b>핵심 포인트:</b> {_esc(core or '입력 시놉시스가 부족합니다.')}</p>
  {('<div class="quiet-note"><strong>가정</strong><ul>' + assumptions + '</ul></div>') if assumptions else ''}
</section>
<section class="section"><h2>시장 적합도 해석</h2><ul class="guide-list">{''.join(f'<li>{_esc(item)}</li>' for item in market_items)}</ul></section>
<section class="section"><h2>문화 메모</h2><ul class="guide-list">{bullets('culturalNotes')}</ul></section>
<section class="section"><h2>플랫폼 정책 체크</h2><ul class="guide-list">{bullets('platformPolicyChecks')}</ul></section>
<section class="section"><h2>제목·소개문·태그 전달 가이드</h2><ul class="guide-list">{bullets('marketTagGuidance')}</ul></section>
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
            "reportMode가 synopsis_deep_guide이면 시놉시스 분석, 추천 국가, 추천 이유, 해당 국가 기준 현지화 전달 가이드를 하나의 심화 리포트로 작성하세요.",
            "reportMode가 country_genre_guide이면 선택 국가와 장르, 사용자가 궁금해하는 파트를 중심으로 일반 현지화 가이드를 작성하세요.",
            "countryRecommendation이 있으면 recommendedCountry를 별도 선택 단계로 남기지 말고, 추천 국가로 확정한 이유를 가이드 본문에 녹여 쓰세요.",
            "liveMarketEvidence가 있으면 최신 웹 근거를 보조 근거로 활용하되, 출처 문장을 그대로 길게 복사하지 마세요.",
            CREATIVE_BOUNDARY_NOTE,
            *CREATIVE_BOUNDARY_RULES,
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
