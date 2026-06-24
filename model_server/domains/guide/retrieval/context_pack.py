from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import ROOT

OBSERVATION_DIR = ROOT / "data" / "platform_observation"
TAG_ANALYTICS_DIR = OBSERVATION_DIR / "tag_analytics"
CONTEXT_DIR = OBSERVATION_DIR / "context_packs"

MARKET_PACKS = {
    "china": "china_observation_context_ko.json",
    "cn": "china_observation_context_ko.json",
    "english": "english_observation_context_ko.json",
    "en": "english_observation_context_ko.json",
    "en-us": "english_observation_context_ko.json",
    "en_us": "english_observation_context_ko.json",
    "us": "english_observation_context_ko.json",
    "usa": "english_observation_context_ko.json",
    "united states": "english_observation_context_ko.json",
    "global english": "english_observation_context_ko.json",
    "us/global english": "english_observation_context_ko.json",
    "japan": "japan_observation_context_ko.json",
    "jp": "japan_observation_context_ko.json",
    "thailand": "thailand_observation_context_ko.json",
    "th": "thailand_observation_context_ko.json",
}

MARKET_CANONICAL = {
    "china_observation_context_ko.json": "china",
    "english_observation_context_ko.json": "english",
    "japan_observation_context_ko.json": "japan",
    "thailand_observation_context_ko.json": "thailand",
}

GENRE_SIGNAL_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("romance", "로맨스", "로판", "연애", "로맨틱", "멜로", "혐관"), ("로맨스",)),
    (("comedy", "코미디", "러브코미디", "로코"), ("코미디",)),
    (("drama", "드라마", "휴먼", "멜로", "치유"), ("드라마",)),
    (("fantasy", "판타지", "이세계", "전생", "회귀"), ("판타지",)),
    (("action", "액션", "전투", "헌터"), ("액션",)),
    (("bl", "boys love", "보이즈러브", "남성 간 로맨스", "오메가버스"), ("BL",)),
)

SYNOPSIS_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("romance", "love", "marriage", "로맨스", "사랑", "연애", "결혼", "약혼", "재회", "전애인", "혐관", "계약연애"), "로맨스"),
    (("comedy", "코미디", "유쾌", "웃음", "로맨틱 코미디", "로코"), "코미디"),
    (("drama", "드라마", "상처", "치유", "트라우마", "휴먼", "감정 서사"), "드라마"),
    (("fantasy", "판타지", "마법", "이세계", "회귀", "전생", "빙의", "환생"), "판타지"),
    (("action", "액션", "전투", "전쟁", "생존", "헌터", "던전"), "액션"),
    (("school", "학교", "학원", "아카데미"), "학원"),
    (("bl", "boys love", "보이즈러브", "남성 간 로맨스", "오메가버스"), "BL"),
    (("r18", "18+", "성인물", "성인 로맨스"), "성인"),
    (("r15", "15+", "청소년"), "청소년"),
)


def resolve_context_market(target_market: str | None) -> str | None:
    raw = str(target_market or "").strip()
    if not raw:
        return None
    filename = MARKET_PACKS.get(raw.lower()) or MARKET_PACKS.get(raw)
    return MARKET_CANONICAL.get(filename or "")


def inspect_context_pack_source(target_market: str | None) -> dict[str, Any]:
    resolved = resolve_context_market(target_market)
    if not resolved:
        return {
            "resolvedTargetMarket": None,
            "contextPackSourceFound": False,
            "contextPackSourceRecordCount": 0,
            "contextPackUseLimits": [],
            "contextPackSkipReason": "unsupported_market",
        }

    path = _market_pack_path(resolved)
    if not path.exists():
        return {
            "resolvedTargetMarket": resolved,
            "contextPackSourceFound": False,
            "contextPackSourceRecordCount": 0,
            "contextPackUseLimits": [],
            "contextPackSkipReason": "source_not_found",
        }

    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "resolvedTargetMarket": resolved,
            "contextPackSourceFound": False,
            "contextPackSourceRecordCount": 0,
            "contextPackUseLimits": [],
            "contextPackSkipReason": "source_not_found",
        }

    record_count = int(pack.get("record_count") or 0)
    return {
        "resolvedTargetMarket": resolved,
        "contextPackSourceFound": True,
        "contextPackSourceRecordCount": record_count,
        "contextPackUseLimits": pack.get("use_limits") or [],
        "contextPackSkipReason": None if record_count else "no_source_records",
    }


