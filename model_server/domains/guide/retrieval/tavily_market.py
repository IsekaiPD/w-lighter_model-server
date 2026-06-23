"""Optional live web evidence for guide reports via Tavily.

This module is deliberately fail-soft. Guide generation must still work when
Tavily is not configured, rate-limited, or temporarily unavailable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


COUNTRY_QUERY_LABELS = {
    "JP": ("Japan", "일본"),
    "CN": ("China", "중국"),
    "US": ("global English webnovel", "미국/글로벌 영어"),
    "TH": ("Thailand", "태국"),
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


def _enabled(payload: dict[str, Any]) -> bool:
    if "includeLiveMarket" in payload:
        return _truthy_flag(payload.get("includeLiveMarket"), default=True)
    if "include_live_market" in payload:
        return _truthy_flag(payload.get("include_live_market"), default=True)
    return _truthy_flag(os.getenv("WLIGHTER_GUIDE_TAVILY"), default=False)


def _target_country(payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    raw = (
        payload.get("targetCountry")
        or payload.get("target_country")
        or payload.get("country")
        or result.get("targetCountry")
        or result.get("country")
        or result.get("recommendedCountry")
    )
    if not raw:
        return None
    text = str(raw).strip()
    lower = text.lower()
    if lower in {"jp", "japan", "일본"}:
        return "JP"
    if lower in {"cn", "china", "중국"}:
        return "CN"
    if lower in {"us", "usa", "english", "global english", "us/global english", "미국", "미국/글로벌 영어"}:
        return "US"
    if lower in {"th", "thailand", "태국"}:
        return "TH"
    return text.upper()


def _story_terms(payload: dict[str, Any], result: dict[str, Any]) -> str:
    parts = [
        payload.get("title") or payload.get("workTitle") or result.get("title"),
        payload.get("genre") or result.get("genre"),
    ]
    synopsis = str(payload.get("synopsis") or payload.get("desc") or "").strip()
    if synopsis:
        parts.append(synopsis[:180])
    return " ".join(str(part).strip() for part in parts if part)


def _queries(payload: dict[str, Any], result: dict[str, Any], *, report_mode: str) -> list[dict[str, str]]:
    terms = _story_terms(payload, result) or "web novel"
    if report_mode == "synopsis_deep_guide" and not _target_country(payload, result):
        return [
            {
                "country": code,
                "query": f"{terms} {label_en} webnovel market trend localization",
            }
            for code, (label_en, _label_ko) in COUNTRY_QUERY_LABELS.items()
        ]

    code = _target_country(payload, result) or "JP"
    label_en, _label_ko = COUNTRY_QUERY_LABELS.get(code, (code, code))
    return [
        {
            "country": code,
            "query": f"{terms} {label_en} webnovel platform trend localization policy",
        }
    ]


def _search(query: str, *, api_key: str, max_results: int) -> dict[str, Any]:
    body = {
        "query": query,
        "search_depth": os.getenv("WLIGHTER_TAVILY_SEARCH_DEPTH", "basic"),
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=float(os.getenv("WLIGHTER_TAVILY_TIMEOUT", "8"))) as response:
        return json.loads(response.read().decode("utf-8"))


def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "content": str(item.get("content") or "")[:700],
        "score": item.get("score"),
    }


def build_live_market_evidence(
    payload: dict[str, Any],
    result: dict[str, Any],
    *,
    report_mode: str,
) -> dict[str, Any] | None:
    """Build optional Tavily-backed market evidence for the LLM prompt."""

    if not _enabled(payload):
        return None
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {
            "enabled": False,
            "provider": "tavily",
            "skipReason": "missing_api_key",
        }

    max_results = int(os.getenv("WLIGHTER_TAVILY_MAX_RESULTS", "3"))
    evidence: dict[str, Any] = {
        "enabled": True,
        "provider": "tavily",
        "reportMode": report_mode,
        "queries": [],
        "countryEvidence": {},
        "limits": [
            "실시간 웹 검색 결과는 참고 근거이며 플랫폼 내부 매출/독점 데이터가 아닙니다.",
            "출처 내용은 요약해 사용하고 원문을 그대로 사용자 응답에 복사하지 않습니다.",
        ],
    }
    try:
        for query_spec in _queries(payload, result, report_mode=report_mode):
            country = query_spec["country"]
            query = query_spec["query"]
            evidence["queries"].append({"country": country, "query": query})
            response = _search(query, api_key=api_key, max_results=max_results)
            evidence["countryEvidence"][country] = [
                _compact_result(item) for item in response.get("results") or []
            ]
        return evidence
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "enabled": False,
            "provider": "tavily",
            "skipReason": "request_failed",
            "errorType": type(exc).__name__,
        }


__all__ = ["build_live_market_evidence"]
