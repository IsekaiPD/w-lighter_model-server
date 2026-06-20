from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from ..engine.literary_package import GlossaryEntry, WorkMemory
from ..infra.locale_utils import country_to_locale, normalize_target_country

# Single-table glossary model.
#
# The glossary is a flat list of translation rules. Each row maps one source
# term to one target term for a given work + target country. Aliases are stored
# as their own rows (one row per surface form), so there is no separate alias
# table, no priority flag, and no forbidden-term table. Every stored row is an
# enforced rule.
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
    id: int | None
    work_id: str
    country: str
    source: str
    target: str
    category: str = DEFAULT_CATEGORY
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


class GlossaryRepository(Protocol):
    def upsert_entry(
        self,
        *,
        work_id: str,
        country: str,
        source: str,
        target: str,
        category: str = DEFAULT_CATEGORY,
    ) -> GlossaryEntryRecord:
        ...

    def list_glossary(self, work_id: str, country: str, *, limit: int = 50) -> list[GlossaryEntryRecord]:
        ...

    def get_entry(self, entry_id: int) -> GlossaryEntryRecord | None:
        ...

    def delete_entry(self, entry_id: int) -> bool:
        ...

    def hydrate_work_memory(self, work_id: str, country: str, *, limit: int = 50) -> WorkMemory | None:
        ...


def glossary_record_to_work_memory_entry(record: GlossaryEntryRecord) -> GlossaryEntry:
    """Convert a stored row into the engine-facing glossary entry.

    Every stored row is an enforced rule, so ``priority`` is always ``"hard"``.
    Aliases live in their own rows, so per-entry ``aliases``/``forbidden`` lists
    are always empty here.
    """

    return GlossaryEntry(
        source=record.source,
        target=record.target,
        category=record.category if record.category in GLOSSARY_CATEGORIES else DEFAULT_CATEGORY,
        priority="hard",
        aliases=[],
        forbidden=[],
        note=None,
    )


def hydrate_work_memory_from_records(
    work_id: str,
    country: str,
    records: list[GlossaryEntryRecord],
    *,
    limit: int = 50,
) -> WorkMemory | None:
    """Build engine WorkMemory from stored rows.

    This is the storage/engine boundary: rows are stored by 2-letter country
    code (JP/US/CN/TH) but the engine expects an internal locale (ko_ja, ...),
    so the country is converted here with ``country_to_locale``.
    """

    selected = records[: max(0, limit)]
    if not selected:
        return None
    return WorkMemory(
        workId=_clean(work_id) or None,
        targetLocale=country_to_locale(country),
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
        country: str,
        source: str,
        target: str,
        category: str = DEFAULT_CATEGORY,
    ) -> GlossaryEntryRecord:
        work_id = _clean(work_id)
        country = normalize_target_country(country) or ""
        source = _clean(source)
        target = _clean(target)
        category = normalize_category(category)
        if not work_id or not country or not source or not target:
            raise ValueError("work_id, country, source, and target are required")
        if is_contextual_reference(source):
            raise ValueError("source is a contextual reference and should not be persisted as a glossary entry")
        with self._lock:
            existing = next(
                (
                    row
                    for row in self._entries.values()
                    if row.work_id == work_id
                    and row.country == country
                    and row.source == source
                    and row.category == category
                ),
                None,
            )
            now = _now_iso()
            if existing is None:
                entry_id = self._next_entry_id
                self._next_entry_id += 1
                existing = GlossaryEntryRecord(
                    id=entry_id,
                    work_id=work_id,
                    country=country,
                    source=source,
                    target=target,
                    category=category,
                    created_at=now,
                    updated_at=now,
                )
                self._entries[entry_id] = existing
            else:
                existing.target = target
                existing.updated_at = now
            return self._clone_entry(existing)

    def list_glossary(self, work_id: str, country: str, *, limit: int = 50) -> list[GlossaryEntryRecord]:
        work_id = _clean(work_id)
        country = normalize_target_country(country) or ""
        with self._lock:
            rows = [
                self._clone_entry(row)
                for row in self._entries.values()
                if row.work_id == work_id and row.country == country
            ]
        rows.sort(key=lambda row: (row.source.casefold(), row.category))
        return rows[: max(0, limit)]

    def get_entry(self, entry_id: int) -> GlossaryEntryRecord | None:
        with self._lock:
            row = self._entries.get(int(entry_id))
            return self._clone_entry(row) if row is not None else None

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock:
            return self._entries.pop(int(entry_id), None) is not None

    def hydrate_work_memory(self, work_id: str, country: str, *, limit: int = 50) -> WorkMemory | None:
        records = self.list_glossary(work_id, country, limit=limit)
        return hydrate_work_memory_from_records(work_id, country, records, limit=limit)

    @staticmethod
    def _clone_entry(row: GlossaryEntryRecord) -> GlossaryEntryRecord:
        return GlossaryEntryRecord(**asdict(row))


default_glossary_repository = InMemoryGlossaryRepository()
