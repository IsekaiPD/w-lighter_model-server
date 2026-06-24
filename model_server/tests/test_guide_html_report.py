from __future__ import annotations

import unittest

from model_server.domains.guide.agents.guide_writer import GUIDE_JSON_SCHEMA, render_llm_html
from model_server.domains.guide.engine.recommendation import _html_report
from model_server.domains.guide.infra.country_recommendation_html import render_country_recommendation_html


class GuideHtmlReportTests(unittest.TestCase):
    def test_llm_strict_schema_requires_every_declared_property(self) -> None:
        self.assertEqual(
            set(GUIDE_JSON_SCHEMA["properties"]),
            set(GUIDE_JSON_SCHEMA["required"]),
        )
        self.assertIn("marketSignalSummary", GUIDE_JSON_SCHEMA["required"])
        self.assertIn("platformCultureReview", GUIDE_JSON_SCHEMA["required"])
        self.assertIn("releaseChecklist", GUIDE_JSON_SCHEMA["required"])
        self.assertNotIn("evidenceExplanation", GUIDE_JSON_SCHEMA["properties"])
        self.assertNotIn("limitations", GUIDE_JSON_SCHEMA["properties"])

    def test_deterministic_html_report_is_self_contained_document(self) -> None:
        html = _html_report(
            title="작품",
            mode_label="국가/장르 기반 기준서",
            target_country="JP",
            genre="판타지",
            sections={"market": {"title": "시장 해석", "items": ["일본 독자 기대에 맞춘 후킹이 필요합니다."]}},
            recommendations=[],
        )

        self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("<style>", html)
        self.assertIn("</style>", html)
        self.assertIn("overflow-wrap:anywhere", html)
        self.assertIn("minmax(min(240px,100%),1fr)", html)
        self.assertIn('class="guide-report"', html)
        self.assertIn('class="guide-cover"', html)
        self.assertIn("핵심 판단", html)
        self.assertIn("출시 전 전달 체크리스트", html)
        self.assertIn("작품을 현재 방향 그대로 두고", html)

    def test_deterministic_html_report_hides_internal_market_noise(self) -> None:
        html = _html_report(
            title="작품",
            mode_label="국가/장르 기반 기준서",
            target_country="US",
            genre="fantasy",
            sections={
                "genre_trope_alignment": {
                    "title": "장르·태그 정리",
                    "items": [
                        "Wattpad/hot_fantasy 순위 1: Sample, 장르 적중 0, 시놉시스 적중 6",
                        "ONGOING, WAIT_UNTIL_FREE, Original",
                        "Fantasy (959)",
                    ],
                },
                "title_synopsis_localization": {
                    "title": "제목·소개문 정리",
                    "items": ["US/global English 독자에게 소개문을 명확히 전달합니다."],
                },
                "terminology_glossary_risks": {
                    "title": "고유명사 정리",
                    "items": ["작품 glossary에 넣어 관리합니다."],
                },
                "evidence_used": {
                    "title": "사용 근거",
                    "items": ["사용 근거를 그대로 노출하지 않습니다."],
                },
                "platform_culture_review_result": {
                    "title": "플랫폼·문화권 검토 결과",
                    "items": ["미국 기준으로 게시 전 확인할 항목을 작품 입력에 맞춰 정리합니다."],
                },
                "market_signal_summary": {
                    "title": "참고한 시장 신호 요약",
                    "items": ["공개 플랫폼 자료는 표현 방향 참고로만 사용합니다."],
                },
                "release_readiness_checklist": {
                    "title": "출시 전 확인할 것",
                    "items": ["제목과 소개문에서 초반 갈등이 보이는지 확인합니다."],
                },
            },
            recommendations=[],
        )

        for hidden in (
            "(959)",
            "ONGOING",
            "WAIT_UNTIL_FREE",
            "Original",
            "Wattpad/hot_fantasy",
            "장르 적중",
            "시놉시스 적중",
            "선택 국가 요약",
            "사용 근거",
            "glossary",
            "US/global English",
        ):
            self.assertNotIn(hidden, html)
        self.assertIn("표기 기준", html)
        self.assertIn("플랫폼·문화권 검토 결과", html)
        self.assertIn("참고한 시장 신호 요약", html)
        self.assertIn("출시 전 확인할 것", html)

    def test_llm_html_report_is_self_contained_document(self) -> None:
        guide = {
            "executiveSummary": ["요약 1", "요약 2"],
            "inputReading": {
                "workTitle": "작품",
                "genre": "판타지",
                "targetCountry": "일본",
                "coreAppeal": ["성장", "학원"],
                "assumptions": ["시놉시스 기반 추정"],
            },
            "marketInterpretation": ["glossary 기준을 확인합니다."],
            "marketSignalSummary": ["공개 플랫폼 자료는 표현 방향 참고로만 사용합니다."],
            "culturalNotes": ["문화 메모"],
            "platformCultureReview": ["시놉시스 기준으로 게시 전 확인할 항목을 정리했습니다."],
            "platformPolicyChecks": ["정책 체크"],
            "marketTagGuidance": ["태그 가이드"],
            "releaseChecklist": ["제목과 소개문을 확인합니다.", "고유명사 표기를 확인합니다.", "정책 리스크를 확인합니다."],
        }
        result = {
            "title": "작품",
            "displayCountry": "일본",
            "genre": "판타지",
            "contextPackBriefing": {"headline_market_labels": []},
            "contextPackEvidence": {"platforms": [], "context_record_count": 0},
        }

        html = render_llm_html(guide, result)

        self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("<style>", html)
        self.assertIn("</style>", html)
        self.assertIn("핵심 전달 전략", html)
        self.assertIn("출시 전 확인할 것", html)
        self.assertIn("시장 적합도 해석", html)
        self.assertIn("참고한 시장 신호 요약", html)
        self.assertIn("번역·표현 주의점", html)
        self.assertIn("플랫폼·문화권 검토 결과", html)
        self.assertIn("플랫폼 게시 전 체크", html)
        self.assertNotIn("판단 근거", html)
        self.assertNotIn("확인 필요 사항", html)
        self.assertIn("작품을 현재 방향 그대로 두고", html)
        self.assertIn("작품 용어 기준", html)
        self.assertNotIn("컨텍스트 팩", html)
        self.assertNotIn("glossary", html)
        self.assertLess(html.index("핵심 전달 전략"), html.index("작품 입력 해석"))
        self.assertLess(html.index("작품 입력 해석"), html.index("제목·소개문·태그 전달 가이드"))
        self.assertLess(html.index("제목·소개문·태그 전달 가이드"), html.index("번역·표현 주의점"))

    def test_llm_html_report_renders_balanced_live_market_items(self) -> None:
        guide = {
            "executiveSummary": ["summary"],
            "inputReading": {
                "workTitle": "work",
                "genre": "fantasy",
                "targetCountry": "Japan",
                "coreAppeal": [],
                "assumptions": [],
            },
            "marketInterpretation": [],
            "marketSignalSummary": ["공개 플랫폼 자료는 표현 방향 참고로만 사용합니다."],
            "culturalNotes": [],
            "platformCultureReview": ["게시 전 확인 항목만 정리합니다."],
            "platformPolicyChecks": [],
            "marketTagGuidance": [],
            "releaseChecklist": ["제목을 확인합니다.", "소개문을 확인합니다.", "태그를 확인합니다."],
        }
        result = {
            "title": "work",
            "displayCountry": "Japan",
            "genre": "fantasy",
            "liveMarketEvidence": {
                "country": "JP",
                "items": [
                    {
                        "category": "platform_reference",
                        "source_type": "trusted",
                        "domain": "kakuyomu.jp",
                        "title": "Kakuyomu guide",
                        "url": "https://kakuyomu.jp/help",
                        "summary": "Platform rule summary",
                    }
                ],
            },
        }

        html = render_llm_html(guide, result)

        self.assertNotIn("최근 플랫폼 참고 자료", html)
        self.assertNotIn("플랫폼 기준", html)
        self.assertNotIn("주요 플랫폼", html)
        self.assertNotIn("kakuyomu.jp", html)
        self.assertNotIn("https://kakuyomu.jp/help", html)
        self.assertIn(".mini-card a,.mini-card h3,.mini-card small", html)
        self.assertNotIn("출처 열기", html)
        self.assertNotIn("본문 가이드를 작성할 때 확인한 공개 자료", html)
        self.assertNotIn("LIVE MARKET EVIDENCE", html)
        self.assertNotIn("원문 스니펫", html)
        self.assertNotIn("Kakuyomu guide", html)
        self.assertNotIn("Platform rule summary", html)
        self.assertNotIn("countryEvidence", html)

    def test_country_recommendation_is_a_self_contained_html_result(self) -> None:
        result = {
            "recommendedCountry": "JP",
            "recommendedCountryDisplay": "일본",
            "confidence": "중간",
            "storyProfile": {"title": "러브 앤 블러드", "genre": "현대 로맨스", "coreSignals": ["작가물"], "analysisSummary": "관계성과 치유가 핵심입니다."},
            "countryComparisons": [
                {"country": "JP", "displayCountry": "일본", "rank": 1, "relativeFitScore": 82, "fitLevel": "상위 적합", "strengths": ["관계성 전달"], "risks": ["제목 보정"]},
                {"country": "US", "displayCountry": "미국/글로벌 영어", "rank": 2, "relativeFitScore": 68, "fitLevel": "비교 적합", "strengths": ["장르 혼합"], "risks": ["소개문 현지화"]},
            ],
            "limitations": ["추천은 선택 전 비교 결과입니다."],
        }

        html = render_country_recommendation_html(result)

        self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn('class="wl-guide-page"', html)
        self.assertIn("국가별 현지화 적합성 분석", html)
        self.assertIn("이 결과는 입력 신호와 공개 관측 자료의 겹침을 비교한 참고 결과입니다.", html)
        self.assertIn("추천은 선택 전 비교 결과입니다.", html)


    def test_country_analysis_separates_market_and_policy_sources_and_collapses_snippets(self) -> None:
        result = {
            "storyProfile": {
                "title": "야근하는 신들의 사무소",
                "genre": "현대 판타지",
                "coreSignals": ["서울시 민원 공무원", "기억을 잃은 산신"],
                "analysisSummary": "한국 행정과 오컬트를 결합한 작품입니다.",
            },
            "countryAnalyses": [
                {
                    "country": "US",
                    "displayCountry": "미국/글로벌 영어",
                    "fitLevel": "일부 연결 신호가 확인됨",
                    "evidenceLevel": "제한적",
                    "strengths": ["서울시 민원 공무원과 산신의 결합은 도시 판타지 소개문 훅으로 전달할 수 있습니다."],
                    "risks": ["민원과 산신의 문화적 의미를 영어권 독자에게 압축해 설명해야 합니다."],
                    "evidenceSummary": ["장르 관측과 정책 자료를 서로 다른 용도로 확인했습니다."],
                    "localizationDifficulty": "중간",
                    "liveEvidence": [
                        {
                            "category": "genre_trend",
                            "source_type": "trusted",
                            "domain": "example.com",
                            "title": "Urban fantasy tags",
                            "url": "https://example.com/tags",
                            "summary": "도시 판타지와 초자연 미스터리 태그 관측 자료입니다." * 20,
                        },
                        {
                            "category": "platform_reference",
                            "source_type": "trusted",
                            "domain": "example.com",
                            "title": "Content policy",
                            "url": "https://example.com/policy",
                            "summary": "폭력 및 성적 콘텐츠 게시 기준 안내입니다." * 20,
                        },
                    ],
                }
            ],
            "limitations": ["검색 결과는 전체 시장 통계가 아닙니다."],
        }

        html = render_country_recommendation_html(result)

        self.assertIn("작품 적합성 근거", html)
        self.assertIn("게시·정책 검토 근거", html)
        self.assertIn("근거 상세 보기", html)
        self.assertIn("<details", html)
        self.assertLess(html.count("도시 판타지와 초자연 미스터리 태그 관측 자료입니다."), 20)
        self.assertLess(html.count("폭력 및 성적 콘텐츠 게시 기준 안내입니다."), 20)

    def test_country_recommendation_collapses_weak_repetition(self) -> None:
        result = {
            "recommendedCountry": "US",
            "recommendedCountryDisplay": "미국/글로벌 영어",
            "recommendationStatus": "insufficient_evidence",
            "confidence": "낮음",
            "storyProfile": {
                "title": "오뚜기 스프",
                "genre": "현대 로맨스",
                "coreSignals": ["작가물", "혐관 로맨스"],
                "analysisSummary": "입력 자체는 작품 시놉시스보다 짧은 작품명에 가깝습니다.",
            },
            "countryComparisons": [
                {
                    "country": "US",
                    "displayCountry": "미국/글로벌 영어",
                    "rank": 1,
                    "relativeFitScore": 88,
                    "fitLevel": "근거 부족 예비 우선",
                    "strengths": ["입력 장르와 공개 태그를 확인해야 합니다."],
                    "risks": ["직접 매칭 근거가 없습니다."],
                    "evidenceSummary": ["참고 컨텍스트 원천은 많지만 직접 매칭은 없습니다."],
                },
                {
                    "country": "JP",
                    "displayCountry": "일본",
                    "rank": 2,
                    "relativeFitScore": 76,
                    "fitLevel": "근거 부족 비교 대상",
                    "strengths": ["소개문과 태그를 다시 확인해야 합니다."],
                    "risks": ["직접 매칭 근거가 없습니다."],
                    "evidenceSummary": ["참고 컨텍스트 원천은 많지만 직접 매칭은 없습니다."],
                },
            ],
            "limitations": [
                "직접 매칭이 0개라 점수는 예비 참고입니다.",
                "직접 매칭이 0개라 점수는 예비 참고입니다.",
                "각 국가 카드는 확인할 지점을 중심으로 읽어야 합니다.",
            ],
        }

        html = render_country_recommendation_html(result)

        self.assertIn("국가별 현지화 적합성 분석", html)
        self.assertIn("작품에서 잘 전달될 요소", html)
        self.assertIn("현지화에서 주의할 요소", html)
        self.assertIn("현지화 난이도", html)
        self.assertNotIn("추천 보류", html)
        self.assertNotIn("국가 우선순위 비교", html)
        self.assertNotIn("우선순위 88", html)
        self.assertNotIn("우선순위 76", html)
        self.assertEqual(html.count("직접 매칭이 0개라 점수는 예비 참고입니다."), 1)
        self.assertIn("이 결과는 입력 신호와 공개 관측 자료의 겹침을 비교한 참고 결과입니다.", html)
        self.assertNotIn("이 결과는 국가 추천이 아니라 현재 보유 자료에서 확인 가능한 관측 신호를 정리한 것입니다.", html)


if __name__ == "__main__":
    unittest.main()
