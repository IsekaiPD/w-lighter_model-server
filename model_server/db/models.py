"""DB 모델 — ERD(`project_docs/ERD_planning.txt`) 매핑, 포터블(SQLite↔MySQL).

모델서버 소유 테이블을 정의한다(works/episodes/characters/translation_results + relation_maps/localization_guides/covers/chat_messages).
USERS·PAYMENTS·PLAN·CREDITTRANSACTION 등 결제/계정 테이블은 WEB(Django) 소유라 제외한다.
그래서 `works.user_id`는 cross-boundary FK(→USERS)지만 여기선 제약 없는 INT로 둔다
(로컬 SQLite에 USERS 테이블이 없어도 동작; 공유 MySQL에선 실제 FK가 존재).

glossary 테이블은 의도적으로 제외 — `domains/translation/glossary/`가 자체 영속화 추상화로 소유한다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, String, Text, func
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
    relation_maps: Mapped[list["RelationMap"]] = relationship(back_populates="work", cascade="all, delete-orphan")
    localization_guides: Mapped[list["LocalizationGuide"]] = relationship(back_populates="work", cascade="all, delete-orphan")
    covers: Mapped[list["Cover"]] = relationship(back_populates="work", cascade="all, delete-orphan")


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

    매핑(extraction → 컬럼): gender는 한글 값으로 정규화한다.
    profile_label은 관계도 카드 표시용 별도 컬럼으로 저장한다.
    """

    __tablename__ = "characters"

    character_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.work_id"), nullable=False, index=True)
    char_name: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    gender: Mapped[str | None] = mapped_column(String(5), nullable=True)  # CHECK: M/F/U
    age: Mapped[str | None] = mapped_column(String(10), nullable=True)
    role: Mapped[str | None] = mapped_column(String(5), nullable=True)
    profile_label: Mapped[str | None] = mapped_column(String(80), nullable=True, default="")
    appearance: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
    target_country: Mapped[str] = mapped_column(CHAR(2), nullable=False)  # ERD CHAR(2): US/CN/JP/TH
    translated_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    glossary_can: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    annotation_can: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    inspection_report: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    episode: Mapped["Episode"] = relationship(back_populates="translation_results")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="translation", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """ERD CHAT_MESSAGES — 번역 검수 챗봇 대화 로그."""

    __tablename__ = "chat_messages"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    translation_id: Mapped[int] = mapped_column(ForeignKey("translation_results.translation_id"), nullable=False, index=True)
    sender_type: Mapped[str] = mapped_column(String(10), nullable=False)  # USER / ASSISTANT
    message_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    translation: Mapped["TranslationResult"] = relationship(back_populates="chat_messages")


class LocalizationGuide(Base):
    """ERD LOCALIZATION_GUIDES — 현지화 가이드 결과 저장."""

    __tablename__ = "localization_guides"

    guide_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.work_id"), nullable=False, index=True)
    target_country: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    guide_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    work: Mapped["Work"] = relationship(back_populates="localization_guides")


class Cover(Base):
    """ERD COVERS — 표지 이미지 URL/경로 저장."""

    __tablename__ = "covers"

    cover_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.work_id"), nullable=False, index=True)
    cover_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_country: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    main_cover_yn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    work: Mapped["Work"] = relationship(back_populates="covers")


class RelationMap(Base):
    """ERD RELATION_MAPS — HTML/JSON 관계도 결과 저장."""

    __tablename__ = "relation_maps"

    map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.work_id"), nullable=False, index=True)
    map_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    work: Mapped["Work"] = relationship(back_populates="relation_maps")
