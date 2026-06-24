"""Character extract 라우터.

POST /api/v1/character-extract : 시놉시스 → 등장인물 목록(이름·역할·외형·관계 등).
"""
from __future__ import annotations

from fastapi import APIRouter

from common.exceptions import EngineNotReady
from core.logging import get_logger
from . import service
from .schemas import CharacterExtractRequest, CharacterExtractResponse

logger = get_logger("character_extract.router")
router = APIRouter(prefix="/character-extract", tags=["character_extract"])


@router.post("", response_model=CharacterExtractResponse)
def character_extract(req: CharacterExtractRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        return service.extract(payload)
    except ValueError:
        raise  # 400 핸들러 (빈 시놉시스/limit 범위 등)
    except Exception as exc:  # noqa: BLE001 — OpenAI 키 미설정 등 -> 503
        logger.warning("character_extract engine error: %r", exc)
        raise EngineNotReady(f"character_extract engine error: {exc}") from exc


@router.get("/_status")
async def status() -> dict:
    return service.status()
