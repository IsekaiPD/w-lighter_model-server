from __future__ import annotations

import hashlib
import html
import json
import os
import re
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
        "marketSignalSummary": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
        "culturalNotes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "platformCultureReview": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "platformPolicyChecks": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "marketTagGuidance": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "releaseChecklist": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
    },
    "required": [
        "executiveSummary",
        "inputReading",
        "marketInterpretation",
        "marketSignalSummary",
        "culturalNotes",
        "platformCultureReview",
        "platformPolicyChecks",
        "marketTagGuidance",
        "releaseChecklist",
    ],
}

GENRE_SIGNALS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "genreSignals": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 8,
        },
        "localizationFocus": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 5,
        },
        "targetCountrySearchTerms": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 6,
        },
    },
    "required": ["genreSignals", "localizationFocus", "targetCountrySearchTerms"],
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


def _user_facing_text(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and not any("\uac00" <= ch <= "\ud7a3" for ch in text) and any(ch.isalpha() for ch in text):
        return "한국어 안내가 필요합니다."
    replacements = {
        "glossary": "작품 용어 기준",
        "Glossary": "작품 용어 기준",
        "컨텍스트 팩": "참고 자료",
        "context pack": "참고 자료",
        "Context Pack": "참고 자료",
        "liveMarketEvidence": "최근 플랫폼 참고 자료",
        "contextPackBriefing": "시장 참고 요약",
        "policyAttention": "정책 확인 항목",
        "US/global English": "미국",
        "Global": "전체",
        "ONGOING": "",
        "WAIT_UNTIL_FREE": "",
        "WAIT_UNTIL_PAID": "",
        "Original": "",
        "ORIGINAL": "",
        "fantasy": "판타지",
        "Fantasy": "판타지",
        "academy": "아카데미",
        "Academy": "아카데미",
        "growth": "성장",
        "Growth": "성장",
        "revenge": "복수",
        "Revenge": "복수",
        "LitRPG": "시스템 성장물",
        "Progression": "성장형 판타지",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    text = re.sub(r"\s*\(\d+(?:\.\d+)?\)", "", text)
    text = re.sub(r"\b(?:Wattpad|KakaoPage|Kakao|Naver|Novelpia|Kakuyomu|Syosetu)/[A-Za-z0-9_\-]+[^,.;\n]*[,.;]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b\s*,?\s*", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _esc_user(value: Any) -> str:
    return html.escape(_user_facing_text(value), quote=True)


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
    env_value = os.getenv("WLIGHTER_GUIDE_LLM")
    if env_value is not None:
        return str(env_value).strip().lower() not in {"0", "false", "no", "off", ""}
    return True


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


def generate_genre_signals(payload: dict[str, Any]) -> dict[str, Any]:
    """장르·제목 기반 경량 LLM 신호 분석 — 시놉시스 없는 country_genre_guide 경로 전용."""
    client, model = _client_and_model(payload)
    title = payload.get("title") or payload.get("workTitle") or "입력 작품"
    genre = payload.get("genre") or "장르 미입력"
    target_country = payload.get("targetCountry") or payload.get("country") or ""
    system = (
        "당신은 한국 웹소설 장르를 분석하는 편집자다. "
        "반드시 한국어 JSON 객체만 출력하고, 확인되지 않은 시장 성과나 독자 선호를 단정하지 않는다."
    )
    user = {
        "task": "장르와 제목을 바탕으로 현지화 기준서 작성에 필요한 신호를 분석해 주세요.",
        "input": {"title": title, "genre": genre, "targetCountry": target_country},
        "requirements": [
            "genreSignals: 이 장르에서 현지화할 때 중요한 구체 신호를 3~8개 작성하세요.",
            "localizationFocus: 대상 국가에서 이 장르를 소개할 때 집중할 2~5개 포인트를 작성하세요.",
            "targetCountrySearchTerms: 대상 국가 플랫폼·트렌드 검색에 쓸 2~6개 검색어를 작성하세요.",
            "확인되지 않은 시장 성과, 독자 선호, 흥행 가능성을 단정하지 마세요.",
            "작품의 플롯, 결말, 캐릭터를 바꾸라는 제안을 하지 마세요.",
            "설명은 모두 한국어로 작성하세요.",
        ],
    }
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "guide_genre_signals",
                "schema": GENRE_SIGNALS_SCHEMA,
                "strict": True,
            }
        },
    )
    return json.loads(response.output_text)


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
        "reportMode": result.get("reportMode") or "country_genre_guide",
        "countryRecommendation": _compact(result.get("countryRecommendation") or {}, 9000),
        "liveMarketEvidence": _compact(result.get("liveMarketEvidence") or {}, 12000),
        "genreSignals": _compact(result.get("genreSignals") or {}, 3000),
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
  <h2>작품과 맞닿는 시장 신호</h2>
  <div class="work-summary">
    <div><small>참고 항목</small><strong>{_esc(record_count or '확인 불가')}</strong></div>
    <div><small>참고 플랫폼</small><strong>{_esc(len(platforms))}</strong></div>
  </div>
  <div class="chips">{platform_chips or '<span class="chip">플랫폼 정보 없음</span>'}</div>
  <ul class="guide-list">{headline_rows or '<li>표시할 신호가 없습니다.</li>'}</ul>
