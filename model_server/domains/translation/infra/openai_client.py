from __future__ import annotations

import os
from functools import lru_cache


def load_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@lru_cache(maxsize=1)
def get_openai_client():
    api_key = load_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required unless mock=True")

    from openai import OpenAI

    # OpenAI SDK 내장 재시도 = 429/408/409/5xx/연결오류에 **지수 백오프**(+`Retry-After` 헤더 존중, 지터).
    # 손수 만든 루프보다 견고하다. 번역 에이전트 7종이 전부 이 클라이언트를 거치므로, 여기 한 곳이
    # 모든 LLM 호출의 단일 레이트리밋 방어 지점이 된다. (서버 전체 동시호출 캡 = §방법3 전역 세마포어, 후속.)
    return OpenAI(
        api_key=api_key,
        max_retries=_int_env("WLIGHTER_OPENAI_MAX_RETRIES", 5),
        timeout=_float_env("WLIGHTER_OPENAI_TIMEOUT", 120.0),  # 호출 1건당 상한(파이프라인 전체 아님)
    )
