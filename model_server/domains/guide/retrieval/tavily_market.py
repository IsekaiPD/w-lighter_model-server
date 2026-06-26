from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse


COUNTRY_ALIASES = {
    "jp": "JP",
    "japan": "JP",
    "일본": "JP",
    "日本": "JP",

    "us": "US",
    "en": "US",
    "usa": "US",
    "english": "US",
    "global english": "US",
    "미국": "US",
    "영어권": "US",

    "cn": "CN",
    "china": "CN",
    "중국": "CN",
    "中国": "CN",

    "th": "TH",
    "thailand": "TH",
    "태국": "TH",
    "ไทย": "TH",
}


TRUSTED_DOMAINS = {
    "JP": [
        "kakuyomu.jp",
        "syosetu.com",
        "ncode.syosetu.com",
        "alphapolis.co.jp",
    ],
    "US": [
        "royalroad.com",
        "wattpad.com",
        "tapas.io",
        "inkitt.com",
    ],
    "CN": [
        "write.qq.com",
        "qidian.com",
        "fanqienovel.com",
        "jjwxc.net",
        "yuewen.com",
        "chinawriter.com.cn",
        "cssn.cn",
    ],
    "TH": [
        "readawrite.com",
        "dek-d.com",
        "novel.dek-d.com",
        "fictionlog.co",
        "tunwalai.com",
    ],
}


REFERENCE_DOMAINS = {
    "JP": [
        "note.com",
        "detail.chiebukuro.yahoo.co.jp",
        "novelmore.jp",
    ],
    "US": [
        "reddit.com",
    ],
    "CN": [
        "zhihu.com",
        "jiemian.com",
    ],
    "TH": [
        "pantip.com",
        "lemon8-app.com",
        "kawebook.com",
    ],
}


QUERY_CONFIG = {
    "JP": {
        "platform_reference": "小説家になろう カクヨム 投稿 ガイドライン コンテンツ規定",
        "k_content_reception": "韓国 ウェブ漫画 マンファ ウェブ小説 日本 人気 流行 受容 読者",
    },
    "US": {
        "platform_reference": "Royal Road content guidelines fiction tags AI sexual violence",
        "k_content_reception": "Korean webtoon manhwa growing popularity US readers Webtoon Tapas LINE",
    },
    "CN": {
        "platform_reference": "起点中文网 晋江文学城 番茄小说 投稿 规则 内容规范",
        "k_content_reception": "Korean webtoon manhwa Chinese market popularity overseas",
    },
    "TH": {
        "platform_reference": "ReadAWrite Dek-D กฎการลงนิยาย เนื้อหาต้องห้าม",
        "k_content_reception": "เว็บตูน เกาหลี ไทย ความนิยม นักอ่าน มังฮวา",
    },
}


REQUIRED_CATEGORIES = [
    "platform_reference",
    "k_content_reception",
]


SOURCE_PRIORITY = {
    "trusted": 1,
    "reference": 2,
    "other": 99,
}


CATEGORY_PRIORITY = {
    "platform_reference": 1,
    "k_content_reception": 2,
}


