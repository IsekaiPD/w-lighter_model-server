from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from model_server.domains.guide.agents.country_recommender import (
    _policy_summary,
    _repair_relative_fit_scores,
    generate_country_recommendation,
)
from model_server.domains.guide.engine.recommendation import (
    _genre_needles,
    _match_count,
    _synopsis_needles,
    rank_countries,
)
from model_server.domains.guide.infra.country_recommendation_html import render_country_recommendation_html
from model_server.domains.guide.guide_pipeline import generate_guide
from model_server.domains.guide.retrieval.context_pack import WorkInput, _input_elements
from model_server.domains.guide.retrieval.tavily_market import (
    build_multi_country_live_market_evidence,
    live_market_enabled,
)


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



    @staticmethod
    def _story_profile() -> dict:
        return {
            "title": "야근하는 신들의 사무소",
            "genre": "현대 한국형 오컬트 오피스 판타지 / 미스터리 / 로맨스",
            "coreSignals": [
                "계약직 공무원과 기억을 잃은 산신",
                "서울 도심 괴이 민원",
                "15년 전 언니 실종 사건",
                "혐관에서 신뢰로 변하는 계약 관계",
                "가족 상실과 죄책감의 치유",
                "한국 설화와 도시 개발 비리",
            ],
            "analysisSummary": "계약직 공무원이 기억을 잃은 산신과 괴이 민원을 해결하며 언니의 실종과 도시 개발 비리를 추적하는 한국형 오컬트 미스터리다.",
            "searchTermsByCountry": {
                "US": ["urban fantasy web fiction", "Korean mythology mystery", "supernatural office romance"],
                "JP": ["現代ファンタジー 怪異", "韓国 神話 ミステリー", "お仕事 ロマンス"],
                "CN": ["都市奇幻 悬疑", "韩国民俗 神灵", "职场 爱情 小说"],
                "TH": ["แฟนตาซีเมือง ลึกลับ", "ตำนานเกาหลี วิญญาณ", "โรแมนซ์ ที่ทำงาน"],
            },
        }

    @staticmethod
    def _live_market(*, allowed: bool) -> dict:
        countries = {}
        for code, domain in (("JP", "kakuyomu.jp"), ("US", "royalroad.com"), ("CN", "write.qq.com"), ("TH", "readawrite.com")):
            countries[code] = {
                "country": code,
                "evidenceLevel": "보통" if allowed else "제한적",
                "trustedCount": 1,
                "referenceCount": 0,
                "categoriesCovered": ["genre_trend", "platform_reference"] if allowed else ["genre_trend"],
                "items": [
                    {
                        "category": "genre_trend",
                        "source_type": "trusted",
                        "domain": domain,
                        "title": f"{code} 공개 장르 자료",
                        "url": f"https://{domain}/sample-{code.lower()}",
                        "summary": "도시 판타지와 초자연 미스터리 관련 공개 설명입니다.",
                    }
                ],
            }
        return {
            "liveMarketEnabled": True,
            "liveMarketUsed": True,
            "liveMarketSkipReason": None,
            "liveMarketResultCount": 16,
            "liveMarketInjectedCount": 4,
            "recommendationAllowed": allowed,
            "countries": countries,
            "limitations": ["검색 결과는 전체 시장 통계가 아닙니다."],
        }

    def test_synopsis_path_calls_two_llm_passes_and_marks_each_country_when_live_evidence_is_limited(self) -> None:
        story_profile = self._story_profile()
        country_analysis = {
            "storyProfile": story_profile,
            "countryAnalyses": [
                {
                    "country": code,
                    "fitLevel": "근거 제한",
                    "strengths": ["공개 출처에서 초자연 장르 신호를 확인했습니다.", "작품의 도시 괴이 요소와 연결할 수 있습니다."],
                    "risks": ["현지화 표현을 추가 확인해야 합니다.", "정책 원문을 다시 확인해야 합니다."],
                    "evidenceSummary": ["표시된 공개 출처만 사용했습니다.", "시장 성과는 추정하지 않았습니다."],
                    "localizationDifficulty": "문화 요소 설명 필요",
                }
                for code in ("US", "CN", "JP", "TH")
            ],
            "limitations": ["국가 간 성과 비교 자료가 아닙니다.", "검색 범위가 제한적입니다.", "최신 정책을 다시 확인해야 합니다."],
        }

        class FakeResponse:
            def __init__(self, payload):
                self.output_text = json.dumps(payload, ensure_ascii=False)

        class FakeResponses:
            def __init__(self):
                self.calls = []
                self.payloads = [story_profile, country_analysis]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return FakeResponse(self.payloads[len(self.calls) - 1])

        class FakeClient:
            def __init__(self):
                self.responses = FakeResponses()

        fake_client = FakeClient()
        with patch("model_server.domains.guide.agents.country_recommender._client_and_model", return_value=(fake_client, "test-guide-model")), patch(
            "model_server.domains.guide.agents.country_recommender.build_multi_country_live_market_evidence",
            return_value=self._live_market(allowed=False),
        ):
            result = generate_country_recommendation(
                {
                    "title": story_profile["title"],
                    "genre": "현대",
                    "synopsis": "계약직 공무원이 기억을 잃은 산신과 서울의 괴이 사건을 추적한다.",
                    "useLLM": False,
                }
            )

        self.assertEqual(len(fake_client.responses.calls), 2)
        self.assertEqual(result["recommendationStatus"], "analyzed")
        self.assertEqual(result["recommendationMethod"], "llm_tavily_country_analysis")
        self.assertTrue(result["liveMarketUsed"])
        self.assertIsNone(result["recommendedCountry"])
        self.assertNotIn("searchTermsByCountry", result["storyProfile"])
        self.assertEqual(len(result["countryAnalyses"]), 4)
        self.assertEqual(result["countryAnalyses"], result["countryComparisons"])
        self.assertTrue(all(item["rank"] is None for item in result["countryAnalyses"]))
        self.assertTrue(all(item["assessment"] == "viable_with_cautions" for item in result["countryAnalyses"]))
        self.assertTrue(all("relativeFitScore" not in item for item in result["countryAnalyses"]))

        html = render_country_recommendation_html(result)
        self.assertEqual(html.count(story_profile["analysisSummary"]), 1)
        self.assertIn("https://royalroad.com/sample-us", html)
        self.assertIn("국가별 현지화 적합성 분석", html)
        self.assertIn("작품에서 잘 전달될 요소", html)
        self.assertIn("현지화에서 주의할 요소", html)
        self.assertIn("현지화 난이도", html)
        self.assertNotIn("추천 보류", html)
        self.assertNotIn("국가 우선순위 비교", html)
        self.assertNotIn("우선순위 88", html)
        self.assertNotIn("참고 컨텍스트 원천", html)

    def test_sufficient_tavily_evidence_returns_four_country_analyses_without_rank_or_score(self) -> None:
        story_profile = self._story_profile()
        comparison = {
            "storyProfile": story_profile,
            "recommendedCountry": "JP",
            "confidence": "중간",
            "countryComparisons": [
                {
                    "country": code,
                    "rank": rank,
                    "fitLevel": "우선 검토" if rank == 1 else "비교 검토",
                    "strengths": ["공개 플랫폼 자료와 작품 신호가 연결됩니다."],
                    "risks": ["문화 요소의 설명 방식을 확인해야 합니다."],
                    "evidenceSummary": ["표시된 Tavily 출처를 사용했습니다."],
                    "localizationDifficulty": "보통",
                }
                for rank, code in enumerate(("JP", "US", "TH", "CN"), start=1)
            ],
            "limitations": ["검색 결과는 전체 시장 통계가 아닙니다.", "흥행 확률로 해석하면 안 됩니다."],
        }

        class FakeResponse:
            def __init__(self, payload):
                self.output_text = json.dumps(payload, ensure_ascii=False)

        class FakeResponses:
            def __init__(self):
                self.calls = []
                self.payloads = [story_profile, comparison]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return FakeResponse(self.payloads[len(self.calls) - 1])

        class FakeClient:
            def __init__(self):
                self.responses = FakeResponses()

        fake_client = FakeClient()
        with patch("model_server.domains.guide.agents.country_recommender._client_and_model", return_value=(fake_client, "test-guide-model")), patch(
            "model_server.domains.guide.agents.country_recommender.build_multi_country_live_market_evidence",
            return_value=self._live_market(allowed=True),
        ):
            result = generate_country_recommendation(
                {"title": story_profile["title"], "genre": "현대", "synopsis": "긴 시놉시스"}
            )

        self.assertEqual(len(fake_client.responses.calls), 2)
        self.assertEqual(result["recommendationStatus"], "analyzed")
        self.assertEqual(result["recommendationMethod"], "llm_tavily_country_analysis")
        self.assertIsNone(result["recommendedCountry"])
        self.assertEqual(len(result["countryAnalyses"]), 4)
        self.assertEqual(result["countryAnalyses"], result["countryComparisons"])
        self.assertTrue(all(item["rank"] is None for item in result["countryAnalyses"]))
        self.assertTrue(all(item["assessment"] == "viable_with_cautions" for item in result["countryAnalyses"]))
        self.assertTrue(all("relativeFitScore" not in item for item in result["countryAnalyses"]))
        html = render_country_recommendation_html(result)
        self.assertIn("국가별 현지화 적합성 분석", html)
        self.assertIn("작품에서 잘 전달될 요소", html)
        self.assertIn("현지화에서 주의할 요소", html)
        self.assertIn("현지화 난이도", html)
        self.assertNotIn("#1", html)
        self.assertNotIn("우선 검토", html)
        self.assertNotIn("relativeFitScore", html)
        self.assertEqual(html.count(story_profile["analysisSummary"]), 1)


    def test_multi_country_tavily_uses_localized_search_terms_without_exposing_search_scores(self) -> None:
        profile = self._story_profile()
        seen: dict[str, list[str]] = {}

        def fake_collect(*, country, genre, max_results, search_depth, signals):
            seen[country] = list(signals)
            domain = {
                "JP": "kakuyomu.jp",
                "US": "royalroad.com",
                "CN": "qidian.com",
                "TH": "readawrite.com",
            }[country]
            return [
                {
                    "country": country,
                    "category": "platform_reference",
                    "query": "policy",
                    "rank_in_search": 1,
                    "title": "공식 정책",
                    "url": f"https://{domain}/policy",
                    "domain": domain,
                    "source_type": "trusted",
                    "content": "공식 플랫폼 정책 안내",
                    "score": 0.91,
                },
                {
                    "country": country,
                    "category": "genre_trend",
                    "query": "genre",
                    "rank_in_search": 1,
                    "title": "장르 태그",
                    "url": f"https://{domain}/genre",
                    "domain": domain,
                    "source_type": "trusted",
                    "content": "도시 판타지와 초자연 미스터리 태그",
                    "score": 0.83,
                },
            ]

        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}, clear=False), patch(
            "model_server.domains.guide.retrieval.tavily_market.collect_live_market_rows", side_effect=fake_collect
        ):
            result = build_multi_country_live_market_evidence(
                {"title": profile["title"], "genre": profile["genre"], "synopsis": "긴 시놉시스"},
                profile,
            )

        self.assertTrue(result["recommendationAllowed"])
        for code in ("US", "CN", "JP", "TH"):
            self.assertEqual(seen[code], profile["searchTermsByCountry"][code])
            self.assertTrue(result["countries"][code]["items"])
            self.assertTrue(all("score" not in item for item in result["countries"][code]["items"]))


    def test_legacy_score_repair_helper_remains_importable_but_is_not_public_contract(self) -> None:
        repaired = _repair_relative_fit_scores(
            [
                {"country": "JP", "rank": 1, "relativeFitScore": 0},
                {"country": "US", "rank": 2, "relativeFitScore": 0},
                {"country": "TH", "rank": 3, "relativeFitScore": 0},
                {"country": "CN", "rank": 4, "relativeFitScore": 0},
            ]
        )
        self.assertEqual([item["relativeFitScore"] for item in repaired], [86, 74, 62, 50])

    def test_selected_country_live_market_remains_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(live_market_enabled({}))
            self.assertTrue(live_market_enabled({"includeLiveMarket": True}))

    def test_public_recommendation_response_does_not_expose_model_name(self) -> None:
        from model_server.domains.guide.guide_pipeline import _shape_recommendation_response

        public = _shape_recommendation_response(
            {},
            {
                "mode": "synopsis_country_recommendation",
                "requiresSelection": True,
                "recommendationStatus": "insufficient_evidence",
                "llmCountryRecommendationModel": "internal-model",
                "recommendedCountry": None,
            },
        )
        self.assertNotIn("llmCountryRecommendationModel", public)

    def test_foreign_confidence_repair_is_low(self) -> None:
        from model_server.domains.guide.infra.output_language_guard import repair_user_facing_explanations

        repaired = repair_user_facing_explanations({"confidence": "medium confidence"})
        self.assertEqual(repaired["confidence"], "낮음")

    def test_irrelevant_policy_matches_are_not_exposed(self) -> None:
        profile = self._story_profile()
        target = {"code": "CN", "targetCountry": "China", "market": "china", "display": "중국"}
        summary = _policy_summary(
            {
                "title": profile["title"],
                "genre": profile["genre"],
                "synopsis": "서울시 공무원과 산신이 실종 사건과 도시개발 비리를 추적한다.",
            },
            target,
            profile,
        )
        messages = " ".join(str(item.get("message") or "") for item in summary["risks"])
        self.assertNotIn("교사·학생", messages)
        self.assertNotIn("타 사이트", messages)
        self.assertLessEqual(summary["riskCount"], 3)

    def test_no_synopsis_and_no_country_returns_selection_without_country_recommendation(self) -> None:
        result = generate_guide({"genre": "현대 판타지"})
        self.assertTrue(result["requiresSelection"])
        self.assertEqual(result["mode"], "needs_country_and_genre_selection")
        self.assertIsNone(result["recommendedCountry"])

    def test_no_synopsis_and_country_without_genre_still_requires_selection(self) -> None:
        result = generate_guide({"targetCountry": "JP"})
        self.assertTrue(result["requiresSelection"])
        self.assertEqual(result["mode"], "needs_country_and_genre_selection")
        self.assertIn("장르", result["message"])


    def test_no_synopsis_llm_failure_does_not_return_deterministic_html(self) -> None:
        live_result = {
            "liveMarketRequested": False,
            "liveMarketEnabled": True,
            "liveMarketUsed": False,
            "liveMarketCountry": "JP",
            "liveMarketResultCount": 0,
            "liveMarketInjectedCount": 0,
            "liveMarketSkipReason": "no_useful_results",
        }
        with patch("model_server.domains.guide.guide_pipeline.build_live_market_evidence", return_value=live_result), patch(
            "model_server.domains.guide.guide_pipeline.generate_llm_guide", side_effect=RuntimeError("model unavailable")
        ):
            result = generate_guide({"targetCountry": "JP", "genre": "현대 판타지"})

        self.assertEqual(result["generationMode"], "llm_guide_failed")
        self.assertFalse(result["llmGeneratedGuide"])
        self.assertNotIn("htmlReport", result)
        self.assertIn("결과를 만들지 못했습니다", result["message"])

    def test_no_synopsis_country_guide_always_uses_live_evidence_and_llm(self) -> None:
        llm_result = {
            "generationMode": "llm_guide",
            "llmGeneratedGuide": True,
            "htmlReport": "<html>LLM guide</html>",
        }
        live_result = {
            "liveMarketRequested": False,
            "liveMarketEnabled": True,
            "liveMarketUsed": True,
            "liveMarketCountry": "JP",
            "liveMarketResultCount": 4,
            "liveMarketInjectedCount": 2,
            "liveMarketSkipReason": None,
            "liveMarketEvidence": {"country": "JP", "items": []},
        }
        with patch("model_server.domains.guide.guide_pipeline.build_live_market_evidence", return_value=live_result) as live_mock, patch(
            "model_server.domains.guide.guide_pipeline.generate_llm_guide", return_value=llm_result
        ) as llm_mock:
            result = generate_guide(
                {"targetCountry": "JP", "genre": "현대 판타지", "useLlm": False}
            )

        live_mock.assert_called_once()
        llm_mock.assert_called_once()
        self.assertFalse(result["requiresSelection"])
        self.assertEqual(result["mode"], "country_genre_guide")
        self.assertEqual(result["generationMode"], "llm_guide")
        self.assertTrue(result["llmGeneratedGuide"])


if __name__ == "__main__":
    unittest.main()
