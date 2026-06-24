from __future__ import annotations

import os
import re
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
    ],
    "CN": [
        "write.qq.com",
        "chinawriter.com.cn",
        "cssn.cn",
    ],
    "TH": [
        "readawrite.com",
        "dek-d.com",
        "novel.dek-d.com",
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
        "platform_reference": "小説家になろう カクヨム ガイドライン AI利用 禁止事項 投稿ルール",
        "genre_trend": "日本 Web小説 ライトノベル 人気ジャンル 傾向 {genre}",
        "title_synopsis_style": "小説家になろう カクヨム Web小説 タイトル あらすじ 傾向",
        "reader_hook": "日本 Web小説 読者 人気 タグ ざまぁ 悪役令嬢 異世界転生",
    },
    "US": {
        "platform_reference": "Royal Road content guidelines fiction tags profanity sexual content AI",
        "genre_trend": "Royal Road popular genres {genre} progression fantasy LitRPG web fiction trends",
        "title_synopsis_style": "Royal Road fiction synopsis title tags progression fantasy LitRPG",
        "reader_hook": "English web fiction reader expectations progression fantasy LitRPG weak to strong",
    },
    "CN": {
        "platform_reference": "起点中文网 作家专区 投稿 规则 内容规范 AI 生成内容",
        "genre_trend": "中国 网络文学 热门题材 趋势 {genre} 玄幻 修仙 重生 系统 爽文",
        "title_synopsis_style": "网络小说 标题 简介 写法 起点 中文网",
        "reader_hook": "中国 网络文学 读者 喜欢 爽点 金手指 升级流 系统流",
    },
    "TH": {
        "platform_reference": "ReadAWrite Dek-D กฎการลงนิยาย เนื้อหาต้องห้าม AI",
        "genre_trend": "นิยายออนไลน์ ไทย แนวโน้ม {genre} แฟนตาซี โรแมนซ์ เกิดใหม่ ระบบ",
        "title_synopsis_style": "นิยายออนไลน์ ไทย ชื่อเรื่อง คำโปรย เรื่องย่อ นิยาย",
        "reader_hook": "นักอ่านนิยายออนไลน์ไทย ชอบ แนว โรแมนซ์ แฟนตาซี จีนโบราณ เกิดใหม่",
    },
}


REQUIRED_CATEGORIES = [
    "platform_reference",
    "genre_trend",
    "title_synopsis_style",
    "reader_hook",
]


SOURCE_PRIORITY = {
    "trusted": 1,
    "reference": 2,
    "other": 99,
}


CATEGORY_PRIORITY = {
    "platform_reference": 1,
    "title_synopsis_style": 2,
    "reader_hook": 3,
    "genre_trend": 4,
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
    if "includeLiveMarket" in payload:
        return _truthy_flag(payload.get("includeLiveMarket"), default=True)

    if "include_live_market" in payload:
        return _truthy_flag(payload.get("include_live_market"), default=True)

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


def build_queries(country: str, genre: str) -> dict[str, str]:
    config = QUERY_CONFIG.get(country)
    if not config:
        return {}

    safe_genre = clean_text(genre) or "web novel"

    return {
        category: query.format(genre=safe_genre)
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
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queries = build_queries(country, genre)

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
            "score": row.get("score"),
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

__all__ = [
    "build_balanced_context_pack",
    "build_live_market_evidence",
    "build_queries",
    "classify_source",
    "collect_live_market_rows",
    "normalize_country_code",
    "resolve_country_code",
]
