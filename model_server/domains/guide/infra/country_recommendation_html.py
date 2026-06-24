"""HTML renderer for the synopsis country-comparison report."""

from __future__ import annotations

from html import escape
from typing import Any


COUNTRY_RECOMMENDATION_CSS = """
:root { --wl-guide-bg:#f7f3ff; --wl-guide-bg-2:#fff7fb; --wl-guide-panel:#fff; --wl-guide-panel-soft:#fbf8ff; --wl-guide-text:#201627; --wl-guide-muted:#6f6177; --wl-guide-border:#eadff3; --wl-guide-primary:#7c3aed; --wl-guide-primary-2:#ec4899; --wl-guide-good:#0f9f6e; --wl-guide-warn:#c47a10; --wl-guide-risk:#dc2626; --wl-guide-shadow:0 18px 50px rgba(51,35,76,.12); }
* { box-sizing:border-box; } body { margin:0; color:var(--wl-guide-text); background:radial-gradient(circle at 0 0,rgba(236,72,153,.16),transparent 32%),radial-gradient(circle at 100% 0,rgba(124,58,237,.16),transparent 36%),linear-gradient(135deg,var(--wl-guide-bg),var(--wl-guide-bg-2)); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR","Apple SD Gothic Neo",sans-serif; line-height:1.65; }
.wl-guide-page { max-width:1180px; margin:0 auto; padding:32px 20px 56px; } .wl-guide-hero { position:relative; overflow:hidden; border-radius:32px; padding:34px; color:#fff; background:linear-gradient(135deg,rgba(44,21,75,.92),rgba(124,58,237,.9)),linear-gradient(90deg,var(--wl-guide-primary),var(--wl-guide-primary-2)); box-shadow:var(--wl-guide-shadow); } .wl-guide-hero::after { content:""; position:absolute; right:-70px; top:-90px; width:260px; height:260px; border-radius:50%; background:rgba(255,255,255,.14); }
.wl-guide-eyebrow { position:relative; display:inline-flex; margin:0 0 14px; padding:6px 12px; border:1px solid rgba(255,255,255,.26); border-radius:999px; color:rgba(255,255,255,.9); font-size:13px; font-weight:700; } .wl-guide-hero h1 { position:relative; margin:0; font-size:clamp(30px,5vw,52px); line-height:1.08; letter-spacing:-.045em; } .wl-guide-hero p { position:relative; max-width:760px; margin:16px 0 0; color:rgba(255,255,255,.84); font-size:17px; }
.wl-guide-meta-grid { position:relative; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:28px; } .wl-guide-meta-card { min-height:94px; padding:16px; border:1px solid rgba(255,255,255,.18); border-radius:20px; background:rgba(255,255,255,.12); backdrop-filter:blur(10px); } .wl-guide-meta-label { color:rgba(255,255,255,.68); font-size:12px; font-weight:700; } .wl-guide-meta-value { display:block; margin-top:8px; font-size:20px; font-weight:850; }
.wl-guide-layout { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(300px,.8fr); gap:18px; margin-top:18px; } .wl-guide-section { margin-top:18px; padding:24px; border:1px solid var(--wl-guide-border); border-radius:28px; background:rgba(255,255,255,.84); box-shadow:0 12px 36px rgba(51,35,76,.08); } .wl-guide-section h2 { display:flex; gap:10px; align-items:center; margin:0 0 14px; font-size:22px; line-height:1.25; letter-spacing:-.025em; } .wl-guide-icon { display:inline-grid; width:34px; height:34px; place-items:center; border-radius:12px; background:var(--wl-guide-panel-soft); } .wl-guide-lead { margin:0; color:var(--wl-guide-muted); font-size:15px; }
.wl-guide-score-row,.wl-guide-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:18px; } .wl-guide-score,.wl-guide-card { padding:18px; border:1px solid var(--wl-guide-border); border-radius:20px; background:var(--wl-guide-panel-soft); } .wl-guide-card { background:#fff; } .wl-guide-score strong { display:block; font-size:28px; line-height:1; } .wl-guide-score span,.wl-guide-card p { display:block; margin-top:8px; color:var(--wl-guide-muted); font-size:13px; } .wl-guide-card h3 { margin:0 0 8px; font-size:16px; } .wl-guide-card p { margin:0; font-size:14px; }
.wl-guide-action-list,.wl-guide-list { display:grid; gap:10px; margin:16px 0 0; padding:0; list-style:none; } .wl-guide-action-list li,.wl-guide-list li { position:relative; padding:14px 14px 14px 42px; border:1px solid var(--wl-guide-border); border-radius:18px; background:#fff; } .wl-guide-action-list li::before { content:"✓"; position:absolute; left:14px; top:14px; width:20px; height:20px; display:grid; place-items:center; border-radius:50%; color:#fff; background:var(--wl-guide-good); font-size:12px; font-weight:900; } .wl-guide-list li::before { content:"•"; position:absolute; left:18px; color:var(--wl-guide-primary); font-weight:900; }
.wl-guide-risk { border-left:5px solid var(--wl-guide-warn); } .wl-guide-risk-high { border-left-color:var(--wl-guide-risk); } .wl-guide-risk-level { display:inline-flex; margin-bottom:8px; padding:4px 9px; border-radius:999px; color:#7c2d12; background:#ffedd5; font-size:12px; font-weight:800; } .wl-guide-rationale { margin-top:14px; padding:14px; border:1px solid #dbeafe; border-radius:18px; background:#eff6ff; } .wl-guide-rationale h4 { margin-top:0; } .wl-guide-market-note { margin-top:14px; padding:14px; border-radius:18px; background:#f8fafc; color:#475569; font-size:13px; } .wl-guide-source { display:block; margin-top:10px; color:var(--wl-guide-primary); overflow-wrap:anywhere; word-break:break-word; } .wl-guide-footer { margin-top:18px; padding:18px 24px; border:1px solid var(--wl-guide-border); border-radius:22px; color:var(--wl-guide-muted); background:rgba(255,255,255,.64); font-size:13px; }
@media (max-width:920px) { .wl-guide-layout,.wl-guide-meta-grid,.wl-guide-score-row,.wl-guide-card-grid { grid-template-columns:1fr; } }
"""


