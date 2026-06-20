"""/api/v1 도메인 라우터 집계.

각 도메인 라우터를 방어적으로 마운트한다 — WIP 도메인(엔진 미완 등)이 import 실패해도
앱은 떠야 하므로 실패는 로그만 남기고 건너뛴다(스캐폴드 단계 정상 동작).
"""
from __future__ import annotations

import importlib

from fastapi import APIRouter

from core.logging import get_logger

logger = get_logger("api.v1")

api_router = APIRouter()

_DOMAINS = ["translation", "guide", "cover", "relationship_map", "character_extract"]

for _name in _DOMAINS:
    try:
        module = importlib.import_module(f"domains.{_name}.router")
        api_router.include_router(module.router)
        logger.info("mounted domain router: /%s", _name)
    except Exception as exc:  # noqa: BLE001 — WIP 도메인 import 실패는 graceful skip
        logger.warning("skip domain '%s' router (import failed): %r", _name, exc)
