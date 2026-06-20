from __future__ import annotations

import os
from functools import lru_cache


def load_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


@lru_cache(maxsize=1)
def get_openai_client():
    api_key = load_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required unless mock=True")

    from openai import OpenAI

    return OpenAI(api_key=api_key)
