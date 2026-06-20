from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

TERMINOLOGY_POLICY_LOCKED = "locked"
TERMINOLOGY_POLICY_PREFERRED = "preferred"
TERMINOLOGY_POLICY_CONTEXTUAL = "contextual"
TERMINOLOGY_POLICY_REVIEW = "review"
TERMINOLOGY_STATUS_CONFIRMED = "confirmed"
TERMINOLOGY_STATUS_SUGGESTED = "suggested"


def ko(value: str) -> str:
    try:
        return value.encode("ascii").decode("unicode_escape")
    except UnicodeEncodeError:
        return value


_NOUN_SUFFIX_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "business_name",
        TERMINOLOGY_POLICY_LOCKED,
        "business/place proper noun",
        tuple(map(ko, ('약국', '서점', '식당', '상회', '상점', '여관', '다방', '카페', '문구점'))),
    ),
    (
        "place_name",
        TERMINOLOGY_POLICY_LOCKED,
        "place proper noun",
        tuple(map(ko, ('시장', '역', '마을', '거리', '골목', '동', '궁', '산', '강'))),
    ),
    (
        "organization_name",
        TERMINOLOGY_POLICY_LOCKED,
        "organization proper noun",
        tuple(map(ko, ('길드', '문파', '학원', '학교', '회사', '가문', '왕국', '제국'))),
    ),
)
_COMMON_NOUNS: dict[str, tuple[str, list[str]]] = {
    ko('약국'): ("pharmacy", ["pharmacy", "drugstore"]),
    ko('시장'): ("market", ["market"]),
    ko('길드'): ("guild", ["guild"]),
    ko('문파'): ("sect", ["sect", "clan"]),
    ko('가문'): ("family", ["family", "house"]),
}
_COMMON_KOREAN_SURNAMES = set(
    ko(
        '김이박최정강조윤장임한오서신'
        '권황안송전홍유고문양손배조백'
        '허남심노하곽성차주우구민유류나'
    )
)
_PERSON_NAME_BLOCKLIST = set(map(ko, ('이름', '표정', '시장', '약국', '번역')))
_PERSON_NAME_REJECT_SUFFIXES = tuple(map(ko, ('되어', '되지', '하여', '하지', '어', '여', '지', '고', '게')))
_HANGUL_NAME_RE = re.compile(r"[\uac00-\ud7a3]{2,4}(?:\uc740|\ub294|\uc774|\uac00|\uc744|\ub97c|\uc5d0|\uc5d0\uac8c|\ud55c\ud14c|\uc640|\uacfc|\uc758|\ub3c4|\ub9cc|\ubd80\ud130|\uae4c\uc9c0|\uc5d0\uc11c|\ub85c|\uc73c\ub85c|\uc544|\uc57c|,)")
_EN_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_PARTICLE_SUFFIXES = tuple(map(ko, ('에게', '한테', '부터', '까지', '에서', '으로', '은', '는', '이', '가', '을', '를', '와', '과', '의', '도', '만', '로', '에', '아', '야', ",")))
_PERSON_ROLE_MARKERS = tuple(map(ko, ('포수', '투수', '대표', '타자')))
_PERSON_TITLE_MARKERS = tuple(map(ko, ('형', '형님', '누나', '선배', '대표님', '대표')))
_PERSON_SUBJECT_PARTICLES = tuple(map(ko, ('은', '는', '이', '가')))
_PERSON_ACTION_MARKERS = tuple(map(ko, ('걸어', '말했', '노려보', '미소', '입가', '자리', '적었', '언급', '바라봤', '들어오', '들었')))
_TEAM_SUFFIXES = tuple(map(ko, ('킹즈', '타이탄즈')))
_PLACE_SUFFIXES = tuple(map(ko, ('동', '야구장')))
_LEAGUE_NAMES = set(("KBO",))
_COMMON_ALIAS_STARTS = set(map(ko, ('민', '현', '연', '태', '주', '윤', '지', '정', '승', '준', '진', '서', '은', '영', '호', '성', '재')))
_COMMON_ALIAS_ENDINGS = set(map(ko, ('우', '주', '성', '재', '형', '준', '진', '희', '호', '윤', '석')))
_EXCLUDED_COMMON_OBJECTS = set(
    map(
        ko,
        (
            '노트북',
            '안경',
            '전화',
            '배트',
            '맥주컵',
            '유니폼',
            '스마트폰',
            '비타민제',
            '스포츠 음료',
        ),
    )
)
_EXCLUDED_BODY_SPACE_TERMS = set(
    map(
        ko,
        (
            '오른팔',
            '왼팔',
            '어깨',
            '손끝',
            '허공',
            '가슴',
            '머리',
            '목',
        ),
    )
)
_EXCLUDED_TIME_TERMS = set(
    map(
        ko,
        (
            '오늘',
            '오래전',
            '다음날',
            '주말',
            '다음 달',
            '일주일',
        ),
    )
)
_EXCLUDED_STATE_TERMS = set(
    map(
        ko,
        (
            '성공적',
            '본격적',
            '압도적',
            '자연적',
            '냉정함',
            '쓁쓸함',
            '해방감',
            '허탈함',
        ),
    )
)
_EXCLUDED_ADVERBS = set(
    map(
        ko,
        (
            '조용히',
            '천천히',
            '갑자기',
            '완전히',
            '성공적으로',
        ),
    )
)
_EXPLICIT_NON_PERSON_TERMS = _EXCLUDED_COMMON_OBJECTS | _EXCLUDED_BODY_SPACE_TERMS | _EXCLUDED_TIME_TERMS | _EXCLUDED_STATE_TERMS | _EXCLUDED_ADVERBS


