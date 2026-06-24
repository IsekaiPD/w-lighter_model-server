
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..retrieval.platform_trends import (
    DEFAULT_INPUT,
    build_collection_profiles,
    build_country_profiles,
    load_trend_data,
)
from ..infra.report_html import build_guide_html_document


KO_US = '미국'
KO_ENGLISH_ZONE = '영어권'
KO_JAPAN = '일본'
JP_JAPAN = "\u65e5\u672c"
KO_ROMANCE_FANTASY_SHORT = '로판'
KO_ROMANCE_FANTASY = '로맨스 판타지'
KO_ROMANCE = '로맨스'
KO_FANTASY = '판타지'
KO_ACTION_FANTASY = '액션 판타지'
KO_GAME_FANTASY = '게임판타지'
KO_WUXIA = '무협'
KO_ISEKAI = '이세계'
KO_REINCARNATION = '전생'

JP_ISEKAI_ROMANCE = "\u7570\u4e16\u754c\u3014\u604b\u611b\u3015"
JP_HIGH_FANTASY = "\u30cf\u30a4\u30d5\u30a1\u30f3\u30bf\u30b8\u30fc"
JP_LOW_FANTASY = "\u30ed\u30fc\u30d5\u30a1\u30f3\u30bf\u30b8\u30fc"
JP_VR_GAME = "VR\u30b2\u30fc\u30e0"
JP_ISEKAI_REINCARNATION = "\u7570\u4e16\u754c\u8ee2\u751f"
JP_ISEKAI_TRANSFER = "\u7570\u4e16\u754c\u8ee2\u79fb"
JP_ENGAGEMENT_BREAK = "\u5a5a\u7d04\u7834\u68c4"
JP_DOTING = "\u6eba\u611b"

COUNTRY_ALIASES = {
    "us": "US/global English",
    "en": "US/global English",
    "usa": "US/global English",
    "united states": "US/global English",
    "america": "US/global English",
    KO_US: "US/global English",
    KO_ENGLISH_ZONE: "US/global English",
    "english": "US/global English",
    "japan": "Japan",
    "jp": "Japan",
    KO_JAPAN: "Japan",
    JP_JAPAN: "Japan",
    "china": "China",
    "cn": "China",
    '중국': "China",
    "thailand": "Thailand",
    "th": "Thailand",
    '태국': "Thailand",
}

EXCLUDED_RECOMMENDATION_COUNTRIES = {"Global"}

ALLOWED_COUNTRY_ORDER = ["Japan", "China", "US/global English", "Thailand"]

COUNTRY_DISPLAY_KO = {
    "Japan": '일본',
    "China": '중국',
    "US/global English": '미국',
    "Thailand": '태국',
}

GENRE_ALIASES = {
    "romance fantasy": ["Romance Fantasy", "Romance", JP_ISEKAI_ROMANCE, "villainess", JP_ENGAGEMENT_BREAK, JP_DOTING],
    "romantasy": ["Romance Fantasy", "Romance", JP_ISEKAI_ROMANCE, "villainess"],
    KO_ROMANCE_FANTASY_SHORT: ["Romance Fantasy", "Romance", JP_ISEKAI_ROMANCE, "villainess", JP_ENGAGEMENT_BREAK, JP_DOTING],
    KO_ROMANCE_FANTASY: ["Romance Fantasy", "Romance", JP_ISEKAI_ROMANCE],
    "romance": ["Romance", "Romance Fantasy", JP_ISEKAI_ROMANCE],
    KO_ROMANCE: ["Romance", "Romance Fantasy", JP_ISEKAI_ROMANCE],
    "bl": ["BL", "Boys Love", "LGBTQ+"],
    "boys love": ["BL", "Boys Love", "LGBTQ+"],
    "보이즈러브": ["BL", "Boys Love", "LGBTQ+"],
    "fantasy": ["Fantasy", "High Fantasy", JP_HIGH_FANTASY, JP_LOW_FANTASY, "Magic", "Adventure"],
    KO_FANTASY: ["Fantasy", "High Fantasy", JP_HIGH_FANTASY, JP_LOW_FANTASY, "Magic", "Adventure"],
    "action fantasy": ["Action Fantasy", "Action", "Adventure", "Fantasy"],
    KO_ACTION_FANTASY: ["Action Fantasy", "Action", "Adventure", "Fantasy"],
    "litrpg": ["LitRPG", "GameLit", "Progression", "System", "Skill"],
    KO_GAME_FANTASY: ["LitRPG", "GameLit", "Progression", "System", "Skill", JP_VR_GAME],
    KO_WUXIA: ["Cultivation", "Martial Arts", "Wuxia"],
    "isekai": ["Isekai", "Portal Fantasy / Isekai", JP_ISEKAI_REINCARNATION, JP_ISEKAI_TRANSFER, "Reincarnation"],
    KO_ISEKAI: ["Isekai", "Portal Fantasy / Isekai", JP_ISEKAI_REINCARNATION, JP_ISEKAI_TRANSFER, "Reincarnation"],
    KO_REINCARNATION: ["Reincarnation", JP_ISEKAI_REINCARNATION, "Isekai"],
}

