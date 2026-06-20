"""DB 세션/엔진 — 포터블(SQLite 로컬 ↔ MySQL 배포는 연결 URL로만 전환).

연결 URL 결정 우선순위:
  1) settings.database_url (DATABASE_URL) — 있으면 그대로 사용 (예: mysql+pymysql://...).
  2) 없으면 로컬 SQLite 파일 폴백: sqlite:///<model_server>/wlighter_local.db

`content_store_backend`(=rdb면 RDB 사용)와는 독립적으로, 엔진은 lazy 싱글턴으로 생성한다.
MySQL 전환은 `.env`에 DATABASE_URL 한 줄만 넣으면 끝 — 모델/repository 코드는 불변.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from core.logging import get_logger

logger = get_logger("db.session")

# model_server/ 루트 (이 파일: model_server/db/session.py → parents[1]=model_server)
_MODEL_SERVER_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SQLITE_PATH = _MODEL_SERVER_ROOT / "wlighter_local.db"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


# 'rdb'로 취급하는 백엔드 값들 (memory만 비-RDB).
_RDB_BACKENDS = {"rdb", "sqlite", "mysql"}


def rdb_enabled() -> bool:
    """content_store_backend가 RDB 계열이면 True(=DB 영속화 활성)."""
    return settings.content_store_backend.strip().lower() in _RDB_BACKENDS


def resolve_database_url() -> str:
    """활성 연결 URL. database_url 우선, 없으면 로컬 SQLite 파일 폴백."""
    url = (settings.database_url or "").strip()
    if url:
        return url
    return f"sqlite:///{_DEFAULT_SQLITE_PATH.as_posix()}"


def get_engine() -> Engine:
    """프로세스 단일 엔진(lazy)."""
    global _engine, _SessionFactory
    if _engine is None:
        url = resolve_database_url()
        # SQLite는 다중 스레드(uvicorn) 접근 위해 check_same_thread=False 필요.
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
        _SessionFactory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
        logger.info("db engine ready: %s", _engine.url.render_as_string(hide_password=True))
    return _engine


def get_session() -> Session:
    """새 ORM 세션. 호출 측이 with/close 책임. (repository가 내부에서 사용)"""
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None
    return _SessionFactory()


def init_db() -> None:
    """테이블 생성(idempotent). 로컬 SQLite 부트스트랩용.

    프로덕션 MySQL은 스키마를 마이그레이션/외부에서 관리할 수 있으나, create_all은
    존재하는 테이블을 건너뛰므로 안전하다. rdb 비활성이면 no-op.
    """
    if not rdb_enabled():
        logger.info("init_db skipped (content_store_backend=memory)")
        return
    from .base import Base
    from . import models  # noqa: F401 — 모델 등록(테이블 메타데이터 채우기)

    Base.metadata.create_all(get_engine())
    logger.info("db tables ensured (create_all)")


def get_backend() -> str:
    """현재 활성 콘텐츠 저장소 백엔드(memory|rdb)."""
    return settings.content_store_backend
