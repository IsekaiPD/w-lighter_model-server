"""저장소 인터페이스 (스텁).

TODO: glossary hydrate / translation 결과 저장 / works·episodes CRUD.
기존 backend/services/{glossary_service, content_service} + backend/store 로직 이관 예정.
지금은 hydrate가 None을 반환(요청 payload의 workMemory만 사용)하도록 graceful.
"""
from __future__ import annotations

from typing import Any


def hydrate_work_memory(work_id: str, country: str) -> Any | None:  # noqa: ARG001
    """승인 glossary로 WorkMemory를 hydrate. TODO: RDB 연동. 현재는 None."""
    return None


def save_translation_result(payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    """번역 결과 영속화. TODO: RDB 저장. 현재는 no-op."""
    return {"saved": False, "reason": "persistence_not_implemented"}
