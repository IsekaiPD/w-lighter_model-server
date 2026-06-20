from __future__ import annotations

from pathlib import Path

# 데이터 자산을 guide 도메인 내부(domains/guide/data/)에 자급자족으로 둔다.
# parents[0] = domains/guide. 엔진들은 ROOT / "data" / {platform_observation, platform_rules} / ... 를 읽는다.
ROOT = Path(__file__).resolve().parents[0]
DATA_DIR = ROOT / "data"
