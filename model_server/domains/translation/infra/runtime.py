from __future__ import annotations

import os


TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def is_mock_mode() -> bool:
    """서비스 계층이 mock(가짜) 어댑터를 쓸지 여부.

    기본값은 False(실제 모드). mock으로 돌리려면 WLIGHTER_MOCK_MODE=true를 명시한다.
    """
    return os.getenv("WLIGHTER_MOCK_MODE", "false").lower() in TRUE_VALUES