def _is_full_name(source: str) -> bool:
    return bool(len(source) == 3 and source[0] in _COMMON_KOREAN_SURNAMES)


def _looks_like_team_name(source: str) -> bool:
    return any(source.endswith(suffix) for suffix in _TEAM_SUFFIXES)


def _looks_like_place_name(source: str) -> bool:
    return any(source.endswith(suffix) for suffix in _PLACE_SUFFIXES)


def _looks_like_league_name(source: str) -> bool:
    return source in _LEAGUE_NAMES


def _looks_like_company_name(source: str, text: str = "") -> bool:
    if not source:
        return False
    escaped = re.escape(source)
    return bool(
        re.search(rf"(?:\uae30\uc5c5|\ud68c\uc0ac)\s*[\"'‘’“”]?\s*{escaped}\s*[\"'‘’“”]?", text)
        or re.search(rf"[\"'‘’“”]{escaped}[\"'‘’“”]\s*\uc758\s*\ub300\ud45c", text)
        or re.search(rf"{escaped}\s*\uc758\s*\ub300\ud45c", text)
    )


def _is_excluded_person_candidate(source: str) -> bool:
    compact = _strip_particle(source)
    if not compact:
        return True
    if compact in _PERSON_NAME_BLOCKLIST or compact in _COMMON_NOUNS:
        return True
    if compact in _EXPLICIT_NON_PERSON_TERMS:
        return True
    if compact.endswith(ko('적')) or compact.endswith(ko('함')) or compact.endswith(ko('적으로')):
        return True
    suffix_terms = {suffix for _, _, _, suffixes in _NOUN_SUFFIX_RULES for suffix in suffixes}
    if compact in suffix_terms or any(compact.endswith(suffix) for suffix in suffix_terms):
        return True
    if any(compact.endswith(suffix) for suffix in _PERSON_NAME_REJECT_SUFFIXES):
        return True
    if _looks_like_team_name(compact) or _looks_like_place_name(compact) or _looks_like_league_name(compact):
        return True
    return False


def _looks_like_person_alias(source: str) -> bool:
    compact = _strip_particle(source)
    return bool(
        len(compact) == 2
        and compact[0] in _COMMON_ALIAS_STARTS
        and compact[-1] in _COMMON_ALIAS_ENDINGS
        and not _is_excluded_person_candidate(compact)
    )


