"""HTML renderer for the synopsis country-comparison report."""

from __future__ import annotations

from html import escape
from typing import Any


COMPARISON_WITHHELD_MESSAGE = (
    "현재 자료로는 국가 간 시장 적합도를 비교할 수 없어 "
    "순위와 점수를 만들지 않았습니다."
)

COMPARISON_REFERENCE_FOOTER = (
    "이 결과는 입력 신호와 공개 관측 자료의 겹침을 비교한 참고 결과입니다."
)

UNGROUNDED_MARKET_LIMITATION = (
    "현재 확보된 자료만으로는 국가별 독자 선호, 플랫폼 실적 등 "
    "실제 시장 성과를 직접 확인할 수 없어 해당 내용을 "
    "확정적으로 판단하지 않았습니다."
)


COUNTRY_RECOMMENDATION_CSS = """
:root { --wl-guide-bg:#f7f3ff; --wl-guide-bg-2:#fff7fb; --wl-guide-panel:#fff; --wl-guide-panel-soft:#fbf8ff; --wl-guide-text:#201627; --wl-guide-muted:#6f6177; --wl-guide-border:#eadff3; --wl-guide-primary:#7c3aed; --wl-guide-primary-2:#ec4899; --wl-guide-good:#0f9f6e; --wl-guide-warn:#c47a10; --wl-guide-risk:#dc2626; --wl-guide-shadow:0 18px 50px rgba(51,35,76,.12); }
* { box-sizing:border-box; } body { margin:0; color:var(--wl-guide-text); background:radial-gradient(circle at 0 0,rgba(236,72,153,.16),transparent 32%),radial-gradient(circle at 100% 0,rgba(124,58,237,.16),transparent 36%),linear-gradient(135deg,var(--wl-guide-bg),var(--wl-guide-bg-2)); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR","Apple SD Gothic Neo",sans-serif; line-height:1.65; }
.wl-guide-page { max-width:1180px; margin:0 auto; padding:32px 20px 56px; } .wl-guide-hero { position:relative; overflow:hidden; border-radius:32px; padding:34px; color:#fff; background:linear-gradient(135deg,rgba(44,21,75,.92),rgba(124,58,237,.9)),linear-gradient(90deg,var(--wl-guide-primary),var(--wl-guide-primary-2)); box-shadow:var(--wl-guide-shadow); } .wl-guide-hero::after { content:""; position:absolute; right:-70px; top:-90px; width:260px; height:260px; border-radius:50%; background:rgba(255,255,255,.14); }
.wl-guide-eyebrow { position:relative; display:inline-flex; margin:0 0 14px; padding:6px 12px; border:1px solid rgba(255,255,255,.26); border-radius:999px; color:rgba(255,255,255,.9); font-size:13px; font-weight:700; } .wl-guide-hero h1 { position:relative; margin:0; font-size:clamp(30px,5vw,52px); line-height:1.08; letter-spacing:-.045em; } .wl-guide-hero p { position:relative; max-width:760px; margin:16px 0 0; color:rgba(255,255,255,.84); font-size:17px; }
.wl-guide-meta-grid { position:relative; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:28px; } .wl-guide-meta-card { min-height:94px; padding:16px; border:1px solid rgba(255,255,255,.18); border-radius:20px; background:rgba(255,255,255,.12); backdrop-filter:blur(10px); } .wl-guide-meta-label { color:rgba(255,255,255,.68); font-size:12px; font-weight:700; } .wl-guide-meta-value { display:block; margin-top:8px; font-size:20px; font-weight:850; }
.wl-guide-layout { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(300px,.8fr); gap:18px; margin-top:18px; } .wl-guide-section { margin-top:18px; padding:24px; border:1px solid var(--wl-guide-border); border-radius:28px; background:rgba(255,255,255,.84); box-shadow:0 12px 36px rgba(51,35,76,.08); } .wl-guide-section h2 { display:flex; gap:10px; align-items:center; margin:0 0 14px; font-size:22px; line-height:1.25; letter-spacing:-.025em; } .wl-guide-icon { display:inline-grid; width:34px; height:34px; place-items:center; border-radius:12px; background:var(--wl-guide-panel-soft); } .wl-guide-lead { margin:0; color:var(--wl-guide-muted); font-size:15px; }
.wl-guide-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:18px; } .wl-guide-card { padding:18px; border:1px solid var(--wl-guide-border); border-radius:20px; background:#fff; } .wl-guide-card p { display:block; margin-top:8px; color:var(--wl-guide-muted); font-size:13px; } .wl-guide-card h3 { margin:0 0 8px; font-size:16px; } .wl-guide-card p { margin:0; font-size:14px; }
.wl-guide-action-list,.wl-guide-list { display:grid; gap:10px; margin:16px 0 0; padding:0; list-style:none; } .wl-guide-action-list li,.wl-guide-list li { position:relative; padding:14px 14px 14px 42px; border:1px solid var(--wl-guide-border); border-radius:18px; background:#fff; } .wl-guide-action-list li::before { content:"✓"; position:absolute; left:14px; top:14px; width:20px; height:20px; display:grid; place-items:center; border-radius:50%; color:#fff; background:var(--wl-guide-good); font-size:12px; font-weight:900; } .wl-guide-list li::before { content:"•"; position:absolute; left:18px; color:var(--wl-guide-primary); font-weight:900; }
.wl-guide-risk { border-left:5px solid var(--wl-guide-warn); } .wl-guide-risk-high { border-left-color:var(--wl-guide-risk); } .wl-guide-risk-level { display:inline-flex; margin-bottom:8px; padding:4px 9px; border-radius:999px; color:#7c2d12; background:#ffedd5; font-size:12px; font-weight:800; } .wl-guide-rationale { margin-top:14px; padding:14px; border:1px solid #dbeafe; border-radius:18px; background:#eff6ff; } .wl-guide-rationale h4 { margin-top:0; } .wl-guide-market-note { margin-top:14px; padding:14px; border-radius:18px; background:#f8fafc; color:#475569; font-size:13px; } .wl-guide-source { display:block; margin-top:10px; color:var(--wl-guide-primary); overflow-wrap:anywhere; word-break:break-word; } .wl-guide-source-list { display:grid; gap:10px; margin:12px 0 0; padding:0; list-style:none; } .wl-guide-source-item { padding:12px 14px; border:1px solid var(--wl-guide-border); border-radius:16px; background:#f8fafc; } .wl-guide-source-item a { color:var(--wl-guide-primary); font-weight:800; text-decoration:none; } .wl-guide-source-item small { display:block; margin-top:4px; color:var(--wl-guide-muted); } .wl-guide-source-item p { margin:6px 0 0; font-size:13px; } .wl-guide-signal-wrap { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; } .wl-guide-signal { padding:7px 10px; border:1px solid var(--wl-guide-border); border-radius:999px; background:var(--wl-guide-panel-soft); font-size:13px; font-weight:700; } .wl-guide-footer { margin-top:18px; padding:18px 24px; border:1px solid var(--wl-guide-border); border-radius:22px; color:var(--wl-guide-muted); background:rgba(255,255,255,.64); font-size:13px; }
@media (max-width:920px) { .wl-guide-layout,.wl-guide-meta-grid,.wl-guide-card-grid { grid-template-columns:1fr; } }
"""


