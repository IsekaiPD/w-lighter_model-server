from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from typing import Any


DEFAULT_MODEL = "gpt-4.1-mini"


GUIDE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "executiveSummary": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 4,
        },
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
        raise RuntimeError("OPENAI_API_KEY가 없어 LLM 현지화 가이드를 생성할 수 없습니다.")
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


def generate_llm_guide(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    client, model = _client_and_model(payload)
    evidence_payload = _evidence_payload(payload, result)
    system = (
        "너는 한국 웹소설 작가를 돕는 현지화 리포트 작성자다. "
        "반드시 제공된 RAG/context/policy 근거 안에서만 판단하고, 없는 규정·플랫폼 수치·독자 반응을 지어내지 않는다. "
        "출력은 한국어 JSON 객체만 반환한다. 코드블록과 마크다운은 쓰지 않는다. "
        "작품을 바꾸라고 단정하지 말고, 첫 장·챕터·문체를 어떻게 쓰라는 창작 지시도 하지 않는다. "
        "대신 현지 플랫폼에서 이 작품 정보가 어떤 장르/태그/규정 맥락으로 읽힐 수 있는지 사용자가 이해하기 쉽게 설명한다. "
        "전문용어는 풀어서 쓰고, '포지셔닝', '컨텍스트', '시그널' 같은 말은 가능하면 쉬운 말로 바꾼다."
    )
    user = {
        "task": "제공된 근거 데이터로 작가용 현지화 가이드를 작성하세요.",
        "requirements": [
            "창작 조언이 아니라 시장 데이터 해석, 문화적 주의사항, 플랫폼 규정 확인을 포함하세요.",
            "marketInterpretation에는 '이렇게 쓰세요'가 아니라 '플랫폼에서는 이렇게 보일 수 있습니다' 형식으로 작성하세요.",
            "첫 장부터, 챕터 제목, 문체 권장, 독자 몰입 유도처럼 작품을 고치라는 문장은 피하세요.",
            "사용자가 어떤 데이터를 넣었고 시스템이 어떤 근거를 사용했는지 설명하세요.",
            "시놉시스가 있으면 작품별 소재·관계·수위 확인 항목을 더 구체화하되, 시놉시스에서 읽은 요소는 확정 태그가 아니라 추정/확인 후보로 표시하세요.",
            "시놉시스가 없으면 장르·대상 국가 기준의 일반 체크 범위라고 밝히고, 작품별 민감 요소나 핵심 소재를 확정하지 마세요.",
            "입력이 부족한 경우 부족하다고 밝히되, 가능한 범위에서 대상 국가 기준으로 작성하세요.",
            "정책 카드는 위반 확정이 아니라 게시 전 체크포인트로 표현하세요.",
            "근거가 약한 내용은 단정하지 마세요.",
            "문장은 사용자 친화적으로 짧고 쉽게 쓰세요.",
        ],
        "evidence": evidence_payload,
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
                "name": "llm_localization_guide",
                "schema": GUIDE_JSON_SCHEMA,
                "strict": True,
            }
        },
    )
    guide = json.loads(response.output_text)
    return {
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
        "llmHtmlReport": render_llm_html(guide, result),
    }


def render_llm_html(guide: dict[str, Any], result: dict[str, Any]) -> str:
    title = result.get("title") or "현지화 가이드"
    country = result.get("displayCountry") or result.get("targetCountryDisplay") or result.get("targetCountry") or result.get("country") or "대상 국가"
    genre = result.get("genre") or "장르 미입력"

    def bullets(key: str) -> str:
        return "".join(f"<li>{_esc(item)}</li>" for item in guide.get(key) or [])

    market_items = guide.get("marketInterpretation") or guide.get("writingDirection") or []
    input_reading = guide.get("inputReading") or {}
    core = " · ".join(str(item) for item in input_reading.get("coreAppeal") or [])
    assumptions = "".join(f"<li>{_esc(item)}</li>" for item in input_reading.get("assumptions") or [])

    return f"""
{render_market_snapshot_html(result)}
<section class="section summary-box">
  <h2>이번 리포트 요약</h2>
  {''.join(f'<p>{_esc(item)}</p>' for item in guide.get('executiveSummary') or [])}
</section>
<section class="section">
  <h2>입력 작품을 이렇게 읽었어요</h2>
  <div class="work-summary">
    <div><small>작품 제목</small><strong>{_esc(input_reading.get('workTitle') or '제목 미입력')}</strong></div>
    <div><small>장르 / 대상</small><strong>{_esc(input_reading.get('genre') or genre)} · {_esc(input_reading.get('targetCountry') or country)}</strong></div>
  </div>
  <p><b>핵심 매력/소재:</b> {_esc(core or '입력 근거 부족')}</p>
  {('<div class="quiet-note"><strong>전제와 한계</strong><ul>' + assumptions + '</ul></div>') if assumptions else ''}
</section>
<section class="section"><h2>현지 플랫폼에서는 이렇게 보일 수 있어요</h2><p class="guide-section-help">작품을 고치라는 뜻이 아니라, 입력 정보가 대상 국가 플랫폼 데이터 안에서 어떤 태그와 소개 맥락으로 읽힐 수 있는지 정리한 내용입니다.</p><ul class="guide-list">{''.join(f'<li>{_esc(item)}</li>' for item in market_items)}</ul></section>
<section class="section"><h2>문화적 주의사항</h2><ul class="guide-list">{bullets('culturalNotes')}</ul></section>
<section class="section"><h2>플랫폼 규정 체크포인트</h2><ul class="guide-list">{bullets('platformPolicyChecks')}</ul></section>
<section class="section"><h2>태그와 소개문에서 참고할 점</h2><ul class="guide-list">{bullets('marketTagGuidance')}</ul></section>
<section class="section"><h2>사용한 근거 설명</h2><ul class="guide-list">{bullets('evidenceExplanation')}</ul></section>
<section class="section"><h2>읽기 전에</h2><ul class="guide-list">{bullets('limitations')}</ul></section>
"""


