"""DB 모델 — ERD(`project_docs/ERD_planning.txt`) 충실 매핑, 포터블(SQLite↔MySQL).

모델서버 소유 테이블만 정의한다(works/episodes/characters/translation_results).
USERS·PAYMENTS·PLAN·CREDITTRANSACTION 등 결제/계정 테이블은 WEB(Django) 소유라 여기서 정의하지 않는다.
그래서 `works.user_id`는 cross-boundary FK(→USERS)지만 여기선 **제약 없는 INT**로 둔다
(로컬 SQLite에 USERS 테이블이 없어도 동작; 공유 MySQL에선 실제 FK가 존재).

glossary 테이블은 의도적으로 제외 — 기존 `domains/translation/glossary/`에 영속화 추상화
(InMemory/MySQL repository + WorkMemory 변환)가 이미 있고, ERD의 컬럼명(original_word/
translated_word/glossary_type)과 기존 코드(source/target/category)가 **충돌**하기 때문이다.
정렬 결정 전까지 새 테이블로 굳히지 않는다(TODO #2 참고). hydrate는 기존 repo에 위임한다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .base import Base, TimestampMixin


class Work(Base, TimestampMixin):
    """ERD WORKS — 작품."""

    __tablename__ = "works"

    work_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # USERS는 WEB 소유 → FK 제약 없이 단순 INT(로컬 SQLite 호환). 미상이면 NULL 허용.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    pen_name: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    genre: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    synopsis: Mapped[str | None] = mapped_column(String(10000), nullable=True)

    episodes: Mapped[list["Episode"]] = relationship(back_populates="work", cascade="all, delete-orphan")
    characters: Mapped[list["Character"]] = relationship(back_populates="work", cascade="all, delete-orphan")


class Episode(Base, TimestampMixin):
    """ERD EPISODES — 회차."""

    __tablename__ = "episodes"

    episode_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.work_id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    original_text: Mapped[str] = mapped_column(String(8000), nullable=False, default="")

    work: Mapped["Work"] = relationship(back_populates="episodes")
    translation_results: Mapped[list["TranslationResult"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )


class Character(Base, TimestampMixin):
    """ERD CHARACTERS — 등장인물. character_extract 결과 적재 대상.

    매핑(extraction → 컬럼): char_name→char_name, age→age, role→role(ERD VARCHAR(5)),
    gender→gender(M/F/U 정규화), relationships→relationships, appearance→`apperance`(ERD 오타 그대로),
    detail_setting→detail_setting. extraction의 `profile_label`은 ERD 컬럼이 없어 미저장.
    """

    __tablename__ = "characters"

    character_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.work_id"), nullable=False, index=True)
    char_name: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    gender: Mapped[str | None] = mapped_column(String(5), nullable=True)  # CHECK: M/F/U
    age: Mapped[str | None] = mapped_column(String(10), nullable=True)
    role: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # ERD 컬럼명은 'apperance'(오타). 물리 컬럼은 ERD와 동일하게, 파이썬 속성만 appearance로 노출.
    appearance: Mapped[str | None] = mapped_column("apperance", String(300), nullable=True)
    relationships: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail_setting: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    work: Mapped["Work"] = relationship(back_populates="characters")


class TranslationResult(Base):
    """ERD TRANSLATIONRESULTS — 번역 결과(버전은 translation_id+created_at로 구분).

    ERD에 updated_at 없음 → TimestampMixin 대신 created_at만 둔다.
    """

    __tablename__ = "translation_results"

    translation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.episode_id"), nullable=False, index=True)
    target_country: Mapped[str] = mapped_column(String(2), nullable=False)  # US/CN/JP/TH
    translated_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    glossary_can: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    annotation_can: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    inspection_report: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    episode: Mapped["Episode"] = relationship(back_populates="translation_results")