def _person_row(source: str, type_name: str = "person_name") -> dict[str, Any]:
    return {
        "source": source,
        "type": type_name,
        "meaning": "Korean person-name candidate",
        "policy": TERMINOLOGY_POLICY_REVIEW,
        "recommendedTranslation": "",
        "allowedTranslations": [],
        "status": TERMINOLOGY_STATUS_SUGGESTED,
    }


def _entity_row(source: str, type_name: str, meaning: str) -> dict[str, Any]:
    return {
        "source": source,
        "type": type_name,
        "meaning": meaning,
        "policy": TERMINOLOGY_POLICY_REVIEW,
        "recommendedTranslation": "",
        "allowedTranslations": [],
        "status": TERMINOLOGY_STATUS_SUGGESTED,
    }


@dataclass(slots=True)
class TerminologyIssue:
    type: str
    source: str
    expected: str
    actual: str
    severity: str
    message: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _strip_particle(value: str) -> str:
    for suffix in _PARTICLE_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: -len(_clean(item.get("source")))):
        key = (_clean(row.get("source")), _clean(row.get("type")))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _is_likely_person_name(source: str) -> bool:
    if not _is_full_name(source):
        return False
    if _is_excluded_person_candidate(source):
        return False
    return _looks_like_person_alias(source[1:])


