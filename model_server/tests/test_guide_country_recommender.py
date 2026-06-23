from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from model_server.domains.guide.agents.country_recommender import generate_country_recommendation
from model_server.domains.guide.agents.guide_writer import _client_and_model
from model_server.domains.guide.engine.recommendation import generate_localization_guide, recommend_country
from model_server.domains.guide.guide_pipeline import generate_guide
from model_server.domains.guide.infra.output_language_guard import (
    repair_user_facing_explanations,
    sanitize_deterministic_explanations,
    validate_user_facing_language,
)


class GuideCountryRecommenderTests(unittest.TestCase):
    def test_synopsis_without_country_returns_recommendation_and_requires_selection(self) -> None:
        payload = {"synopsis": "A heroine enters a magical academy.", "genre": "fantasy"}
        with patch(
            "model_server.domains.guide.guide_pipeline.generate_country_recommendation",
            return_value={
                "mode": "synopsis_country_recommendation",
                "requiresSelection": False,
                "recommendedCountry": "JP",
                "recommendedCountryDisplay": "일본",
            },
        ) as mocked_recommendation:
            result = generate_guide(payload)

        self.assertFalse(result["requiresSelection"])
        self.assertEqual(result["reportMode"], "synopsis_country_recommendation")
        self.assertEqual(result["recommendedCountry"], "JP")
        mocked_recommendation.assert_called_once()

    def test_country_present_with_synopsis_still_returns_recommendation(self) -> None:
        payload = {"synopsis": "A heroine enters a magical academy.", "genre": "fantasy", "targetCountry": "JP"}
        with patch(
            "model_server.domains.guide.guide_pipeline.generate_country_recommendation",
            return_value={
                "mode": "synopsis_country_recommendation",
                "requiresSelection": False,
                "recommendedCountry": "JP",
                "recommendedCountryDisplay": "일본",
                "countryComparisons": [],
            },
        ) as mocked_recommendation:
            result = generate_guide(payload)

        self.assertFalse(result["requiresSelection"])
        self.assertEqual(result["reportMode"], "synopsis_country_recommendation")
        mocked_recommendation.assert_called_once_with(payload)

    def test_legacy_recommendation_ignores_selected_country_when_synopsis_exists(self) -> None:
        result = recommend_country(
            {
                "synopsis": "A heroine enters a magical academy.",
                "genre": "fantasy",
                "targetCountry": "JP",
            }
        )

        self.assertFalse(result["requiresSelection"])
        self.assertEqual(result["mode"], "synopsis_country_recommendation")
        self.assertNotIn("targetCountry", result)

        direct_guide = generate_localization_guide(
            {
                "synopsis": "A heroine enters a magical academy.",
                "genre": "fantasy",
                "targetCountry": "JP",
            }
        )
        self.assertFalse(direct_guide["requiresSelection"])
        self.assertEqual(direct_guide["mode"], "synopsis_country_recommendation")

    def test_live_market_diagnostics_stay_out_of_public_response(self) -> None:
        payload = {"genre": "fantasy", "targetCountry": "JP", "includeLiveMarket": True}
        with patch(
            "model_server.domains.guide.guide_pipeline.build_localization_advice",
            return_value={
                "requiresSelection": False,
                "title": "work",
                "genre": "fantasy",
                "targetCountry": "JP",
                "country": "JP",
                "displayCountry": "Japan",
                "htmlReport": "<!doctype html><html><body>guide</body></html>",
            },
        ), patch(
            "model_server.domains.guide.guide_pipeline._attach_context_pack_briefing",
            side_effect=lambda _payload, result: dict(result),
        ), patch(
            "model_server.domains.guide.guide_pipeline.build_live_market_evidence",
            return_value={
                "liveMarketRequested": True,
                "liveMarketEnabled": True,
                "liveMarketUsed": True,
                "liveMarketCountry": "JP",
                "liveMarketResultCount": 4,
                "liveMarketInjectedCount": 2,
                "liveMarketSkipReason": None,
                "liveMarketEvidence": {
                    "country": "JP",
                    "items": [
                        {
                            "category": "platform_reference",
                            "source_type": "trusted",
                            "domain": "kakuyomu.jp",
                            "title": "Rules",
                            "url": "https://kakuyomu.jp/help",
                            "summary": "rules",
                        }
                    ],
                },
            },
        ), patch(
            "model_server.domains.guide.guide_pipeline.build_policy_attention_payload",
            return_value={"policyAttentionCards": [], "policyLimitations": []},
        ), patch(
            "model_server.domains.guide.guide_pipeline.llm_requested",
            return_value=False,
        ):
            result = generate_guide(payload)

        self.assertEqual(result["htmlReport"], "<!doctype html><html><body>guide</body></html>")
        self.assertNotIn("liveMarketEvidence", result)
        self.assertNotIn("liveMarketResultCount", result)
        self.assertNotIn("liveMarketSkipReason", result)

    def test_llm_failure_falls_back_to_manual_selection_without_random_choice(self) -> None:
        evidence = {
            "story": {"title": "작품", "genre": "fantasy", "synopsis": "story"},
            "countries": [
                {"country": "JP", "targetCountry": "Japan", "displayCountry": "일본", "matchedSignals": ["school"], "platformEvidence": [1], "policyRiskSummary": {"riskCount": 1}},
                {"country": "CN", "targetCountry": "China", "displayCountry": "중국", "matchedSignals": ["action"], "platformEvidence": [1], "policyRiskSummary": {"riskCount": 2}},
                {"country": "US", "targetCountry": "US/global English", "displayCountry": "미국/글로벌 영어", "matchedSignals": [], "platformEvidence": [], "policyRiskSummary": {"riskCount": 0}},
                {"country": "TH", "targetCountry": "Thailand", "displayCountry": "태국", "matchedSignals": [], "platformEvidence": [], "policyRiskSummary": {"riskCount": 0}},
            ],
            "contextPackDiagnosticsByCountry": [],
        }
        with patch(
            "model_server.domains.guide.agents.country_recommender.build_country_recommendation_evidence",
            return_value=evidence,
        ), patch(
            "model_server.domains.guide.agents.country_recommender.llm_requested",
            return_value=True,
        ), patch(
            "model_server.domains.guide.agents.country_recommender._client_and_model",
            side_effect=RuntimeError("boom"),
        ):
            result = generate_country_recommendation({"synopsis": "story", "genre": "fantasy"})

        self.assertIsNone(result["recommendedCountry"])
        self.assertEqual(result["countryComparisons"], [])
        self.assertIn("추천 생성에 실패", result["message"])
        self.assertEqual(result["recommendationMethod"], "llm_country_comparison_failed")

    def test_user_facing_language_guard_repairs_to_korean(self) -> None:
        payload = {
            "title": "Country recommendation",
            "message": "Pick one",
            "limitations": ["English only"],
            "recommendedCountry": "JP",
        }
        self.assertFalse(validate_user_facing_language(payload)["ok"])
        repaired = repair_user_facing_explanations(payload)
        self.assertTrue(validate_user_facing_language(repaired)["ok"])
        self.assertIn("한국어", repaired["message"])
        sanitized = sanitize_deterministic_explanations(payload)
        self.assertTrue(validate_user_facing_language(sanitized)["ok"])

    def test_default_guide_model_falls_back_to_gpt_5_4_mini(self) -> None:
        fake_openai = types.ModuleType("openai")

        class FakeOpenAI:
            def __init__(self, api_key: str):
                self.api_key = api_key

        fake_openai.OpenAI = FakeOpenAI
        with patch.dict(sys.modules, {"openai": fake_openai}), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key"},
            clear=False,
        ):
            os.environ.pop("WLIGHTER_GUIDE_MODEL", None)
            os.environ.pop("OPENAI_GUIDE_MODEL", None)
            client, model = _client_and_model({})

        self.assertEqual(model, "gpt-5.4-mini")
        self.assertEqual(client.api_key, "test-key")


if __name__ == "__main__":
    unittest.main()
