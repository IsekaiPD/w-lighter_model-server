from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

GlossaryCategory = Literal["person", "alias", "place", "organization", "skill", "system_term", "genre_term", "honorific", "idiom", "title", "epithet", "other"]
GlossaryPriority = Literal["hard", "soft"]


@dataclass(slots=True)
class GlossaryEntry:
    source: str
    target: str
    category: GlossaryCategory = "other"
    priority: GlossaryPriority = "soft"
    aliases: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass(slots=True)
class WorkMemory:
    workId: str | None
    targetLocale: str
    approvedGlossary: list[GlossaryEntry] = field(default_factory=list)
    styleMemory: dict[str, Any] = field(default_factory=dict)
    previousSummary: str | None = None


@dataclass(slots=True)
class LiteraryPackageResult:
    pipeline: str
    finalTranslation: str
    qaIssues: list[dict[str, Any]] = field(default_factory=list)
    authorReviewCards: list[dict[str, Any]] = field(default_factory=list)
    internal: dict[str, Any] = field(default_factory=dict)
    readerEndnotes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class TranslationLoopResult:
    finalTranslation: str
    iterations: list[dict[str, Any]]
    judge: dict[str, Any]
    qaIssues: list[dict[str, Any]]
    authorReviewCards: list[dict[str, Any]]


