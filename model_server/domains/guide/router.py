"""Guide 도메인 라우터 (스텁).

TODO: 기존 api_server.py의 /api/guide 를 이식. 엔진은 domains/guide/ 에 일부 복사돼 있으나
service/schemas 배선 미완. 통합초안 backend/services/guide_service.py 참고.
"""
from __future__ import annotations

from fastapi import APIRouter

from . import service

router = APIRouter(prefix="/guide", tags=["guide"])


@router.get("/_status")
async def status() -> dict:
    return service.status()
