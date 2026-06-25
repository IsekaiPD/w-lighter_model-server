from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable, Literal

LiteralRisk = Literal["low", "medium", "high"]
GlossaryCategory = Literal["person", "alias", "place", "organization", "skill", "system_term", "genre_term", "honorific", "idiom", "title", "epithet", "other"]
GlossaryPriority = Literal["hard", "soft"]


@dataclass(slots=True)
class IdiomNote:
    sourceSpan: str
    canonical: str
    meaningKo: str
    literalRisk: LiteralRisk
    translatorNote: str
    confidence: float


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
class RAGPackets:
    translatorBrief: dict[str, Any]
    editorEvidence: dict[str, Any]
    rationaleEvidence: dict[str, Any]


@dataclass(slots=True)
class V3LiteraryPackageResult:
    pipeline: str
    finalTranslation: str
    qaIssues: list[dict[str, Any]] = field(default_factory=list)
    authorReviewCards: list[dict[str, Any]] = field(default_factory=list)
    internal: dict[str, Any] = field(default_factory=dict)
    readerEndnotes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class V3Guidelines:
    translatorGuideline: str
    editorGuideline: str


@dataclass(slots=True)
class TranslationLoopResult:
    finalTranslation: str
    iterations: list[dict[str, Any]]
    judge: dict[str, Any]
    qaIssues: list[dict[str, Any]]
    authorReviewCards: list[dict[str, Any]]


_IDIOM_RULES: tuple[dict[str, Any], ...] = (
    {"source": "발등에 불이 떨어지다", "canonical": "발등에 불이 떨어지다", "meaning": "매우 급박한 상황에 몰려 즉시 대응해야 함.", "risk": "high", "note": "Render urgency or pressure naturally; do not translate the fire/foot image literally."},
    {"source": "꼬리가 길어져 밟히다", "canonical": "꼬리가 길면 밟힌다", "meaning": "숨긴 행동이 반복되면 결국 들통남.", "risk": "high", "note": "Render exposure after repeated suspicious behavior; avoid a literal tail image unless the target idiom supports it."},
    {"source": "숨통이 트이다", "canonical": "숨통이 트이다", "meaning": "막혔던 상황이 풀려 한숨 돌릴 여지가 생김.", "risk": "medium", "note": "Render relief or room to breathe naturally; avoid anatomical wording if it sounds clinical."},
    {"source": "간이 콩알만 해지다", "canonical": "간이 콩알만 해지다", "meaning": "몹시 겁이 나고 위축됨.", "risk": "high", "note": "Render fear or shrinking courage; do not translate liver/bean imagery literally."},
    {"source": "눈에 밟히다", "canonical": "눈에 밟히다", "meaning": "자꾸 마음에 걸리고 잊히지 않음.", "risk": "medium", "note": "Render lingering concern or an image that stays with the speaker; avoid literal eye/step phrasing."},
    {"source": "손발이 오그라들다", "canonical": "손발이 오그라들다", "meaning": "민망하거나 오글거려 견디기 어려움.", "risk": "medium", "note": "Render cringe or secondhand embarrassment; avoid literal shrinking hands and feet."},
    {"source": "귀에 못이 박히다", "canonical": "귀에 못이 박히다", "meaning": "같은 말을 너무 많이 들어 지겨움.", "risk": "medium", "note": "Render being sick of hearing something repeated; avoid literal nails in ears."},
    {"source": "식은 죽 먹기", "canonical": "식은 죽 먹기", "meaning": "아주 쉬운 일.", "risk": "medium", "note": "Render ease with a target-natural idiom such as a cakewalk/easy task equivalent."},
)

_JA_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("발등에 불이 떨어지다", "切羽詰まる"),
    ("발등에 불이 떨어졌다", "切羽詰まった"),
    ("꼬리가 길어져 밟히다", "隠し事が長引いて足がつく"),
    ("숨통이 트이다", "ようやく息がつける"),
    ("숨통이 트였다", "ようやく息がつけた"),
    ("간이 콩알만 해지다", "肝を冷やす"),
    ("눈에 밟히다", "ずっと気にかかる"),
    ("손발이 오그라들다", "見ていていたたまれない"),
    ("귀에 못이 박히다", "耳にたこができるほど聞かされる"),
    ("식은 죽 먹기", "朝飯前"),
)

