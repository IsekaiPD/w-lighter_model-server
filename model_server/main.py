"""FastAPI 진입점 — `uvicorn main:app` (model_server/ 안에서 실행).

도메인 주도 구조: health + /api/v1(도메인 라우터 집계) 마운트, lifespan에서 warm-up,
미들웨어(CORS)/예외 핸들러 등록.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.v1.router import api_router
from common.exceptions import register_exception_handlers
from common.middleware import register_middleware
from core.config import settings
from core.lifespan import lifespan
from health.router import router as health_router

_MODEL_SERVER_ROOT = Path(__file__).resolve().parent
_GENERATED_DIR = _MODEL_SERVER_ROOT / "generated"


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(health_router)  # GET /health
    app.include_router(api_router, prefix=settings.api_v1_prefix)  # /api/v1/<domain>/...
    # 표지 생성 결과를 파일로 저장했을 때 covers.cover_url=/generated/covers/... 로 조회 가능하게 한다.
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/generated", StaticFiles(directory=str(_GENERATED_DIR)), name="generated")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
