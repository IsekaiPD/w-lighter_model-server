"""Cover 도메인 라우터.

POST /api/v1/cover : 작품·캐릭터 정보 → 표지 이미지(base64). dryRun=true면 최종 프롬프트만.
"""
from __future__ import annotations

from fastapi import APIRouter

from common.exceptions import EngineNotReady
from core.logging import get_logger
from . import service
from .schemas import CoverRequest, CoverResponse

logger = get_logger("cover.router")
router = APIRouter(prefix="/cover", tags=["cover"])


@router.post("", response_model=CoverResponse)
def cover(req: CoverRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        return service.generate_cover(payload)
    except ValueError:
        raise  # 400 핸들러 (프롬프트 검증 실패 등)
    except Exception as exc:  # noqa: BLE001 — OpenAI 키 미설정 등 -> 503
        logger.warning("cover engine error: %r", exc)
        raise EngineNotReady(f"cover engine error: {exc}") from exc


@router.get("/_status")
async def status() -> dict:
    return service.status()
