from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from ..engine.literary_package import GlossaryEntry, WorkMemory
from ..infra.locale_utils import country_to_locale, normalize_target_country

# Single-table glossary model: a flat list of translation rules. Each row maps
# one source term to one target term for a given work + target country. Aliases
# are their own rows (one per surface form) — no separate alias table, no
# priority flag, no forbidden-term table. Every stored row is an enforced rule.
GLOSSARY_CATEGORIES = {"person", "place", "organization"}
DEFAULT_CATEGORY = "person"

_CONTEXTUAL_REFERENCES_KO = {
    "그",
    "그녀",
    "남자",
    "여자",
    "저 남자",
    "그 남자",
    "이 남자",
    "저 여자",
    "그 여자",
    "이 여자",
    "그분",
    "이분",
    "저분",
    "이 사람",
    "저 사람",
    "그 사람",
    "그 자",
    "저 자",
    "이 자",
}
_KOREAN_REFERENCE_PARTICLES = ("은", "는", "이", "가", "을", "를", "에게", "한테", "께", "도", "만", "와", "과", "의")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def is_contextual_reference(text: str) -> bool:
    """Return True for clear Korean pronouns/deictic references.

    These references are intentionally rejected as glossary sources because
    their referent can change by episode or scene.
    """

    normalized = " ".join(_clean(text).split())
    if normalized in _CONTEXTUAL_REFERENCES_KO:
        return True
    for particle in _KOREAN_REFERENCE_PARTICLES:
        if normalized.endswith(particle) and normalized[: -len(particle)] in _CONTEXTUAL_REFERENCES_KO:
            return True
    return False


def normalize_category(value: Any) -> str:
    category = _clean(value).lower()
    return category if category in GLOSSARY_CATEGORIES else DEFAULT_CATEGORY


@dataclass(slots=True)
class GlossaryEntryRecord:
    """ERD GLOSSARY 테이블 행의 1:1 거울. 컬럼명은 ERD(`project_docs/ERD_planning.txt`)를 정본으로 따른다.

    엔진 도메인 객체(`GlossaryEntry`)와는 ``glossary_record_to_work_memory_entry`` 가 변환해 분리한다.
    """

    glossary_id: int | None
    work_id: str
    target_country: str
    original_word: str
    translated_word: str
    glossary_type: str = DEFAULT_CATEGORY
    memo: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


class GlossaryRepository(Protocol):
    def upsert_entry(
        self,
        *,
        work_id: str,
        target_country: str,
        original_word: str,
        translated_word: str,
        glossary_type: str = DEFAULT_CATEGORY,
        memo: str | None = None,
    ) -> GlossaryEntryRecord:
        ...

    def list_glossary(self, work_id: str, target_country: str, *, limit: int = 50) -> list[GlossaryEntryRecord]:
        ...

    def get_entry(self, entry_id: int) -> GlossaryEntryRecord | None:
        ...

    def delete_entry(self, entry_id: int) -> bool:
        ...

    def hydrate_work_memory(self, work_id: str, target_country: str, *, limit: int = 0) -> WorkMemory | None:
        ...


def glossary_record_to_work_memory_entry(record: GlossaryEntryRecord) -> GlossaryEntry:
    """저장층(ERD 컬럼) → 엔진 GlossaryEntry(도메인 언어) 변환.

    original_word→source, translated_word→target, glossary_type→category, memo→note.
    모든 저장 행은 강제 규칙이라 ``priority``는 항상 ``"hard"``. aliases는 별도 행이라 비움.
    """

    return GlossaryEntry(
        source=record.original_word,
        target=record.translated_word,
        category=record.glossary_type if record.glossary_type in GLOSSARY_CATEGORIES else DEFAULT_CATEGORY,
        priority="hard",
        aliases=[],
        forbidden=[],
        note=record.memo or None,
    )


