"""Translation 도메인 라우터 — /translate, /inspect-chat 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter

from common.exceptions import EngineNotReady
from core.logging import get_logger
from domains.translation import service
from domains.translation.infra.locale_utils import LocaleNormalizationError
from domains.translation.schemas import (
    InspectChatRequest,
    InspectChatResponse,
    TranslateRequest,
    TranslateResponse,
)

logger = get_logger("translation.router")
router = APIRouter(prefix="/translation", tags=["translation"])


@router.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        return service.translate(payload)
    except (LocaleNormalizationError, ValueError):
        raise  # 400 핸들러가 처리
    except Exception as exc:  # noqa: BLE001 — 엔진(qdrant/KURE/openai) 미준비 등 -> 503
        logger.warning("translate engine error: %r", exc)
        raise EngineNotReady(f"translation engine error: {exc}") from exc


@router.post("/inspect-chat", response_model=InspectChatResponse)
def inspect_chat(req: InspectChatRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    try:
        return service.inspect_chat(payload)
    except (LocaleNormalizationError, ValueError):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("inspect_chat engine error: %r", exc)
        raise EngineNotReady(f"inspect-chat engine error: {exc}") from exc
