from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from model_server.domains.guide.guide_pipeline import _attach_context_pack_briefing


class GuideContextPackBriefingTests(unittest.TestCase):
    def test_context_pack_internal_diagnostics_expose_source_match_and_injected_state(self) -> None:
        payload = {
            "title": "작품",
            "genre": "판타지",
            "synopsis": "A story with a magical academy.",
            "targetCountry": "JP",
            "titleElements": ["academy"],
            "comparableSignals": ["magic"],
            "declaredSignals": ["magic"],
            "includeContextPack": True,
        }
        result = {"title": "작품", "genre": "판타지"}
        report = {
            "ui_briefing_payload": {"headline_market_labels": [{"label_ko": "마법", "count": 3, "share": 0.3}]},
            "evidence": {
                "target_market_ko": "일본",
                "context_record_count": 12,
                "platforms": ["A", "B"],
                "signal_types": ["hot"],
                "summary": {"declared_signal_count": 1, "observed_signal_count": 2},
                "data_limits": ["limit"],
                "direct_signal_rows": [
                    {
                        "work_signal": "academy",
                        "direct_observation": "observed",
                        "match_status": "direct",
                        "observed_label": "academy",
                        "candidate_observations": [{"label_ko": "학원"}],
                        "aggregate": {"count": 3},
                        "platform_balanced": {"count": 3},
                    },
                    {
                        "work_signal": "missing",
                        "direct_observation": "unobserved",
                        "match_status": "missing",
                        "observed_label": None,
                        "candidate_observations": [],
                        "aggregate": None,
                        "platform_balanced": None,
                    },
                ],
            },
        }
        with patch.dict(os.environ, {"WLIGHTER_GUIDE_INCLUDE_INTERNAL": "true"}), patch(
            "model_server.domains.guide.guide_pipeline.inspect_context_pack_source",
            return_value={
                "resolvedTargetMarket": "japan",
                "contextPackSourceFound": True,
                "contextPackSourceRecordCount": 12,
                "contextPackSkipReason": None,
            },
        ), patch(
            "model_server.domains.guide.guide_pipeline.build_context_pack_overlap_report",
            return_value=report,
        ):
            enriched = _attach_context_pack_briefing(payload, result)

        self.assertIn("contextPackBriefing", enriched)
        self.assertIn("contextPackEvidence", enriched)
        self.assertEqual(enriched["contextPackSourceRecordCount"], 12)
        self.assertEqual(enriched["contextPackMatchedRecordCount"], 1)
        self.assertEqual(enriched["contextPackInjectedRecordCount"], 1)
        self.assertGreater(enriched["contextPackInjectedEvidenceBytes"], 0)
        self.assertEqual(enriched["contextPackSkipReason"], "injected")

    def test_include_internal_false_hides_internal_diagnostics(self) -> None:
        payload = {
            "title": "작품",
            "genre": "판타지",
            "synopsis": "A story with a magical academy.",
            "targetCountry": "JP",
            "titleElements": ["academy"],
            "comparableSignals": ["magic"],
            "declaredSignals": ["magic"],
            "includeContextPack": True,
        }
        result = {"title": "작품", "genre": "판타지"}
        report = {
            "ui_briefing_payload": {"headline_market_labels": [{"label_ko": "마법", "count": 3, "share": 0.3}]},
            "evidence": {
                "target_market_ko": "일본",
                "context_record_count": 12,
                "platforms": ["A", "B"],
                "signal_types": ["hot"],
                "summary": {"declared_signal_count": 1, "observed_signal_count": 2},
                "data_limits": ["limit"],
                "direct_signal_rows": [],
            },
        }
        with patch.dict(os.environ, {"WLIGHTER_GUIDE_INCLUDE_INTERNAL": "false"}), patch(
            "model_server.domains.guide.guide_pipeline.inspect_context_pack_source",
            return_value={
                "resolvedTargetMarket": "japan",
                "contextPackSourceFound": True,
                "contextPackSourceRecordCount": 12,
                "contextPackSkipReason": None,
            },
        ), patch(
            "model_server.domains.guide.guide_pipeline.build_context_pack_overlap_report",
            return_value=report,
        ):
            enriched = _attach_context_pack_briefing(payload, result)

        self.assertIn("contextPackBriefing", enriched)
        self.assertIn("contextPackEvidence", enriched)
        self.assertNotIn("contextPackSourceFound", enriched)
        self.assertNotIn("contextPackMatchedRecordCount", enriched)
        self.assertNotIn("contextPackInjectedEvidenceBytes", enriched)


if __name__ == "__main__":
    unittest.main()
