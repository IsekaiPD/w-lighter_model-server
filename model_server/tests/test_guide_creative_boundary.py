from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from model_server.domains.guide.agents.country_recommender import generate_country_recommendation
from model_server.domains.guide.agents.guide_writer import generate_llm_guide, render_llm_html


class GuideCreativeBoundaryTests(unittest.TestCase):
    def test_guide_prompt_forbids_story_direction_changes(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)

                class FakeResponse:
                    output_text = json.dumps(
                        {
                            "executiveSummary": ["요약 A", "요약 B"],
                            "inputReading": {
                                "workTitle": "작품",
                                "genre": "fantasy",
                                "targetCountry": "JP",
                                "coreAppeal": ["성장"],
                                "assumptions": [],
                            },
                            "marketInterpretation": ["시장 해석"] * 3,
                            "culturalNotes": ["문화 메모"] * 2,
                            "platformPolicyChecks": ["정책 체크"] * 2,
                            "marketTagGuidance": ["태그 전달"] * 2,
                            "evidenceExplanation": ["근거 설명"] * 2,
                            "limitations": ["한계"] * 2,
                        },
                        ensure_ascii=False,
                    )

                return FakeResponse()

        class FakeClient:
            responses = FakeResponses()

        with patch(
            "model_server.domains.guide.agents.guide_writer._client_and_model",
            return_value=(FakeClient(), "gpt-5.4-mini"),
        ):
            generate_llm_guide(
                {"title": "작품", "genre": "fantasy", "synopsis": "story"},
                {"title": "작품", "genre": "fantasy", "targetCountry": "JP", "reportMode": "country_genre_guide"},
            )

        user_payload = json.loads(captured["input"][1]["content"])
        requirements = "\n".join(user_payload["requirements"])
        self.assertIn("작품의 플롯, 결말, 캐릭터 성격, 핵심 설정", requirements)
        self.assertIn("작품을 현재 방향 그대로 두고", requirements)
        self.assertIn("제목, 소개문, 태그", requirements)

    def test_country_recommendation_prompt_is_market_fit_not_rewrite(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)

                class FakeResponse:
                    output_text = json.dumps(
                        {
                            "storyProfile": {
                                "title": "작품",
                                "genre": "fantasy",
                                "coreSignals": ["성장"],
                                "analysisSummary": "현재 시놉시스 기준 시장 적합도를 봅니다.",
                            },
                            "recommendedCountry": "JP",
                            "confidence": "중간",
                            "countryComparisons": [
                                {
                                    "country": code,
                                    "rank": rank,
                                    "relativeFitScore": 90 - rank,
                                    "fitLevel": "적합",
                                    "strengths": ["전달 포인트가 명확합니다."],
                                    "risks": ["정책 검토가 필요합니다."],
                                    "evidenceSummary": ["근거"],
                                    "localizationDifficulty": "보통",
                                }
                                for rank, code in enumerate(["JP", "US", "CN", "TH"], start=1)
                            ],
                            "limitations": ["한계", "추가 검토 필요"],
                        },
                        ensure_ascii=False,
                    )

                return FakeResponse()

        class FakeClient:
            responses = FakeResponses()

        with patch(
            "model_server.domains.guide.agents.country_recommender._client_and_model",
            return_value=(FakeClient(), "gpt-5.4-mini"),
        ), patch(
            "model_server.domains.guide.agents.country_recommender.llm_requested",
            return_value=True,
        ), patch(
            "model_server.domains.guide.agents.country_recommender.build_country_recommendation_evidence",
            return_value={
                "story": {"title": "작품", "genre": "fantasy", "synopsis": "story"},
                "countries": [],
                "contextPackDiagnosticsByCountry": [],
            },
        ):
            generate_country_recommendation({"synopsis": "story", "genre": "fantasy", "useLlm": True})

        user_payload = json.loads(captured["input"][1]["content"])
        requirements = "\n".join(user_payload["requirements"])
        self.assertIn("작품 자체를 바꾸는 방향 제안이 아니라", requirements)
        self.assertIn("현재 시놉시스 기준", requirements)
        self.assertIn("제목, 소개문, 태그", requirements)

    def test_rendered_html_states_localization_not_story_rewrite(self) -> None:
        html = render_llm_html(
            {
                "executiveSummary": ["요약"],
                "inputReading": {
                    "workTitle": "작품",
                    "genre": "fantasy",
                    "targetCountry": "JP",
                    "coreAppeal": ["성장"],
                    "assumptions": [],
                },
                "marketInterpretation": ["시장 해석"],
                "culturalNotes": [],
                "platformPolicyChecks": [],
                "marketTagGuidance": [],
                "evidenceExplanation": [],
                "limitations": [],
            },
            {"title": "작품", "targetCountry": "JP"},
        )

        self.assertIn("작품을 현재 방향 그대로 두고", html)
        self.assertIn("제목·소개문·태그 전달 가이드", html)
        self.assertNotIn("스토리 개선안", html)
        self.assertNotIn("플롯 수정안", html)


if __name__ == "__main__":
    unittest.main()
