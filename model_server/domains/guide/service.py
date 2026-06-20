"""Guide 도메인 서비스 (스텁). TODO: 통합초안 backend/services/guide_service.guide() 이식."""
from __future__ import annotations


def status() -> dict:
    return {"domain": "guide", "status": "scaffold", "todo": "guide_service.guide() 이식 + schemas 배선"}