</section>
"""


def render_live_market_evidence_html(result: dict[str, Any]) -> str:
    evidence = result.get("liveMarketEvidence") or {}
    items = evidence.get("items") or []
    if not items:
        return ""
    category_labels = {
        "platform_reference": "플랫폼 기준",
        "genre_trend": "장르 흐름",
        "title_synopsis_style": "제목·소개문 흐름",
        "reader_hook": "독자 반응 포인트",
    }
    source_labels = {
        "trusted": "주요 플랫폼",
        "reference": "참고 자료",
        "other": "웹 참고",
    }
    cards = []
    for item in items[:6]:
        category = str(item.get("category") or "")
        label = category_labels.get(category, category.replace("_", " ") or "참고 자료")
        source = item.get("source_type") or "reference"
        cards.append(
            f"""
<article class="mini-card">
  <div class="guide-section-header">
    <strong>{_esc(label or 'market reference')}</strong>
    <span class="badge ok">{_esc(source_labels.get(str(source), str(source)))}</span>
  </div>
  <h3>{_esc(item.get('domain') or '출처 미상')}</h3>
  <a href="{_esc(item.get('url'))}" target="_blank" rel="noreferrer">출처 열기</a>
  <small>{_esc(item.get('domain') or '')}</small>
</article>
"""
        )
    return f"""
<section class="section live-market-section">
  <p class="eyebrow">참고 출처</p>
  <h2>최근 플랫폼 참고 자료</h2>
  <p class="quiet-note">아래 링크는 본문 가이드를 작성할 때 확인한 공개 자료입니다. 원문 문장을 그대로 보여주기보다, 위의 해석과 체크리스트에 반영했습니다.</p>
  <div class="cards">{''.join(cards)}</div>
</section>
"""


def render_llm_html(guide: dict[str, Any], result: dict[str, Any]) -> str:
    title = result.get("title") or "가이드"
    country = result.get("displayCountry") or result.get("targetCountryDisplay") or result.get("targetCountry") or result.get("country") or "대상국가"
    genre = result.get("genre") or "장르 미입력"

    def bullets(key: str) -> str:
        return "".join(f"<li>{_esc_user(item)}</li>" for item in guide.get(key) or [])

    market_items = guide.get("marketInterpretation") or []
    market_signal_items = guide.get("marketSignalSummary") or []
    platform_review_items = guide.get("platformCultureReview") or []
    release_check_items = guide.get("releaseChecklist") or []
    input_reading = guide.get("inputReading") or {}
    core = " · ".join(str(item) for item in input_reading.get("coreAppeal") or [])
    assumptions = "".join(f"<li>{_esc_user(item)}</li>" for item in input_reading.get("assumptions") or [])
    action_items = [
        f"{country}용 제목/소개문에서 핵심 포인트({core or '작품 강점'})가 초반에 보이는지 확인합니다.",
        "고유명사·호칭·스킬명은 작품 안에서 같은 방식으로 쓰이도록 기준을 정한 뒤 번역에 반영합니다.",
        "플랫폼 정책 체크와 문화 메모는 게시 전 검수 항목으로 분리합니다.",
    ]
    for key in ("releaseChecklist", "marketTagGuidance", "platformPolicyChecks"):
        for item in guide.get(key) or []:
            text = str(item).strip()
            if text and text not in action_items:
                action_items.append(text)
                break
    action_html = "".join(f"<li>{_esc_user(item)}</li>" for item in action_items[:5])

    body_html = f"""
<section class="section summary-box">
  <p class="eyebrow">핵심 결론</p>
  <h2>핵심 전달 전략</h2>
  {''.join(f'<p>{_esc_user(item)}</p>' for item in guide.get('executiveSummary') or [])}
