"""애플리케이션 lifespan — startup warm-up / shutdown.

무거운 객체(KURE 임베딩, 번역 파이프라인)는 startup에 1회 warm-up해 프로세스 캐시에 적재한다.
Qdrant/KURE 미준비여도 앱은 떠야 하므로 warm-up 실패는 로그만 남기고 계속한다. (기본 warmup_on_startup=False)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings
from core.logging import get_logger, setup_logging

logger = get_logger("lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("starting %s (mock=%s, qdrant_url=%s)", settings.app_name, settings.wlighter_mock_mode, settings.qdrant_url or "(embedded path TODO)")
    app.state.warm = {"translation": False}

    # DB 테이블 보장(rdb일 때만; memory면 no-op). 로컬 SQLite 부트스트랩.
    try:
        from db.session import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001 — DB 미준비여도 앱은 뜬다
        logger.warning("init_db skipped/failed: %r", exc)

    if settings.warmup_on_startup:
        try:
            from domains.translation import service as translation_service

            translation_service.warmup()
            app.state.warm["translation"] = True
            logger.info("translation pipeline warm-up done")
        except Exception as exc:  # noqa: BLE001 — warm-up 실패해도 앱은 뜬다(엔진 미준비 정상)
            logger.warning("translation warm-up skipped/failed: %r", exc)
    else:
        logger.info("warm-up off (set WARMUP_ON_STARTUP=1 to enable)")

    yield

    logger.info("shutting down %s", settings.app_name)
