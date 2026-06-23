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
        self.assertIn("시장 해석", html)

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
            "culturalNotes": ["문화 메모"],
            "platformPolicyChecks": ["정책 체크"],
            "marketTagGuidance": ["태그 가이드"],
            "evidenceExplanation": ["증거 설명"],
            "limitations": ["한계"],
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
        self.assertIn("출시 전 체크리스트", html)
        self.assertIn("시장 적합도 해석", html)
        self.assertIn("번역·표현 주의점", html)
        self.assertIn("플랫폼 게시 전 체크", html)
        self.assertIn("판단 근거", html)
        self.assertIn("확인 필요 사항", html)
        self.assertIn("작품을 현재 방향 그대로 두고", html)
        self.assertIn("작품과 맞닿는 시장 신호", html)
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
            "culturalNotes": [],
            "platformPolicyChecks": [],
            "marketTagGuidance": [],
            "evidenceExplanation": [],
            "limitations": [],
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

        self.assertIn("최근 플랫폼 참고 자료", html)
        self.assertIn("플랫폼 기준", html)
        self.assertIn("주요 플랫폼", html)
        self.assertIn("kakuyomu.jp", html)
        self.assertIn("https://kakuyomu.jp/help", html)
        self.assertIn(".mini-card a,.mini-card h3,.mini-card small", html)
        self.assertIn("출처 열기", html)
        self.assertIn("본문 가이드를 작성할 때 확인한 공개 자료", html)
        self.assertNotIn("LIVE MARKET EVIDENCE", html)
        self.assertNotIn("원문 스니펫", html)
        self.assertNotIn("Kakuyomu guide", html)
        self.assertNotIn("Platform rule summary", html)
        self.assertNotIn("countryEvidence", html)
        self.assertLess(html.index("핵심 전달 전략"), html.index("최근 플랫폼 참고 자료"))

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
        self.assertIn("국가 적합도 비교", html)
        self.assertIn("작품 특성과 국가별 전달 환경을 비교한 결과입니다.", html)
        self.assertIn("추천은 선택 전 비교 결과입니다.", html)


if __name__ == "__main__":
    unittest.main()
