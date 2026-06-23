from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from model_server.domains.guide.retrieval.tavily_market import (
    build_balanced_context_pack,
    build_live_market_evidence,
    classify_source,
)


class GuideTavilyMarketTests(unittest.TestCase):
    def test_live_market_evidence_is_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            evidence = build_live_market_evidence({}, {}, report_mode="country_genre_guide")

        self.assertFalse(evidence["liveMarketEnabled"])
        self.assertFalse(evidence["liveMarketUsed"])
        self.assertEqual(evidence["liveMarketSkipReason"], "disabled")
        self.assertNotIn("liveMarketEvidence", evidence)

    def test_enabled_without_key_returns_non_blocking_skip_reason(self) -> None:
        with patch.dict(os.environ, {"WLIGHTER_GUIDE_TAVILY": "true"}, clear=True):
            evidence = build_live_market_evidence({}, {"targetCountry": "JP"}, report_mode="country_genre_guide")

        self.assertTrue(evidence["liveMarketEnabled"])
        self.assertFalse(evidence["liveMarketUsed"])
        self.assertEqual(evidence["liveMarketSkipReason"], "missing_api_key")
        self.assertEqual(evidence["liveMarketCountry"], "JP")

    def test_balanced_context_pack_prefers_trusted_reference_and_deduplicates(self) -> None:
        rows = [
            {
                "category": "platform_reference",
                "source_type": "trusted",
                "domain": "kakuyomu.jp",
                "title": "Rules",
                "url": "https://kakuyomu.jp/help",
                "content": "a" * 500,
                "score": 0.6,
            },
            {
                "category": "platform_reference",
                "source_type": "trusted",
                "domain": "kakuyomu.jp",
                "title": "Rules duplicate",
                "url": "https://kakuyomu.jp/help",
                "content": "duplicate",
                "score": 0.9,
            },
            {
                "category": "genre_trend",
                "source_type": "reference",
                "domain": "note.com",
                "title": "Trend",
                "url": "https://note.com/trend",
                "content": "trend",
                "score": 0.7,
            },
            {
                "category": "reader_hook",
                "source_type": "other",
                "domain": "example.com",
                "title": "Other",
                "url": "https://example.com/other",
                "content": "other",
                "score": 1.0,
            },
        ]

        items = build_balanced_context_pack(rows, max_items=4, max_chars_per_content=30)

        self.assertEqual([item["url"] for item in items], ["https://kakuyomu.jp/help", "https://note.com/trend"])
        self.assertLessEqual(len(items[0]["summary"]), 30)
        self.assertEqual(items[0]["source_type"], "trusted")
        self.assertEqual(items[1]["source_type"], "reference")

    def test_search_results_are_classified_and_injected_as_items(self) -> None:
        calls = {"count": 0}

        def fake_search(query: str, *, max_results: int, search_depth: str):
            calls["count"] += 1
            if calls["count"] == 1:
                return [
                    {
                        "title": "Kakuyomu guide",
                        "url": "https://kakuyomu.jp/help/rules",
                        "content": "official rule" * 50,
                        "score": 0.9,
                    }
                ]
            if calls["count"] == 2:
                return [
                    {
                        "title": "Note trend",
                        "url": "https://note.com/webnovel-trend",
                        "content": "trend note",
                        "score": 0.7,
                    }
                ]
            return [
                {
                    "title": "Untrusted",
                    "url": "https://example.com/post",
                    "content": "ignored",
                    "score": 1.0,
                }
            ]

        with patch.dict(
            os.environ,
            {"WLIGHTER_GUIDE_TAVILY": "true", "TAVILY_API_KEY": "test-key", "WLIGHTER_TAVILY_CONTENT_CHARS": "40"},
            clear=True,
        ), patch(
            "model_server.domains.guide.retrieval.tavily_market._search_tavily",
            side_effect=fake_search,
        ) as mocked_search:
            evidence = build_live_market_evidence(
                {"genre": "fantasy", "targetCountry": "JP"},
                {"targetCountry": "JP"},
                report_mode="country_genre_guide",
            )

        self.assertTrue(evidence["liveMarketUsed"])
        self.assertEqual(evidence["liveMarketCountry"], "JP")
        self.assertEqual(evidence["liveMarketResultCount"], 4)
        self.assertEqual(evidence["liveMarketInjectedCount"], 2)
        items = evidence["liveMarketEvidence"]["items"]
        self.assertEqual(items[0]["source_type"], "trusted")
        self.assertEqual(items[1]["source_type"], "reference")
        self.assertLessEqual(len(items[0]["summary"]), 40)
        self.assertEqual(mocked_search.call_count, 4)

    def test_source_classification_uses_country_domain_lists(self) -> None:
        self.assertEqual(classify_source("JP", "https://kakuyomu.jp/help"), "trusted")
        self.assertEqual(classify_source("JP", "https://note.com/example"), "reference")
        self.assertEqual(classify_source("JP", "https://example.com/example"), "other")


if __name__ == "__main__":
    unittest.main()
