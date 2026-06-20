from __future__ import annotations

import os


TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def is_mock_mode() -> bool:
    """서비스 계층이 mock(가짜) 어댑터를 쓸지 여부.

    기본값은 False(실제 모드) — PipelineConfig(mock=False)와 동일하게 통일됨.
    mock 으로 돌리려면 환경변수 WLIGHTER_MOCK_MODE=true 를 명시적으로 설정한다.
    """
    return os.getenv("WLIGHTER_MOCK_MODE", "false").lower() in TRUE_VALUES