SYNOPSIS_KEYWORDS = {
    "romance": ["romance", "love", "marriage", "husband", "wife", "duke", "prince", "villainess", '약혼', '결혼', '공작', '황태자', '악녀', '공녀', '귀족', '가문', KO_ROMANCE, '사랑'],
    "progression": ["level", "skill", "system", "rank", "dungeon", "quest", '성장', '스킬', '레벨', '시스템', '던전', '랭커'],
    "isekai": ["reincarn", "isekai", "another world", "transport", '회귀', KO_REINCARNATION, '빙의', KO_ISEKAI, '환생'],
    "action": ["battle", "war", "fight", "survival", "apocalypse", '전투', '전쟁', '복수', '잔혹', '피', '생존', '멸망', '아포칼립스'],
    "bl": ["omega", "alpha", "bl", "boys love", "보이즈러브", "남성 간 로맨스", "오메가버스", '오메가', '알파'],
}

SYNOPSIS_MOTIF_LABELS = {
    "romance": '관계/로맨스 축',
    "progression": '성장·시스템 축',
    "isekai": '회귀·전생·이세계 축',
    "action": '전투·생존 축',
    "bl": 'BL/관계성 축',
}

NON_GENRE_PUBLIC_TAGS = {
    "ONGOING",
    "WAIT_UNTIL_FREE",
    "WAIT_UNTIL_PAID",
    "COMPLETED",
    "COMPLETE",
    "ORIGINAL",
    "EXCLUSIVE",
    "FREE",
    "PAID",
    "HOT",
    "NEW",
}

PUBLIC_LABEL_TRANSLATIONS = {
    "fantasy": "판타지",
    "high fantasy": "하이 판타지",
    "low fantasy": "로우 판타지",
    "action fantasy": "액션 판타지",
    "romance fantasy": "로맨스 판타지",
    "romantasy": "로맨스 판타지",
    "romance": "로맨스",
    "adventure": "모험",
    "action": "액션",
    "magic": "마법",
    "litrpg": "시스템 성장물",
    "gamelit": "게임 판타지",
    "progression": "성장형 판타지",
    "system": "시스템",
    "skill": "스킬",
    "isekai": "이세계",
    "academy": "아카데미",
    "growth": "성장",
    "revenge": "복수",
}

PUBLIC_SECTION_KEYS = (
    "genre_trope_alignment",
    "title_synopsis_localization",
    "terminology_glossary_risks",
    "platform_culture_review_result",
    "market_signal_summary",
    "release_readiness_checklist",
)


def _strip_public_noise(value: Any) -> str:
    text = str(value if value is not None else "")
    text = re.sub(r"\s*\(\d+(?:\.\d+)?\)", "", text)
    text = re.sub(r"\b(?:Wattpad|KakaoPage|Kakao|Naver|Novelpia|Kakuyomu|Syosetu)/[A-Za-z0-9_\-]+[^,.;\n]*[,.;]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:ONGOING|WAIT_UNTIL_FREE|WAIT_UNTIL_PAID|ORIGINAL|COMPLETED|COMPLETE)\b\s*,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\uc7a5\ub974 \uc801\uc911\s*\d+\s*,?\s*", "", text)
    text = re.sub(r"\uc2dc\ub189\uc2dc\uc2a4 \uc801\uc911\s*\d+\s*,?\s*", "", text)
    text = re.sub(r"\uc21c\uc704\s*\d+\s*:?\s*", "", text)
    text = text.replace("`", "")
    text = text.replace("US/global English", "\ubbf8\uad6d")
    text = text.replace("Global", "\uc804\uccb4")
    text = text.replace("\uc791\ud488 glossary", "\uc791\ud488 \ud45c\uae30 \uae30\uc900")
    text = text.replace("glossary", "\ud45c\uae30 \uae30\uc900")
    text = text.replace("Glossary", "\ud45c\uae30 \uae30\uc900")
    text = re.sub(r",\s*(?=[,.:;]|$)", "", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _is_public_tag_label(label: Any) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    if normalized in NON_GENRE_PUBLIC_TAGS or "WAIT_UNTIL" in normalized:
        return False
    return True


def _public_label(label: Any) -> str:
    text = _strip_public_noise(label)
    key = re.sub(r"\s+", " ", text.strip().lower())
    return PUBLIC_LABEL_TRANSLATIONS.get(key, text)


def _public_label_list(rows: list[tuple[Any, Any]], *, limit: int) -> list[str]:
    labels: list[str] = []
    for label, _count in rows:
        clean = _public_label(label)
        if not _is_public_tag_label(clean):
            continue
        if clean not in labels:
            labels.append(clean)
        if len(labels) >= limit:
            break
    return labels


def _clean_public_items(items: list[Any], *, limit: int = 6) -> list[str]:
    clean: list[str] = []
    for item in items:
        text = _strip_public_noise(item)
        if not text:
            continue
        if text not in clean:
            clean.append(text)
        if len(clean) >= limit:
            break
    return clean


@dataclass(frozen=True)
class EvidenceItem:
    platform: str
    collection: str
    rank: int
    title: str
    genre: str | None
    tags: list[str]
    source_url: str | None
    reason: str


@dataclass(frozen=True)
class Recommendation:
    country: str
    score: float
    reasons: list[str]
    evidence: list[EvidenceItem]


def normalize_country(value: str | None) -> str | None:
    key = (value or "").strip().lower()
    if not key:
        return None
    return COUNTRY_ALIASES.get(key, value.strip())


def _text(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: str) -> list[str]:
    lowered = value.lower()
    words = re.findall(r"[a-z][a-z0-9+/-]{2,}|[가-힣]{2,}|[ぁ-んァ-ン一-龯]{2,}", lowered)
    return words


def _split_genre_terms(genre: str | None) -> list[str]:
    raw = _text(genre)
    if not raw:
        return []
    parts = re.split(r"[\n,/;|·]+", raw)
    return list(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _genre_needles(genre: str | None) -> list[str]:
    needles: list[str] = []
    for term in _split_genre_terms(genre):
        lowered = term.lower()
        for key, values in GENRE_ALIASES.items():
            key_text = str(key)
            if key_text.lower() in lowered or key_text in term:
                needles.extend(values)
        needles.append(term)
    return list(dict.fromkeys(needle for needle in needles if needle))


def _synopsis_needles(synopsis: str | None) -> list[str]:
    text = _text(synopsis).lower()
    if not text:
        return []
    needles: list[str] = []
    signal_aliases = {
        "romance": ["Romance", "Romance Fantasy", JP_ISEKAI_ROMANCE],
        "progression": ["LitRPG", "GameLit", "Progression", "System", "Skill"],
        "isekai": ["Isekai", "Portal Fantasy / Isekai", JP_ISEKAI_REINCARNATION, JP_ISEKAI_TRANSFER, "Reincarnation"],
        "action": ["Action", "Adventure", "Action Fantasy"],
        "bl": ["BL", "Boys Love", "LGBTQ+"],
    }
    for signal, values in SYNOPSIS_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in values):
            needles.extend(signal_aliases.get(signal, []))
    return list(dict.fromkeys(needle for needle in needles if needle))


def _synopsis_motifs(synopsis: str | None) -> list[str]:
    text = _text(synopsis).lower()
    if not text:
        return []
    motifs: list[str] = []
    for key, values in SYNOPSIS_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in values):
            motifs.append(SYNOPSIS_MOTIF_LABELS.get(key, key))
    return list(dict.fromkeys(motifs))