def _truthy_flag(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"", "0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True

    return default


def live_market_enabled(payload: dict[str, Any]) -> bool:
    """Return whether Tavily enrichment is enabled for a selected-country guide.

    Compatibility contract: the ordinary country/genre guide remains opt-in by
    default. Synopsis four-country comparison uses the separate
    ``_synopsis_live_market_enabled`` gate, which is default-on.
    """
    if "includeLiveMarket" in payload:
        return _truthy_flag(payload.get("includeLiveMarket"), default=False)

    if "include_live_market" in payload:
        return _truthy_flag(payload.get("include_live_market"), default=False)

    return _truthy_flag(os.getenv("WLIGHTER_GUIDE_TAVILY"), default=False)


def normalize_country_code(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    return COUNTRY_ALIASES.get(text.lower()) or COUNTRY_ALIASES.get(text) or text.upper()[:2]


def resolve_country_code(payload: dict[str, Any], result: dict[str, Any] | None = None) -> str | None:
    result = result or {}

    raw = (
        payload.get("targetCountry")
        or payload.get("target_country")
        or payload.get("targetMarket")
        or payload.get("target_market")
        or payload.get("country")
        or result.get("targetCountry")
        or result.get("country")
        or result.get("recommendedCountry")
    )

    return normalize_country_code(raw)


def clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def get_domain(url: str | None) -> str:
    if not url:
        return ""

    domain = urlparse(url).netloc.lower()

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def domain_matches(domain: str, allowed_domains: list[str]) -> bool:
    return any(
        domain == allowed
        or domain.endswith("." + allowed)
        for allowed in allowed_domains
    )


def classify_source(country: str, url: str) -> str:
    domain = get_domain(url)

    if domain_matches(domain, TRUSTED_DOMAINS.get(country, [])):
        return "trusted"

    if domain_matches(domain, REFERENCE_DOMAINS.get(country, [])):
        return "reference"

    return "other"


def build_queries(country: str, genre: str, signals: list[str] | None = None) -> dict[str, str]:
    config = QUERY_CONFIG.get(country)
    if not config:
        return {}

    safe_genre = clean_text(genre) or "web novel"
    signal_text = clean_text(" ".join(str(item) for item in (signals or []) if str(item).strip()))
    safe_signals = signal_text[:180] or safe_genre

    return {
        category: clean_text(query.format(genre=safe_genre, signals=safe_signals))
        for category, query in config.items()
    }


def _search_tavily(query: str, *, max_results: int, search_depth: str) -> list[dict[str, Any]]:
    from tavily import TavilyClient

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is missing")

    client = TavilyClient(api_key=api_key)

    response = client.search(
        query=query,
        search_depth=search_depth,
        max_results=max_results,
        include_answer=False,
        include_raw_content=False,
    )

    return response.get("results", []) or []


def collect_live_market_rows(
    *,
    country: str,
    genre: str,
    max_results: int,
    search_depth: str,
    signals: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queries = build_queries(country, genre, signals)

    for category, query in queries.items():
        try:
            results = _search_tavily(
                query,
                max_results=max_results,
                search_depth=search_depth,
            )

            for idx, item in enumerate(results, start=1):
                url = item.get("url", "")
                source_type = classify_source(country, url)

                rows.append({
                    "country": country,
                    "category": category,
                    "query": query,
                    "rank_in_search": idx,
                    "title": clean_text(item.get("title")),
                    "url": url,
                    "domain": get_domain(url),
                    "source_type": source_type,
                    "content": clean_text(item.get("content")),
                    "score": item.get("score"),
                })

        except Exception as exc:  # noqa: BLE001
            rows.append({
                "country": country,
                "category": category,
                "query": query,
                "rank_in_search": None,
                "title": "ERROR",
                "url": "",
                "domain": "",
                "source_type": "error",
                "content": f"{type(exc).__name__}: {exc}",
                "score": None,
            })

    return rows


def build_balanced_context_pack(
    rows: list[dict[str, Any]],
    *,
    max_items: int,
    max_chars_per_content: int,
) -> list[dict[str, Any]]:
    useful_rows = [
        row for row in rows
        if row.get("title") != "ERROR"
        and row.get("url")
        and row.get("source_type") in {"trusted", "reference"}
    ]

    selected: list[dict[str, Any]] = []
    selected_urls: set[str] = set()

    # 1. 카테고리별 최소 1개 확보
    for category in REQUIRED_CATEGORIES:
        candidates = [row for row in useful_rows if row.get("category") == category]

        candidates.sort(
            key=lambda row: (
                SOURCE_PRIORITY.get(row.get("source_type"), 99),
                -(row.get("score") or 0),
            )
        )

        if candidates:
            row = candidates[0]
            url = row.get("url", "")
            if url and url not in selected_urls:
                selected.append(row)
                selected_urls.add(url)

    # 2. 남은 슬롯 채우기
    remaining = [
        row for row in useful_rows
        if row.get("url") not in selected_urls
    ]

    remaining.sort(
        key=lambda row: (
            SOURCE_PRIORITY.get(row.get("source_type"), 99),
            CATEGORY_PRIORITY.get(row.get("category"), 99),
            -(row.get("score") or 0),
        )
    )

    for row in remaining:
        if len(selected) >= max_items:
            break

        url = row.get("url", "")
        if url and url not in selected_urls:
            selected.append(row)
            selected_urls.add(url)

    return [
        {
            "category": row.get("category", ""),
            "source_type": row.get("source_type", ""),
            "domain": row.get("domain", ""),
            "title": row.get("title", ""),
            "url": row.get("url", ""),
            "summary": (row.get("content", "") or "")[:max_chars_per_content],
        }
        for row in selected[:max_items]
    ]


def build_live_market_evidence(
    payload: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    report_mode: str = "country_genre_guide",
) -> dict[str, Any]:
    result = result or {}

    requested = "includeLiveMarket" in payload or "include_live_market" in payload
    enabled = live_market_enabled(payload)

    country = resolve_country_code(payload, result)
    genre = str(payload.get("genre") or result.get("genre") or "").strip()

    if not enabled:
        return {
            "liveMarketRequested": requested,
            "liveMarketEnabled": False,
            "liveMarketUsed": False,
            "liveMarketSkipReason": "disabled",
        }

    if not country or country not in QUERY_CONFIG:
        return {
            "liveMarketRequested": requested,
            "liveMarketEnabled": True,
            "liveMarketUsed": False,
            "liveMarketSkipReason": "unsupported_country",
            "liveMarketCountry": country,
        }

    if not os.getenv("TAVILY_API_KEY", "").strip():
        return {
            "liveMarketRequested": requested,
            "liveMarketEnabled": True,
            "liveMarketUsed": False,
            "liveMarketSkipReason": "missing_api_key",
            "liveMarketCountry": country,
        }

    max_results = int(os.getenv("WLIGHTER_TAVILY_MAX_RESULTS", "3"))
    max_items = int(os.getenv("WLIGHTER_TAVILY_MAX_ITEMS", "6"))
    max_chars = int(os.getenv("WLIGHTER_TAVILY_CONTENT_CHARS", "300"))
    search_depth = os.getenv("WLIGHTER_TAVILY_SEARCH_DEPTH", "basic")

    rows = collect_live_market_rows(
        country=country,
        genre=genre,
        max_results=max_results,
        search_depth=search_depth,
    )

    context_items = build_balanced_context_pack(
        rows,
        max_items=max_items,
        max_chars_per_content=max_chars,
    )

    return {
        "liveMarketRequested": requested,
        "liveMarketEnabled": True,
        "liveMarketUsed": bool(context_items),
        "liveMarketCountry": country,
        "liveMarketResultCount": len(rows),
        "liveMarketInjectedCount": len(context_items),
        "liveMarketSkipReason": None if context_items else "no_useful_results",
        "liveMarketEvidence": {
            "country": country,
            "genre": genre,
            "reportMode": report_mode,
            "items": context_items,
            "limitations": [
                "Tavily 검색 결과는 최신 웹 참고자료이며, 전체 시장 통계가 아닙니다.",
                "플랫폼 규정은 대표 플랫폼 공개 자료 기준이므로 실제 게시 전 최신 공식 가이드라인 확인이 필요합니다.",
                "trusted 출처는 우선 참고하고, reference 출처는 보조 경향으로만 사용합니다.",
            ],
        },
    }


COUNTRY_DISPLAY = {
    "JP": "일본",
    "US": "미국/글로벌 영어",
    "CN": "중국",
    "TH": "태국",
}


def _synopsis_live_market_enabled(payload: dict[str, Any]) -> bool:
    """Synopsis comparison uses Tavily by default unless the caller explicitly disables it."""
    if "includeLiveMarket" in payload:
        return _truthy_flag(payload.get("includeLiveMarket"), default=True)
    if "include_live_market" in payload:
        return _truthy_flag(payload.get("include_live_market"), default=True)
    return _truthy_flag(os.getenv("WLIGHTER_GUIDE_TAVILY"), default=True)


def _story_search_signals(story_profile: dict[str, Any], country: str) -> list[str]:
    localized = (story_profile.get("searchTermsByCountry") or {}).get(country) or []
    values: list[str] = []
    for item in localized:
        text = clean_text(str(item))
        if text and text not in values:
            values.append(text)
    if values:
        return values[:6]

    # Compatibility fallback for profiles created before localized search terms were added.
    for item in story_profile.get("coreSignals") or []:
        text = clean_text(str(item))
        if text and text not in values:
            values.append(text)
    genre = clean_text(str(story_profile.get("genre") or ""))
    for item in re.split(r"[\n,/;|·]+", genre):
        item = clean_text(item)
        if item and item not in values:
            values.append(item)
    return values[:6]


def _evidence_level(items: list[dict[str, Any]]) -> str:
    trusted = sum(1 for item in items if item.get("source_type") == "trusted")
    categories = {str(item.get("category") or "") for item in items if item.get("category")}
    if trusted >= 2 and len(categories) >= 2 and len(items) >= 3:
        return "충분"
    if trusted >= 1 and len(categories) >= 2 and len(items) >= 2:
        return "보통"
    if items:
        return "제한적"
    return "없음"


def _country_live_summary(country: str, rows: list[dict[str, Any]], items: list[dict[str, Any]]) -> dict[str, Any]:
    trusted_count = sum(1 for item in items if item.get("source_type") == "trusted")
    reference_count = sum(1 for item in items if item.get("source_type") == "reference")
    categories = sorted({str(item.get("category") or "") for item in items if item.get("category")})
    return {
        "country": country,
        "displayCountry": COUNTRY_DISPLAY.get(country, country),
        "evidenceLevel": _evidence_level(items),
        "rawResultCount": len(rows),
        "injectedCount": len(items),
        "trustedCount": trusted_count,
        "referenceCount": reference_count,
        "categoriesCovered": categories,
        "items": items,
    }


def build_multi_country_live_market_evidence(
    payload: dict[str, Any],
    story_profile: dict[str, Any],
    *,
    report_mode: str = "synopsis_country_recommendation",
) -> dict[str, Any]:
    """Collect balanced Tavily evidence for all four target markets before LLM comparison."""
    requested = "includeLiveMarket" in payload or "include_live_market" in payload
    enabled = _synopsis_live_market_enabled(payload)
    countries = ("JP", "US", "CN", "TH")

    if not enabled:
        return {
            "liveMarketRequested": requested,
            "liveMarketEnabled": False,
            "liveMarketUsed": False,
            "liveMarketSkipReason": "disabled",
            "recommendationAllowed": False,
            "countries": {},
        }

    if not os.getenv("TAVILY_API_KEY", "").strip():
        return {
            "liveMarketRequested": requested,
            "liveMarketEnabled": True,
            "liveMarketUsed": False,
            "liveMarketSkipReason": "missing_api_key",
            "recommendationAllowed": False,
            "countries": {},
        }

    max_results = int(os.getenv("WLIGHTER_TAVILY_MAX_RESULTS", "3"))
    max_items = int(os.getenv("WLIGHTER_TAVILY_COUNTRY_ITEMS", os.getenv("WLIGHTER_TAVILY_MAX_ITEMS", "5")))
    max_chars = int(os.getenv("WLIGHTER_TAVILY_CONTENT_CHARS", "420"))
    min_score = float(os.getenv("WLIGHTER_TAVILY_MIN_SCORE", "0.20"))
    search_depth = os.getenv("WLIGHTER_TAVILY_SEARCH_DEPTH", "basic")
    rows_by_country: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                collect_live_market_rows,
                country=country,
                genre="",
                max_results=max_results,
                search_depth=search_depth,
                signals=[],
            ): country
            for country in countries
        }
        for future in as_completed(futures):
            country = futures[future]
            try:
                rows_by_country[country] = future.result()
            except Exception as exc:  # noqa: BLE001
                rows_by_country[country] = [{
                    "country": country,
                    "category": "collection_error",
                    "query": "",
                    "rank_in_search": None,
                    "title": "ERROR",
                    "url": "",
                    "domain": "",
                    "source_type": "error",
                    "content": f"{type(exc).__name__}: {exc}",
                    "score": None,
                }]

    country_payloads: dict[str, dict[str, Any]] = {}
    total_rows = 0
    total_items = 0
    for country in countries:
        rows = rows_by_country.get(country, [])
        total_rows += len(rows)
        filtered_rows = [
            row for row in rows
            if row.get("title") != "ERROR"
            and (
                row.get("source_type") == "trusted"
                or float(row.get("score") or 0) >= min_score
            )
        ]
        items = build_balanced_context_pack(
            filtered_rows,
            max_items=max_items,
            max_chars_per_content=max_chars,
        )
        total_items += len(items)
        country_payloads[country] = _country_live_summary(country, rows, items)

    levels = [country_payloads[country]["evidenceLevel"] for country in countries]
    all_markets_observed = all(level != "없음" for level in levels)
    comparable_markets = sum(level in {"충분", "보통"} for level in levels)
    recommendation_allowed = all_markets_observed and comparable_markets >= 2

    return {
        "liveMarketRequested": requested,
        "liveMarketEnabled": True,
        "liveMarketUsed": total_items > 0,
        "liveMarketSkipReason": None if total_items else "no_useful_results",
        "liveMarketResultCount": total_rows,
        "liveMarketInjectedCount": total_items,
        "recommendationAllowed": recommendation_allowed,
        "reportMode": report_mode,
        "genre": "",
        "signalsByCountry": {},
        "countries": country_payloads,
        "limitations": [
            "Tavily 결과는 검색 시점의 공개 웹 자료이며 전체 시장 통계가 아닙니다.",
            "공식 플랫폼·정책 출처를 우선하고 참고 출처는 보조 근거로만 사용합니다.",
            "검색 결과의 존재는 흥행 가능성을 의미하지 않으며 작품과의 연결은 LLM의 근거 기반 추론입니다.",
        ],
    }

__all__ = [
    "build_balanced_context_pack",
    "build_live_market_evidence",
    "build_multi_country_live_market_evidence",
    "build_queries",
    "classify_source",
    "collect_live_market_rows",
    "normalize_country_code",
    "resolve_country_code",
]