def extract_noun_terminology_candidates(source_text: str) -> list[dict[str, Any]]:
    """Suggest noun/proper-noun glossary rows without enforcing verbs/adjectives."""
    text = source_text or ""
    rows: list[dict[str, Any]] = []

    for type_name, policy, meaning, suffixes in _NOUN_SUFFIX_RULES:
        for suffix in suffixes:
            if len(suffix) == 1:
                pattern = re.compile(rf"[\uac00-\ud7a3]{{2,8}}{re.escape(suffix)}")
            else:
                pattern = re.compile(rf"(?:[\uac00-\ud7a3]{{2,8}}\s+)?{re.escape(suffix)}")
            for match in pattern.finditer(text):
                source = match.group(0).strip()
                rows.append(
                    {
                        "source": source,
                        "type": type_name,
                        "meaning": meaning,
                        "policy": policy,
                        "recommendedTranslation": "",
                        "allowedTranslations": [],
                        "status": TERMINOLOGY_STATUS_SUGGESTED,
                    }
                )

    for term, (target, allowed) in _COMMON_NOUNS.items():
        if term in text:
            rows.append(
                {
                    "source": term,
                    "type": "common_noun",
                    "meaning": "recurring noun; prefer consistency but allow natural variants",
                    "policy": TERMINOLOGY_POLICY_PREFERRED,
                    "recommendedTranslation": target,
                    "allowedTranslations": allowed,
                    "status": TERMINOLOGY_STATUS_SUGGESTED,
                }
            )

    team_pattern = re.compile(rf"((?:[\uac00-\ud7a3]{{2,10}}\s+){{0,2}}(?:{'|'.join(re.escape(suffix) for suffix in _TEAM_SUFFIXES)}))")
    for match in team_pattern.finditer(text):
        source = match.group(1).strip()
        rows.append(_entity_row(source, "team_name", "team-name candidate"))

    place_pattern = re.compile(rf"([\uac00-\ud7a3]{{2,12}}(?:{'|'.join(re.escape(suffix) for suffix in _PLACE_SUFFIXES)}))")
    for match in place_pattern.finditer(text):
        source = match.group(1).strip()
        rows.append(_entity_row(source, "place_name", "place-name candidate"))

    for league in _LEAGUE_NAMES:
        if league in text:
            rows.append(_entity_row(league, "league_name", "league-name candidate"))

    company_patterns = [
        re.compile(r"(?:기업|회사)\s*[\"'‘’“”]?\s*([A-Za-z0-9\uac00-\ud7a3]{2,20})\s*[\"'‘’“”]?"),
        re.compile(r"[\"'‘’“”]([A-Za-z0-9\uac00-\ud7a3]{2,20})[\"'‘’“”]\s*의\s*대표"),
        re.compile(r"([A-Za-z0-9\uac00-\ud7a3]{2,20})\s*의\s*대표"),
    ]
    for pattern in company_patterns:
        for match in pattern.finditer(text):
            source = match.group(1).strip()
            rows.append(_entity_row(source, "company_name", "company-name candidate"))

    sender_pattern = re.compile(r"\[([\uac00-\ud7a3]{2,4})\s*:\]")
    for match in sender_pattern.finditer(text):
        source = _strip_particle(match.group(1).strip())
        if not _is_excluded_person_candidate(source):
            rows.append(_person_row(source, "person_name_alias"))

    role_pattern = re.compile(rf"(?:{'|'.join(re.escape(role) for role in _PERSON_ROLE_MARKERS)})\s+([\uac00-\ud7a3]{{2,4}})")
    for match in role_pattern.finditer(text):
        source = _strip_particle(match.group(1).strip())
        if not _is_excluded_person_candidate(source):
            rows.append(_person_row(source, "person_name" if _is_full_name(source) else "person_name_alias"))

    title_pattern = re.compile(rf"([\uac00-\ud7a3]{{2,4}}(?:\uc774)?\s*(?:{'|'.join(re.escape(title) for title in _PERSON_TITLE_MARKERS)}))")
    for match in title_pattern.finditer(text):
        source = match.group(1).strip()
        base = _strip_particle(source.split()[0].rstrip(ko('이')))
        if not _is_excluded_person_candidate(base) and not _looks_like_company_name(base, text):
            rows.append(_person_row(source, "person_name_alias"))
            rows.append(_person_row(base, "person_name_alias"))

    full_name_pattern = re.compile(
        rf"([\uac00-\ud7a3]{{3}})(?:{'|'.join(re.escape(particle) for particle in _PERSON_SUBJECT_PARTICLES)}|\uc544|\uc57c)"
    )
    full_names: set[str] = set()
    for match in full_name_pattern.finditer(text):
        source = _strip_particle(match.group(1).strip())
        if _is_likely_person_name(source):
            rows.append(_person_row(source, "person_name"))
            full_names.add(source)

    for source in full_names:
        alias = source[1:]
        if len(alias) < 2 or _is_excluded_person_candidate(alias):
            continue
        if (
            re.search(rf"\[{re.escape(alias)}\s*:\]", text)
            or re.search(
                rf"{re.escape(alias)}(?:{'|'.join(re.escape(particle) for particle in _PERSON_SUBJECT_PARTICLES)})",
                text,
            )
            or re.search(
                rf"{re.escape(alias)}\s*(?:{'|'.join(re.escape(title) for title in _PERSON_TITLE_MARKERS)})",
                text,
            )
        ):
            rows.append(_person_row(alias, "person_name_alias"))

    alias_counts: dict[str, int] = {}
    alias_subject_pattern = re.compile(
        rf"([\uac00-\ud7a3]{{2,3}})(?:{'|'.join(re.escape(particle) for particle in _PERSON_SUBJECT_PARTICLES)})"
    )
    for match in alias_subject_pattern.finditer(text):
        source = _strip_particle(match.group(1).strip())
        if _is_excluded_person_candidate(source):
            continue
        if _is_full_name(source):
            continue
        if source not in {full_name[1:] for full_name in full_names} and not _looks_like_person_alias(source):
            continue
        alias_counts[source] = alias_counts.get(source, 0) + 1

    for source, count in alias_counts.items():
        if count >= 2 or _looks_like_person_alias(source):
            rows.append(_person_row(source, "person_name_alias"))

    for match in _HANGUL_NAME_RE.finditer(text):
        source = _strip_particle(match.group(0).strip())
        if source in full_names and _is_likely_person_name(source):
            rows.append(_person_row(source, "person_name"))

    for match in _EN_NAME_RE.finditer(text):
        source = match.group(0).strip()
        rows.append(
            {
                "source": source,
                "type": "proper_noun",
                "meaning": "proper noun candidate",
                "policy": TERMINOLOGY_POLICY_LOCKED,
                "recommendedTranslation": "",
                "allowedTranslations": [],
                "status": TERMINOLOGY_STATUS_SUGGESTED,
            }
        )

    return _dedupe_rows(rows)


