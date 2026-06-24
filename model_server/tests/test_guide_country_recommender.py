from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from model_server.domains.guide.agents.country_recommender import _canonicalize_result, generate_country_recommendation
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
            "model_server.domains.guide.guide_pipeline.generate_llm_guide",
            return_value={
                "htmlReport": "<!doctype html><html><body><main>final live guide for work fantasy</main></body></html>",
                "llmGeneratedGuide": True,
                "generationMode": "llm_guide",
            },
        ):
            result = generate_guide(payload)

        self.assertNotEqual(result["htmlReport"], "<!doctype html><html><body>guide</body></html>")
        self.assertIn("<!doctype html>", result["htmlReport"].lower())
        self.assertIn("<main>", result["htmlReport"])
        self.assertIn("work", result["htmlReport"])
        self.assertIn("fantasy", result["htmlReport"])
        self.assertNotIn("liveMarketEvidence", result)
        self.assertNotIn("liveMarketResultCount", result)
        self.assertNotIn("liveMarketSkipReason", result)
        self.assertNotIn("liveMarketEvidence", result["htmlReport"])
        self.assertNotIn("includeInternal", result["htmlReport"])

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

    def test_flat_country_scores_are_repaired_to_ranked_priority_scores(self) -> None:
        def build_raw(score: int) -> dict:
            return {
            "recommendedCountry": "US",
            "confidence": "medium",
            "storyProfile": {
                "title": "work",
                "genre": "romance",
                "coreSignals": ["romance"],
                "analysisSummary": "summary",
            },
            "limitations": ["limit"],
                "countryComparisons": [
                    {
                        "country": "US",
                        "rank": 1,
                        "relativeFitScore": score,
                        "fitLevel": "high",
                        "strengths": ["strength"],
                        "risks": ["risk"],
                        "evidenceSummary": ["evidence"],
                    },
                    {
                        "country": "JP",
                        "rank": 2,
                        "relativeFitScore": score,
                        "fitLevel": "mid",
                        "strengths": ["strength"],
                        "risks": ["risk"],
                        "evidenceSummary": ["evidence"],
                    },
                    {
                        "country": "TH",
                        "rank": 3,
                        "relativeFitScore": score,
                        "fitLevel": "mid",
                        "strengths": ["strength"],
                        "risks": ["risk"],
                        "evidenceSummary": ["evidence"],
                    },
                    {
                        "country": "CN",
                        "rank": 4,
                        "relativeFitScore": score,
                        "fitLevel": "low",
                        "strengths": ["strength"],
                        "risks": ["risk"],
                        "evidenceSummary": ["evidence"],
                    },
                ],
            }

        for score in (0, 10):
            with self.subTest(score=score):
                result = _canonicalize_result(build_raw(score), evidence_size=0)

                self.assertEqual(
                    [item["relativeFitScore"] for item in result["countryComparisons"]],
                    [86, 74, 62, 50],
                )

    def test_ungrounded_llm_market_claims_are_replaced_with_evidence_limits(self) -> None:
        raw = {
            "recommendedCountry": "US",
            "confidence": "medium",
            "storyProfile": {
                "title": "work",
                "genre": "romance",
                "coreSignals": ["romance"],
                "analysisSummary": "English readers prefer this trope.",
            },
            "limitations": ["limit"],
            "countryComparisons": [
                {
                    "country": "US",
                    "rank": 1,
                    "relativeFitScore": 86,
                    "fitLevel": "high",
                    "strengths": ["영어권 독자에게 익숙한 조합이라 유리합니다."],
                    "risks": ["risk"],
                    "evidenceSummary": ["English romance market fit"],
                },
                {
                    "country": "JP",
                    "rank": 2,
                    "relativeFitScore": 74,
                    "fitLevel": "mid",
                    "strengths": ["일본 독자에게 익숙합니다."],
                    "risks": ["risk"],
                    "evidenceSummary": ["Japanese market fit"],
                },
                {
                    "country": "TH",
                    "rank": 3,
                    "relativeFitScore": 62,
                    "fitLevel": "mid",
                    "strengths": ["태국 시장에 맞습니다."],
                    "risks": ["risk"],
                    "evidenceSummary": ["Thai market fit"],
                },
                {
                    "country": "CN",
                    "rank": 4,
                    "relativeFitScore": 50,
                    "fitLevel": "low",
                    "strengths": ["중국 시장에 맞습니다."],
                    "risks": ["risk"],
                    "evidenceSummary": ["China market fit"],
                },
            ],
        }
        evidence = {
            "countries": [
                {
                    "country": "US",
                    "matchedSignals": [],
                    "matchedContextEvidence": [],
                    "platformEvidence": [{"status": "missing"}],
                    "policyRiskSummary": {"riskCount": 0},
                },
                {
                    "country": "JP",
                    "matchedSignals": [],
                    "matchedContextEvidence": [],
                    "platformEvidence": [{"status": "missing"}],
                    "policyRiskSummary": {"riskCount": 0},
                },
                {
                    "country": "TH",
                    "matchedSignals": [],
                    "matchedContextEvidence": [],
                    "platformEvidence": [{"status": "missing"}],
                    "policyRiskSummary": {"riskCount": 0},
                },
                {
                    "country": "CN",
                    "matchedSignals": [],
                    "matchedContextEvidence": [],
                    "platformEvidence": [{"status": "missing"}],
                    "policyRiskSummary": {"riskCount": 0},
                },
            ],
            "contextPackDiagnosticsByCountry": [
                {"country": "US", "contextPackSourceRecordCount": 450, "contextPackInjectedRecordCount": 0},
                {"country": "JP", "contextPackSourceRecordCount": 340, "contextPackInjectedRecordCount": 0},
                {"country": "TH", "contextPackSourceRecordCount": 220, "contextPackInjectedRecordCount": 0},
                {"country": "CN", "contextPackSourceRecordCount": 136, "contextPackInjectedRecordCount": 0},
            ],
        }

        result = _canonicalize_result(raw, evidence_size=0, evidence=evidence)

        self.assertEqual(result["confidence"], "낮음")
        self.assertIn("직접 매칭된 컨텍스트 근거는 아직 확인되지 않았습니다", result["countryComparisons"][0]["strengths"][0])
        self.assertIn("국가별 독자 선호, 플랫폼 실적", result["limitations"][0])
        self.assertNotIn("영어권 독자에게 익숙", " ".join(result["countryComparisons"][0]["strengths"]))
        self.assertIn("해석 수준: 근거 부족 예비 비교", result["countryComparisons"][0]["evidenceSummary"])


if __name__ == "__main__":
    unittest.main()