def _esc(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)



def _items(values: Any, *, checklist: bool = False) -> str:
    entries = [str(item).strip() for item in (values or []) if str(item).strip()]
    class_name = "wl-guide-action-list" if checklist else "wl-guide-list"
    if not entries:
        return ""
    return f'<ul class="{class_name}">' + "".join(f"<li>{_esc(item)}</li>" for item in entries) + "</ul>"




def render_country_recommendation_html(result: dict[str, Any]) -> str:
    """Render the pre-selection synopsis country comparison as a full document."""
    profile = result.get("storyProfile") or {}
    title = profile.get("title") or result.get("title") or "입력 작품"
    genre = profile.get("genre") or result.get("genre") or "장르 미입력"
    recommendation = result.get("recommendedCountryDisplay") or result.get("recommendedCountry") or "추천 결과 없음"
    signals = profile.get("coreSignals") or []
    comparisons = sorted(result.get("countryComparisons") or [], key=lambda item: int(item.get("rank") or 99))
    top = comparisons[0] if comparisons else {}
    top_evidence = top.get("evidenceSummary") or []
    cards = []
    for item in comparisons:
        country = item.get("displayCountry") or item.get("country") or "국가"
        score = max(0, min(100, int(float(item.get("relativeFitScore") or 0))))
        evidence_html = _items(item.get("evidenceSummary"))
        cards.append(
            f'''<article class="wl-guide-card">
  <span class="wl-guide-risk-level">#{_esc(item.get('rank') or '-')} · 적합도 {score}</span>
  <h3>{_esc(country)}</h3><p>{_esc(item.get('fitLevel') or '비교 검토')}</p>
  <h4>잘 맞는 지점</h4>{_items(item.get('strengths'))}
  {f'<div class="wl-guide-rationale"><h4>판단 근거</h4>{evidence_html}</div>' if evidence_html else ''}
  <h4>확인할 지점</h4>{_items(item.get('risks'))}
</article>'''
        )
    body = f'''<main class="wl-guide-page">
  <section class="wl-guide-hero">
    <div class="wl-guide-eyebrow">Synopsis country recommendation</div>
    <h1>{_esc(title)}</h1>
    <p>{_esc(profile.get('analysisSummary') or '시놉시스에서 드러난 매력을 기준으로 4개국의 전달 적합도를 비교했습니다.')}</p>
    <div class="wl-guide-meta-grid">
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">장르</span><strong class="wl-guide-meta-value">{_esc(genre)}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">우선 추천</span><strong class="wl-guide-meta-value">{_esc(recommendation)}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">판단 신뢰도</span><strong class="wl-guide-meta-value">{_esc(result.get('confidence') or '근거 기반 비교')}</strong></div>
      <div class="wl-guide-meta-card"><span class="wl-guide-meta-label">결과 유형</span><strong class="wl-guide-meta-value">4개국 적합도 비교</strong></div>
    </div>
  </section>
  <div class="wl-guide-layout"><div>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">📌</span>한눈에 보는 작품 분석</h2><p class="wl-guide-lead">{' · '.join(_esc(signal) for signal in signals) or '입력 시놉시스의 핵심 매력을 정리합니다.'}</p></section>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">🌏</span>국가 적합도 비교</h2><p class="wl-guide-lead">추천은 확정 배포 국가가 아닙니다. 각 시장의 전달 적합도와 주의점을 비교해 검토하세요.</p><div class="wl-guide-card-grid">{''.join(cards) or '<p class="wl-guide-lead">비교 결과를 준비하지 못했습니다.</p>'}</div></section>
  </div><aside>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">🧭</span>우선 추천을 읽는 법</h2><p class="wl-guide-lead">{_esc(recommendation)}은 지금 입력된 장르와 시놉시스 기준에서 먼저 검토하기 좋은 국가입니다. 아래 근거는 확정 배포 판단이 아니라 소개문·태그·정책 확인 우선순위를 잡기 위한 비교입니다.</p>{_items(top_evidence)}</section>
    <section class="wl-guide-section"><h2><span class="wl-guide-icon">⚠️</span>해석 시 유의점</h2>{_items(result.get('limitations') or ['추천 결과는 참고용이며, 실제 출시 전에는 플랫폼 정책과 현지화 표현을 별도로 확인하세요.'])}</section>
  </aside></div>
  <footer class="wl-guide-footer">이 결과는 작품 특성과 국가별 전달 환경을 비교한 결과입니다.</footer>
</main>'''
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>{_esc(title)} 국가 추천</title><style>{COUNTRY_RECOMMENDATION_CSS}</style></head><body>{body}</body></html>'''



__all__ = [
    "COUNTRY_RECOMMENDATION_CSS",
    "render_country_recommendation_html",
]
