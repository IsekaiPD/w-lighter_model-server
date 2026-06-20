
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import ROOT
DEFAULT_INPUT = ROOT / "data" / "platform_observation" / "platform_trends_current.json"
DEFAULT_REPORT = ROOT / "data" / "platform_observation" / "platform_trend_localization_guide.md"
DEFAULT_PROMPT = ROOT / "data" / "platform_observation" / "platform_trend_guide_prompt.json"

STOPWORDS = {
    "with", "from", "that", "this", "their", "there", "into", "only", "have", "after", "before",
    "when", "where", "what", "will", "been", "being", "they", "them", "than", "then", "herself",
    "himself", "story", "novel", "series", "world", "must", "life", "find", "more", "about", "would",
    "could", "should", "because", "while", "through", "against", "first", "second", "again",
}

JP_ISEKAI_REINCARNATION = "\u7570\u4e16\u754c\u8ee2\u751f"
JP_ISEKAI_TRANSFER = "\u7570\u4e16\u754c\u8ee2\u79fb"
JP_ISEKAI_ROMANCE = "\u7570\u4e16\u754c\u3014\u604b\u611b\u3015"
JP_MALE_LEAD = "\u7537\u4e3b\u4eba\u516c"
JP_FEMALE_LEAD = "\u5973\u4e3b\u4eba\u516c"
JP_ENGAGEMENT_BREAK = "\u5a5a\u7d04\u7834\u68c4"
JP_DOTING = "\u6eba\u611b"
JP_CHEAT = "\u30c1\u30fc\u30c8"
JP_SKILL = "\u30b9\u30ad\u30eb"
JP_CRUEL_WARNING = "\u6b8b\u9177\u306a\u63cf\u5199\u3042\u308a"


@dataclass(frozen=True)
class CollectionProfile:
    key: str
    country: str
    platform: str
    collection: str
    ranking_basis: str
    item_count: int
    top_genres: list[tuple[str, int]]
    top_tags: list[tuple[str, int]]
    status_counts: list[tuple[str, int]]
    metric_coverage: dict[str, int]
    top_titles: list[str]
    synopsis_terms: list[tuple[str, int]]


@dataclass(frozen=True)
class CountryProfile:
    country: str
    collections: list[CollectionProfile]
    top_genres: list[tuple[str, int]]
    top_tags: list[tuple[str, int]]
    synopsis_terms: list[tuple[str, int]]
    localization_signals: list[str]
    adaptation_guidance: list[str]
    caution_points: list[str]