@dataclass(frozen=True)
class WorkInput:
    title: str
    target_market: str
    genre: str = ""
    synopsis: str = ""
    declared_signals: tuple[str, ...] = ()
    title_elements: tuple[str, ...] = ()
    comparable_signals: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkInput":
        title_elements = tuple(
            str(item).strip()
            for item in (payload.get("title_elements") or payload.get("titleElements") or [])
            if str(item).strip()
        )
        comparable_signals = tuple(
            str(item).strip()
            for item in (payload.get("comparable_signals") or payload.get("comparableSignals") or [])
            if str(item).strip()
        )
        declared_signals = tuple(
            str(item).strip()
            for item in (payload.get("declared_signals") or payload.get("signals") or [])
            if str(item).strip()
        )
        return cls(
            title=str(payload.get("title") or payload.get("workTitle") or "Untitled"),
            target_market=str(
                payload.get("target_market")
                or payload.get("targetMarket")
                or payload.get("market")
                or payload.get("targetCountry")
                or "japan"
            ),
            genre=str(payload.get("genre") or ""),
            synopsis=str(payload.get("synopsis") or payload.get("desc") or ""),
            declared_signals=declared_signals,
            title_elements=title_elements,
            comparable_signals=comparable_signals,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "target_market": self.target_market,
            "genre": self.genre,
            "synopsis": self.synopsis,
            "declared_signals": list(self.declared_signals),
            "title_elements": list(self.title_elements),
            "comparable_signals": list(self.comparable_signals),
        }


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _market_pack_path(target_market: str) -> Path:
    raw = str(target_market or "").strip()
    filename = MARKET_PACKS.get(raw.lower()) or MARKET_PACKS.get(raw)
    if not filename:
        raise ValueError(f"Unsupported target_market={target_market!r}")
    return CONTEXT_DIR / filename


def load_market_context_pack(target_market: str) -> dict[str, Any]:
    path = _market_pack_path(target_market)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_processed_json(filename: str) -> Any:
    path = TAG_ANALYTICS_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _market_value(evidence: dict[str, Any]) -> str:
    return str(evidence.get("target_market") or evidence.get("work", {}).get("target_market") or "")


def _label_dictionary_by_ko() -> dict[str, dict[str, Any]]:
    payload = _load_processed_json("label_dictionary.json") or {}
    return {str(item.get("label_ko")): item for item in payload.get("labels") or []}


def _label_category(label_ko: str) -> str:
    item = _label_dictionary_by_ko().get(label_ko)
    return str(item.get("category") or "other") if item else "other"


