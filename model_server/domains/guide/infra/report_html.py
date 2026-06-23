"""Self-contained HTML document helpers for guide reports."""

from __future__ import annotations

from html import escape


GUIDE_REPORT_CSS = """
:root { --bg:#fff8fb; --panel:#fff; --text:#241528; --muted:#73606f; --line:#f0ddea; --ok:#8b2f83; --soft:#fff0fa; --accent:#d94697; --mint:#edfdf7; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR","Malgun Gothic",sans-serif; background:radial-gradient(circle at top left,#fff0fa,#fff8fb 38%,#f8fbff); color:var(--text); }
main { max-width:1120px; margin:0 auto; padding:32px 20px 48px; }
h1,h2,h3 { margin-top:0; }
h1 { font-size:34px; line-height:1.18; }
p,li { line-height:1.7; }
.guide-report { display:block; }
.guide-cover { background:linear-gradient(135deg,#7c2d8a,#ec4899); color:white; border-radius:28px; padding:34px; box-shadow:0 18px 40px rgba(124,45,138,.22); margin-bottom:18px; }
.guide-cover-label { color:#ffeaf7; font-size:13px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; margin-bottom:10px; }
.guide-cover-title { font-size:34px; font-weight:900; line-height:1.18; }
.guide-cover-title em { color:#ffeaf7; font-style:normal; font-weight:700; }
.guide-cover-sub { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
.guide-cover-sub span,.chip,.badge,.tag-chip { display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:7px 12px; font-size:13px; }
.guide-cover-sub span { background:rgba(255,255,255,.18); color:white; }
.guide-legacy-anchors { margin:0 0 18px; color:var(--muted); font-size:13px; font-weight:800; }
.section,.guide-section,.soft-card,.mini-card,.summary-box { background:rgba(255,255,255,.9); border:1px solid var(--line); border-radius:22px; padding:20px; box-shadow:0 10px 28px rgba(124,45,138,.06); }
.section,.guide-section { margin-top:18px; }
.guide-section-header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
.guide-section-title { color:var(--accent); font-size:16px; font-weight:900; }
.guide-list { margin:0; padding-left:20px; }
.guide-list li + li { margin-top:6px; }
.two,.work-summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; }
.work-summary > div { background:#fbf7fa; border:1px solid var(--line); border-radius:18px; padding:14px; }
.work-summary small { display:block; color:var(--muted); margin-bottom:4px; }
.work-summary strong { color:var(--text); }
.chips { display:flex; flex-wrap:wrap; gap:10px; }
.chip { background:#fdf2f8; color:#9d174d; font-weight:700; }
.chip.soft { background:#f5f0ff; color:#6d28d9; }
.tag-chip { background:#fff; border:1px solid var(--line); flex-direction:column; align-items:flex-start; border-radius:18px; }
.tag-chip small,.soft-card small { color:var(--muted); }
.badge.ok { color:var(--ok); background:var(--soft); font-weight:800; margin-top:10px; }
.muted-card { background:#fbf7fa; }
.eyebrow { color:var(--accent); font-size:13px; font-weight:800; margin:0 0 8px; }
.cards,.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr)); gap:14px; min-width:0; }
.mini-card,.chart-card { padding:14px; border-radius:18px; background:#fff; border:1px solid var(--line); box-shadow:0 8px 20px rgba(124,45,138,.05); min-width:0; overflow:hidden; }
.mini-card a,.mini-card h3,.mini-card small { max-width:100%; overflow-wrap:anywhere; word-break:break-word; }
a { color:var(--ok); overflow-wrap:anywhere; word-break:break-word; }
.chart-row { margin-top:10px; }
.chart-label { display:flex; justify-content:space-between; gap:12px; color:var(--muted); font-size:13px; margin-bottom:5px; }
.chart-track { height:9px; background:#f8e9f4; border-radius:999px; overflow:hidden; }
.chart-track span { display:block; height:100%; background:linear-gradient(90deg,#d94697,#8b2f83); border-radius:999px; }
.quiet-note,.notice { color:var(--muted); }
.quiet-note { background:#fbf7fa; border:1px solid var(--line); border-radius:18px; padding:14px; margin-top:12px; }
details { margin-top:18px; }
summary { cursor:pointer; color:var(--ok); font-weight:800; }
@media(max-width:760px) { main { padding:20px 12px 36px; } .guide-cover { padding:24px; border-radius:22px; } .guide-cover-title,h1 { font-size:28px; } }
"""


def build_guide_html_document(*, title: str, body_html: str) -> str:
    """Wrap guide report body in a full HTML document with embedded CSS.

    Relationship-map already returns `<!doctype html>...<style>...</style>`.
    Guide uses the same response contract so frontend rendering can be shared.
    """

    text = body_html.strip()
    if text.lower().startswith("<!doctype html"):
        return text
    safe_title = escape(title or "현지화 가이드", quote=True)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <style>
{GUIDE_REPORT_CSS}
  </style>
</head>
<body>
<main>
{text}
</main>
</body>
</html>"""


__all__ = ["GUIDE_REPORT_CSS", "build_guide_html_document"]