def load_trend_data(path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_space(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def collect_metric_coverage(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    coverage: Counter[str] = Counter()
    for row in records:
        for key, value in (row.get("public_metrics") or {}).items():
            if value is not None:
                coverage[key] += 1
    return dict(coverage.most_common())


def synopsis_keyword_counter(records: Iterable[dict[str, Any]], *, limit: int = 20) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in records:
        text = normalize_space(" ".join([row.get("title") or "", row.get("synopsis") or ""]))
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text.lower()):
            token = token.strip("'-")
            if token and token not in STOPWORDS:
                counter[token] += 1
    return counter.most_common(limit)


def counter_from_records(records: Iterable[dict[str, Any]], field: str, *, limit: int = 30) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in records:
        values = row.get(field)
        if isinstance(values, list):
            for value in values:
                if value:
                    counter[str(value)] += 1
        elif values:
            counter[str(values)] += 1
    return counter.most_common(limit)


def build_collection_profiles(data: dict[str, Any]) -> list[CollectionProfile]:
    profiles: list[CollectionProfile] = []
    for key, records in (data.get("collections") or {}).items():
        if not records:
            continue
        first = records[0]
        profiles.append(
            CollectionProfile(
                key=key,
                country=first.get("country") or "unknown",
                platform=first.get("platform") or "unknown",
                collection=first.get("collection") or key,
                ranking_basis=first.get("ranking_basis") or "unknown",
                item_count=len(records),
                top_genres=counter_from_records(records, "genres", limit=20),
                top_tags=counter_from_records(records, "tags", limit=30),
                status_counts=counter_from_records(records, "status", limit=10),
                metric_coverage=collect_metric_coverage(records),
                top_titles=[row.get("title") or "" for row in records[:10]],
                synopsis_terms=synopsis_keyword_counter(records, limit=20),
            )
        )
    return profiles


def merge_counter(profiles: Iterable[CollectionProfile], attr: str, *, limit: int = 30) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for profile in profiles:
        for label, count in getattr(profile, attr):
            counter[label] += count
    return counter.most_common(limit)


def has_any(items: Iterable[tuple[str, int]], needles: Iterable[str]) -> bool:
    haystack = " | ".join(label.lower() for label, _ in items)
    return any(needle.lower() in haystack for needle in needles)


def derive_signals(country: str, genres: list[tuple[str, int]], tags: list[tuple[str, int]], terms: list[tuple[str, int]]) -> list[str]:
    signals: list[str] = []
    if has_any(tags, ["litrpg", "progression", "gamelit", "cultivation"]):
        signals.append("System/progression readability is a primary market signal: levels, skills, growth loops, and payoff cadence should be explicit.")
    if has_any(tags, ["isekai", "reincarnation", "portal fantasy", JP_ISEKAI_REINCARNATION, JP_ISEKAI_TRANSFER]):
        signals.append("Isekai/reincarnation framing is prominent; early setup should clarify transfer/rebirth rules and the protagonist's advantage.")
    if has_any(genres, ["Romance Fantasy", "Romance", "BL", "LGBTQ+", JP_ISEKAI_ROMANCE]):
        signals.append("Relationship-forward fantasy/romance demand is strong; emotional stakes and pairing dynamics need clear early hooks.")
    if has_any(tags, ["male lead", JP_MALE_LEAD]):
        signals.append("Male-protagonist adventure/power-fantasy remains visible in platform exposure.")
    if has_any(tags, ["female lead", JP_FEMALE_LEAD, "villainess", JP_ENGAGEMENT_BREAK, JP_DOTING]):
        signals.append("Female-lead status reversal, romance conflict, and social-position tropes are visible localization levers.")
    if has_any(tags, ["r15", JP_CRUEL_WARNING, "war", "apocalypse", "survival"]):
        signals.append("Content-intensity labels recur; violence, survival pressure, and age-rating expectations should be handled explicitly.")
    if not signals:
        signals.append("Use the platform's top genre/tag mix as the primary guide; avoid overclaiming beyond the collected public ranking metadata.")
    return signals


def derive_guidance(country: str, genres: list[tuple[str, int]], tags: list[tuple[str, int]]) -> list[str]:
    guidance = [
        "Anchor the pitch in the dominant platform-visible genre mix before adding niche cultural explanations.",
        "Convert synopsis observations into title hooks, opening-episode stakes, and tag/copy choices rather than copying source descriptions.",
    ]
    if has_any(tags, ["litrpg", "progression", "gamelit", "magic", "cheat", JP_CHEAT, JP_SKILL]):
        guidance.append("Preserve progression mechanics in translation: skill names, rank terms, and upgrade cadence should be consistent across episodes.")
    if has_any(genres, ["Romance Fantasy", "BL", "Romance", JP_ISEKAI_ROMANCE]):
        guidance.append("Make relationship premise, power imbalance, consent boundary, and emotional payoff legible in synopsis and chapter-one localization.")
    if has_any(tags, ["isekai", "reincarnation", JP_ISEKAI_REINCARNATION, JP_ISEKAI_TRANSFER]):
        guidance.append("Explain reincarnation/transport premises compactly; readers tolerate familiar setups when the unique advantage is clear.")
    if "Japan" in country:
        guidance.append("For Japan, compare Korean proper nouns and honorific/social-rank terms against light-novel readability; keep hierarchy clear but reduce unexplained Korean-only institutional terms.")
    if "US" in country or "English" in country:
        guidance.append("For English platforms, foreground premise clarity and genre tags; avoid long cultural footnote-style exposition in the opening pitch.")
    return guidance


def derive_cautions(country: str, genres: list[tuple[str, int]], tags: list[tuple[str, int]]) -> list[str]:
    cautions = [
        "Do not treat platform exposure order as a universal national market ranking; it is platform-specific evidence.",
        "Do not use collected synopsis text as story content; summarize signals and cite platform/source/date instead.",
    ]
    if has_any(tags, ["fan fiction"]):
        cautions.append("Royal Road includes fan fiction in trend exposure; separate original-work localization advice from fandom-specific popularity.")
    if has_any(tags, ["r15", JP_CRUEL_WARNING]):
        cautions.append("Japanese rankings expose age/content warnings; localization should preserve rating-sensitive violence/sexual-content cues.")
    if has_any(genres, ["BL", "LGBTQ+", "GL"]):
        cautions.append("BL/LGBTQ+ categories need tone and consent sensitivity; do not flatten identity-coded works into generic romance.")
    return cautions


def build_country_profiles(collection_profiles: list[CollectionProfile]) -> list[CountryProfile]:
    grouped: dict[str, list[CollectionProfile]] = defaultdict(list)
    for profile in collection_profiles:
        grouped[profile.country].append(profile)
    countries: list[CountryProfile] = []
    for country, profiles in sorted(grouped.items()):
        genres = merge_counter(profiles, "top_genres", limit=30)
        tags = merge_counter(profiles, "top_tags", limit=40)
        terms = merge_counter(profiles, "synopsis_terms", limit=30)
        countries.append(
            CountryProfile(
                country=country,
                collections=profiles,
                top_genres=genres,
                top_tags=tags,
                synopsis_terms=terms,
                localization_signals=derive_signals(country, genres, tags, terms),
                adaptation_guidance=derive_guidance(country, genres, tags),
                caution_points=derive_cautions(country, genres, tags),
            )
        )
    return countries


def fmt_pairs(pairs: Iterable[tuple[str, int]], *, limit: int = 10) -> str:
    values = [f"{label} ({count})" for label, count in list(pairs)[:limit]]
    return ", ".join(values) if values else "not observed"


def bullet_lines(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_markdown(data: dict[str, Any]) -> str:
    collection_profiles = build_collection_profiles(data)
    country_profiles = build_country_profiles(collection_profiles)
    generated_at = datetime.now(timezone.utc).isoformat()
    source_generated_at = data.get("generated_at", "unknown")
    lines: list[str] = [
        "# Platform Trend Localization Guide Draft",
        "",
        f"Generated at: {generated_at}",
        f"Source trend snapshot: {source_generated_at}",
        "",
        "## Method",
        "",
        "This guide is generated from public platform trend/exposure metadata. It uses ranks, titles, genres, tags, public metrics, and public synopsis/description fields. It does not use episode/story body text, paid content, login-only data, or image downloads.",
        "",
        "Use it as a current trend signal for localization planning, not as a universal national readership survey.",
        "",
        "## Executive Summary",
        "",
    ]
    for country in country_profiles:
        lines.extend(
            [
                f"### {country.country}",
                "",
                f"Dominant genres: {fmt_pairs(country.top_genres, limit=8)}.",
                f"Dominant tags/signals: {fmt_pairs(country.top_tags, limit=12)}.",
                "",
                "Key localization signals:",
                bullet_lines(country.localization_signals),
                "",
            ]
        )

    lines.append("## Country and Platform Notes")
    lines.append("")
    for country in country_profiles:
        lines.extend([f"## {country.country}", ""])
        lines.extend(["### Adaptation guidance", "", bullet_lines(country.adaptation_guidance), ""])
        lines.extend(["### Caution points", "", bullet_lines(country.caution_points), ""])
        lines.extend(["### Platform evidence", ""])
        for profile in country.collections:
            lines.extend(
                [
                    f"#### {profile.platform} - {profile.collection}",
                    "",
                    f"- Ranking basis: `{profile.ranking_basis}`",
                    f"- Items collected: {profile.item_count}",
                    f"- Top genres: {fmt_pairs(profile.top_genres, limit=8)}",
                    f"- Top tags: {fmt_pairs(profile.top_tags, limit=12)}",
                    f"- Status mix: {fmt_pairs(profile.status_counts, limit=6)}",
                    f"- Metric coverage: {fmt_pairs(list(profile.metric_coverage.items()), limit=8)}",
                    f"- Repeated synopsis/title terms: {fmt_pairs(profile.synopsis_terms, limit=12)}",
                    f"- Sample top titles: {', '.join(profile.top_titles[:5])}",
                    "",
                ]
            )

    lines.extend(
        [
            "## Recommended Generator Prompt Shape",
            "",
            "When an API/model layer uses this guide, provide:",
            "",
            "1. Target country/platform.",
            "2. Korean original genre, synopsis, tags, and target age rating.",
            "3. This trend summary and top RAG documents as evidence.",
            "4. Required output: keep/change/avoid recommendations with evidence references.",
            "",
            "Suggested output sections:",
            "",
            "```txt",
            "Market trend fit",
            "Genre/trope alignment",
            "Title and synopsis localization",
            "Terminology/glossary risks",
            "Content-rating and sensitivity notes",
            "Concrete adaptation checklist",
            "Evidence used",
            "```",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_prompt_payload(data: dict[str, Any], *, max_docs_per_collection: int = 8) -> dict[str, Any]:
    collection_profiles = build_collection_profiles(data)
    country_profiles = build_country_profiles(collection_profiles)
    docs_by_collection: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in data.get("rag_documents") or []:
        metadata = doc.get("metadata") or {}
        key = f"{metadata.get('platform')}::{metadata.get('collection')}"
        if len(docs_by_collection[key]) < max_docs_per_collection:
            docs_by_collection[key].append(doc)
    return {
        "role": "localization_guide_generator",
        "source_generated_at": data.get("generated_at"),
        "task": "Generate country/platform-specific localization guidance for a Korean webnovel using current platform trend evidence.",
        "safety_policy": {
            "allowed_evidence": ["public rank/exposure metadata", "title", "genre", "tags", "public metrics", "public synopsis/description"],
            "disallowed_evidence": ["episode/story body text", "paid or locked content", "login-only data", "image downloads"],
            "claim_limit": "Do not claim national readership certainty; phrase as platform trend evidence.",
        },
        "country_profiles": [
            {
                "country": profile.country,
                "top_genres": profile.top_genres[:12],
                "top_tags": profile.top_tags[:16],
                "synopsis_terms": profile.synopsis_terms[:12],
                "localization_signals": profile.localization_signals,
                "adaptation_guidance": profile.adaptation_guidance,
                "caution_points": profile.caution_points,
            }
            for profile in country_profiles
        ],
        "evidence_documents_sample": docs_by_collection,
        "required_output_sections": [
            "market_trend_fit",
            "genre_trope_alignment",
            "title_synopsis_localization",
            "terminology_glossary_risks",
            "content_rating_sensitivity",
            "adaptation_checklist",
            "evidence_used",
        ],
    }


def write_outputs(data: dict[str, Any], *, report_path: Path = DEFAULT_REPORT, prompt_path: Path = DEFAULT_PROMPT) -> tuple[Path, Path]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(data), encoding="utf-8")
    prompt_path.write_text(json.dumps(build_prompt_payload(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path, prompt_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate localization guide draft from collected platform trend metadata.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    args = parser.parse_args()
    data = load_trend_data(args.input)
    report, prompt = write_outputs(data, report_path=args.report, prompt_path=args.prompt)
    print(report)
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