def _esc(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)



def _items(values: Any, *, checklist: bool = False) -> str:
    entries = [str(item).strip() for item in (values or []) if str(item).strip()]
    class_name = "wl-guide-action-list" if checklist else "wl-guide-list"
    if not entries:
        return ""
    return f'<ul class="{class_name}">' + "".join(f"<li>{_esc(item)}</li>" for item in entries) + "</ul>"


SOURCE_CATEGORY_LABELS = {
    "platform_reference": "플랫폼 정책·운영 기준",
    "genre_trend": "장르·태그 관측",
    "title_synopsis_style": "제목·소개문 관습",
    "reader_hook": "독자 훅·태그 표현",
}

SOURCE_TYPE_LABELS = {
    "trusted": "공식·플랫폼 출처",
    "reference": "참고 출처",
}


def _source_items(values: Any) -> str:
    entries: list[str] = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or item.get("domain") or "공개 근거").strip()
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        domain = str(item.get("domain") or "").strip()
        raw_category = str(item.get("category") or "").strip()
        raw_source_type = str(item.get("source_type") or "").strip()
        category = SOURCE_CATEGORY_LABELS.get(raw_category, raw_category)
        source_type = SOURCE_TYPE_LABELS.get(raw_source_type, raw_source_type)
        summary = str(item.get("summary") or "").strip()
        meta = " · ".join(value for value in (domain, category, source_type) if value)
        entries.append(
            '<li class="wl-guide-source-item">'
            f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title)}</a>'
            f'{f"<small>{_esc(meta)}</small>" if meta else ""}'
            f'{f"<p>{_esc(summary)}</p>" if summary else ""}'
            '</li>'
        )
    if not entries:
        return ""
    return '<ul class="wl-guide-source-list">' + "".join(entries) + "</ul>"


def _dedupe_entries(values: Any) -> list[str]:
    deduped: list[str] = []
    for item in values or []:
        text = str(item).strip()
        if not text or text in deduped:
            continue
        deduped.append(text)
    return deduped



