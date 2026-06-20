"""FastAPI 의존성(Depends) 제공자.

지금은 설정 주입 위주. 무거운 파이프라인 싱글턴은 domains/translation/service.py 의
프로세스 캐시(get_translation_pipeline)가 담당하고, warm-up은 lifespan에서 트리거한다.
(TODO: 파이프라인 핸들을 app.state로 올려 라우터에 Depends 주입하는 형태로 확장 가능)
"""
from __future__ import annotations

from core.config import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()
