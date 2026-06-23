from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

# The ASGI app runs with model_server as its import root (core, db, common).
MODEL_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(MODEL_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_SERVER_ROOT))

from model_server.domains.guide import service


class GuideServiceTests(unittest.TestCase):
    def test_country_recommendation_is_not_persisted_without_a_target_country(self) -> None:
        generated = {
            "reportMode": "synopsis_country_recommendation",
            "requiresSelection": False,
            "htmlReport": "<!doctype html><html></html>",
        }
        with (
            patch("model_server.domains.guide.service.generate_guide", return_value=generated),
            patch("model_server.domains.guide.service.db_repo.get_work", return_value={"title": "작품"}),
            patch("model_server.domains.guide.service.db_repo.save_localization_guide") as save_guide,
        ):
            result = service.generate({"workId": 42, "synopsis": "시놉시스"})

        self.assertIs(result, generated)
        save_guide.assert_not_called()

    def test_country_genre_guide_is_persisted_as_html(self) -> None:
        generated = {
            "reportMode": "country_genre_guide",
            "requiresSelection": False,
            "targetCountry": "JP",
            "htmlReport": "<!doctype html><html><body>guide</body></html>",
        }
        with (
            patch("model_server.domains.guide.service.generate_guide", return_value=generated),
            patch("model_server.domains.guide.service.db_repo.get_work", return_value={"title": "작품"}),
            patch(
                "model_server.domains.guide.service.db_repo.save_localization_guide",
                return_value={"saved": True, "guide_id": 7},
            ) as save_guide,
        ):
            result = service.generate({"workId": 42, "genre": "로맨스", "targetCountry": "JP"})

        self.assertEqual(result["persistedGuide"], {"saved": True, "guide_id": 7})
        self.assertEqual(save_guide.call_args.kwargs["guide_content"], generated["htmlReport"])


if __name__ == "__main__":
    unittest.main()
