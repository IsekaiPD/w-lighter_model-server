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
.wl-guide-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:18px; } .wl-guide-card { padding:18px; border:1px solid var(--wl-guide-border); border-radius:20px; background:#fff; break-inside:avoid; page-break-inside:avoid; } .wl-guide-card p { display:block; margin-top:8px; color:var(--wl-guide-muted); font-size:13px; } .wl-guide-card h3 { margin:0 0 8px; font-size:16px; } .wl-guide-card p { margin:0; font-size:14px; }
.wl-guide-action-list,.wl-guide-list { display:grid; gap:10px; margin:16px 0 0; padding:0; list-style:none; } .wl-guide-action-list li,.wl-guide-list li { position:relative; padding:14px 14px 14px 42px; border:1px solid var(--wl-guide-border); border-radius:18px; background:#fff; } .wl-guide-action-list li::before { content:"✓"; position:absolute; left:14px; top:14px; width:20px; height:20px; display:grid; place-items:center; border-radius:50%; color:#fff; background:var(--wl-guide-good); font-size:12px; font-weight:900; } .wl-guide-list li::before { content:"•"; position:absolute; left:18px; color:var(--wl-guide-primary); font-weight:900; }
.wl-guide-risk { border-left:5px solid var(--wl-guide-warn); } .wl-guide-risk-high { border-left-color:var(--wl-guide-risk); } .wl-guide-risk-level { display:inline-flex; margin-bottom:8px; padding:4px 9px; border-radius:999px; color:#7c2d12; background:#ffedd5; font-size:12px; font-weight:800; } .wl-guide-rationale { margin-top:14px; padding:14px; border:1px solid #dbeafe; border-radius:18px; background:#eff6ff; } .wl-guide-rationale h4 { margin-top:0; } .wl-guide-market-note { margin-top:14px; padding:14px; border-radius:18px; background:#f8fafc; color:#475569; font-size:13px; } .wl-guide-source { display:block; margin-top:10px; color:var(--wl-guide-primary); overflow-wrap:anywhere; word-break:break-word; } .wl-guide-source-list { display:grid; gap:10px; margin:12px 0 0; padding:0; list-style:none; } .wl-guide-source-item { padding:12px 14px; border:1px solid var(--wl-guide-border); border-radius:16px; background:#f8fafc; } .wl-guide-source-item a { color:var(--wl-guide-primary); font-weight:800; text-decoration:none; } .wl-guide-source-item small { display:block; margin-top:4px; color:var(--wl-guide-muted); } .wl-guide-source-item p { margin:6px 0 0; font-size:13px; } .wl-guide-source-details { margin-top:10px; } .wl-guide-source-details summary { cursor:pointer; color:var(--wl-guide-primary); font-weight:800; } .wl-guide-source-details[open] summary { margin-bottom:10px; } .wl-guide-signal-wrap { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; } .wl-guide-signal { padding:7px 10px; border:1px solid var(--wl-guide-border); border-radius:999px; background:var(--wl-guide-panel-soft); font-size:13px; font-weight:700; } .wl-guide-footer { margin-top:18px; padding:18px 24px; border:1px solid var(--wl-guide-border); border-radius:22px; color:var(--wl-guide-muted); background:rgba(255,255,255,.64); font-size:13px; }
@media (max-width:920px) { .wl-guide-layout,.wl-guide-meta-grid,.wl-guide-card-grid { grid-template-columns:1fr; } }
@media print { .wl-guide-layout,.wl-guide-meta-grid,.wl-guide-card-grid { grid-template-columns:1fr; } .wl-guide-card { break-inside:avoid; page-break-inside:avoid; } .wl-guide-section { break-inside:avoid; page-break-inside:avoid; } }
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


def _source_items(values: Any, *, categories: set[str] | None = None) -> str:
    entries: list[str] = []
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    for item in values or []:
        if not isinstance(item, dict):
            continue
        raw_category = str(item.get("category") or "").strip()
        if categories is not None and raw_category not in categories:
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or item.get("domain") or "공개 근거").strip()
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen_urls:
            continue
        domain = str(item.get("domain") or "").strip()
        if domain and domain in seen_domains:
            continue
        seen_urls.add(url)
        if domain:
            seen_domains.add(domain)
        raw_source_type = str(item.get("source_type") or "").strip()
        category = SOURCE_CATEGORY_LABELS.get(raw_category, raw_category)
        source_type = SOURCE_TYPE_LABELS.get(raw_source_type, raw_source_type)
        meta = " · ".join(value for value in (domain, category, source_type) if value)
        entries.append(
            '<li class="wl-guide-source-item">'
            f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title)}</a>'
            f'{f"<small>{_esc(meta)}</small>" if meta else ""}'
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
    """Render a four-country synopsis analysis from validated structured data."""
    profile = result.get("storyProfile") or {}
    title = profile.get("title") or result.get("title") or "입력 작품"
    genre = profile.get("genre") or result.get("genre") or "장르 미입력"
    signals = _dedupe_entries(profile.get("coreSignals") or [])
    analysis_summary = str(profile.get("analysisSummary") or "입력 시놉시스의 핵심 구조를 분석했습니다.")
    country_order = {"US": 0, "CN": 1, "JP": 2, "TH": 3}
    comparisons = sorted(
        result.get("countryAnalyses") or result.get("countryComparisons") or [],
        key=lambda item: country_order.get(str(item.get("country") or ""), 99),
    )

    cards: list[str] = []
    for item in comparisons:
        country = item.get("displayCountry") or item.get("country") or "국가"
        fit_level = item.get("fitLevel") or "추가 확인 필요"
        evidence_level = item.get("evidenceLevel") or "확인 필요"
        market_source_html = _source_items(item.get("liveEvidence"), categories={"k_content_reception"})
        policy_source_html = _source_items(item.get("liveEvidence"), categories={"platform_reference"})
        evidence_level_html = f'<p>근거 수준 · {_esc(evidence_level)}</p>' if evidence_level and evidence_level not in ("없음", "확인 필요") else ""
        cards.append(
            f'''<article class="wl-guide-card">
  <span class="wl-guide-risk-level">{_esc(fit_level)}</span>
  <h3>{_esc(country)}</h3>{evidence_level_html}
  <h4>작품에서 잘 전달될 요소</h4>{_items(item.get('strengths'))}
  <h4>현지화에서 주의할 요소</h4>{_items(item.get('risks'))}
  <h4>현지화 난이도</h4><p>{_esc(item.get('localizationDifficulty') or '추가 확인 필요')}</p>
</article>'''
        )

    limitations = _dedupe_entries(result.get("limitations") or [])
    if not limitations:
        limitations = [UNGROUNDED_MARKET_LIMITATION]
    signal_html = "".join(f'<span class="wl-guide-signal">{_esc(signal)}</span>' for signal in signals)
    message = result.get("message") or "현재 시놉시스를 기준으로 4개국의 적합 요소와 주의 요소를 각각 정리했습니다."

    body = f'''<main class="wl-guide-page">
  <section class="wl-guide-hero">
    <div class="wl-guide-eyebrow">시놉시스 현지화 분석</div>
    <h1>{_esc(title)}</h1>
    <p>{_esc(message)}</p>
    <div class="wl-guide-meta-grid">
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">장르</span><strong class="wl-guide-meta-value">{_esc(genre)}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">분석 범위</span><strong class="wl-guide-meta-value">미국 · 중국 · 일본 · 태국</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">분석 방식</span><strong class="wl-guide-meta-value">국가별 독립 분석</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">결과 성격</span><strong class="wl-guide-meta-value">현지화 참고 자료</strong></div>
    </div>
  </section>
  <div class="wl-guide-layout"><div>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">📌</span>작품 분석</h2><p class="wl-guide-lead">{_esc(analysis_summary)}</p>{f'<div class="wl-guide-signal-wrap">{signal_html}</div>' if signal_html else ''}</section>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">🌏</span>국가별 현지화 적합성 분석</h2><p class="wl-guide-lead">점수나 순위를 표시하지 않고, 각 국가에서 확인되는 적합 요소와 주의 요소를 독립적으로 정리했습니다.</p><div class="wl-guide-card-grid">{''.join(cards) or '<p class="wl-guide-lead">표시할 국가별 분석 결과가 없습니다.</p>'}</div></section>
  </div><aside>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">🧭</span>결과 읽는 법</h2><p class="wl-guide-lead">각 카드의 판단은 다른 국가와의 우열이 아니라 해당 국가에서 작품을 전달할 때 확인되는 신호와 부담을 의미합니다.</p></section>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">⚠️</span>근거와 한계</h2>{_items(limitations)}</section>
  </aside></div>
  <footer class="wl-guide-footer">{_esc(COMPARISON_REFERENCE_FOOTER)}</footer>
</main>'''
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>{_esc(title)} 4개국 현지화 분석</title><style>{COUNTRY_RECOMMENDATION_CSS}</style></head><body>{body}</body></html>'''


__all__ = [
    "COMPARISON_REFERENCE_FOOTER",
    "COMPARISON_WITHHELD_MESSAGE",
    "COUNTRY_RECOMMENDATION_CSS",
    "UNGROUNDED_MARKET_LIMITATION",
    "render_country_recommendation_html",
]
