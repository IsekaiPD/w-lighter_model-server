from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from model_server.domains.guide.agents.country_recommender import generate_country_recommendation
from model_server.domains.guide.agents.guide_writer import _client_and_model
from model_server.domains.guide.guide_pipeline import generate_guide
from model_server.domains.guide.infra.output_language_guard import (
    repair_user_facing_explanations,
    sanitize_deterministic_explanations,
    validate_user_facing_language,
)


class GuideCountryRecommenderTests(unittest.TestCase):
    def test_synopsis_without_country_routes_to_recommendation(self) -> None:
        payload = {"synopsis": "A heroine enters a magical academy.", "genre": "fantasy"}
        with patch(
            "model_server.domains.guide.guide_pipeline.build_localization_advice",
            return_value={"requiresSelection": True, "title": "base", "genre": "fantasy"},
        ), patch(
            "model_server.domains.guide.guide_pipeline.generate_country_recommendation",
            return_value={"mode": "synopsis_country_recommendation", "recommendedCountry": "JP"},
        ) as mocked_recommendation:
            result = generate_guide(payload)

        self.assertEqual(result["recommendedCountry"], "JP")
        mocked_recommendation.assert_called_once()

    def test_country_present_skips_recommendation_and_generates_guide(self) -> None:
        payload = {"synopsis": "A heroine enters a magical academy.", "genre": "fantasy", "targetCountry": "JP"}
        with patch(
            "model_server.domains.guide.guide_pipeline.build_localization_advice",
            return_value={
                "title": "작품",
                "genre": "fantasy",
                "targetCountry": "JP",
                "country": "JP",
                "displayCountry": "일본",
            },
        ), patch(
            "model_server.domains.guide.guide_pipeline.build_policy_attention_payload",
            return_value={"policyAttentionCards": [], "policyLimitations": []},
        ), patch(
            "model_server.domains.guide.guide_pipeline.llm_requested",
            return_value=True,
        ), patch(
            "model_server.domains.guide.guide_pipeline.generate_llm_guide",
            return_value={"llmGeneratedGuide": True, "generationMode": "llm_with_rag"},
        ) as mocked_llm, patch(
            "model_server.domains.guide.guide_pipeline.generate_country_recommendation"
        ) as mocked_recommendation:
            result = generate_guide(payload)

        self.assertTrue(result["llmGeneratedGuide"])
        mocked_llm.assert_called_once()
        mocked_recommendation.assert_not_called()

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
        self.assertIn("직접 선택", result["message"])
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
