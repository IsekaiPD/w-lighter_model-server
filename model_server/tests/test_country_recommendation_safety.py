from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from model_server.domains.guide.agents.country_recommender import (
    _repair_relative_fit_scores,
    _score_from_support,
    generate_country_recommendation,
)
from model_server.domains.guide.engine.recommendation import (
    _genre_needles,
    _match_count,
    _synopsis_needles,
    rank_countries,
)
from model_server.domains.guide.infra.country_recommendation_html import render_country_recommendation_html
from model_server.domains.guide.retrieval.context_pack import WorkInput, _input_elements


class CountryRecommendationSafetyTests(unittest.TestCase):
    def test_romance_does_not_expand_to_bl(self) -> None:
        needles = _genre_needles("현대 로맨스 / 혐관 로맨스 / 로맨틱 코미디")
        self.assertIn("Romance", needles)
        self.assertNotIn("BL", needles)
        self.assertNotIn("LGBTQ+", needles)

    def test_generic_male_word_does_not_trigger_bl(self) -> None:
        needles = _synopsis_needles("남자 주인공과 여자 주인공이 계약 관계로 만난다.")
        self.assertNotIn("BL", needles)
        self.assertNotIn("Boys Love", needles)

    def test_short_ascii_signal_uses_word_boundary(self) -> None:
        for false_positive in ("Building", "Noble", "Blood", "Blade"):
            self.assertEqual(_match_count(false_positive.lower(), ["BL"]), 0)
        self.assertEqual(_match_count("BL/순애".lower(), ["BL"]), 1)

    def test_ranker_has_no_top_exposure_fallback(self) -> None:
        data = {
            "collections": {
                "sample": [
                    {
                        "country": "US/global English",
                        "rank": 1,
                        "title": "Unrelated Building Story",
                        "genre": "Mystery",
                        "genres": ["Mystery"],
                        "tags": ["Building"],
                        "synopsis": "No matching signal.",
                    }
                ]
            }
        }
        rec = next(item for item in rank_countries(data, genre="BL", synopsis="") if item.country == "US/global English")
        self.assertEqual(rec.score, 0.0)
        self.assertEqual(rec.evidence, [])
        self.assertTrue(any("직접 겹치는" in reason for reason in rec.reasons))

    def test_genre_and_korean_synopsis_are_split_into_signals(self) -> None:
        work = WorkInput(
            title="테스트",
            target_market="english",
            genre="현대 로맨스 / 작가물 / 혐관 로맨스 / 상처 치유 / 로맨틱 코미디",
            synopsis="계약 관계로 시작한 두 작가가 혐관에서 로맨스로 변하고 상처를 치유한다.",
        )
        rows = _input_elements(work)
        signals = [row["element"] for row in rows]
        self.assertIn("로맨스", signals)
        self.assertIn("코미디", signals)
        self.assertIn("드라마", signals)
        self.assertNotIn(work.genre, signals)
        self.assertNotIn(work.synopsis[:80], signals)

    def test_policy_count_does_not_change_overlap_score(self) -> None:
        support = {"normalizedScore": 0.7, "rankIndex": 1}
        base = {"matchedSignals": ["로맨스"], "platformEvidence": [{"status": "direct"}]}
        low_policy = {**base, "policyRiskSummary": {"riskCount": 1}}
        high_policy = {**base, "policyRiskSummary": {"riskCount": 99}}
        self.assertEqual(_score_from_support(low_policy, support), _score_from_support(high_policy, support))

    def test_score_repair_does_not_invent_rank_scores(self) -> None:
        comparisons = [
            {"country": code, "rank": rank, "relativeFitScore": 0}
            for rank, code in enumerate(("US", "TH", "JP", "CN"), start=1)
        ]
        repaired = _repair_relative_fit_scores(comparisons)
        self.assertEqual([item["relativeFitScore"] for item in repaired], [0, 0, 0, 0])

    def test_current_observation_data_still_calls_llm_and_returns_recommendation_hold(self) -> None:
        llm_payload = {
            "storyProfile": {
                "title": "임시 제목",
                "genre": "현대 판타지 / 오피스 오컬트 / 미스터리 / 상처 치유 로맨스",
                "coreSignals": [
                    "계약직 공무원과 기억을 잃은 산신",
                    "서울 도심 괴이 민원",
                    "15년 전 언니 실종 사건",
                    "혐관에서 신뢰로 변하는 계약 관계",
                    "가족 상실과 죄책감의 치유",
                    "한국 설화와 도시 개발 비리",
                ],
                "analysisSummary": "신을 믿지 않는 계약직 공무원이 기억을 잃은 산신과 괴이 민원을 해결하며 언니의 실종과 도시 개발 비리를 추적하는 한국형 오컬트 미스터리다.",
            },
            "countryAnalyses": [
                {
                    "country": code,
                    "fitLevel": "관측 신호 설명",
                    "strengths": [
                        f"{code} 관측 자료에서 확인된 장르 신호와 작품의 현대 판타지 요소를 연결해 설명할 수 있습니다.",
                        "소개문에서는 도시 괴이와 가족 미스터리를 분리해 전달할 수 있습니다.",
                    ],
                    "risks": [
                        "정책 후보는 별도 검토가 필요합니다.",
                        "시장 성과로 확대 해석하면 안 됩니다.",
                    ],
                    "evidenceSummary": ["제공된 관측 신호만 사용했습니다.", "추천 점수는 생성하지 않았습니다."],
                    "localizationDifficulty": "문화 요소 설명 필요",
                }
                for code in ("US", "CN", "JP", "TH")
            ],
            "limitations": [
                "국가 간 성과 비교 자료가 아닙니다.",
                "플랫폼별 표본 조건이 다릅니다.",
                "직접 선택 후 상세 가이드를 생성해야 합니다.",
            ],
        }

        class FakeResponse:
            output_text = json.dumps(llm_payload, ensure_ascii=False)

        class FakeResponses:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return FakeResponse()

        class FakeClient:
            def __init__(self) -> None:
                self.responses = FakeResponses()

        fake_client = FakeClient()
        with patch(
            "model_server.domains.guide.agents.country_recommender._client_and_model",
            return_value=(fake_client, "test-guide-model"),
        ):
            result = generate_country_recommendation(
                {
                    "title": "임시 제목",
                    "genre": "현대",
                    "synopsis": "계약직 공무원이 기억을 잃은 산신과 서울의 괴이 사건을 추적하며 실종된 언니의 비밀을 찾는다.",
                    "useLLM": False,
                }
            )

        self.assertEqual(len(fake_client.responses.calls), 1)
        self.assertEqual(result["recommendationStatus"], "insufficient_evidence")
        self.assertEqual(result["recommendationMethod"], "llm_evidence_analysis")
        self.assertEqual(result["llmCountryRecommendationModel"], "test-guide-model")
        self.assertIn("오피스 오컬트", result["storyProfile"]["genre"])
        self.assertGreaterEqual(len(result["storyProfile"]["coreSignals"]), 6)
        self.assertIsNone(result["recommendedCountry"])
        self.assertTrue(result["requiresSelection"])
        self.assertTrue(all(item["rank"] is None for item in result["countryComparisons"]))
        self.assertTrue(all(item["relativeFitScore"] is None for item in result["countryComparisons"]))

        html = render_country_recommendation_html(result)
        self.assertIn("추천 보류", html)
        self.assertIn("오피스 오컬트", html)
        self.assertIn("국가별 근거 상태", html)
        self.assertNotIn("우선순위 88", html)
        self.assertNotIn("먼저 검토하기 좋은 국가", html)


if __name__ == "__main__":
    unittest.main()