def _target_for_locale(row: dict[str, Any], locale: str) -> str:
    targets = row.get("targets")
    if isinstance(targets, dict):
        return _clean(targets.get(locale) or targets.get("default"))
    return _clean(row.get("target") or row.get("translation") or row.get("recommendedTranslation"))


def normalize_terminology_row(row: dict[str, Any], locale: str) -> dict[str, Any]:
    source = _clean(row.get("source") or row.get("term"))
    target = _target_for_locale(row, locale)
    allowed = [_clean(item) for item in (row.get("allowedTranslations") or row.get("allowed") or [])]
    allowed = [item for item in allowed if item]
    if target and target not in allowed:
        allowed.insert(0, target)
    policy = _clean(row.get("policy")) or TERMINOLOGY_POLICY_LOCKED
    if policy not in {TERMINOLOGY_POLICY_LOCKED, TERMINOLOGY_POLICY_PREFERRED, TERMINOLOGY_POLICY_CONTEXTUAL, TERMINOLOGY_POLICY_REVIEW}:
        policy = TERMINOLOGY_POLICY_LOCKED if row.get("type") != "common_noun" else TERMINOLOGY_POLICY_PREFERRED
    return {
        **row,
        "source": source,
        "target": target,
        "allowedTranslations": allowed,
        "policy": policy,
        "status": _clean(row.get("status")) or TERMINOLOGY_STATUS_SUGGESTED,
        "type": _clean(row.get("type")) or "term",
    }


def terminology_rows_for_locale(terms: Any, locale: str, *, confirmed_only: bool = False) -> list[dict[str, Any]]:
    if not terms:
        return []
    if isinstance(terms, dict):
        raw_rows = terms.get("terms") or terms.get("terminology") or terms.get("glossary") or []
    elif isinstance(terms, list):
        raw_rows = terms
    else:
        return []

    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row = normalize_terminology_row(raw, locale)
        if not row["source"]:
            continue
        if confirmed_only and row.get("status") != TERMINOLOGY_STATUS_CONFIRMED:
            continue
        rows.append(row)
    return _dedupe_rows(rows)


def merge_terminology(existing: Any, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = terminology_rows_for_locale(existing, "default")
    existing_sources = {_clean(row.get("source")) for row in rows}
    for candidate in candidates:
        source = _clean(candidate.get("source"))
        if source and source not in existing_sources:
            rows.append(dict(candidate))
            existing_sources.add(source)
    return _dedupe_rows(rows)


def render_terminology_context(terms: Any, locale: str, *, source_text: str = "") -> str:
    rows = []
    for row in terminology_rows_for_locale(terms, locale, confirmed_only=False):
        if source_text and row["source"] not in source_text:
            continue
        if row.get("policy") == TERMINOLOGY_POLICY_CONTEXTUAL:
            continue
        rows.append(row)
    if not rows:
        return ""

    lines = [
        "Terminology / proper-noun consistency glossary:",
        "- Enforce only noun/proper-noun rows listed here; do not freeze verbs, adjectives, or normal phrasing.",
        "- LOCKED rows must use the listed target consistently when the source appears.",
        "- PREFERRED rows may use listed variants when the sentence needs natural wording.",
    ]
    for row in rows:
        allowed = [item for item in row.get("allowedTranslations", []) if item and item != row.get("target")]
        allowed_text = f"; allowed variants: {', '.join(allowed)}" if allowed else ""
        target = row.get("target", "")
        if target:
            lines.append(f"- [{row['policy'].upper()}] {row['source']} => {target}{allowed_text} ({row.get('type', 'term')})")
        else:
            lines.append(
                f"- [SUGGESTED {row['policy'].upper()}] {row['source']} => choose one translation/transliteration and reuse it ({row.get('type', 'term')})"
            )
    return "\n".join(lines)


def present_any(translated_text: str, candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate and candidate in translated_text:
            return candidate
    return ""


def issue_to_dict(issue: TerminologyIssue) -> dict[str, Any]:
    return asdict(issue)
