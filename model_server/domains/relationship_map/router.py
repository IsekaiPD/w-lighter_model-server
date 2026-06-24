"""Relationship map 라우터.

POST /api/v1/relationship-map : 캐릭터 설정집 → 인물 관계도 데이터(+옵션 HTML).
"""
from __future__ import annotations

from fastapi import APIRouter

from common.exceptions import EngineNotReady
from core.logging import get_logger
from . import service
from .schemas import RelationRequest, RelationResponse

logger = get_logger("relationship_map.router")
router = APIRouter(prefix="/relationship-map", tags=["relationship_map"])


@router.post("", response_model=RelationResponse)
def relationship_map(req: RelationRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        return service.generate_relationship(payload)
    except ValueError:
        raise  # 400 핸들러 (빈 캐릭터/limit 범위 등)
    except Exception as exc:  # noqa: BLE001 — OpenAI 키 미설정 등 -> 503
        logger.warning("relationship_map engine error: %r", exc)
        raise EngineNotReady(f"relationship_map engine error: {exc}") from exc


@router.get("/_status")
async def status() -> dict:
    return service.status()