def _synopsis_input_note(synopsis: str | None) -> str:
    motifs = _synopsis_motifs(synopsis)
    if not _text(synopsis):
        return '시놉시스가 없어 세부 소재·관계·수위 요소는 확정하지 않고, 입력 장르와 대상 국가 기준으로만 확인합니다.'
    if motifs:
        return f"시놉시스에서 {', '.join(motifs)} 관련 신호를 참고했지만, 확정 소재로 보지는 않았습니다."
    return '시놉시스는 제공됐지만 특정 소재 축을 단정하지 않고 장르·국가 기준의 참고 신호만 확인했습니다.'


def _row_search_text(row: dict[str, Any]) -> str:
    return " ".join(
        [
            _text(row.get("title")),
            _text(row.get("genre")),
            " ".join(_text(x) for x in row.get("genres") or []),
            " ".join(_text(x) for x in row.get("tags") or []),
            _text(row.get("synopsis")),
        ]
    ).lower()


def _contains_signal(text: str, needle: str) -> bool:
    signal = _text(needle)
    if not signal:
        return False
    if signal.isascii() and len(signal) <= 3:
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(signal)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE))
    return signal.lower() in text.lower()


def _match_count(text: str, needles: list[str]) -> int:
    return sum(1 for needle in needles if _contains_signal(text, needle))


