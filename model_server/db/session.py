"""DB 세션 (스텁).

TODO: 실제 RDB 연결. 기존 backend/store/memory_store + mysql_content_store 로직을
여기 repository 패턴으로 이관 예정. 지금은 구성도/스캐폴드 단계라 메모리 폴백.
"""
from __future__ import annotations

from core.config import settings


def get_backend() -> str:
    """현재 활성 저장소 백엔드(memory|mysql). 실제 세션은 TODO."""
    return settings.content_store_backend
