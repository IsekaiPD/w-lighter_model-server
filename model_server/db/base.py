"""SQLAlchemy 선언적 베이스 + 공통 타임스탬프 믹스인.

컬럼/모델은 DB 종류와 무관하며 SQLite(로컬)·MySQL(배포)는 연결 URL로만 갈린다(`db/session.py`).
`func.now()`/`server_default`는 양쪽 모두에서 동작한다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 모델의 공통 베이스."""


class TimestampMixin:
    """created_at/updated_at. DB 서버 기본값(CURRENT_TIMESTAMP) 사용 → SQLite·MySQL 호환."""

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