def hydrate_work_memory_from_records(
    work_id: str,
    target_country: str,
    records: list[GlossaryEntryRecord],
    *,
    limit: int = 0,
) -> WorkMemory | None:
    """Build engine WorkMemory from stored rows.

    This is the storage/engine boundary: rows are stored by 2-letter country
    code (JP/US/CN/TH) but the engine expects an internal locale (ko_ja, ...),
    so the country is converted here with ``country_to_locale``.
    """

    selected = records if limit <= 0 else records[:limit]  # limit<=0 → 무제한
    if not selected:
        return None
    return WorkMemory(
        workId=_clean(work_id) or None,
        targetLocale=country_to_locale(target_country),
        approvedGlossary=[glossary_record_to_work_memory_entry(row) for row in selected],
        styleMemory={},
        previousSummary=None,
    )


class InMemoryGlossaryRepository:
    """Process-local glossary repository with a single flat entry table."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, GlossaryEntryRecord] = {}
        self._next_entry_id = 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._next_entry_id = 1

    def upsert_entry(
        self,
        *,
        work_id: str,
        target_country: str,
        original_word: str,
        translated_word: str,
        glossary_type: str = DEFAULT_CATEGORY,
        memo: str | None = None,
    ) -> GlossaryEntryRecord:
        work_id = _clean(work_id)
        target_country = normalize_target_country(target_country) or ""
        original_word = _clean(original_word)[:30]  # ERD VARCHAR(30)
        translated_word = _clean(translated_word)[:30]  # ERD VARCHAR(30)
        glossary_type = normalize_category(glossary_type)
        memo_value = _clean(memo)[:500] or None  # ERD memo VARCHAR(500)
        if not work_id or not target_country or not original_word or not translated_word:
            raise ValueError("work_id, target_country, original_word, and translated_word are required")
        if is_contextual_reference(original_word):
            raise ValueError("original_word is a contextual reference and should not be persisted as a glossary entry")
        with self._lock:
            existing = next(
                (
                    row
                    for row in self._entries.values()
                    if row.work_id == work_id
                    and row.target_country == target_country
                    and row.original_word == original_word
                    and row.glossary_type == glossary_type
                ),
                None,
            )
            now = _now_iso()
            if existing is None:
                entry_id = self._next_entry_id
                self._next_entry_id += 1
                existing = GlossaryEntryRecord(
                    glossary_id=entry_id,
                    work_id=work_id,
                    target_country=target_country,
                    original_word=original_word,
                    translated_word=translated_word,
                    glossary_type=glossary_type,
                    memo=memo_value,
                    created_at=now,
                    updated_at=now,
                )
                self._entries[entry_id] = existing
            else:
                existing.translated_word = translated_word
                if memo is not None:
                    existing.memo = memo_value
                existing.updated_at = now
            return self._clone_entry(existing)

    def list_glossary(self, work_id: str, target_country: str, *, limit: int = 50) -> list[GlossaryEntryRecord]:
        work_id = _clean(work_id)
        target_country = normalize_target_country(target_country) or ""
        with self._lock:
            rows = [
                self._clone_entry(row)
                for row in self._entries.values()
                if row.work_id == work_id and row.target_country == target_country
            ]
        rows.sort(key=lambda row: (row.original_word.casefold(), row.glossary_type))
        return rows if limit <= 0 else rows[:limit]  # limit<=0 → 무제한(상한 제거)

    def get_entry(self, entry_id: int) -> GlossaryEntryRecord | None:
        with self._lock:
            row = self._entries.get(int(entry_id))
            return self._clone_entry(row) if row is not None else None

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock:
            return self._entries.pop(int(entry_id), None) is not None

    def hydrate_work_memory(self, work_id: str, target_country: str, *, limit: int = 0) -> WorkMemory | None:
        records = self.list_glossary(work_id, target_country, limit=limit)
        return hydrate_work_memory_from_records(work_id, target_country, records, limit=limit)

    @staticmethod
    def _clone_entry(row: GlossaryEntryRecord) -> GlossaryEntryRecord:
        return GlossaryEntryRecord(**asdict(row))


default_glossary_repository = InMemoryGlossaryRepository()