def render_country_recommendation_html(result: dict[str, Any]) -> str:
    """Render a source-grounded synopsis country comparison without duplicating work analysis."""
    profile = result.get("storyProfile") or {}
    title = profile.get("title") or result.get("title") or "입력 작품"
    genre = profile.get("genre") or result.get("genre") or "장르 미입력"
    status = str(result.get("recommendationStatus") or "")
    insufficient = status == "insufficient_evidence" or not result.get("recommendedCountry")
    recommendation = (
        "추천 보류"
        if insufficient
        else result.get("recommendedCountryDisplay") or result.get("recommendedCountry") or "추천 결과 없음"
    )
    signals = _dedupe_entries(profile.get("coreSignals") or [])
    analysis_summary = str(profile.get("analysisSummary") or "입력 시놉시스의 핵심 구조를 분석했습니다.")

    def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            rank = 99
        return rank, str(item.get("country") or "")

    comparisons = sorted(result.get("countryComparisons") or [], key=_sort_key)
    cards: list[str] = []
    for item in comparisons:
        country = item.get("displayCountry") or item.get("country") or "국가"
        rank = item.get("rank")
        evidence_level = item.get("evidenceLevel") or "확인 필요"
        ranking_label = (
            f"#{_esc(rank)} · 우선 검토" if not insufficient and rank else f"근거 수준 · {_esc(evidence_level)}"
        )
        source_html = _source_items(item.get("liveEvidence"))
        cards.append(
            f'''<article class="wl-guide-card">
  <span class="wl-guide-risk-level">{ranking_label}</span>
  <h3>{_esc(country)}</h3><p>{_esc(item.get('fitLevel') or '근거 확인')}</p>
  <h4>작품과 연결되는 지점</h4>{_items(item.get('strengths'))}
  <div class="wl-guide-rationale"><h4>근거 요약</h4>{_items(item.get('evidenceSummary'))}</div>
  {f'<h4>확인한 공개 출처</h4>{source_html}' if source_html else ''}
  <h4>현지화·정책 확인점</h4>{_items(item.get('risks'))}
</article>'''
        )

    if insufficient:
        comparison_title = "국가별 근거 상태"
        comparison_lead = COMPARISON_WITHHELD_MESSAGE
        guide_title = "추천이 보류된 이유"
        guide_text = COMPARISON_WITHHELD_MESSAGE
        result_type = "근거 수집 후 직접 선택"
        meta_label = "추천 상태"
        footer = "작품 분석은 LLM이 생성했고, 국가별 설명은 표시된 공개 출처 범위에서만 작성했습니다."
    else:
        comparison_title = "국가 우선순위 비교"
        comparison_lead = "순위는 최신 공개 플랫폼·정책 자료와 작품 신호를 연결한 검토 순서이며 흥행 확률이 아닙니다."
        guide_title = "추천 결과 읽는 법"
        guide_text = result.get("message") or f"{recommendation}을 먼저 검토할 수 있습니다. 각 카드의 실제 출처와 현지화 부담을 함께 확인하세요."
        result_type = "최신 공개 근거 비교"
        meta_label = "우선 검토"
        footer = COMPARISON_REFERENCE_FOOTER

    limitations = _dedupe_entries(result.get("limitations") or [])
    if not limitations:
        limitations = ["검색 결과는 전체 시장 통계가 아니며 실제 출시 전 최신 공식 정책을 확인해야 합니다."]
    signal_html = "".join(f'<span class="wl-guide-signal">{_esc(signal)}</span>' for signal in signals)

    body = f'''<main class="wl-guide-page">
  <section class="wl-guide-hero">
    <div class="wl-guide-eyebrow">Synopsis country recommendation</div>
    <h1>{_esc(title)}</h1>
    <div class="wl-guide-meta-grid">
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">장르</span><strong class="wl-guide-meta-value">{_esc(genre)}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">{_esc(meta_label)}</span><strong class="wl-guide-meta-value">{_esc(recommendation)}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">판단 신뢰도</span><strong class="wl-guide-meta-value">{_esc(result.get('confidence') or '근거 확인')}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">결과 유형</span><strong class="wl-guide-meta-value">{_esc(result_type)}</strong></div>
    </div>
  </section>
  <div class="wl-guide-layout"><div>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">📌</span>작품 분석</h2><p class="wl-guide-lead">{_esc(analysis_summary)}</p>{f'<div class="wl-guide-signal-wrap">{signal_html}</div>' if signal_html else ''}</section>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">🌏</span>{_esc(comparison_title)}</h2><p class="wl-guide-lead">{_esc(comparison_lead)}</p><div class="wl-guide-card-grid">{''.join(cards) or '<p class="wl-guide-lead">표시할 국가별 공개 근거가 없습니다.</p>'}</div></section>
  </div><aside>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">🧭</span>{_esc(guide_title)}</h2><p class="wl-guide-lead">{_esc(guide_text)}</p></section>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">⚠️</span>근거와 한계</h2>{_items(limitations)}</section>
  </aside></div>
  <footer class="wl-guide-footer">{_esc(footer)}</footer>
</main>'''
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>{_esc(title)} 국가 추천</title><style>{COUNTRY_RECOMMENDATION_CSS}</style></head><body>{body}</body></html>'''



__all__ = [
    "COMPARISON_REFERENCE_FOOTER",
    "COMPARISON_WITHHELD_MESSAGE",
    "COUNTRY_RECOMMENDATION_CSS",
    "UNGROUNDED_MARKET_LIMITATION",
    "render_country_recommendation_html",
]