def _country_records(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for records in (data.get("collections") or {}).values():
        for row in records:
            grouped[row.get("country") or "unknown"].append(row)
    return grouped



def _available_countries() -> list[dict[str, str]]:
    return [{"country": country, "targetCountry": country, "displayCountry": COUNTRY_DISPLAY_KO.get(country, country)} for country in ALLOWED_COUNTRY_ORDER]


def _recommendation_notice(*, synopsis_present: bool) -> str:
    if synopsis_present:
        return '이 추천은 시장 흥행 예측이 아니라 장르와 시놉시스 기준의 1차 현지화 적합도 참고입니다. 작품의 줄거리, 결말, 캐릭터 정체성, 중심 갈등은 바꾸지 않습니다.'
    return '시놉시스가 없어 국가 추천은 제공하지 않고, 선택한 국가를 기준으로 번역 전 현지화 기준서만 만듭니다.'


def _translation_profile(country: str, *, genre: str, synopsis_present: bool) -> dict[str, Any]:
    display = COUNTRY_DISPLAY_KO.get(country, country)
    localization_level = "balanced" if synopsis_present else "conservative"
    if country == "Japan":
        dialogue_style = '장면 톤을 살리는 자연스러운 구어체와 호칭 체계를 우선한다.'
        proper_noun_policy = '고유명사는 작품 안에서 정한 표기 기준을 우선하고, 호칭은 일본 독자 기준으로 무리하게 바꾸지 않는다.'
        culture_policy = '한국 문화 요소는 현지 제도로 바꾸기보다 의미를 유지한 채 자연스럽게 풀어준다.'
    elif country == "China":
        dialogue_style = '관계와 긴장감을 살리는 간결한 구어체를 우선한다.'
        proper_noun_policy = '고유명사는 병기 기준을 유지하고, 호칭·직책은 작품 안에서 정한 표기 기준을 우선한다.'
        culture_policy = '한국 문화 요소는 설명을 덧붙이되 현지 권력/제도로 치환하지 않는다.'
    elif country == "Thailand":
        dialogue_style = '대사 리듬과 감정선을 우선하는 자연스러운 구어체를 쓴다.'
        proper_noun_policy = '고유명사는 음차 우선, 호칭은 작품 내 관계망을 훼손하지 않는 방식으로 유지한다.'
        culture_policy = '한국 문화 요소는 과한 현지화 대신 맥락 설명 중심으로 다룬다.'
    else:
        dialogue_style = '웹소설 문체의 속도감과 캐릭터 말맛을 살리는 자연스러운 구어체를 우선한다.'
        proper_noun_policy = '고유명사는 작품 안에서 같은 표기로 유지하고, 필요할 때만 짧게 보충 설명한다.'
        culture_policy = '한국 문화 요소는 삭제하거나 다른 문화로 치환하지 말고, 이해를 돕는 최소 설명만 덧붙인다.'

    return {
        "tone": f"{display} 독자에게도 과장 없이 읽히되 웹소설 특유의 속도감과 감정선을 살리는 톤",
        "dialogue_style": dialogue_style,
        "narration_style": '장면 기능과 시점 일관성을 유지하는 문장으로, 교과서식 평탄화는 피한다.',
        "localization_level": localization_level,
        "proper_noun_policy": proper_noun_policy,
        "culture_policy": culture_policy,
        "do_not": [
            '줄거리 변경 제안 금지',
            '결말 변경 제안 금지',
            '캐릭터 정체성 변경 제안 금지',
            '중심 갈등 변경 제안 금지',
            '장르나 서사 자체를 대상 국가에 맞춰 바꾸라는 제안 금지',
        ],
        "genre": genre,
        "country": country,
    }


def _evidence_from_row(row: dict[str, Any], reason: str) -> EvidenceItem:
    return EvidenceItem(
        platform=row.get("platform") or "unknown",
        collection=row.get("collection") or "unknown",
        rank=int(row.get("rank") or 0),
        title=row.get("title") or "",
        genre=row.get("genre"),
        tags=list(row.get("tags") or [])[:10],
        source_url=row.get("source_url"),
        reason=reason,
    )


def rank_countries(data: dict[str, Any], *, genre: str | None, synopsis: str | None) -> list[Recommendation]:
    genre_needles = _genre_needles(genre)
    synopsis_needles = _synopsis_needles(synopsis)
    grouped = _country_records(data)
    recommendations: list[Recommendation] = []
    for country, records in grouped.items():
        if country in EXCLUDED_RECOMMENDATION_COUNTRIES:
            continue
        score = 0.0
        reasons: Counter[str] = Counter()
        evidence_rows: list[tuple[float, dict[str, Any], str]] = []
        matched_rows = 0
        for row in records:
            text = _row_search_text(row)
            genre_hits = _match_count(text, genre_needles)
            synopsis_hits = _match_count(text, synopsis_needles)
            rank = int(row.get("rank") or 999)
            rank_weight = max(0.1, (120 - min(rank, 120)) / 120)
            row_score = (genre_hits * 3.0 + synopsis_hits * 1.2) * rank_weight
            if row_score <= 0:
                continue
            matched_rows += 1
            score += row_score
            if genre_hits:
                reasons["입력 장르가 공개 플랫폼 장르/태그와 겹칩니다"] += genre_hits
            if synopsis_hits:
                reasons["시놉시스 관련 신호가 공개 제목/설명/태그와 겹칩니다"] += synopsis_hits
            evidence_rows.append((row_score, row, f"장르 적중 {genre_hits}, 시놉시스 적중 {synopsis_hits}, 순위 {rank}"))
        if score > 0:
            # Normalize so larger crawls do not dominate the overlap reference.
            coverage_bonus = min(1.0, matched_rows / max(1, len(records))) * 20.0
            score = (score / max(1, len(records))) * 100.0 + coverage_bonus
        else:
            score = 0.0
            reasons["입력 장르·시놉시스와 직접 겹치는 공개 관측 근거가 없습니다"] = 1
            evidence_rows = []
        evidence = [_evidence_from_row(row, reason) for _, row, reason in sorted(evidence_rows, key=lambda x: x[0], reverse=True)[:8]]
        recommendations.append(
            Recommendation(
                country=country,
                score=round(score, 3),
                reasons=[f"{label} ({count})" for label, count in reasons.most_common(5)],
                evidence=evidence,
            )
        )
    seen = {rec.country for rec in recommendations}
    for country in ALLOWED_COUNTRY_ORDER:
        if country in seen or country in EXCLUDED_RECOMMENDATION_COUNTRIES:
            continue
        recommendations.append(
            Recommendation(
                country=country,
                score=0.0,
                reasons=["데이터셋에 입력과 직접 겹치는 공개 관측 근거가 없습니다"],
                evidence=[],
            )
        )
    return sorted(recommendations, key=lambda rec: rec.score, reverse=True)


def _country_profile(data: dict[str, Any], country: str):
    profiles = build_country_profiles(build_collection_profiles(data))
    normalized = normalize_country(country) or country
    for profile in profiles:
        if profile.country == normalized:
            return profile
    return profiles[0] if profiles else None


def _select_evidence(data: dict[str, Any], *, country: str, genre: str | None, synopsis: str | None, limit: int = 10) -> list[EvidenceItem]:
    normalized = normalize_country(country) or country
    recs = rank_countries(data, genre=genre, synopsis=synopsis)
    for rec in recs:
        if rec.country == normalized:
            return rec.evidence[:limit]
    records = _country_records(data).get(normalized, [])[:limit]
    return [_evidence_from_row(row, "country top exposure") for row in records]


def _section_payload(country_profile: Any, *, target_country: str, genre: str, synopsis: str, recommendations: list[Recommendation], evidence: list[EvidenceItem]) -> dict[str, Any]:
    raw_top_genres = country_profile.top_genres[:8] if country_profile else []
    raw_top_tags = country_profile.top_tags[:14] if country_profile else []
    top_genres = _public_label_list(raw_top_genres, limit=5)
    top_tags = _public_label_list(raw_top_tags, limit=8)
    signals = country_profile.localization_signals if country_profile else []
    guidance = country_profile.adaptation_guidance if country_profile else []
    cautions = country_profile.caution_points if country_profile else []
    synopsis_mode = bool(synopsis.strip())
    best_reasons = recommendations[0].reasons if recommendations else []
    genre_label = _public_label(genre) if genre else '미지정'  # '미지정' (py3.10 f-string 백슬래시 제약 회피)
    _top_genre_join = ', '.join(top_genres[:5])
    top_genres_label = _top_genre_join or '근거 부족'
    synopsis_note = _synopsis_input_note(synopsis)
    inferred_motifs = _synopsis_motifs(synopsis)
    top_tag_line = f"공개 플랫폼 자료에서 참고할 만한 태그 표현: {', '.join(top_tags[:8])}" if top_tags else '태그 참고 근거가 충분하지 않습니다.'
    target_label = _display_country_label(target_country)
    recommendation_note = _recommendation_notice(synopsis_present=synopsis_mode)
    localized_cautions = _clean_public_items([_localize_caution_item(item) for item in cautions[:5]], limit=5)
    localized_guidance = _clean_public_items([_localize_guidance_item(item) for item in guidance[:6]], limit=5)
    market_signal_items = [
        f"{target_label} 공개 플랫폼 자료는 흥행 예측이 아니라 제목·소개문·태그 표현을 점검하는 참고 신호로만 사용했습니다.",
        f"장르 참고 표현은 {top_genres_label} 범위에서만 확인하고, 작품의 장르 방향을 바꾸라는 의미로 쓰지 않았습니다.",
        f"시놉시스에서 읽힌 신호는 {', '.join(inferred_motifs)}이며, 소개문 후보를 점검하는 보조 기준으로만 사용합니다." if inferred_motifs else "시놉시스 근거가 부족하므로 시장 신호는 장르 일반 기대치 수준에서만 참고합니다.",
    ]
    if top_tags:
        market_signal_items.append(f"태그는 {', '.join(top_tags[:5])} 같은 공개 표현을 참고하되, 상태 태그나 노출용 메타 태그는 장르처럼 쓰지 않습니다.")
    platform_review_items = [
        f"{target_label} 기준으로 연령등급, 폭력/성적 표현, 플랫폼별 제한 표현을 게시 전 확인 대상으로 분리했습니다.",
        "현재 입력만으로 위반을 단정하지 않고, 본문 수위와 플랫폼별 최신 정책을 대조할 항목으로 표시합니다.",
    ] + localized_cautions
    release_items = [
        f"{target_label}용 제목·소개문·태그에서 장르 훅, 관계 축, 초반 갈등이 한눈에 보이는지 확인합니다.",
        "고유명사·호칭·스킬명은 작품 안에서 같은 표기로 유지되도록 표기 기준을 먼저 정합니다.",
        "공개 플랫폼 자료의 문장이나 제목을 그대로 옮기지 않고, 작품의 기존 방향을 유지한 표현 후보로만 반영합니다.",
    ] + localized_guidance
    return {
        "market_trend_fit": {
            "title": '현지화 기준서 요약',
            "items": [
                f"대상 국가: {target_label} / 입력 장르: {genre_label}",
                synopsis_note,
                f"상위 장르 참고: {top_genres_label}",
                recommendation_note,
            ],
        },
        "genre_trope_alignment": {
            "title": '번역/표현 방향을 이렇게 읽었어요',
            "items": [
                f"입력 장르 `{genre_label}`을 우선 기준으로 삼되, 이야기 구조를 바꾸지 않고 번역 방향만 정리했습니다.",
                synopsis_note,
                f"시놉시스에서 보이는 관련 신호: {', '.join(inferred_motifs)}" if inferred_motifs else '시놉시스 관련 신호: 확인할 내용이 부족합니다.',
                '장면 톤과 캐릭터 말투는 살리고, 문장을 교과서식으로 평평하게 만들지 않습니다.',
            ]
            + signals[:4],
        },
        "title_synopsis_localization": {
            "title": f"{target_label} 독자에게는 어떻게 소개하면 좋을까요?",
            "items": [
                '플랫폼 상위 노출작은 장르 훅과 관계 축을 빠르게 드러내는 경향이 있지만, 이 가이드는 흥행 예측이 아니라 표현 방향 참고만 제공합니다.',
                f"시놉시스에서 읽힌 관련 신호는 {', '.join(inferred_motifs)}입니다. 다만 이것은 확정 태그가 아니라 소개문·태그 후보를 점검하기 위한 참고입니다." if inferred_motifs else '시놉시스 근거가 부족하므로 제목·소개문 후보는 장르의 대표 기대치 수준에서만 확인합니다.',
                '공개 시놉시스는 신호 분석에만 사용하고 문장을 그대로 옮기지 않습니다.',
            ],
        },
        "terminology_glossary_risks": {
            "title": f"{target_label} 고유명사·호칭·문화 요소 처리",
            "items": [
                top_tag_line,
                '이 키워드는 적용 지시가 아니라 대상 플랫폼에서 자주 보인 공개 태그/장르 표현입니다.',
                '고유명사, 스킬명, 계급명, 호칭은 작품 안에서 같은 표기로 유지하고 태그 표현과 충돌하지 않는지 확인합니다.',
            ],
        },
        "content_rating_sensitivity": {
            "title": '플랫폼/문화권 검토 항목',
            "items": [
                '연령등급, 잔혹/성적 표현, 플랫폼별 금지·제한 표현은 시장 분위기와 별개로 확인합니다.',
                '시놉시스에서 나온 민감 요소는 위반 확정이 아니라 게시 전 확인 후보로 표시합니다.' if synopsis_mode else '시놉시스가 없으면 민감 요소 확인은 장르 일반론을 넘어서 확정하지 않습니다.',
            ]
            + [_localize_caution_item(item) for item in cautions[:5]]
            + ['플랫폼별 노출 순서는 시장 전체가 아니라 해당 플랫폼 증거로만 표현합니다.'],
        },
        "adaptation_checklist": {
            "title": '피해야 할 방식과 다음 확인',
            "items": [_localize_guidance_item(item) for item in guidance[:6]] + [
                '최종 가이드는 스토리 수정 지시가 아니라 번역/현지화 기준서로만 사용합니다.',
                '본문 수집 없이 공개 메타데이터와 사용자가 입력한 시놉시스 신호만 사용합니다.',
            ],
        },
        "evidence_used": {
            "title": '사용 근거',
            "items": [
                f"{ev.platform}/{ev.collection} 순위 {ev.rank}: {ev.title} ({ev.genre or '장르 미확인'}) — {ev.reason}"
                for ev in evidence[:8]
            ] or best_reasons or ["직접 선택한 근거가 없습니다."],
        },
        "platform_culture_review_result": {
            "title": '플랫폼·문화권 검토 결과',
            "items": platform_review_items,
        },
        "market_signal_summary": {
            "title": '참고한 시장 신호 요약',
            "items": market_signal_items,
        },
        "release_readiness_checklist": {
            "title": '출시 전 확인할 것',
            "items": release_items,
        },
    }


def _localize_guidance_item(item: str) -> str:
    text = str(item or "").strip()
    if not text:
        return text
    translations = {
        "Anchor the pitch in the dominant platform-visible genre mix before adding niche cultural explanations.": "먼저 해당 플랫폼에서 두드러진 장르 조합을 기준으로 잡고, 세부 문화 설명은 그 다음에 덧붙입니다.",
        "Convert synopsis observations into title hooks, opening-episode stakes, and tag/copy choices rather than copying source descriptions.": "시놉시스에서 읽은 내용은 제목 훅, 첫 화 갈등, 소개문·태그 선택으로 바꾸고 원문 설명을 그대로 옮기지 않습니다.",
        "Use the platform's top genre/tag mix as the primary guide; avoid overclaiming beyond the collected public ranking metadata.": "가장 두드러진 장르·태그 조합을 우선 참고하고, 수집된 공개 순위 메타데이터를 넘어서 단정하지 않습니다.",
        "No strong overlap was found, so keep the guide conservative and anchored in public evidence.": "강한 겹침이 없어 가이드는 보수적으로 유지하고 공개 근거에만 기대어 작성합니다.",
        "Preserve progression mechanics in translation: skill names, rank terms, and upgrade cadence should be consistent across episodes.": "번역에서는 성장 메커니즘을 유지하고, 스킬명·등급 표현·강화 흐름이 회차마다 일관되게 보이도록 합니다.",
        "Make relationship premise, power imbalance, consent boundary, and emotional payoff legible in synopsis and chapter-one localization.": "시놉시스와 첫 화 현지화에서는 관계 전제, 힘의 차이, 동의 경계, 감정적 보상이 분명하게 읽히도록 합니다.",
        "Explain reincarnation/transport premises compactly; readers tolerate familiar setups when the unique advantage is clear.": "회귀·전생·이세계 전제는 짧고 분명하게 설명하고, 익숙한 설정이라도 고유한 강점이 드러나면 수용된다는 점을 반영합니다.",
        "For English platforms, foreground premise clarity and genre tags; avoid long cultural footnote-style exposition in the opening pitch.": "영어권 플랫폼에서는 전제의 선명함과 장르 태그를 먼저 보여주고, 첫 소개문에서 긴 문화 주석형 설명은 피합니다.",
    }
    return translations.get(text, text)


def _localize_caution_item(item: str) -> str:
    text = str(item or "").strip()
    if not text:
        return text
    translations = {
        "Do not treat platform exposure order as a universal national market ranking; it is platform-specific evidence.": "플랫폼 노출 순서는 국가 전체 시장 순위로 보지 말고, 해당 플랫폼에서만 확인된 근거로 다룹니다.",
        "Do not use collected synopsis text as story content; summarize signals and cite platform/source/date instead.": "수집한 시놉시스 문장을 이야기 본문처럼 쓰지 말고, 신호만 요약한 뒤 플랫폼·출처·날짜를 함께 적습니다.",
    }
    return translations.get(text, text)


def _model_prompt_payload(*, original: dict[str, Any], target_country: str, recommendations: list[Recommendation], sections: dict[str, Any], evidence: list[EvidenceItem]) -> dict[str, Any]:
    return {
        "role": "localization_guide_generator",
        "task": "Generate a pre-translation localization criteria guide. Do not rewrite the story, ending, character identity, or central conflict.",
        "original": original,
        "targetCountry": target_country,
        "recommendedCountries": [asdict(rec) for rec in recommendations[:3]],
        "evidence": [asdict(ev) for ev in evidence],
        "requiredOutputSections": list(sections.keys()),
        "claimLimit": "Phrase conclusions as first-pass localization fit, not market success prediction or national readership certainty.",
        "evidencePolicy": {
            "allowed": ["public rank/exposure metadata", "title", "genre", "tags", "public metrics", "public synopsis/description"],
            "excluded": ["episode/story body text", "paid or locked content", "login-only data", "image downloads"],
        },
        "translation_profile": _translation_profile(target_country, genre=original.get("genre") or "", synopsis_present=bool(original.get("synopsis"))),
    }


def _html_report(*, title: str, mode_label: str, target_country: str, genre: str, sections: dict[str, Any], recommendations: list[Recommendation]) -> str:
    def esc(value: Any) -> str:
        return html.escape(_strip_public_noise(value))

    section_html = []
    for key in PUBLIC_SECTION_KEYS:
        section = sections.get(key) or {}
        clean_items = [_strip_public_noise(item) for item in section.get("items", [])]
        items = "".join(f"<li>{esc(item)}</li>" for item in clean_items if item)
        if not items:
            continue
        section_html.append(
            f"<div class='guide-section'><div class='guide-section-header'><span class='guide-section-title'>{esc(section.get('title', key))}</span></div><ul class='guide-list'>{items}</ul></div>"
        )
    display_country = _display_country_label(target_country)
    quality_items = "".join(
        f"<li>{esc(item)}</li>"
        for item in _guide_quality_summary(
            target_country=target_country,
            genre=genre,
            sections=sections,
            recommendations=recommendations,
        )
    )
    action_items = "".join(
        f"<li>{esc(item)}</li>"
        for item in _guide_action_checklist(target_country=target_country, sections=sections)
    )
    boundary_note = (
        "이 리포트는 작품을 바꾸는 컨설팅이 아니라, 작품을 현재 방향 그대로 두고 "
        "어느 국가에서 어떻게 전달하면 좋은지 정리하는 현지화 리포트입니다."
    )
    body_html = f"""
    <div class="guide-report">
      <div class="guide-cover">
        <div class="guide-cover-label">번역 전 현지화 기준서 · 플랫폼 참고 근거</div>
        <div class="guide-cover-title">{esc(display_country)} 현지화 기준서<br><em>번역/표현 방향 리포트</em></div>
        <div class="guide-cover-sub"><span>{esc(mode_label)}</span><span>{esc(genre or '장르 미입력')}</span><span>플랫폼 트렌드 참고</span></div>
      </div>
      <div class="guide-legacy-anchors">번역 방향 · 문화 주의사항 · 플랫폼 검토 항목</div>
      <div class="guide-section"><p class="quiet-note">{esc(boundary_note)}</p></div>
      <div class="guide-section"><div class="guide-section-header"><span class="guide-section-title">핵심 판단</span></div><ul class="guide-list">{quality_items}</ul></div>
      <div class="guide-section"><div class="guide-section-header"><span class="guide-section-title">출시 전 전달 체크리스트</span></div><ul class="guide-list">{action_items}</ul></div>
      {''.join(section_html)}
    </div>
    """
    return build_guide_html_document(title=f"{display_country} 현지화 기준서", body_html=body_html)


def _display_country_label(target_country: str) -> str:
    key = str(target_country).strip()
    return COUNTRY_DISPLAY_KO.get(key, key)


def _recommendation_payload(recommendations: list[Recommendation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in recommendations:
        item = asdict(rec)
        item["displayCountry"] = _display_country_label(rec.country)
        rows.append(item)
    return rows


def _guide_quality_summary(*, target_country: str, genre: str, sections: dict[str, Any], recommendations: list[Recommendation]) -> list[str]:
    """Build short user-facing summary bullets from deterministic evidence."""

    target_label = _display_country_label(target_country)
    items = [f"{target_label} 기준으로 장르·시놉시스·공개 플랫폼 신호를 분리해 번역 전 기준을 정리했습니다."]
    if genre:
        items.append(f"입력 장르 `{genre}`는 제목/소개문 훅과 태그 후보를 점검하는 1차 기준으로만 사용합니다.")
    if recommendations:
        top = recommendations[0]
        top_label = _display_country_label(top.country)
        if top.reasons:
            if top.country == target_country:
                items.append(f"입력 시놉시스 기준 추천 상위 후보도 {top_label}이며, 주요 근거는 {top.reasons[0]}입니다.")
            else:
                items.append(f"입력 시놉시스 기준 추천 상위 후보는 {top_label}이지만, 이 리포트는 사용자가 선택한 {target_label} 기준으로 작성했습니다.")
    for section_key in ("title_synopsis_localization", "terminology_glossary_risks", "content_rating_sensitivity"):
        section = sections.get(section_key) or {}
        section_items = section.get("items") or []
        if section_items:
            items.append(_strip_public_noise(section_items[0]))
    return items[:5]


def _guide_action_checklist(*, target_country: str, sections: dict[str, Any]) -> list[str]:
    """Concrete next actions for WEB users after reading the guide."""

    target_label = _display_country_label(target_country)
    checklist = [
        f"{target_label}용 제목/소개문에서 장르 훅, 관계 축, 초반 갈등이 한눈에 보이는지 확인합니다.",
        "고유명사·호칭·스킬명은 작품 안에서 같은 방식으로 쓰이도록 기준을 정한 뒤 번역에 반영합니다.",
        "연령등급, 폭력/성적 표현, 플랫폼 정책 리스크는 게시 전 별도 검수 항목으로 표시합니다.",
    ]
    section = sections.get("release_readiness_checklist") or sections.get("title_synopsis_localization") or {}
    for item in section.get("items") or []:
        text = _strip_public_noise(item)
        if text and text not in checklist:
            checklist.append(text)
            break
    return checklist[:5]


def recommend_country(payload: dict[str, Any], *, data_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    data = load_trend_data(data_path)
    genre = _text(payload.get("genre"))
    synopsis = _text(payload.get("synopsis") or payload.get("desc"))
    requested_country = normalize_country(payload.get("targetCountry") or payload.get("country"))
    recommendations = rank_countries(data, genre=genre, synopsis=synopsis)
    limitation_notice = _recommendation_notice(synopsis_present=bool(synopsis))

    if not synopsis and (not requested_country or not genre):
        missing = []
        if not requested_country:
            missing.append("대상 국가")
        if not genre:
            missing.append("장르")
        return {
            "mode": "needs_country_and_genre_selection",
            "requiresSelection": True,
            "message": f"시놉시스가 없어 국가 추천은 제공할 수 없습니다. {'와 '.join(missing)}를 선택하면 번역 전 현지화 기준서를 만들 수 있습니다.",
            "availableCountries": _available_countries(),
            "limitation_notice": limitation_notice,
            "recommendedCountry": None,
            "recommendedCountries": [],
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    if synopsis:
        top = recommendations[0] if recommendations else None
        return {
            "mode": "synopsis_country_recommendation",
            "requiresSelection": False,
            "title": "4개국 비교 추천",
            "genre": genre,
            "synopsis": synopsis,
            "availableCountries": _available_countries(),
            "recommendedCountry": top.country if top else None,
            "recommendedCountryDisplay": _display_country_label(top.country) if top else None,
            "recommendedCountries": _recommendation_payload(recommendations[:3]),
            "limitation_notice": limitation_notice,
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    selected_country = requested_country or (recommendations[0].country if recommendations else "US/global English")
    top = recommendations[0] if recommendations else None
    selected_display = _display_country_label(selected_country)
    return {
        "mode": "country_genre_guide",
        "requiresSelection": False,
        "targetCountry": selected_country,
        "targetCountryDisplay": selected_display,
        "country": selected_country,
        "displayCountry": selected_display,
        "recommendedCountry": top.country if top else None,
        "recommendedCountryDisplay": _display_country_label(top.country) if top else None,
        "recommendedCountries": _recommendation_payload(recommendations[:3]),
        "availableCountries": _available_countries(),
        "limitation_notice": limitation_notice,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def generate_localization_guide(payload: dict[str, Any], *, data_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    data = load_trend_data(data_path)
    genre = _text(payload.get("genre"))
    synopsis = _text(payload.get("synopsis") or payload.get("desc"))
    requested_country = normalize_country(payload.get("targetCountry") or payload.get("country"))
    if synopsis:
        return recommend_country(payload, data_path=data_path)
    if not requested_country or not genre:
        return recommend_country(payload, data_path=data_path)

    recommendations = rank_countries(data, genre=genre, synopsis=synopsis)
    top = recommendations[0] if recommendations else None
    selected_country = requested_country
    selected_display = _display_country_label(selected_country)
    profile = _country_profile(data, selected_country)
    evidence = _select_evidence(data, country=selected_country, genre=genre, synopsis=synopsis)
    synopsis_present = bool(synopsis)
    sections = _section_payload(
        profile,
        target_country=selected_country,
        genre=genre,
        synopsis=synopsis,
        recommendations=recommendations,
        evidence=evidence,
    )
    quality_summary = _guide_quality_summary(
        target_country=selected_country,
        genre=genre,
        sections=sections,
        recommendations=recommendations,
    )
    recommendation_notice = _recommendation_notice(synopsis_present=synopsis_present)
    recommended_country = top.country if synopsis_present and top else None
    display_title = f"{selected_display} 현지화 기준서"
    html_report = _html_report(
        title=display_title,
        mode_label='시놉시스 기반 추천 반영' if synopsis_present else '국가/장르 기반 기준서',
        target_country=selected_country,
        genre=genre,
        sections=sections,
        recommendations=recommendations,
    )
    original = {
        "title": payload.get("title"),
        "genre": genre,
        "synopsis": synopsis,
        "tags": payload.get("tags") or [],
        "ageRating": payload.get("ageRating") or payload.get("rating"),
        "glossary": payload.get("glossary") or {},
    }
    result = {
        "mode": "country_genre_guide",
        "generationMode": "deterministic_guide",
        "requiresSelection": False,
        "title": display_title,
        "country": selected_country,
        "targetCountry": selected_country,
        "displayCountry": selected_display,
        "targetCountryDisplay": selected_display,
        "genre": genre,
        "synopsis": synopsis,
        "recommendedCountry": recommended_country,
        "recommendedCountryDisplay": _display_country_label(recommended_country) if recommended_country else None,
        "limitation_notice": recommendation_notice,
        "availableCountries": _available_countries(),
        "recommendedCountries": _recommendation_payload(recommendations[:3]) if synopsis_present else [],
        "qualitySummary": quality_summary,
        "sections": sections,
        "evidenceUsed": [asdict(ev) for ev in evidence],
        "modelPromptPayload": _model_prompt_payload(
            original=original,
            target_country=selected_country,
            recommendations=recommendations,
            sections=sections,
            evidence=evidence,
        ),
        "htmlReport": html_report,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return result


def build_localization_advice(payload: dict[str, Any], *, data_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    """Backward-compatible wrapper for the guide flow."""

    return generate_localization_guide(payload, data_path=data_path)

__all__ = [
    "EvidenceItem",
    "Recommendation",
    "build_localization_advice",
    "generate_localization_guide",
    "normalize_country",
    "rank_countries",
    "recommend_country",
]
