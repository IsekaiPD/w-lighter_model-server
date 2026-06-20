from __future__ import annotations

import os
from pathlib import Path

# 데이터 자산은 guide 도메인 내부(domains/guide/data/)에 둔다. parents[0] = domains/guide.
ROOT = Path(__file__).resolve().parents[0]
DATA_DIR = ROOT / "data"

# 텍스트(채팅) 모델 — 도메인 공통 단일 노브(WLIGHTER_TEXT_MODEL).
TEXT_MODEL = os.getenv("WLIGHTER_TEXT_MODEL", "gpt-5.4-mini")