_HANGUL_RE = re.compile(r"[가-힣]")
_HANGUL_SPAN_RE = re.compile(r"[가-힣]+")
_BRACKET_BLOCK_RE = re.compile(r"(?:\[[^\[\]\r\n]{1,160}\]|［[^［］\r\n]{1,160}］|【[^【】\r\n]{1,160}】)")
_SYSTEM_MARKERS = ("[STRICT", "assistant:", "user:")
_ALLOWED_IDIOM_MODES = {"rule", "llm", "ft"}
_ALLOWED_CATEGORIES = {"person", "alias", "place", "organization", "skill", "system_term", "genre_term", "honorific", "idiom", "title", "epithet", "other"}
_CONTEXTUAL_REF_TOKENS = ("그", "그녀", "남자", "저 남자", "그 남자", "그분", "이 사람", "저 사람")
_CHARACTER_RULES: tuple[dict[str, Any], ...] = (
    {"source": "리아", "target": {"ko_en_us": "Ria", "ko_ja": "リア"}, "aliases": []},
    {"source": "카이든 에른스트", "target": {"ko_en_us": "Kaiden Ernst", "ko_ja": "カイデン・エルンスト"}, "aliases": ["카이든", "북부대공", "대공 전하", "검은 늑대"]},
    {"source": "로웬 경", "target": {"ko_en_us": "Sir Lowen", "ko_ja": "ローウェン卿"}, "aliases": ["로웬"]},
    {"source": "강현우", "target": {"ko_en_us": "Kang Hyunwoo", "ko_ja": "カン・ヒョヌ"}, "aliases": []},
    {"source": "한연주", "target": {"ko_en_us": "Han Yeonju", "ko_ja": "ハン・ヨンジュ"}, "aliases": []},
)
_ENTITY_RULES: tuple[dict[str, Any], ...] = (
    {"source": "북부대공", "target": {"ko_en_us": "the Northern Grand Duke", "ko_ja": "北部大公"}, "category": "title", "aliases": ["대공 전하", "검은 늑대", "카이든"]},
    {"source": "황태자", "target": {"ko_en_us": "the Crown Prince", "ko_ja": "皇太子"}, "category": "title", "aliases": []},
    {"source": "성녀", "target": {"ko_en_us": "the saintess", "ko_ja": "聖女"}, "category": "title", "aliases": []},
    {"source": "검은 늑대", "target": {"ko_en_us": "the black wolf", "ko_ja": "黒い狼"}, "category": "epithet", "aliases": ["북부대공"]},
    {"source": "균열", "target": {"ko_en_us": "rift", "ko_ja": "亀裂"}, "category": "genre_term", "aliases": ["게이트"]},
    {"source": "[스킬]", "target": {"ko_en_us": "[Skill]", "ko_ja": "[スキル]"}, "category": "system_term", "aliases": []},
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", _clean(value))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _target_for(rule: dict[str, Any], target_locale: str) -> str:
    target = rule.get("target") or {}
    if isinstance(target, dict):
        return _clean(target.get(target_locale) or target.get("ko_en_us") or next(iter(target.values()), ""))
    return _clean(target)


def _source_span_for_terms(source_text: str, terms: list[str]) -> str:
    present = [term for term in terms if term and term in source_text]
    return ", ".join(dict.fromkeys(present))


def analyze_source_references(source_text: str, target_locale: str) -> dict[str, list[dict[str, Any]]]:
    """Deterministic source-evidence adapter for v3 internal/candidate capture.

    This does not call an LLM. It keeps character/entity evidence out of the
    translator brief while making later candidate capture testable and stable.
    """

    text = source_text or ""
    character_references: list[dict[str, Any]] = []
    entity_candidates: list[dict[str, Any]] = []

    for index, rule in enumerate(_CHARACTER_RULES, start=1):
        source = _clean(rule.get("source"))
        aliases = [alias for alias in (rule.get("aliases") or []) if alias in text]
        if source not in text and not aliases:
            continue
        references = [source] if source in text else []
        references.extend(aliases)
        references.extend([token for token in _CONTEXTUAL_REF_TOKENS if token in text])
        references = list(dict.fromkeys([ref for ref in references if ref]))
        target = _target_for(rule, target_locale)
        character_references.append(
            {
                "character_id": f"C{index}",
                "canonical_name_ko": source,
                "canonical_name_target": target,
                "references_ko": references,
                "references_target": [target] + (["she", "her"] if "그녀" in references else ["he", "him"] if "그" in references else []),
                "same_person_reason_ko": "반복 등장한 이름/호칭과 주변 지시어를 같은 회차 내부 인물 참조 evidence로 묶었습니다.",
                "confidence": 0.92 if source in text else 0.78,
            }
        )

    for rule in _ENTITY_RULES:
        source = _clean(rule.get("source"))
        aliases = [alias for alias in (rule.get("aliases") or []) if alias in text]
        if source not in text and not aliases:
            continue
        all_terms = [source] + aliases
        entity_candidates.append(
            {
                "source": source,
                "suggested_target": _target_for(rule, target_locale),
                "category": _clean(rule.get("category") or "other"),
                "confidence": 0.88 if source in text else 0.74,
                "source_span": _source_span_for_terms(text, all_terms),
                "reason": "반복되거나 장기 표기 일관성이 필요한 인물/용어 후보입니다.",
                "aliases": aliases,
            }
        )

    return {"characterReferences": character_references, "entityCandidates": entity_candidates}


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
    """Return a small in-memory WorkMemory payload for v3 lab/smoke testing."""
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


def detect_idiom_notes(source_text: str, target_locale: str, mode: str = "rule") -> list[IdiomNote]:
    mode = _clean(mode).lower() or "rule"
    if mode not in _ALLOWED_IDIOM_MODES:
        mode = "rule"
    if mode != "rule":
        return []
    del target_locale
    notes: list[IdiomNote] = []
    for rule in _IDIOM_RULES:
        if rule["source"] in (source_text or ""):
            notes.append(IdiomNote(rule["source"], rule["canonical"], rule["meaning"], rule["risk"], rule["note"], 0.92 if rule["risk"] == "high" else 0.84))
    return notes


def _compact_glossary(entries: list[GlossaryEntry], *, limit: int, include_soft: bool) -> list[dict[str, Any]]:
    hard = [row for row in entries if row.priority == "hard"]
    soft = [row for row in entries if row.priority != "hard"] if include_soft else []
    selected = (hard + soft)[:limit]
    return [{"source": row.source, "target": row.target, "category": row.category, "priority": row.priority, "aliases": row.aliases[:3], "forbidden": row.forbidden[:3], "note": row.note} for row in selected]


def build_rag_packets(source_text: str, target_locale: str, genre: str, idiom_notes: list[IdiomNote], work_memory: Any = None, source_evidence: dict[str, Any] | None = None) -> RAGPackets:
    memory = normalize_work_memory(work_memory, target_locale)
    glossary = memory.approvedGlossary if memory else []
    genre_text = _clean(genre) or "modern web novel"
    brief_notes = [{"sourceSpan": n.sourceSpan, "canonical": n.canonical, "literalRisk": n.literalRisk, "translatorNote": n.translatorNote} for n in idiom_notes]
    full_notes = [asdict(n) for n in idiom_notes]
    approved_glossary = _compact_glossary(glossary, limit=50, include_soft=True)
    locale_policy = ["Translate into the requested target locale only.", "Preserve scene pacing, emotion, and dialogue energy.", "Do not expose raw retrieval chunks in the reader-facing translation."]
    if target_locale == "ko_ja":
        locale_policy.append("For Japanese output, avoid leaving Korean sentence-level text unless it is an intentional proper noun.")
        locale_policy.extend(
            [
                "Do not translate Korean idioms, proverbs, or figurative expressions word-for-word.",
                "Convert Korean figurative expressions into natural Japanese narration that preserves scene meaning, emotional pressure, fatigue, and tension.",
                "If no equivalent Japanese idiom fits naturally, paraphrase the meaning in plain literary Japanese.",
                "Avoid literal Korean body-part idiom images such as feet on fire, dry face-washing, throat, liver, chest, or stomach expressions unless Japanese naturally uses the same image.",
                "Examples: '그는 마른세수를 했다' -> '彼は疲れ切った顔を両手でこすった。'; '지금은 발등에 불이 떨어져도 눈이 감길 것 같았다' -> '今は何が起きても眠気に負けそうだった。'",
                "Naturalize Korean company ranks for Japanese readers without over-changing rank meaning; choose contextually among チーム長, 上司, or a similar title.",
                "Preserve web novel pacing with short impact sentences, readable narration, and natural dialogue.",
            ]
        )
    evidence = source_evidence or {"characterReferences": [], "entityCandidates": []}
    return RAGPackets(
        translatorBrief={"styleBrief": f"{genre_text}. Preserve pacing, emotion, and dialogue energy.", "idiomNotes": brief_notes, "glossary": approved_glossary, "termHints": [], "nameHints": []},
        editorEvidence={"idiomNotes": full_notes, "localePolicy": locale_policy, "genreTerms": [genre_text], "approvedGlossary": approved_glossary, "characterReferences": evidence.get("characterReferences") or [], "entityCandidates": evidence.get("entityCandidates") or [], "styleMemory": memory.styleMemory if memory else {}, "previousSummary": memory.previousSummary if memory else None},
        rationaleEvidence={"sourcePreview": _clip(source_text, 400), "idiomNotes": full_notes, "approvedGlossary": approved_glossary, "characterReferences": evidence.get("characterReferences") or [], "entityCandidates": evidence.get("entityCandidates") or [], "styleBasis": genre_text, "locale": target_locale},
    )


def build_v3_guidelines(source_text: str, target_locale: str, genre: str, idiom_notes: list[IdiomNote], rag_packets: RAGPackets) -> V3Guidelines:
    del source_text, idiom_notes
    idiom_lines = [f"- {row['sourceSpan']}: {row['translatorNote']}" for row in rag_packets.translatorBrief.get("idiomNotes", [])]
    glossary_lines = [f"- {row['source']} -> {row['target']}" for row in rag_packets.translatorBrief.get("glossary", [])]
    parts = [f"Target locale: {target_locale}.", f"Genre/style: {_clean(genre) or rag_packets.translatorBrief.get('styleBrief', 'modern web novel')}.", "Prioritize literary fluency over word-for-word rendering."]
    if target_locale == "ko_ja":
        parts.append(
            "Japanese idiom policy:\n"
            "- Do not translate Korean idioms, proverbs, or figurative expressions word-for-word.\n"
            "- Preserve scene meaning, emotional pressure, fatigue, and tension in natural Japanese narration.\n"
            "- If no equivalent Japanese idiom fits naturally, paraphrase in plain literary Japanese.\n"
            "- Avoid literal Korean body-part idiom images such as feet on fire or dry face-washing unless Japanese naturally uses the same image.\n"
            "- Examples: 그는 마른세수를 했다 -> 彼は疲れ切った顔を両手でこすった。 / 지금은 발등에 불이 떨어져도 눈이 감길 것 같았다 -> 今は何が起きても眠気に負けそうだった。\n"
            "- Naturalize Korean company ranks such as 팀장 contextually as チーム長, 上司, or a similar title without over-changing rank meaning."
        )
    if glossary_lines:
        parts.append("Approved glossary:\n" + "\n".join(glossary_lines[:20]))
    if idiom_lines:
        parts.append("Idiom handling:\n" + "\n".join(idiom_lines[:6]))
    translator = "\n".join(parts)
    editor = "\n".join([translator, "", "Editor evidence:", f"- idiom count: {len(rag_packets.editorEvidence.get('idiomNotes', []))}", f"- glossary count: {len(rag_packets.editorEvidence.get('approvedGlossary', []))}", f"- locale policy: {'; '.join(rag_packets.editorEvidence.get('localePolicy', []))}", "Glossary consistency is normally P1 review, not blocked safety.", "Leave uncertain idiom/style concerns as P1 or lower review items."])
    return V3Guidelines(translator, editor)


def _ja_idiom_fallback(note: IdiomNote) -> str:
    mapping = {
        "발등에 불이 떨어지다": "切羽詰まる",
        "꼬리가 길면 밟힌다": "隠し事が長引いて足がつく",
        "숨통이 트이다": "ようやく息がつける",
        "간이 콩알만 해지다": "肝を冷やす",
        "눈에 밟히다": "ずっと気にかかる",
        "손발이 오그라들다": "見ていていたたまれない",
        "귀에 못이 박히다": "耳にたこができるほど聞かされる",
        "식은 죽 먹기": "朝飯前"
    }
    return mapping.get(note.canonical, "自然な慣用表現")


def _mock_literary_translation(source_text: str, target_locale: str, idiom_notes: list[IdiomNote], work_memory: Any = None) -> str:
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
        for src, dst in _JA_REPLACEMENTS:
            translated = translated.replace(src, dst)
        for note in idiom_notes:
            translated = translated.replace(note.sourceSpan, _ja_idiom_fallback(note))
        if _HANGUL_RE.search(translated) or "?" in translated:
            idiom_summary = ", ".join(_ja_idiom_fallback(note) for note in idiom_notes) or "物語の感情線"
            translated = f"Localized Japanese mock translation: {idiom_summary}."
        return translated
    return f"[mock literary translation] {text}"


def _hangul_ratio(text: str) -> float:
    chars = [ch for ch in (text or "") if not ch.isspace()]
    return 0.0 if not chars else sum(1 for ch in chars if _HANGUL_RE.match(ch)) / len(chars)


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


def _issue(
    priority: str,
    code: str,
    message: str,
    *,
    source_span: str = "",
    target_span: str = "",
    suggestion: str = "",
    auto: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue = {
        "type": code,
        "priority": priority,
        "code": code,
        "message": message,
        "sourceSpan": source_span,
        "targetSpan": target_span,
        "suggestion": suggestion,
        "autoRevisionEligible": auto,
    }
    if details:
        issue["details"] = details
    return issue


def _glossary_issues(source_text: str, final_translation: str, work_memory: WorkMemory | None) -> list[dict[str, Any]]:
    if not work_memory:
        return []
    issues: list[dict[str, Any]] = []
    glossary_sources = _glossary_source_set(work_memory)
    for entry in work_memory.approvedGlossary:
        if not _source_present(source_text, entry, glossary_sources):
            continue
        if entry.priority == "hard" and entry.target not in final_translation:
            issues.append(
                _issue(
                    "P1",
                    "glossary_consistency",
                    f"Approved glossary target '{entry.target}' may be missing for '{entry.source}'.",
                    source_span=entry.source,
                    target_span=entry.target,
                    suggestion=f"Use '{entry.target}' consistently for '{entry.source}' and its aliases.",
                    auto=True,
                    details={
                        "source": entry.source,
                        "target": entry.target,
                        "aliases": entry.aliases,
                        "priority": entry.priority,
                        "category": entry.category,
                    },
                )
            )
        for forbidden in entry.forbidden:
            if forbidden and forbidden in final_translation:
                issues.append(_issue("P1", "glossary_forbidden_translation", f"Forbidden translation '{forbidden}' appears for '{entry.source}'.", source_span=entry.source, suggestion=f"Use approved target '{entry.target}'."))
    return issues


def _critic_issues(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None = None) -> list[dict[str, Any]]:
    del safety_metadata
    issues: list[dict[str, Any]] = []
    if not _clean(final_translation):
        issues.append(_issue("P0", "empty_translation", "Final translation is empty.", auto=True))
    for note in idiom_notes:
        if note.sourceSpan and note.sourceSpan in final_translation:
            issues.append(_issue("P1", "idiom_literal_risk_detected", f"Detected idiom may have been copied literally: {note.sourceSpan}", source_span=note.sourceSpan))
    issues.extend(_glossary_issues(source_text, final_translation, work_memory))
    return issues


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