_HANGUL_RE = re.compile(r"[가-힣]")
_ALLOWED_CATEGORIES = {"person", "alias", "place", "organization", "skill", "system_term", "genre_term", "honorific", "idiom", "title", "epithet", "other"}
def _clean(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    return dict(value) if isinstance(value, dict) else {}


def _coerce_glossary_entry(value: Any) -> GlossaryEntry | None:
    data = _as_dict(value)
    source = _clean(data.get("source"))
    target = _clean(data.get("target"))
    if not source or not target:
        return None
    category = _clean(data.get("category") or "other")
    if category not in _ALLOWED_CATEGORIES:
        category = "other"
    priority = _clean(data.get("priority") or "soft").lower()
    if priority not in {"hard", "soft"}:
        priority = "soft"
    aliases = [_clean(row) for row in (data.get("aliases") or []) if _clean(row)]
    forbidden = [_clean(row) for row in (data.get("forbidden") or []) if _clean(row)]
    note = _clean(data.get("note")) or None
    return GlossaryEntry(source=source, target=target, category=category, priority=priority, aliases=aliases, forbidden=forbidden, note=note)


def normalize_work_memory(work_memory: Any, target_locale: str) -> WorkMemory | None:
    if work_memory is None:
        return None
    if isinstance(work_memory, WorkMemory):
        return work_memory
    data = _as_dict(work_memory)
    rows = data.get("approvedGlossary") or data.get("approved_glossary") or []
    glossary = [entry for row in rows if (entry := _coerce_glossary_entry(row)) is not None]
    return WorkMemory(
        workId=_clean(data.get("workId") or data.get("work_id")) or None,
        targetLocale=_clean(data.get("targetLocale") or data.get("target_locale") or target_locale),
        approvedGlossary=glossary,
        styleMemory=data.get("styleMemory") or data.get("style_memory") or {},
        previousSummary=_clean(data.get("previousSummary") or data.get("previous_summary")) or None,
    )


def build_sample_work_memory(target_locale: str, work_id: str | None = "sample_work") -> dict[str, Any]:
    """Return a small in-memory WorkMemory payload for lab/smoke testing."""
    locale = _clean(target_locale) or "ko_ja"
    if locale == "ko_en_us":
        glossary = [
            {"source": '강현우', "target": 'Kang Hyunwoo', "category": 'person', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'main protagonist approved romanization'},
            {"source": '한연주', "target": 'Han Yeonju', "category": 'person', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'main character approved romanization'},
            {"source": '균열', "target": 'rift', "category": 'genre_term', "priority": 'hard', "aliases": [], "forbidden": ['crack', 'fissure'], "note": 'hunter-fantasy setting term'},
            {"source": '[스킬]', "target": '[Skill]', "category": 'system_term', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'preserve bracketed system UI term'},
            {"source": '선배', "target": 'senior/senpai/name depending on context', "category": 'honorific', "priority": 'soft', "aliases": [], "forbidden": [], "note": 'resolve by relationship and dialogue context'},
        ]
    elif locale == "ko_ja":
        glossary = [
            {"source": '강현우', "target": 'カン・ヒョヌ', "category": 'person', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'approved Japanese name rendering'},
            {"source": '한연주', "target": 'ハン・ヨンジュ', "category": 'person', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'approved Japanese name rendering'},
            {"source": '균열', "target": '亀裂', "category": 'genre_term', "priority": 'soft', "aliases": [], "forbidden": [], "note": 'genre term; review context before hard enforcement'},
            {"source": '[스킬]', "target": '[スキル]', "category": 'system_term', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'preserve bracketed system UI term'},
            {"source": '선배', "target": '先輩', "category": 'honorific', "priority": 'soft', "aliases": [], "forbidden": [], "note": 'dialogue honorific; preserve when natural'},
        ]
    else:
        glossary = [
            {"source": '강현우', "target": 'Kang Hyunwoo', "category": 'person', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'main protagonist approved romanization'},
            {"source": '한연주', "target": 'Han Yeonju', "category": 'person', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'main character approved romanization'},
            {"source": '균열', "target": 'rift', "category": 'genre_term', "priority": 'hard', "aliases": [], "forbidden": ['crack', 'fissure'], "note": 'hunter-fantasy setting term'},
            {"source": '[스킬]', "target": '[Skill]', "category": 'system_term', "priority": 'hard', "aliases": [], "forbidden": [], "note": 'preserve bracketed system UI term'},
        ]
    return {
        "workId": work_id,
        "targetLocale": locale,
        "approvedGlossary": glossary,
        "styleMemory": {"tone": "literary web novel", "policy": "compact translator brief only"},
        "previousSummary": None,
    }


def _mock_literary_translation(source_text: str, target_locale: str, work_memory: Any = None) -> str:
    text = _clean(source_text)
    if not text:
        return ""
    if target_locale == "ko_ja":
        translated = text
        memory = normalize_work_memory(work_memory, target_locale)
        if memory:
            for entry in memory.approvedGlossary:
                if entry.source in translated:
                    translated = translated.replace(entry.source, entry.target)
                for alias in entry.aliases:
                    if alias in translated:
                        translated = translated.replace(alias, entry.target)
        if _HANGUL_RE.search(translated) or "?" in translated:
            translated = "Localized Japanese mock translation: 物語の感情線."
        return translated
    return f"[mock literary translation] {text}"


def _glossary_source_set(work_memory: WorkMemory | None) -> set[str]:
    if not work_memory:
        return set()
    return {entry.source for entry in work_memory.approvedGlossary if entry.source}


def _source_present(source_text: str, entry: GlossaryEntry, glossary_sources: set[str] | None = None) -> bool:
    if entry.source and entry.source in source_text:
        return True
    protected_sources = glossary_sources or set()
    for alias in entry.aliases:
        if not alias or alias not in source_text:
            continue
        if alias in protected_sources and alias != entry.source:
            continue
        return True
    return False


def _judge(issues: list[dict[str, Any]]) -> dict[str, Any]:
    has_p0 = any(i.get("priority") == "P0" for i in issues)
    has_p1 = any(i.get("priority") == "P1" for i in issues)
    auto_revision_required = has_p0 or any(bool(i.get("autoRevisionEligible")) for i in issues)
    return {"status": "needs_revision" if auto_revision_required else "pass_with_review_items" if has_p1 else "pass", "autoRevisionRequired": auto_revision_required, "maxSeverity": "P0" if has_p0 else "P1" if has_p1 else "none"}


def _failure_signals(issues: list[dict[str, Any]]) -> list[str]:
    mapping = {"idiom_literal_risk_detected", "glossary_consistency", "glossary_forbidden_translation", "korean_residue_detected", "hangul_residue_integrity", "bracket_block_count_mismatch", "bracket_block_role_or_order_mismatch", "system_message_missing"}
    signals = []
    for issue in issues:
        code = str(issue.get("code") or issue.get("type") or "")
        if code in mapping and code not in signals:
            signals.append(code if code != "glossary_consistency" else "glossary_consistency_issue")
    return signals


