from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domains.guide.config import ROOT
OBSERVATION_DIR = ROOT / "data" / "platform_observation"
TAG_ANALYTICS_DIR = OBSERVATION_DIR / "tag_analytics"
CONTEXT_DIR = OBSERVATION_DIR / "context_packs"

MARKET_PACKS = {
    "china": "china_observation_context_ko.json",
    "cn": "china_observation_context_ko.json",
    "중국": "china_observation_context_ko.json",
    "english": "english_observation_context_ko.json",
    "en": "english_observation_context_ko.json",
    "us": "english_observation_context_ko.json",
    "영어권": "english_observation_context_ko.json",
    "미국": "english_observation_context_ko.json",
    "japan": "japan_observation_context_ko.json",
    "jp": "japan_observation_context_ko.json",
    "일본": "japan_observation_context_ko.json",
    "thailand": "thailand_observation_context_ko.json",
    "th": "thailand_observation_context_ko.json",
    "태국": "thailand_observation_context_ko.json",
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
        title_elements = tuple(str(item) for item in payload.get("title_elements") or payload.get("titleElements") or [] if item)
        comparable_signals = tuple(
            str(item) for item in payload.get("comparable_signals") or payload.get("comparableSignals") or [] if item
        )
        return cls(
            title=str(payload.get("title") or "Untitled"),
            target_market=str(payload.get("target_market") or payload.get("targetMarket") or payload.get("market") or "japan"),
            genre=str(payload.get("genre") or ""),
            synopsis=str(payload.get("synopsis") or ""),
            declared_signals=tuple(str(item) for item in payload.get("declared_signals") or payload.get("signals") or [] if item),
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
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _market_pack_path(target_market: str) -> Path:
    raw = target_market.strip()
    key = raw.lower()
    filename = MARKET_PACKS.get(key) or MARKET_PACKS.get(raw)
    if not filename:
        available = ", ".join(sorted({"china", "english", "japan", "thailand"}))
        raise ValueError(f"Unsupported target_market={target_market!r}. Use one of: {available}")
    return CONTEXT_DIR / filename


def load_market_context_pack(target_market: str) -> dict[str, Any]:
    path = _market_pack_path(target_market)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_processed_json(filename: str) -> Any:
    path = TAG_ANALYTICS_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _market_value(evidence: dict[str, Any]) -> str:
    return str(evidence.get("target_market") or evidence.get("work", {}).get("target_market") or "")


def _label_dictionary_by_ko() -> dict[str, dict[str, Any]]:
    payload = _load_processed_json("label_dictionary.json") or {}
    return {str(item.get("label_ko")): item for item in payload.get("labels") or []}


def _market_projection(filename: str, market: str) -> dict[str, Any] | None:
    payload = _load_processed_json(filename) or []
    for item in payload:
        if str(item.get("market")) == market:
            return item
    return None


def _label_category(label_ko: str) -> str:
    item = _label_dictionary_by_ko().get(label_ko)
    return str(item.get("category") or "other") if item else "other"


SIGNAL_TYPE_LABELS = {
    "hot_24h": "24시간 인기작",
    "hot_fantasy": "인기 판타지",
    "trending": "실시간 인기작",
    "rising": "상승작",
    "weekly": "주간 랭킹",
    "weekly_popular": "주간 인기작",
    "weekly_ranking": "주간 랭킹",
    "weekly_r": "주간 랭킹",
    "monthly_rank": "월간 랭킹",
    "monthly_ranking": "월간 랭킹",
    "monthly_ticket": "월간 티켓 랭킹",
    "popular": "인기작",
    "popular_novels": "인기 소설",
    "homepage_ranking": "홈 화면 랭킹",
}


CATEGORY_LABELS = {
    "genre": "장르",
    "plot_device": "사건/소재",
    "tone": "분위기",
    "setting": "배경",
    "character": "인물",
    "content_flag": "민감 요소",
    "ending_signal": "결말 분위기",
    "other": "작품 태그",
}


def _writer_signal_type(value: Any) -> str:
    text = str(value or "").strip()
    return SIGNAL_TYPE_LABELS.get(text, text.replace("_", " ") or "순위권")


def _join_natural(items: list[str], fallback: str = "-") -> str:
    clean = [item for item in items if item]
    return " · ".join(dict.fromkeys(clean)) if clean else fallback


def _writer_limits(evidence: dict[str, Any]) -> list[str]:
    return [
        "이 화면은 “이렇게 바꾸세요”라고 말하는 추천서가 아닙니다.",
        f"{evidence['target_market_ko']} 플랫폼 순위권 작품들에서 어떤 태그가 함께 보였는지 정리한 참고 자료입니다.",
        "작품의 방향, 제목, 장르를 바꿀지 여부는 이 데이터만으로 판단하지 마세요.",
        "이번 데이터에서 보이지 않은 요소는 부적합하다는 뜻이 아니라, 살펴본 범위 안에서 직접 태그로 확인되지 않았다는 뜻입니다.",
        "플랫폼마다 공개 지표의 의미가 다르므로 숫자는 플랫폼 간 우열 비교가 아니라 참고값으로만 봐주세요.",
    ]


DECOMPOSED_LABELS = {
    "로맨스 판타지": ["연애/로맨스", "이세계 로맨스", "이세계 판타지", "로맨스"],
    "로판": ["연애/로맨스", "이세계 로맨스", "이세계 판타지", "로맨스"],
    "romance fantasy": ["연애/로맨스", "이세계 로맨스", "이세계 판타지", "로맨스"],
}


NEAR_LABELS = {
    "계약 결혼": ["혼약 파기", "정략결혼", "결혼"],
    "계약결혼": ["혼약 파기", "정략결혼", "결혼"],
    "몰락한 영지": ["국가/영지 건설", "내정", "신분상승/성공담"],
    "영지 재건": ["국가/영지 건설", "내정", "신분상승/성공담"],
    "재건": ["국가/영지 건설", "내정", "신분상승/성공담"],
    "성장": ["성장", "성장형 판타지", "신분상승/성공담"],
    "악역영애": ["악역영애", "영애", "악녀", "악역"],
    "귀족": ["귀족", "왕족/왕실", "지배 계층/귀족", "궁정/귀족"],
}

SYNOPSIS_HINTS = {
    "관계/로맨스 축": ["사랑", "연애", "로맨스", "결혼", "약혼", "공작", "왕자", "황태자", "악녀", "악역영애"],
    "회귀·전생·이세계 축": ["회귀", "전생", "빙의", "환생", "이세계"],
    "성장·시스템 축": ["성장", "레벨", "스킬", "시스템", "던전", "랭커"],
    "전투·생존 축": ["전투", "전쟁", "복수", "피", "잔혹", "생존", "멸망"],
    "연령/민감 표현 축": ["R15", "R18", "성적", "잔혹", "폭력", "유혈"],
}


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _synopsis_hint_elements(synopsis: str) -> list[str]:
    text = str(synopsis or "").lower()
    if not text:
        return []
    hints: list[str] = []
    for label, keywords in SYNOPSIS_HINTS.items():
        if any(keyword.lower() in text for keyword in keywords):
            hints.append(label)
    return _dedupe(hints)


def _input_elements(work: WorkInput) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in work.title_elements:
        rows.append({"element": item, "source": "title_explicit", "source_label": "제목에서 읽히는 요소"})
    if work.genre:
        rows.append({"element": work.genre, "source": "genre", "source_label": "장르"})
    for item in work.comparable_signals:
        rows.append({"element": item, "source": "comparable", "source_label": "장르상 함께 확인해볼 수 있는 요소"})
    for item in work.declared_signals:
        rows.append({"element": item, "source": "declared", "source_label": "작가가 명시한 요소"})
    for item in _synopsis_hint_elements(work.synopsis):
        rows.append({"element": item, "source": "synopsis_inferred", "source_label": "시놉시스에서 조심스럽게 추정한 요소"})

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if row["element"] in seen:
            continue
        seen.add(row["element"])
        deduped.append(row)
    return deduped


def _by_label(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("label_ko")): item for item in items}


def _lookup_label(label: str, aggregate: dict[str, dict[str, Any]], balanced: dict[str, dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return aggregate.get(label), balanced.get(label)


def _candidate_observations(
    candidates: list[str],
    aggregate: dict[str, dict[str, Any]],
    balanced: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        agg, bal = _lookup_label(candidate, aggregate, balanced)
        if agg or bal:
            out.append(
                {
                    "label_ko": candidate,
                    "aggregate": agg,
                    "platform_balanced": bal,
                    "source_labels": (agg or bal or {}).get("source_labels") or [],
                }
            )
    return out


def _match_input_element(
    element: str,
    aggregate: dict[str, dict[str, Any]],
    balanced: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    agg, bal = _lookup_label(element, aggregate, balanced)
    if agg or bal:
        return {
            "status": "direct",
            "observed_label": element,
            "aggregate": agg,
            "platform_balanced": bal,
            "candidate_observations": [],
            "note": None,
        }

    decomposed = _candidate_observations(DECOMPOSED_LABELS.get(element, []), aggregate, balanced)
    if decomposed:
        return {
            "status": "decomposed",
            "observed_label": None,
            "aggregate": None,
            "platform_balanced": None,
            "candidate_observations": decomposed,
            "note": "하나의 태그가 아니라 여러 가까운 태그로 나뉘어 보임",
        }

    near = _candidate_observations(NEAR_LABELS.get(element, []), aggregate, balanced)
    if near:
        return {
            "status": "near",
            "observed_label": None,
            "aggregate": None,
            "platform_balanced": None,
            "candidate_observations": near,
            "note": "동일 태그는 아니지만 가까운 맥락으로 비교 가능",
        }

    return {
        "status": "not_observed",
        "observed_label": None,
        "aggregate": None,
        "platform_balanced": None,
        "candidate_observations": [],
        "note": "이번 데이터에서는 직접 보이지 않음",
    }


STATUS_LABELS = {
    "direct": "직접 겹침",
    "near": "가까운 맥락",
    "decomposed": "나뉘어 보임",
    "not_observed": "이번 데이터에서는 직접 보이지 않음",
}


def _row_primary_count(row: dict[str, Any]) -> Any:
    if row.get("aggregate"):
        return row["aggregate"].get("count")
    candidates = row.get("candidate_observations") or []
    counts = [(item.get("aggregate") or {}).get("count") for item in candidates]
    counts = [count for count in counts if isinstance(count, (int, float))]
    return max(counts) if counts else None


def _row_primary_share(row: dict[str, Any]) -> Any:
    if row.get("aggregate"):
        return row["aggregate"].get("share")
    candidates = row.get("candidate_observations") or []
    shares = [(item.get("aggregate") or {}).get("share") for item in candidates]
    shares = [share for share in shares if isinstance(share, (int, float))]
    return max(shares) if shares else None


def _row_source_labels(row: dict[str, Any]) -> list[str]:
    if row.get("aggregate") or row.get("platform_balanced"):
        return (row.get("aggregate") or row.get("platform_balanced") or {}).get("source_labels") or []
    labels: list[str] = []
    for item in row.get("candidate_observations") or []:
        labels.extend(item.get("source_labels") or [])
    return _dedupe(labels)[:6]


def _row_candidate_labels(row: dict[str, Any]) -> list[str]:
    return [str(item.get("label_ko")) for item in row.get("candidate_observations") or [] if item.get("label_ko")]


def _row_platform_coverage_text(row: dict[str, Any]) -> str:
    balanced = row.get("platform_balanced") or {}
    platforms_observed = balanced.get("platforms_observed")
    platform_count = balanced.get("platform_count")
    if platforms_observed is not None and platform_count is not None:
        return f"{platforms_observed}/{platform_count} 플랫폼에서 보임"

    coverages: list[tuple[int, int]] = []
    for item in row.get("candidate_observations") or []:
        candidate_balanced = item.get("platform_balanced") or {}
        observed = candidate_balanced.get("platforms_observed")
        total = candidate_balanced.get("platform_count")
        if isinstance(observed, int) and isinstance(total, int):
            coverages.append((observed, total))
    if coverages:
        observed = max(value[0] for value in coverages)
        total = max(value[1] for value in coverages)
        return f"관련 태그 최대 {observed}/{total} 플랫폼에서 보임"
    return "플랫폼별 참고값 없음"


def _overlap_sentence(row: dict[str, Any], market_ko: str) -> str:
    signal = str(row["work_signal"])
    status = row.get("match_status")
    source = row.get("input_source")
    candidates = _row_candidate_labels(row)
    candidate_text = " · ".join(candidates[:4])
    if status == "direct":
        if source == "title_explicit":
            return f"{signal}: 제목에서 읽히는 요소가 {market_ko} 순위권 작품 태그 흐름과 직접 겹쳐 보입니다."
        return f"입력 작품에 {signal} 요소가 있다면 {market_ko} 순위권 태그 흐름과 함께 비교해볼 수 있습니다."
    if status == "decomposed":
        return f"{signal}: 이번 데이터에서는 하나의 태그보다 {candidate_text}처럼 나뉘어 보입니다."
    if status == "near":
        return f"{signal}: 동일 태그는 아니지만 {candidate_text} 계열과 가까운 맥락으로 비교해볼 수 있습니다."
    return "이번 데이터에서는 직접 보이지 않았습니다. 부적합하다는 뜻은 아니에요."


def build_deterministic_evidence(work: WorkInput | dict[str, Any], pack: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build deterministic context-pack overlap evidence.

    This deliberately avoids LLM inference. It only uses exact overlaps between
    user/work-provided signals and the already-built Korean context pack labels.
    """

    work_input = WorkInput.from_dict(work) if isinstance(work, dict) else work
    pack = pack or load_market_context_pack(work_input.target_market)
    input_rows = _input_elements(work_input)
    signals = [row["element"] for row in input_rows]

    aggregate = _by_label(pack.get("observed_top_label_groups") or [])
    balanced = _by_label(pack.get("platform_balanced_label_groups") or [])

    direct_rows: list[dict[str, Any]] = []
    observed_count = 0
    for input_row in input_rows:
        signal = input_row["element"]
        match = _match_input_element(signal, aggregate, balanced)
        observed = match["status"] in {"direct", "near", "decomposed"}
        observed_count += int(observed)
        direct_rows.append(
            {
                "work_signal": signal,
                "input_source": input_row["source"],
                "input_source_label": input_row["source_label"],
                "match_status": match["status"],
                "direct_observation": "observed" if observed else "not_observed",
                "observed_label": match.get("observed_label"),
                "candidate_observations": match.get("candidate_observations") or [],
                "aggregate": {
                    "count": match["aggregate"].get("count"),
                    "share": match["aggregate"].get("share"),
                    "source_labels": match["aggregate"].get("source_labels"),
                }
                if match["aggregate"]
                else None,
                "platform_balanced": {
                    "platforms_observed": match["platform_balanced"].get("platforms_observed"),
                    "platform_count": match["platform_balanced"].get("platform_count"),
                    "avg_platform_share": match["platform_balanced"].get("avg_platform_share"),
                    "max_platform_share": match["platform_balanced"].get("max_platform_share"),
                    "source_labels": match["platform_balanced"].get("source_labels"),
                }
                if match["platform_balanced"]
                else None,
                "note": match["note"],
            }
        )

    platform_rows: list[dict[str, Any]] = []
    for platform in pack.get("platform_summaries") or []:
        labels = _by_label(platform.get("top_label_groups") or [])
        hits = []
        for signal in signals:
            item = labels.get(signal)
            if item:
                hits.append(
                    {
                        "work_signal": signal,
                        "count": item.get("count"),
                        "share": item.get("share"),
                        "source_labels": item.get("source_labels"),
                    }
                )
        if hits:
            platform_rows.append(
                {
                    "platform": platform.get("platform"),
                    "record_count": platform.get("record_count"),
                    "signal_types": platform.get("signal_types"),
                    "direct_hits": hits,
                }
            )

    signal_type_rows: list[dict[str, Any]] = []
    for item in pack.get("signal_type_summaries") or []:
        labels = _by_label(item.get("top_label_groups") or [])
        hits = []
        for signal in signals:
            label_item = labels.get(signal)
            if label_item:
                hits.append(
                    {
                        "work_signal": signal,
                        "count": label_item.get("count"),
                        "share": label_item.get("share"),
                        "source_labels": label_item.get("source_labels"),
                    }
                )
        if hits:
            signal_type_rows.append(
                {
                    "platform": item.get("platform"),
                    "signal_type": item.get("signal_type"),
                    "record_count": item.get("record_count"),
                    "direct_hits": hits,
                }
            )

    sensitive_labels = {
        label.get("label_ko")
        for candidate in pack.get("sensitive_label_candidates") or []
        for label in candidate.get("matched_labels") or []
    }
    sensitive_direct_hits = [signal for signal in signals if signal in sensitive_labels]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_scope": "context_pack_direct_observation_overlap",
        "work": work_input.to_dict(),
        "target_market": pack.get("market"),
        "target_market_ko": pack.get("market_ko"),
        "context_record_count": pack.get("record_count"),
        "platforms": pack.get("platforms"),
        "signal_types": pack.get("signal_types"),
        "summary": {
            "declared_signal_count": len(signals),
            "observed_signal_count": observed_count,
            "not_observed_signal_count": len(signals) - observed_count,
            "title_element_count": len([row for row in input_rows if row["source"] == "title_explicit"]),
            "comparable_signal_count": len([row for row in input_rows if row["source"] in {"genre", "comparable", "declared"}]),
            "synopsis_inferred_signal_count": len([row for row in input_rows if row["source"] == "synopsis_inferred"]),
        },
        "direct_signal_rows": direct_rows,
        "platform_direct_rows": platform_rows,
        "signal_type_direct_rows": signal_type_rows,
        "regulation_join_candidates": {
            "sensitive_direct_hits": sensitive_direct_hits,
            "note": "규정/규제 데이터 미결합 상태입니다. 직접 일치한 민감 라벨만 후보로 제공합니다.",
        },
        "data_limits": (pack.get("use_limits") or [])
        + [
            "이 리포트는 참고 데이터의 한국어 표시명과 작가/작품 입력 요소의 직접 일치만 사용합니다.",
            "이번 데이터에서는 직접 보이지 않음은 인기/부적합 판단이 아니라 살펴본 범위 안에 동일 라벨이 없다는 뜻입니다.",
            "추천, 성과 예측, 창작 방향 제안은 수행하지 않습니다.",
        ],
    }


def render_context_pack_overlap_markdown(evidence: dict[str, Any]) -> str:
    rankings = _join_natural([_writer_signal_type(item) for item in evidence.get("signal_types") or []])
    lines = [
        f"# {evidence['target_market_ko']} 플랫폼 분위기 스냅샷",
        "",
        "작가님의 작품이 순위권 작품들의 태그 흐름과 어떤 지점에서 겹쳐 보이는지 가볍게 살펴봤어요.",
        "",
        f"- 작품: {evidence['work']['title']}",
        f"- 장르: {evidence['work'].get('genre') or '-'}",
        f"- 살펴본 범위: {evidence['target_market_ko']} 플랫폼 {len(evidence.get('platforms') or [])}곳 · 순위권 작품 {evidence.get('context_record_count')}편",
        f"- 참고한 순위: {rankings}",
        f"- 내 작품과 겹쳐 보이는 요소: {evidence['summary']['observed_signal_count']} / {evidence['summary']['declared_signal_count']}",
        "",
        "## 내 작품과 겹쳐 보이는 지점",
        "",
        "| 입력 요소 | 구분 | 이번 데이터에서 보였나요? | 살펴본 작품 기준 | 함께 확인한 태그 | 메모 |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in evidence["direct_signal_rows"]:
        status_text = STATUS_LABELS.get(str(row.get("match_status")), "이번 데이터에서는 직접 보이지 않음")
        sample = "-"
        count = _row_primary_count(row)
        share = _row_primary_share(row)
        if count is not None:
            sample = f"{count}건 / {_pct(share)}"
        source_labels = ", ".join(_row_source_labels(row)) or "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["work_signal"]),
                    str(row.get("input_source_label") or "-"),
                    status_text,
                    sample,
                    source_labels,
                    _overlap_sentence(row, str(evidence["target_market_ko"])),
                ]
            )
            + " |"
        )

    lines.extend(["", "## 플랫폼마다 달라 보이는 작품 분위기", ""])
    if evidence["platform_direct_rows"]:
        for platform in evidence["platform_direct_rows"]:
            lines.append(f"### {platform['platform']} ({platform['record_count']}편)")
            for hit in platform["direct_hits"]:
                lines.append(f"- {hit['work_signal']}: {hit['count']}건 / {_pct(hit.get('share'))}")
            lines.append("")
    else:
        lines.append("- 이번 데이터에서는 플랫폼별로 뚜렷하게 겹쳐 보이는 요소가 없습니다.")

    lines.extend(["", "## 민감 요소 검토 후보", ""])
    sensitive_hits = evidence["regulation_join_candidates"]["sensitive_direct_hits"]
    if sensitive_hits:
        for signal in sensitive_hits:
            lines.append(f"- {signal}")
    else:
        lines.append("- 참고 데이터 기준 직접 보이는 민감 후보 없음")

    lines.extend(["", "## 읽기 전에", ""])
    for limit in _writer_limits(evidence):
        lines.append(f"- {limit}")
    lines.append("")
    return "\n".join(lines)


def render_context_pack_overlap_html(evidence: dict[str, Any]) -> str:
    ui = build_ui_briefing_payload(evidence)
    writer = ui["writer_copy"]
    observed = evidence["summary"]["observed_signal_count"]
    declared = evidence["summary"]["declared_signal_count"]

    title_chips = "".join(f"<span class='chip'>{_esc(item)}</span>" for item in ui["input_summary"].get("title_elements") or [])
    comparable_chips = "".join(f"<span class='chip soft'>{_esc(item)}</span>" for item in ui["input_summary"].get("comparable_elements") or [])
    if not title_chips:
        title_chips = "".join(f"<span class='chip'>{_esc(item)}</span>" for item in ui["input_summary"].get("detected_elements") or [])
    headline_chips = "".join(
        f"<span class='tag-chip'><b>{_esc(item.get('label_ko'))}</b><small>{_esc(CATEGORY_LABELS.get(str(item.get('category')), '작품 태그'))}</small></span>"
        for item in ui["headline_market_labels"][:10]
    )
    overlap_cards = "".join(
        "<article class='soft-card'>"
        f"<p class='eyebrow'>{_esc(card.get('status_label') or CATEGORY_LABELS.get(str(card.get('card_type')), '작품 태그'))}</p>"
        f"<h3>{_esc(card['card_title'])}</h3>"
        f"<p>{_esc(card['display_sentence'])}</p>"
        f"<span class='badge ok'>{_esc(card['platform_coverage_text'])}</span>"
        "</article>"
        for card in ui["overlap_cards"]
    )
    missing_cards = "".join(
        "<article class='soft-card muted-card'>"
        f"<p class='eyebrow'>{_esc(card.get('status_label') or '이번 데이터에서는 직접 보이지 않음')}</p>"
        f"<h3>{_esc(card['input_element'])}</h3>"
        f"<p>{_esc(card['display_sentence'])}</p>"
        "</article>"
        for card in ui["missing_cards"]
    )
    platform_cards = "".join(
        "<article class='soft-card'>"
        f"<h3>{_esc(card.get('platform'))}</h3>"
        f"<p>{_esc(card.get('display_sentence'))}</p>"
        f"<small>참고한 순위: {_esc(_join_natural([str(item) for item in card.get('reference_rankings') or []]))}</small>"
        "</article>"
        for card in ui["platform_mood_cards"]
    )
    cooccurrence_cards = "".join(
        "<article class='mini-card'>"
        f"<b>{_esc(' · '.join(card.get('labels') or []))}</b>"
        f"<p>{_esc(card.get('display_sentence'))}</p>"
        "</article>"
        for card in ui["cooccurrence_cards"][:6]
    )
    limits_html = "".join(f"<li>{_esc(limit)}</li>" for limit in ui["limitations"])

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(writer['page_title'])}</title>
  <style>
    :root {{ --bg:#fff8fb; --panel:#fff; --text:#241528; --muted:#73606f; --line:#f0ddea; --ok:#8b2f83; --soft:#fff0fa; --accent:#d94697; --mint:#edfdf7; }}
    body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:radial-gradient(circle at top left,#fff0fa,#fff8fb 38%,#f8fbff); color:var(--text); }}
    main {{ max-width:1120px; margin:0 auto; padding:32px 20px 48px; }}
    .hero {{ background:linear-gradient(135deg,#7c2d8a,#ec4899); color:white; border-radius:28px; padding:34px; box-shadow:0 18px 40px rgba(124,45,138,.22); }}
    .hero p {{ color:#ffeaf7; max-width:780px; line-height:1.7; }}
    .scope {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }}
    .scope span,.chip,.badge,.tag-chip {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:7px 12px; font-size:13px; }}
    .scope span {{ background:rgba(255,255,255,.18); color:white; }}
    .section,.soft-card,.mini-card {{ background:rgba(255,255,255,.9); border:1px solid var(--line); border-radius:22px; padding:20px; box-shadow:0 10px 28px rgba(124,45,138,.06); }}
    .section {{ margin-top:18px; }}
    .two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:10px; }}
    .chip {{ background:#fdf2f8; color:#9d174d; font-weight:700; }}
    .chip.soft {{ background:#f5f0ff; color:#6d28d9; }}
    .tag-chip {{ background:#fff; border:1px solid var(--line); flex-direction:column; align-items:flex-start; border-radius:18px; }}
    .tag-chip small,.soft-card small {{ color:var(--muted); }}
    .badge.ok {{ color:var(--ok); background:var(--soft); font-weight:800; margin-top:10px; }}
    .muted-card {{ background:#fbf7fa; }}
    .eyebrow {{ color:var(--accent); font-size:13px; font-weight:800; margin:0 0 8px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }}
    .mini-card {{ padding:14px; border-radius:18px; background:#fff; }}
    details {{ margin-top:18px; }}
    summary {{ cursor:pointer; color:var(--ok); font-weight:800; }}
    .notice {{ color:var(--muted); }}
    h1,h2,h3 {{ margin-top:0; }}
    h1 {{ font-size:34px; }}
    p,li {{ line-height:1.7; }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <h1>{_esc(writer['page_title'])}</h1>
    <p>{_esc(writer['hero_subtitle'])}</p>
    <div class="scope">
      <span>{_esc(writer['scope_sentence'])}</span>
      <span>참고한 순위: {_esc(writer['ranking_sentence'])}</span>
    </div>
  </section>

  <section class="section">
    <h2>작품 정보</h2>
    <div class="two">
      <div><p class="eyebrow">제목</p><h3>{_esc(evidence['work']['title'])}</h3></div>
      <div><p class="eyebrow">장르</p><h3>{_esc(evidence['work'].get('genre') or '-')}</h3></div>
    </div>
  </section>

  <section class="section">
    <h2>{_esc(writer['input_elements_title'])}</h2>
    <div class="chips">{title_chips or "<p class='notice'>제목에서 따로 분리한 요소가 없습니다.</p>"}</div>
  </section>

  <section class="section">
    <h2>{_esc(writer['comparable_elements_title'])}</h2>
    <div class="chips">{comparable_chips or "<p class='notice'>장르상 함께 확인할 요소를 입력하지 않았습니다.</p>"}</div>
  </section>

  <section class="section">
    <h2>{_esc(writer['top_tags_title'])}</h2>
    <div class="chips">{headline_chips}</div>
  </section>

  <section class="section">
    <h2>{_esc(writer['overlap_title'])}</h2>
    <p class="notice">비교해볼 수 있는 요소 {observed}개, 이번 데이터에서는 직접 보이지 않은 요소 {declared - observed}개를 나눠 표시했어요.</p>
    <div class="cards">{overlap_cards or "<p class='notice'>이번 데이터에서 비교해볼 수 있는 요소가 없습니다.</p>"}</div>
    <div class="cards" style="margin-top:14px">{missing_cards}</div>
  </section>

  <section class="section">
    <h2>{_esc(writer['platform_mood_title'])}</h2>
    <div class="cards">{platform_cards}</div>
  </section>

  <section class="section">
    <h2>{_esc(writer['cooccurrence_title'])}</h2>
    <div class="cards">{cooccurrence_cards or "<p class='notice'>겹쳐 보이는 요소와 함께 자주 보인 태그를 찾지 못했습니다.</p>"}</div>
  </section>

  <section class="section">
    <h2>읽기 전에</h2>
    <ul>{limits_html}</ul>
    <details>
      <summary>자세한 숫자 보기</summary>
      <p class="notice">살펴본 작품 기준 비율, 플랫폼별 편차를 줄여 본 값, 원문 태그 예시는 JSON 산출물의 detailed_reference_tables에 보관됩니다.</p>
    </details>
  </section>
</main>
</body>
</html>
"""


def build_ui_briefing_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    """Project deterministic evidence into card-ready UI copy/data.

    This payload is intentionally presentation-oriented. It preserves the
    evidence boundary: observed means overlap/comparison in prepared context
    data, while missing means "not observed in this context", not poor fit.
    """

    work = evidence["work"]
    market = _market_value(evidence)
    market_profile = _market_projection("platform_tag_profiles.json", market) or {}
    cooccurrence = _market_projection("cooccurrence_patterns.json", market) or {}
    snapshot = _market_projection("market_tag_snapshot.json", market) or {}

    observed_rows = [row for row in evidence["direct_signal_rows"] if row["direct_observation"] == "observed"]
    missing_rows = [row for row in evidence["direct_signal_rows"] if row["direct_observation"] != "observed"]

    title_elements = list(work.get("title_elements") or [])
    comparable_elements = _dedupe(
        ([work.get("genre")] if work.get("genre") else [])
        + list(work.get("comparable_signals") or [])
        + list(work.get("declared_signals") or [])
    )
    synopsis_elements = _synopsis_hint_elements(str(work.get("synopsis") or ""))
    detected = _dedupe(title_elements + comparable_elements + synopsis_elements)

    overlap_cards = []
    for row in observed_rows:
        aggregate = row.get("aggregate") or {}
        source = _row_source_labels(row)
        candidate_labels = _row_candidate_labels(row)
        card_type = _label_category(str(row.get("observed_label") or row["work_signal"]))
        if candidate_labels:
            card_type = _label_category(candidate_labels[0])
        overlap_cards.append(
            {
                "card_title": str(row["work_signal"]),
                "card_type": card_type,
                "match_status": row.get("match_status"),
                "status_label": STATUS_LABELS.get(str(row.get("match_status")), "겹쳐 보이는 지점"),
                "input_source": row.get("input_source"),
                "input_source_label": row.get("input_source_label"),
                "observed_label": row.get("observed_label") or (candidate_labels[0] if candidate_labels else None),
                "candidate_labels": candidate_labels,
                "raw_label_examples": source[:5],
                "count": aggregate.get("count") or _row_primary_count(row),
                "share": aggregate.get("share") or _row_primary_share(row),
                "platform_coverage_text": _row_platform_coverage_text(row),
                "display_sentence": _overlap_sentence(row, str(evidence["target_market_ko"])),
            }
        )

    missing_cards = [
        {
            "input_element": row["work_signal"],
            "status": "not_observed",
            "status_label": STATUS_LABELS["not_observed"],
            "input_source": row.get("input_source"),
            "input_source_label": row.get("input_source_label"),
            "display_sentence": _overlap_sentence(row, str(evidence["target_market_ko"])),
        }
        for row in missing_rows
    ]

    platform_mood_cards = []
    for platform in (market_profile.get("platform_profiles") or [])[:6]:
        distinctive = platform.get("distinctive_labels") or []
        platform_mood_cards.append(
            {
                "platform": platform.get("platform"),
                "reference_rankings": [_writer_signal_type(item) for item in platform.get("signal_types") or []],
                "display_sentence": platform.get("summary_sentence"),
                "top_labels": platform.get("top_labels") or [],
                "distinctive_labels": [
                    {
                        "label_ko": item.get("label_ko"),
                        "category": item.get("category"),
                        "platform_share": item.get("platform_share"),
                        "market_share": item.get("market_share"),
                        "stands_out_score": item.get("lift"),
                    }
                    for item in distinctive[:5]
                ],
            }
        )

    cooccurrence_cards = []
    observed_labels = {
        str(label)
        for row in observed_rows
        for label in ([row.get("observed_label")] if row.get("observed_label") else _row_candidate_labels(row))
        if label
    }
    for pair in cooccurrence.get("pairs") or []:
        labels = [str(label) for label in pair.get("label_ko") or []]
        if observed_labels and not observed_labels.intersection(labels):
            continue
        cooccurrence_cards.append(
            {
                "labels": labels,
                "count": pair.get("count"),
                "together_ratio": pair.get("jaccard"),
                "together_score": pair.get("lift"),
                "platform_spread": pair.get("platform_coverage"),
                "display_sentence": pair.get("display_sentence") or "두 태그가 같은 순위권 작품 안에서 함께 보인 경우가 있습니다.",
            }
        )
        if len(cooccurrence_cards) >= 8:
            break

    headline_labels = [
        {
            "label_ko": item.get("label_ko"),
            "category": item.get("category"),
            "count": item.get("count"),
            "share": item.get("share"),
            "weighted_share": item.get("weighted_share"),
            "display_note": item.get("display_note"),
        }
        for item in (snapshot.get("labels") or [])[:10]
    ]

    ranking_sentence = _join_natural([_writer_signal_type(item) for item in evidence.get("signal_types") or []])
    scope_sentence = (
        f"{evidence['target_market_ko']} 플랫폼 {len(evidence.get('platforms') or [])}곳에서 "
        f"순위권 작품 {evidence.get('context_record_count')}편을 살펴봤어요."
    )

    return {
        "title": f"{evidence['target_market_ko']} 플랫폼 분위기 스냅샷",
        "subtitle": f"작가님의 작품이 {evidence['target_market_ko']} 순위권 작품들의 태그 흐름과 어떤 지점에서 겹쳐 보이는지 정리했습니다.",
        "scope_badges": [
            str(evidence.get("target_market_ko")),
            f"살펴본 작품 {evidence.get('context_record_count')}편",
            f"참고 플랫폼 {len(evidence.get('platforms') or [])}곳",
            f"참고한 순위 {ranking_sentence}",
        ],
        "writer_copy": {
            "page_title": f"{evidence['target_market_ko']} 플랫폼 분위기 스냅샷",
            "hero_subtitle": f"작가님의 작품이 {evidence['target_market_ko']} 순위권 작품들의 태그 흐름과 어떤 지점에서 겹쳐 보이는지 정리했습니다.",
            "scope_sentence": scope_sentence,
            "ranking_sentence": ranking_sentence,
            "input_elements_title": "작품에서 먼저 읽히는 요소",
            "comparable_elements_title": "장르상 함께 확인해볼 수 있는 요소",
            "top_tags_title": f"{evidence['target_market_ko']} 순위권 작품에서 자주 보인 태그",
            "overlap_title": "내 작품과 겹쳐 보이는 지점",
            "platform_mood_title": "플랫폼마다 달라 보이는 작품 분위기",
            "rank_band_title": "상위권에서 더 자주 보였는지 보기",
            "cooccurrence_title": "함께 자주 보인 태그",
            "missing_label": "이번 데이터에서는 직접 보이지 않음",
            "detail_toggle": "자세한 숫자 보기",
        },
        "input_summary": {
            "work_title": work.get("title"),
            "genre": work.get("genre"),
            "synopsis_present": bool(str(work.get("synopsis") or "").strip()),
            "synopsis_inferred_elements": synopsis_elements,
            "title_elements": title_elements,
            "comparable_elements": comparable_elements,
            "detected_elements": detected,
        },
        "briefing_paragraphs": [
            f"제목에서는 {', '.join(title_elements[:6]) or '명시 요소 없음'} 같은 요소를 먼저 확인했습니다.",
            f"시놉시스에서는 {', '.join(synopsis_elements[:6])}을 조심스러운 추정 요소로 분리했습니다." if synopsis_elements else "시놉시스에서 확정적으로 표시할 추가 소재 축은 분리하지 않았습니다.",
            f"{evidence['target_market_ko']} 순위권 작품에서는 {', '.join(str(item.get('label_ko')) for item in headline_labels[:5])} 같은 작품 태그가 자주 보였습니다.",
            "아래 내용은 적용 추천이 아니라 입력 요소와 공개 플랫폼 태그 흐름 사이의 참고 비교입니다.",
        ],
        "headline_market_labels": headline_labels,
        "overlap_cards": overlap_cards,
        "missing_cards": missing_cards,
        "platform_mood_cards": platform_mood_cards,
        "cooccurrence_cards": cooccurrence_cards,
        "detailed_reference_tables": {
            "work_element_rows": [
                {
                    "work_element": row["work_signal"],
                    "input_source": row.get("input_source"),
                    "input_source_label": row.get("input_source_label"),
                    "status": STATUS_LABELS.get(str(row.get("match_status")), "이번 데이터에서는 직접 보이지 않음"),
                    "match_status": row.get("match_status"),
                    "looked_works_count": _row_primary_count(row),
                    "looked_works_share": _row_primary_share(row),
                    "platform_spread": row.get("platform_balanced"),
                    "candidate_labels": _row_candidate_labels(row),
                    "source_tag_examples": _row_source_labels(row),
                }
                for row in evidence["direct_signal_rows"]
            ],
            "platform_rows": [
                {
                    "platform": row.get("platform"),
                    "looked_works_count": row.get("record_count"),
                    "reference_rankings": [_writer_signal_type(item) for item in row.get("signal_types") or []],
                    "overlap_examples": row.get("direct_hits") or [],
                }
                for row in evidence["platform_direct_rows"]
            ],
        },
        "limitations": _writer_limits(evidence),
    }


def build_context_pack_overlap_report(work: WorkInput | dict[str, Any]) -> dict[str, Any]:
    evidence = build_deterministic_evidence(work)
    return {
        "evidence": evidence,
        "ui_briefing_payload": build_ui_briefing_payload(evidence),
        "markdown": render_context_pack_overlap_markdown(evidence),
        "html": render_context_pack_overlap_html(evidence),
    }
