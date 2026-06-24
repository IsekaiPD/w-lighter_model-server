"""Guide 도메인 라우터.

POST /api/v1/guide : 작품 정보 → 현지화 가이드(시장 트렌드·컨텍스트팩·정책 유의사항).
"""
from __future__ import annotations

from fastapi import APIRouter

from common.exceptions import EngineNotReady
from core.logging import get_logger
from . import service
from .schemas import GuideRequest, GuideResponse

logger = get_logger("guide.router")
router = APIRouter(prefix="/guide", tags=["guide"])


@router.post("", response_model=GuideResponse)
def guide(req: GuideRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        return service.generate(payload)
    except ValueError:
        raise  # 400 핸들러가 처리
    except Exception as exc:  # noqa: BLE001 — 데이터/LLM 미준비 등 -> 503
        logger.warning("guide engine error: %r", exc)
        raise EngineNotReady(f"guide engine error: {exc}") from exc


@router.get("/_status")
async def status() -> dict:
    return service.status()
