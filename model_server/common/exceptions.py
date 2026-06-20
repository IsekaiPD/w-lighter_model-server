"""도메인 에러 → HTTP 응답 매핑 + 핸들러 등록."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from domains.translation.infra.locale_utils import LocaleNormalizationError


class EngineNotReady(Exception):
    """엔진(파이프라인)이 아직 준비되지 않음 — Qdrant(self-host)/KURE/데이터 미설정.

    구성도/스캐폴드 단계에서는 정상. 503으로 응답한다.
    """

    def __init__(self, message: str = "Model engine is not ready (Qdrant/KURE not configured yet).") -> None:
        self.message = message
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LocaleNormalizationError)
    async def _locale_error(_: Request, exc: LocaleNormalizationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "errorCode": exc.error_code, "message": exc.message})

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "errorCode": "invalid_request", "message": str(exc)})

    @app.exception_handler(EngineNotReady)
    async def _engine_not_ready(_: Request, exc: EngineNotReady) -> JSONResponse:
        return JSONResponse(status_code=503, content={"ok": False, "errorCode": "engine_not_ready", "message": exc.message})
