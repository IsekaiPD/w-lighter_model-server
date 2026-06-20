"""FastAPI 진입점 — `uvicorn main:app` (model_server/ 안에서 실행).

도메인 주도 구조: health + /api/v1(도메인 라우터 집계) 마운트, lifespan에서 warm-up,
미들웨어(CORS)/예외 핸들러 등록.
"""
from __future__ import annotations

from fastapi import FastAPI

from api.v1.router import api_router
from common.exceptions import register_exception_handlers
from common.middleware import register_middleware
from core.config import settings
from core.lifespan import lifespan
from health.router import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(health_router)  # GET /health
    app.include_router(api_router, prefix=settings.api_v1_prefix)  # /api/v1/<domain>/...
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
