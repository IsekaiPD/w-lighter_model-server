from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ROOT
REGULATION_DIR = ROOT / "data" / "regulation"
RAW_PLATFORM_RULES_DIR = ROOT / "data" / "platform_rules"

COUNTRY_CODE_ALIASES = {
    "jp": "JP",
    "japan": "JP",
    "일본": "JP",
    "日本": "JP",
    "us": "US",
    "usa": "US",
    "united states": "US",
    "us/global english": "US",
    "english": "US",
    "영어권": "US",
    "미국": "US",
    "cn": "CN",
    "china": "CN",
    "중국": "CN",
    "th": "TH",
    "thailand": "TH",
    "태국": "TH",
}

GENERIC_MATCH_TERMS = {
    "가이드",
    "국가",
    "등록",
    "게시",
    "규정",
    "금지",
    "내용",
    "대상",
    "문제",
    "묘사",
    "민감",
    "모집",
    "상호",
    "사용",
    "유출",
    "설정",
    "선전",
    "신고",
    "역사",
    "영업",
    "운영",
    "이벤트",
    "이용",
    "추천",
    "작품",
    "점검",
    "정보",
    "제재",
    "종교",
    "중지",
    "체크",
    "출처",
    "평가",
    "표시",
    "표현",
    "플랫폼",
    "확인",
    "활동",
}

POLICY_LIMITATIONS = [
    "이 섹션은 법적 판단이나 위반 확정이 아니라 게시 전 확인 후보입니다.",
    "플랫폼 상위 태그 관찰과 규정 확인 후보는 별도로 표시합니다.",
    "시놉시스 기반 매칭은 명시 입력보다 약한 후보로 표시합니다.",
]


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    country: str
    platform_display_name: str
    source_url: str
    risk_type_labels_ko: tuple[str, ...]
    severity: str
    rule_summary_ko: str
    guide_message_ko: str
    keywords_ko: tuple[str, ...]
    raw: dict[str, Any]


def normalize_country_code(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return COUNTRY_CODE_ALIASES.get(text.lower()) or COUNTRY_CODE_ALIASES.get(text) or text.upper()


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for chunk in value.split("\n") for part in chunk.split(",") if part.strip()]
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_rule(raw: dict[str, Any]) -> PolicyRule | None:
    rule_id = str(raw.get("rule_id") or "").strip()
    country = normalize_country_code(raw.get("country"))
    labels = _list(raw.get("risk_type_labels_ko"))
    keywords = _list(raw.get("keywords_ko"))
    if not rule_id or not country or not (labels or keywords):
        return None

    summary = str(raw.get("rule_summary_ko") or "").strip()
    message = str(raw.get("guide_message_ko") or summary).strip()
    if not message:
        return None

    return PolicyRule(
        rule_id=rule_id,
        country=country,
        platform_display_name=str(raw.get("platform_display_name") or raw.get("platform") or "플랫폼 규정").strip(),
        source_url=str(raw.get("source_url") or "").strip(),
        risk_type_labels_ko=tuple(labels),
        severity=str(raw.get("severity") or "medium").strip().lower(),
        rule_summary_ko=summary,
        guide_message_ko=message,
        keywords_ko=tuple(keywords),
        raw=dict(raw),
    )


def _rule_files(country_code: str | None, rules_dir: Path = REGULATION_DIR) -> list[Path]:
    files: list[Path] = []
    if country_code:
        raw_country_rules = RAW_PLATFORM_RULES_DIR / f"platform_rules_report_{country_code.upper()}.json"
        if raw_country_rules.exists():
            return [raw_country_rules]
    elif RAW_PLATFORM_RULES_DIR.exists():
        raw_files = sorted(RAW_PLATFORM_RULES_DIR.glob("platform_rules_report_*.json"))
        if raw_files:
            return raw_files

    all_rules = rules_dir / "rules.json"
    if all_rules.exists():
        files.append(all_rules)
    if country_code:
        country_rules = rules_dir / f"{country_code.lower()}_rules.json"
        if country_rules.exists():
            files.append(country_rules)
    if not files and rules_dir.exists():
        files.extend(sorted(rules_dir.glob("*_rules.json")))
    return files