def _bar_rows(items: list[tuple[str, float, str]], *, max_rows: int = 8) -> str:
    clean = [(label, float(value or 0), note) for label, value, note in items[:max_rows] if label]
    max_value = max([value for _, value, _ in clean] or [1.0])
    rows = []
    for label, value, note in clean:
        width = max(4, min(100, int((value / max_value) * 100))) if max_value else 4
        rows.append(
            "<div class='chart-row'>"
            f"<div class='chart-label'>{_esc(label)}</div>"
            f"<div class='chart-track'><span style='width:{width}%'></span></div>"
            f"<div class='chart-value'>{_esc(note)}</div>"
            "</div>"
        )
    return "".join(rows) or "<p class='muted'>표시할 데이터가 없습니다.</p>"


def render_market_snapshot_html(result: dict[str, Any]) -> str:
    briefing = result.get("contextPackBriefing") or {}
    headline = briefing.get("headline_market_labels") or []
    cooccurrence = briefing.get("cooccurrence_cards") or []
    evidence = result.get("contextPackEvidence") or {}
    platforms = evidence.get("platforms") or []
    record_count = evidence.get("context_record_count")
    tag_rows = [
        (
            str(item.get("label_ko") or item.get("label") or "태그"),
            float(item.get("count") or item.get("weighted_share") or item.get("share") or 0),
            f"{item.get('count')}건" if item.get("count") is not None else "참고",
        )
        for item in headline[:8]
    ]
    combo_rows = [
        (
            " + ".join(str(label) for label in item.get("labels") or []),
            float(item.get("count") or 0),
            f"{item.get('count')}건"
            + (
                f" · {((item.get('platform_spread') or {}).get('observed'))}/{((item.get('platform_spread') or {}).get('total'))} 플랫폼"
                if item.get("platform_spread")
                else ""
            ),
        )
        for item in cooccurrence[:8]
    ]
    platform_chips = "".join(f"<span class='chip'>{_esc(item)}</span>" for item in platforms)
    return f"""
<section class="section market-snapshot">
  <h2>이번 리포트가 참고한 플랫폼 데이터</h2>
  <p class="guide-section-help">아래 내용은 대상 국가 플랫폼에서 공개적으로 관찰한 작품/태그 데이터만 간단히 보여줍니다. 국가별 우열이나 시장 성공 가능성을 뜻하지 않습니다.</p>
  <div class="work-summary">
    <div><small>참고한 작품 수</small><strong>{_esc(record_count or '확인 중')}편</strong></div>
    <div><small>참고한 플랫폼</small><strong>{_esc(len(platforms))}곳</strong></div>
  </div>
  <div class="chips">{platform_chips or '<span class="chip">플랫폼 정보 없음</span>'}</div>
  <div class="grid" style="margin-top:14px">
    <article class="chart-card"><h3>참고 데이터에서 자주 보인 태그</h3>{_bar_rows(tag_rows, max_rows=8)}</article>
    <article class="chart-card"><h3>함께 자주 보인 태그 조합</h3>{_bar_rows(combo_rows, max_rows=8)}<p class="muted">같은 작품에 함께 붙어 있던 태그 조합입니다. 내 작품에 모두 적용하라는 뜻은 아닙니다.</p></article>
  </div>
</section>
"""


def _display_country_name(value: str) -> str:
    text = str(value or "").strip()
    mapping = {
        "us/global english": "미국",
        "us": "미국",
        "usa": "미국",
        "japan": "일본",
        "jp": "일본",
        "china": "중국",
        "cn": "중국",
        "thailand": "태국",
        "th": "태국",
    }
    return mapping.get(text.lower()) or mapping.get(text) or text
