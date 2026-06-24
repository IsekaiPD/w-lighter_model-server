"""Public response-shape tests for guide generation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from model_server.domains.guide.guide_pipeline import generate_guide


HTML_REPORT = "<!doctype html><html><body><main>guide</main></body></html>"
FINAL_HTML_REPORT = "<!doctype html><html lang=\"ko\"><body><main>Sample Work final guide</main></body></html>"


def _guide_base_result() -> dict:
    return {
        "mode": "guide",
        "requiresSelection": False,
        "title": "Sample Work",
        "targetCountry": "JP",
        "displayCountry": "Japan",
        "htmlReport": HTML_REPORT,
        "guide_html": HTML_REPORT,
        "sections": [{"title": "internal section"}],
        "qualitySummary": {"score": 91},
        "actionChecklist": ["localize title"],
        "modelPromptPayload": {"prompt": "internal"},
        "evidenceUsed": [{"source": "internal"}],
        "contextPackBriefing": {"summary": "internal"},
        "contextPackEvidence": {"rows": [1]},
        "recommendedCountries": [{"country": "JP"}],
        "translationProfile": {"tone": "internal"},
    }


def _attach_internal_fields(_payload: dict, result: dict) -> dict:
    enriched = dict(result)
    enriched.update(
        {
            "contextPackBriefing": {"summary": "internal"},
            "contextPackEvidence": {"rows": [1]},
            "contextPackInjectedEvidenceBytes": 123,
        }
    )
    return enriched


class GuideResponseShapeTests(unittest.TestCase):
    def test_public_guide_response_is_html_centered(self) -> None:
        with (
            patch(
                "model_server.domains.guide.guide_pipeline.build_localization_advice",
                return_value=_guide_base_result(),
            ),
            patch(
                "model_server.domains.guide.guide_pipeline._attach_context_pack_briefing",
                side_effect=_attach_internal_fields,
            ),
            patch(
                "model_server.domains.guide.guide_pipeline.build_policy_attention_payload",
                return_value={
                    "policyAttentionCards": [{"title": "internal"}],
                    "policyLimitations": ["internal"],
                },
            ),
            patch(
                "model_server.domains.guide.guide_pipeline.generate_llm_guide",
                return_value={
                    "htmlReport": FINAL_HTML_REPORT,
                    "llmGeneratedGuide": True,
                    "generationMode": "llm_guide",
                },
            ),
        ):
            result = generate_guide({"targetCountry": "JP"})

        self.assertEqual(result["htmlReport"], FINAL_HTML_REPORT)
        self.assertNotEqual(result["htmlReport"], HTML_REPORT)
        self.assertIn("<!doctype html>", result["htmlReport"].lower())
        self.assertIn("<main>", result["htmlReport"])
        self.assertIn("Sample Work", result["htmlReport"])
        self.assertEqual(result["mode"], "guide")
        self.assertEqual(result["generationMode"], "llm_guide")
        self.assertFalse(result["requiresSelection"])
        self.assertNotIn("internal", result)
        self.assertNotIn("internal", result["htmlReport"])

        for key in (
            "guide_html",
            "sections",
            "qualitySummary",
            "actionChecklist",
            "modelPromptPayload",
            "evidenceUsed",
            "contextPackBriefing",
            "contextPackEvidence",
            "contextPackInjectedEvidenceBytes",
            "policyAttentionCards",
            "policyLimitations",
            "recommendedCountries",
            "translationProfile",
        ):
            self.assertNotIn(key, result)

    def test_include_internal_request_field_is_ignored_by_public_api(self) -> None:
        with (
            patch(
                "model_server.domains.guide.guide_pipeline.build_localization_advice",
                return_value=_guide_base_result(),
            ),
            patch(
                "model_server.domains.guide.guide_pipeline._attach_context_pack_briefing",
                side_effect=_attach_internal_fields,
            ),
            patch(
                "model_server.domains.guide.guide_pipeline.build_policy_attention_payload",
                return_value={"policyAttentionCards": [{"title": "internal"}]},
            ),
            patch(
                "model_server.domains.guide.guide_pipeline.generate_llm_guide",
                return_value={
                    "htmlReport": FINAL_HTML_REPORT,
                    "llmGeneratedGuide": True,
                    "generationMode": "llm_guide",
                },
            ),
        ):
            result = generate_guide({"targetCountry": "JP", "includeInternal": True})

        self.assertEqual(result["htmlReport"], FINAL_HTML_REPORT)
        self.assertNotEqual(result["htmlReport"], HTML_REPORT)
        self.assertIn("<!doctype html>", result["htmlReport"].lower())
        self.assertIn("Sample Work", result["htmlReport"])
        self.assertNotIn("internal", result["htmlReport"])
        self.assertNotIn("internal", result)
        self.assertNotIn("contextPackEvidence", result)
        self.assertNotIn("modelPromptPayload", result)
        self.assertNotIn("policyAttentionCards", result)
        self.assertNotIn("qualitySummary", result)

    def test_llm_fallback_hides_error_publicly(self) -> None:
        with (
            patch(
                "model_server.domains.guide.guide_pipeline.build_localization_advice",
                return_value=_guide_base_result(),
            ),
            patch(
                "model_server.domains.guide.guide_pipeline._attach_context_pack_briefing",
                side_effect=lambda _payload, result: dict(result),
            ),
            patch("model_server.domains.guide.guide_pipeline.build_policy_attention_payload", return_value={}),
            patch("model_server.domains.guide.guide_pipeline.llm_requested", return_value=True),
            patch(
                "model_server.domains.guide.guide_pipeline.generate_llm_guide",
                side_effect=RuntimeError("provider secret"),
            ),
        ):
            public_result = generate_guide({"targetCountry": "JP", "useLlm": True})
            internal_requested_result = generate_guide(
                {"targetCountry": "JP", "useLlm": True, "includeInternal": True}
            )

        self.assertFalse(public_result["llmGeneratedGuide"])
        self.assertNotIn("llmGuideError", public_result)
        self.assertNotIn("internal", public_result)
        self.assertFalse(internal_requested_result["llmGeneratedGuide"])
        self.assertNotIn("llmGuideError", internal_requested_result)
        self.assertNotIn("internal", internal_requested_result)

    def test_country_recommendation_response_strips_llm_diagnostics_publicly(self) -> None:
        recommendation = {
            "mode": "country_recommendation",
            "requiresSelection": False,
            "recommendedCountry": "JP",
            "recommendedCountries": [{"country": "JP"}],
            "llmRecommendationEvidenceBytes": 456,
            "llmCountryRecommendationModel": "internal-model",
            "llmCountryRecommendationError": "provider detail",
        }
        with (
            patch(
                "model_server.domains.guide.guide_pipeline.build_localization_advice",
                return_value={"requiresSelection": False},
            ),
            patch(
                "model_server.domains.guide.guide_pipeline.generate_country_recommendation",
                return_value={**recommendation, "htmlReport": "<html>lower mock</html>"},
            ),
            patch(
                "model_server.domains.guide.guide_pipeline.render_country_recommendation_html",
                return_value="<!doctype html><html><body>renderer final</body></html>",
            ),
        ):
            public_result = generate_guide({"synopsis": "story"})
            internal_requested_result = generate_guide({"synopsis": "story", "includeInternal": True})

        self.assertEqual(public_result["recommendedCountry"], "JP")
        self.assertEqual(public_result["htmlReport"], "<!doctype html><html><body>renderer final</body></html>")
        self.assertNotEqual(public_result["htmlReport"], "<html>lower mock</html>")
        self.assertNotIn("llmRecommendationEvidenceBytes", public_result)
        self.assertNotIn("llmCountryRecommendationModel", public_result)
        self.assertNotIn("llmCountryRecommendationError", public_result)
        self.assertNotIn("llmCountryRecommendationModel", internal_requested_result)
        self.assertNotIn("internal", internal_requested_result)

    def test_synopsis_recommendation_exposes_html_but_not_internal_evidence(self) -> None:
        recommendation = {
            "mode": "synopsis_country_recommendation",
            "requiresSelection": False,
            "recommendedCountry": "JP",
            "recommendedCountryDisplay": "일본",
            "confidence": "중간",
            "storyProfile": {"title": "작품", "genre": "판타지", "coreSignals": ["성장"], "analysisSummary": "요약"},
            "countryComparisons": [],
            "limitations": ["한계"],
            "llmRecommendationEvidenceBytes": 456,
        }
        with patch(
            "model_server.domains.guide.guide_pipeline.generate_country_recommendation",
            return_value=recommendation,
        ):
            result = generate_guide({"title": "작품", "synopsis": "충분히 긴 시놉시스", "targetCountry": "JP"})

        self.assertTrue(result["htmlReport"].lstrip().lower().startswith("<!doctype html>"))
        self.assertFalse(result["requiresSelection"])
        self.assertNotIn("llmRecommendationEvidenceBytes", result)
        self.assertNotIn("recommended_country", result)
        self.assertNotIn("available_countries", result)


if __name__ == "__main__":
    unittest.main()
