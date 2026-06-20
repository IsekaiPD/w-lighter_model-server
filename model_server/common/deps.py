"""FastAPI 의존성(Depends) 제공자.

설정 주입 담당. 무거운 파이프라인 싱글턴은 domains/translation/service.py 의
프로세스 캐시(get_translation_pipeline)가 맡고, warm-up은 lifespan에서 트리거한다.
"""
from __future__ import annotations

from core.config import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()