</section>
<section class="section">
  <h2>작품 입력 해석</h2>
  <div class="work-summary">
    <div><small>작품 제목</small><strong>{_esc(input_reading.get('workTitle') or title)}</strong></div>
    <div><small>장르 / 대상</small><strong>{_esc(input_reading.get('genre') or genre)} · {_esc(country)}</strong></div>
  </div>
  <p class="quiet-note">{_esc(CREATIVE_BOUNDARY_NOTE)}</p>
  <p><b>핵심 포인트:</b> {_esc(core or '입력 시놉시스가 부족합니다.')}</p>
  {('<div class="quiet-note"><strong>가정</strong><ul>' + assumptions + '</ul></div>') if assumptions else ''}
</section>
<section class="section"><h2>제목·소개문·태그 전달 가이드</h2><ul class="guide-list">{bullets('marketTagGuidance')}</ul></section>
<section class="section"><h2>시장 적합도 해석</h2><ul class="guide-list">{''.join(f'<li>{_esc_user(item)}</li>' for item in market_items)}</ul></section>
<section class="section"><h2>참고한 시장 신호 요약</h2><ul class="guide-list">{''.join(f'<li>{_esc_user(item)}</li>' for item in market_signal_items)}</ul></section>
<section class="section"><h2>번역·표현 주의점</h2><ul class="guide-list">{bullets('culturalNotes')}</ul></section>
<section class="section"><h2>플랫폼·문화권 검토 결과</h2><ul class="guide-list">{''.join(f'<li>{_esc_user(item)}</li>' for item in platform_review_items)}</ul></section>
<section class="section"><h2>플랫폼 게시 전 체크</h2><ul class="guide-list">{bullets('platformPolicyChecks')}</ul></section>
<section class="section">
  <h2>출시 전 확인할 것</h2>
  <ul class="guide-list">{''.join(f'<li>{_esc_user(item)}</li>' for item in release_check_items) or action_html}</ul>
</section>
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
            "reportMode가 country_genre_guide이면 선택 국가와 장르, 사용자가 궁금해하는 파트를 중심으로 일반 현지화 가이드를 작성하세요.",
            "genreSignals가 있으면 장르 특화 신호(genreSignals·localizationFocus)를 가이드 본문에 직접 반영해 구체적인 내용을 작성하세요.",
            "liveMarketEvidence가 있으면 최신 웹 근거를 보조 근거로 활용하되, 출처 문장을 그대로 길게 복사하지 마세요.",
            "liveMarketEvidence는 최신 웹 참고자료이며 전체 시장 통계처럼 단정하지 마세요.",
            "liveMarketEvidence의 원문이 일본어, 영어, 중국어, 태국어여도 그대로 복사하지 말고 한국어로 요약·해석하세요.",
            "liveMarketEvidence, contextPackBriefing, policyAttention 같은 내부 필드명을 사용자에게 직접 쓰지 마세요.",
            "glossary라는 내부 기능명을 쓰지 말고, 필요하면 '작품 용어 기준' 또는 '고유명사 기준'처럼 사용자에게 보이는 말로 바꾸세요.",
            "liveMarketEvidence 안의 외국어 원문 제목·태그·문장을 그대로 출력하지 마세요.",
            CREATIVE_BOUNDARY_NOTE,
            *CREATIVE_BOUNDARY_RULES,
            "시놉시스, 장르, 대상국가, 문화 주의사항, 플랫폼 정책 점검을 포함하세요.",
            "marketSignalSummary에는 순위, 카운트, URL, 원문 제목을 쓰지 말고 사용자가 이해할 수 있는 시장 신호 해석만 쓰세요.",
            "platformCultureReview에는 검토 기준만 나열하지 말고 이 작품 입력을 기준으로 실제로 무엇을 확인했는지 쓰세요.",
            "releaseChecklist에는 내부 판단 근거가 아니라 출시 전 사용자가 확인할 수 있는 행동 항목만 쓰세요.",
            "evidenceExplanation, limitations, 사용 근거, 판단 근거 같은 제목이나 표현은 출력하지 마세요.",
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
        "htmlReport": html_report,
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
    "GENRE_SIGNALS_SCHEMA",
    "GUIDE_JSON_SCHEMA",
    "_client_and_model",
    "llm_requested",
    "generate_genre_signals",
    "generate_llm_guide",
    "render_llm_html",
]
