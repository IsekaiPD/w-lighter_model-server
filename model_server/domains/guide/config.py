from __future__ import annotations

import os
from pathlib import Path

# 데이터 자산을 guide 도메인 내부(domains/guide/data/)에 자급자족으로 둔다.
# parents[0] = domains/guide. 엔진들은 ROOT / "data" / {platform_observation, platform_rules} / ... 를 읽는다.
ROOT = Path(__file__).resolve().parents[0]
DATA_DIR = ROOT / "data"

# 텍스트(채팅) 모델 — 다른 도메인과 동일한 단일 노브(WLIGHTER_TEXT_MODEL, 기본 gpt-5.4-mini).
TEXT_MODEL = os.getenv("WLIGHTER_TEXT_MODEL", "gpt-5.4-mini")
