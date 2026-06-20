"""용어집 저장소 서브패키지.

- store      : 단일 테이블 glossary 모델 + 메모리 백엔드(기본)
- mysql_store: MySQL 백엔드(선택, PyMySQL 필요)

mysql_store 는 PyMySQL 의존이 있어 패키지 로드 시 자동 import 하지 않는다 — 필요할 때 직접 가져온다.
"""
from __future__ import annotations

from .store import (
    DEFAULT_CATEGORY,
    GLOSSARY_CATEGORIES,
    GlossaryEntryRecord,
    GlossaryRepository,
    InMemoryGlossaryRepository,
    default_glossary_repository,
    glossary_record_to_work_memory_entry,
    hydrate_work_memory_from_records,
    is_contextual_reference,
    normalize_category,
)
from ..engine.literary_package import GlossaryEntry, WorkMemory

__all__ = [
    "DEFAULT_CATEGORY",
    "GLOSSARY_CATEGORIES",
    "GlossaryEntry",
    "GlossaryEntryRecord",
    "GlossaryRepository",
    "InMemoryGlossaryRepository",
    "WorkMemory",
    "default_glossary_repository",
    "glossary_record_to_work_memory_entry",
    "hydrate_work_memory_from_records",
    "is_contextual_reference",
    "normalize_category",
]