def load_policy_rules(country: Any = None, rules_dir: Path = REGULATION_DIR) -> list[PolicyRule]:
    country_code = normalize_country_code(country)
    rules: list[PolicyRule] = []
    seen: set[str] = set()
    for path in _rule_files(country_code, rules_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_rules = payload.get("rules") if isinstance(payload, dict) else payload
        for raw in raw_rules or []:
            if not isinstance(raw, dict):
                continue
            rule = _normalize_rule(raw)
            if not rule or rule.rule_id in seen:
                continue
            if country_code and rule.country != country_code:
                continue
            seen.add(rule.rule_id)
            rules.append(rule)
    return rules


def _field_list(payload: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        if key in payload:
            return _list(payload.get(key))
    return []


def _input_buckets(payload: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, list[str]]:
    result = result or {}
    return {
        "direct_input": (
            _field_list(payload, "titleElements", "title_elements")
            + _field_list(payload, "comparableSignals", "comparable_signals")
            + _field_list(payload, "declaredSignals", "declared_signals", "signals")
            + _field_list(payload, "tags")
        ),
        "title_or_genre": _list(payload.get("title") or payload.get("workTitle") or result.get("title"))
        + _list(payload.get("genre") or result.get("genre")),
        "synopsis_inferred": _list(payload.get("synopsis") or result.get("synopsis")),
    }


def _term_variants(term: str) -> list[str]:
    clean = str(term or "").strip()
    if not clean:
        return []
    pieces = [clean]
    pieces.extend(part.strip() for part in re.split(r"[\s,;/·・()（）\[\]{}]+", clean) if part.strip())
    variants: list[str] = []
    for piece in pieces:
        if len(piece) < 2 and not re.fullmatch(r"R\d+", piece, flags=re.IGNORECASE):
            continue
        if piece in GENERIC_MATCH_TERMS:
            continue
        variants.append(piece)
    return list(dict.fromkeys(variants))


def _match_rule(rule: PolicyRule, buckets: dict[str, list[str]]) -> dict[str, Any] | None:
    terms = []
    for raw_term in list(rule.keywords_ko) + list(rule.risk_type_labels_ko):
        terms.extend(_term_variants(raw_term))
    terms = list(dict.fromkeys(terms))
    if not terms:
        return None

    matched_by_source: dict[str, list[str]] = {}
    for source, values in buckets.items():
        haystack = "\n".join(values).lower()
        if not haystack:
            continue
        hits = [term for term in terms if term.lower() in haystack]
        if hits:
            matched_by_source[source] = hits
    if not matched_by_source:
        return None

    for source in ("direct_input", "title_or_genre", "synopsis_inferred"):
        if source in matched_by_source:
            primary_source = source
            break
    else:
        primary_source = next(iter(matched_by_source))

    all_hits: list[str] = []
    for source in ("direct_input", "title_or_genre", "synopsis_inferred"):
        all_hits.extend(matched_by_source.get(source, []))
    return {
        "match_source": primary_source,
        "matched_elements": list(dict.fromkeys(all_hits)),
        "matched_by_source": {key: list(dict.fromkeys(value)) for key, value in matched_by_source.items()},
    }


def _status_label(severity: str) -> str:
    if severity in {"high", "critical", "severe"}:
        return "검토 권장"
    if severity in {"low", "info"}:
        return "참고 확인"
    return "게시 전 확인"


def build_policy_attention_report(
    payload: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    rules: list[PolicyRule] | None = None,
) -> dict[str, Any]:
    result = result or {}
    country = (
        payload.get("targetCountry")
        or payload.get("target_country")
        or payload.get("targetMarket")
        or payload.get("target_market")
        or payload.get("country")
        or result.get("targetCountry")
        or result.get("country")
    )
    country_code = normalize_country_code(country)
    policy_rules = rules if rules is not None else load_policy_rules(country_code)
    buckets = _input_buckets(payload, result)

    cards: list[dict[str, Any]] = []
    for rule in policy_rules:
        match = _match_rule(rule, buckets)
        if not match:
            continue
        title = " · ".join(rule.risk_type_labels_ko) if rule.risk_type_labels_ko else "규정 확인"
        card = {
            "card_title": title,
            "status_label": _status_label(rule.severity),
            "severity": rule.severity,
            "match_source": match["match_source"],
            "matched_elements": match["matched_elements"],
            "matched_rule_ids": [rule.rule_id],
            "platform_display_name": rule.platform_display_name,
            "display_sentence": rule.guide_message_ko,
            "guide_message_ko": rule.guide_message_ko,
            "rule_summary_ko": rule.rule_summary_ko,
            "source_refs": [
                {
                    "label": rule.platform_display_name,
                    "url": rule.source_url,
                }
            ]
            if rule.source_url
            else [],
            "matched_by_source": match["matched_by_source"],
            "country": rule.country,
        }
        cards.append(card)

    return {
        "policy_attention_cards": cards,
        "policy_limitations": list(POLICY_LIMITATIONS)
        if cards
        else [
            "현재 입력에서 규정 확인 후보로 표시할 직접 키워드는 발견되지 않았습니다.",
            "이 결과는 법적 판단이나 위반 확정이 아닙니다.",
        ],
    }


def build_policy_attention_payload(payload: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
    report = build_policy_attention_report(payload, result)
    return {
        "policyAttentionCards": report["policy_attention_cards"],
        "policyLimitations": report["policy_limitations"],
        "policy_attention_cards": report["policy_attention_cards"],
        "policy_limitations": report["policy_limitations"],
    }
