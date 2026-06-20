"""용어집 저장소 서브패키지.

번역 파이프라인이 아닌 "저장소(repository)" 관심사라 최상위에서 이 하위 폴더로 분리했다.
- store      : 단일 테이블 glossary 모델 + 메모리 백엔드(기본)
- mysql_store: MySQL 백엔드(선택, PyMySQL 필요)

mysql_store 는 PyMySQL 의존이 있어 패키지 로드 시 자동 import 하지 않는다.
필요할 때 `from app.translation.glossary.mysql_store import MySQLGlossaryRepository` 로 직접 가져온다.
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