def _split_genre_elements(genre: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[\n,/;|·]+", str(genre or "")) if part.strip()]
    signals: list[str] = []
    for part in parts:
        signals.append(part)
        lowered = part.lower()
        for aliases, normalized in GENRE_SIGNAL_ALIASES:
            if any(alias.lower() in lowered for alias in aliases):
                signals.extend(normalized)
    return _dedupe(signals)


def _input_elements(work: WorkInput) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in work.title_elements:
        rows.append({"element": item, "source": "title", "source_label": "제목"})
    for item in _split_genre_elements(work.genre):
        rows.append({"element": item, "source": "genre", "source_label": "장르"})
    for item in work.comparable_signals:
        rows.append({"element": item, "source": "comparable", "source_label": "비교 신호"})
    for item in work.declared_signals:
        rows.append({"element": item, "source": "declared", "source_label": "사용자 신호"})
    for item in _synopsis_hint_elements(work.synopsis):
        rows.append({"element": item, "source": "synopsis", "source_label": "시놉시스"})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["source"], row["element"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _signal_in_label(element: str, label: str) -> bool:
    signal = str(element or "").strip()
    target = str(label or "").strip()
    if not signal or not target:
        return False
    if signal.isascii() and len(signal) <= 3:
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(signal)}(?![A-Za-z0-9])", target, flags=re.IGNORECASE))
    return signal.lower() in target.lower()


def _match_from_labels(element: str, labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in labels:
        label_ko = str(item.get("label_ko") or "")
        label_original = str(item.get("label_original") or "")
        if _signal_in_label(element, label_ko) or _signal_in_label(element, label_original):
            matches.append(item)
    return matches


def _candidate_observations(candidates: list[str], labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        matches = _match_from_labels(candidate, labels)
        if matches:
            out.append(
                {
                    "label_ko": candidate,
                    "aggregate": matches[0],
                    "platform_balanced": matches[0],
                    "source_labels": [item.get("label_original") or item.get("label_ko") for item in matches[:3]],
                }
            )
    return out


def _synopsis_hint_elements(synopsis: str) -> list[str]:
    text = str(synopsis or "").lower()
    if not text:
        return []
    hints: list[str] = []
    for needles, label in SYNOPSIS_HINTS:
        if any(needle.lower() in text for needle in needles):
            hints.append(label)
    return _dedupe(hints)


def _match_input_element(element: str, labels: list[dict[str, Any]]) -> dict[str, Any]:
    matches = _match_from_labels(element, labels)
    if matches:
        return {
            "status": "direct",
            "observed_label": element,
            "aggregate": matches[0],
            "platform_balanced": matches[0],
            "candidate_observations": [],
            "note": None,
        }
    inferred = _candidate_observations(_synopsis_hint_elements(element), labels)
    if inferred:
        return {
            "status": "inferred",
            "observed_label": inferred[0]["label_ko"],
            "aggregate": inferred[0]["aggregate"],
            "platform_balanced": inferred[0]["platform_balanced"],
            "candidate_observations": inferred,
            "note": "시놉시스 추정 신호",
        }
    return {
        "status": "missing",
        "observed_label": None,
        "aggregate": None,
        "platform_balanced": None,
        "candidate_observations": [],
        "note": "매칭 없음",
    }


def _row_primary_count(row: dict[str, Any]) -> Any:
    return (row.get("aggregate") or {}).get("count") or (row.get("platform_balanced") or {}).get("count")


def _row_primary_share(row: dict[str, Any]) -> Any:
    return (row.get("aggregate") or {}).get("share") or (row.get("platform_balanced") or {}).get("share")


def _row_platform_coverage_text(row: dict[str, Any]) -> str:
    aggregate = row.get("aggregate") or {}
    balanced = row.get("platform_balanced") or {}
    if aggregate.get("platform_spread"):
        spread = aggregate["platform_spread"]
        return f"{spread.get('observed')}/{spread.get('total')} 개 플랫폼"
    if balanced.get("platform_spread"):
        spread = balanced["platform_spread"]
        return f"{spread.get('observed')}/{spread.get('total')} 개 플랫폼"
    return "-"


def _overlap_sentence(row: dict[str, Any], market_ko: str) -> str:
    label = row.get("observed_label") or row.get("element") or "-"
    count = _row_primary_count(row) or 0
    share = _pct(_row_primary_share(row))
    return f"{market_ko}에서 {label} 신호가 {count}회, 점유율 {share}로 관측됩니다."


def build_deterministic_evidence(work: WorkInput | dict[str, Any], pack: dict[str, Any] | None = None) -> dict[str, Any]:
    work = work if isinstance(work, WorkInput) else WorkInput.from_dict(work)
    pack = pack or load_market_context_pack(work.target_market)
    labels = pack.get("observed_top_labels") or []
    input_elements = _input_elements(work)
    direct_signal_rows = []
    matched_rows = []
    unmatched_rows = []
    for row in input_elements:
        matched = _match_input_element(row["element"], labels)
        direct_signal_rows.append(
            {
                "work_signal": row["element"],
                "source": row["source"],
                "source_label": row["source_label"],
                "direct_observation": "observed" if matched["status"] != "missing" else "unobserved",
                "match_status": matched["status"],
                "observed_label": matched["observed_label"],
                "candidate_observations": matched["candidate_observations"],
                "aggregate": matched["aggregate"],
                "platform_balanced": matched["platform_balanced"],
            }
        )
        if matched["status"] == "missing":
            unmatched_rows.append(row["element"])
        else:
            matched_rows.append(row["element"])

    market_ko = str(pack.get("market_ko") or work.target_market)
    evidence = {
        "target_market": work.target_market,
        "target_market_ko": market_ko,
        "record_count": int(pack.get("record_count") or 0),
        "context_record_count": int(pack.get("record_count") or 0),
        "platforms": pack.get("platforms") or [],
        "signal_types": pack.get("signal_types") or [],
        "use_limits": pack.get("use_limits") or [],
        "source": inspect_context_pack_source(work.target_market),
        "work": work.to_dict(),
        "input_elements": input_elements,
        "direct_signal_rows": direct_signal_rows,
        "matched_signal_rows": matched_rows,
        "unmatched_signal_rows": unmatched_rows,
        "summary": {
            "declared_signal_count": len(work.declared_signals),
            "observed_signal_count": len(direct_signal_rows),
            "matched_signal_count": len(matched_rows),
        },
        "signal_types_by_label": {str(item.get("label_ko") or ""): _label_category(str(item.get("label_ko") or "")) for item in labels},
        "data_limits": pack.get("use_limits") or [],
    }
    return evidence


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


def render_context_pack_overlap_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        f"# Context Pack: {evidence.get('target_market_ko') or evidence.get('target_market')}",
        f"- records: {evidence.get('context_record_count') or 0}",
        f"- platforms: {', '.join(evidence.get('platforms') or []) or '-'}",
        f"- signal types: {', '.join(evidence.get('signal_types') or []) or '-'}",
    ]
    for row in (evidence.get("direct_signal_rows") or [])[:8]:
        lines.append(f"- {row.get('work_signal')}: {row.get('match_status')}")
    return "\n".join(lines)


def render_context_pack_overlap_html(evidence: dict[str, Any]) -> str:
    title = _esc(evidence.get("target_market_ko") or evidence.get("target_market"))
    platform_chips = "".join(f"<span class='chip'>{_esc(item)}</span>" for item in (evidence.get("platforms") or []))
    rows = [
        (
            str(item.get("work_signal") or "-"),
            float(1 if item.get("match_status") != "missing" else 0),
            str(item.get("match_status") or "-"),
        )
        for item in (evidence.get("direct_signal_rows") or [])[:8]
    ]
    return f"""
<section class="section market-snapshot">
  <h2>{title} 컨텍스트 팩</h2>
  <div class="chips">{platform_chips or '<span class="chip">플랫폼 없음</span>'}</div>
  <div class="grid" style="margin-top:14px">
    <article class="chart-card"><h3>입력 신호 매칭</h3>{_bar_rows(rows, max_rows=8)}</article>
  </div>
</section>
"""


def build_ui_briefing_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    labels = evidence.get("work", {}).get("title_elements") or []
    top_labels = (evidence.get("direct_signal_rows") or [])[:8]
    return {
        "headline_market_labels": [
            {
                "label_ko": row.get("observed_label") or row.get("work_signal"),
                "count": 1 if row.get("match_status") != "missing" else 0,
                "share": 1.0 if row.get("match_status") != "missing" else 0.0,
            }
            for row in top_labels
            if row.get("observed_label") or row.get("work_signal")
        ],
        "cooccurrence_cards": [
            {
                "labels": [labels[i], labels[i + 1]] if i + 1 < len(labels) else [labels[i]],
                "count": 1,
                "platform_spread": {"observed": 1, "total": max(1, len(evidence.get("platforms") or []))},
            }
            for i in range(min(len(labels), 3))
        ],
        "summary": evidence.get("target_market_ko"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def build_context_pack_overlap_report(work: WorkInput | dict[str, Any]) -> dict[str, Any]:
    evidence = build_deterministic_evidence(work)
    briefing = build_ui_briefing_payload(evidence)
    html_report = render_context_pack_overlap_html(evidence)
    return {
        "work": evidence.get("work") or {},
        "evidence": evidence,
        "ui_briefing_payload": briefing,
        "markdown_report": render_context_pack_overlap_markdown(evidence),
        "html_report": html_report,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "CONTEXT_DIR",
    "TAG_ANALYTICS_DIR",
    "WorkInput",
    "build_context_pack_overlap_report",
    "build_deterministic_evidence",
    "build_ui_briefing_payload",
    "inspect_context_pack_source",
    "load_market_context_pack",
    "resolve_context_market",
]
