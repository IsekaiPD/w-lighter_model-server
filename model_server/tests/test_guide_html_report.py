from __future__ import annotations

import unittest

from model_server.domains.guide.agents.guide_writer import render_llm_html
from model_server.domains.guide.engine.recommendation import _html_report


class GuideHtmlReportTests(unittest.TestCase):
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
        self.assertIn('class="guide-report"', html)
        self.assertIn('class="guide-cover"', html)
        self.assertIn("핵심 판단", html)
        self.assertIn("바로 적용할 체크리스트", html)
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
            "marketInterpretation": ["시장 해석"],
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
        self.assertIn("가이드 요약", html)
        self.assertIn("바로 적용할 체크리스트", html)
        self.assertIn("시장 해석", html)


if __name__ == "__main__":
    unittest.main()
