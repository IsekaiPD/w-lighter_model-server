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
class TranslationRationaleItem:
    sourceSpan: str
    targetSpan: str
    category: str
    strategy: str
    explanation: str


@dataclass(slots=True)
class TranslationRationale:
    title: str
    overview: str
    styleIntent: str
    strategyRatio: dict[str, int]
    items: list[TranslationRationaleItem] = field(default_factory=list)


@dataclass(slots=True)
class V3LiteraryPackageResult:
    pipeline: str
    deliveryStatus: str
    finalTranslation: str
    translationRationale: TranslationRationale
    qaIssues: list[dict[str, Any]] = field(default_factory=list)
    authorReviewCards: list[dict[str, Any]] = field(default_factory=list)
    internal: dict[str, Any] = field(default_factory=dict)
    readerEndnotes: list[dict[str, Any]] = field(default_factory=list)
    userVisibleErrorCode: str | None = None


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
    deliveryStatus: str
    userVisibleErrorCode: str | None = None


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


def _contains_system_artifact(text: str) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in _SYSTEM_MARKERS)


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


_KNOWN_GLOSSARY_WRONG_VARIANTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("\ucca0\uc218", "\u30c1\u30e7\u30eb\u30b9"): ("\u9244\uc218",),
    ("\ub099\uc6d0\ub3d9", "\u30ca\u30af\u30a6\u30a9\u30f3\u30c9\u30f3"): (
        "\ub099\uc6d0\ub3d9",
        "\u697d\u5712\u6d1e",
        "\u843d\u5712\u6d1e",
        "\u30ca\u30b0\u30a9\u30f3\u30c9\u30f3",
        "\u30ca\u30af\u30a9\u30f3\u30c9\u30f3",
        "\u30ca\u30b0\u30a6\u30a9\u30f3\u30c9\u30f3",
        "\u30ca\u30b0\u30a9\u30f3\u6d1e",
        "\u30ca\u30af\u30a6\u30a9\u30f3\u6d1e",
    ),
}


def _glossary_patch_variants(entry: GlossaryEntry, target_locale: str) -> tuple[str, ...]:
    variants: list[str] = []
    if target_locale == "ko_ja" and entry.source:
        variants.append(entry.source)
    variants.extend(_KNOWN_GLOSSARY_WRONG_VARIANTS.get((entry.source, entry.target), ()))
    variants.extend(term for term in entry.forbidden if term)
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        if not variant or variant == entry.target or variant in seen:
            continue
        seen.add(variant)
        ordered.append(variant)
    return tuple(ordered)


def _hard_glossary_entries_for_issues(issues: list[dict[str, Any]], work_memory: WorkMemory | None) -> list[GlossaryEntry]:
    if not work_memory:
        return []
    wanted = {
        (str((issue.get("details") or {}).get("source") or issue.get("sourceSpan") or ""), str((issue.get("details") or {}).get("target") or issue.get("targetSpan") or ""))
        for issue in issues
        if issue.get("code") == "glossary_consistency" and issue.get("autoRevisionEligible")
    }
    if not wanted:
        return []
    return [entry for entry in work_memory.approvedGlossary if entry.priority == "hard" and (entry.source, entry.target) in wanted]


_KO_JA_GLOSSARY_PARTICLE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\uc5d0\uac8c", "\u306b"),
    ("\ud55c\ud14c", "\u306b"),
    ("\ud558\uace0", "\u3068"),
    ("\uc73c\ub85c", "\u3067"),
    ("\uc740", "\u306f"),
    ("\ub294", "\u306f"),
    ("\uc774", "\u304c"),
    ("\uac00", "\u304c"),
    ("\uc744", "\u3092"),
    ("\ub97c", "\u3092"),
    ("\uc5d0", "\u306b"),
    ("\uc758", "\u306e"),
    ("\uacfc", "\u3068"),
    ("\uc640", "\u3068"),
    ("\ub791", "\u3068"),
    ("\ub85c", "\u3067"),
)
_JA_ATTACHED_GLOSSARY_PARTICLES = ("\u306f", "\u304c", "\u3092", "\u306e", "\u306b", "\u3078", "\u3068", "\u3082", "\u3067", "\u3084")
_KO_JA_GLOSSARY_PARTICLE_MAP = dict(_KO_JA_GLOSSARY_PARTICLE_REPLACEMENTS)


def _hard_glossary_source_pattern(source: str, target_locale: str) -> re.Pattern[str] | None:
    if target_locale != "ko_ja" or not source:
        return None
    particles = [re.escape(particle) for particle, _ in _KO_JA_GLOSSARY_PARTICLE_REPLACEMENTS]
    particles.extend(re.escape(particle) for particle in _JA_ATTACHED_GLOSSARY_PARTICLES)
    return re.compile(f"(?<![\uac00-\ud7a3]){re.escape(source)}({'|'.join(particles)})?(?![\uac00-\ud7a3])")


def _contains_hard_glossary_source_surface(text: str, source: str, target_locale: str) -> bool:
    pattern = _hard_glossary_source_pattern(source, target_locale)
    return bool(pattern.search(text or "")) if pattern else bool(source and source in (text or ""))


def _hard_glossary_source_residue_entries(source_text: str, final_translation: str, work_memory: WorkMemory | None, target_locale: str) -> list[GlossaryEntry]:
    if not work_memory or not source_text or not final_translation:
        return []
    return [
        entry
        for entry in work_memory.approvedGlossary
        if entry.priority == "hard"
        and entry.source
        and entry.target
        and _contains_hard_glossary_source_surface(source_text, entry.source, target_locale)
        and _contains_hard_glossary_source_surface(final_translation, entry.source, target_locale)
    ]


def _replace_hard_glossary_source_residue(text: str, entry: GlossaryEntry, target_locale: str) -> tuple[str, int]:
    if target_locale != "ko_ja" or not entry.source or not entry.target or entry.source not in text:
        return text, 0
    pattern = _hard_glossary_source_pattern(entry.source, target_locale)
    if pattern is None:
        return text, 0
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        particle = match.group(1) or ""
        return entry.target + _KO_JA_GLOSSARY_PARTICLE_MAP.get(particle, particle)

    return pattern.sub(replace, text), count


def deterministic_glossary_patch_pass(source_text: str, final_translation: str, target_locale: str, work_memory: WorkMemory | None, issues: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if not work_memory or not final_translation:
        return final_translation, {"attempted": False, "patched": False, "replacements": []}
    glossary_sources = _glossary_source_set(work_memory)
    patched = final_translation
    replacements: list[dict[str, str]] = []
    residue_entries = _hard_glossary_source_residue_entries(source_text, patched, work_memory, target_locale)
    for entry in residue_entries:
        before = patched
        patched, count = _replace_hard_glossary_source_residue(patched, entry, target_locale)
        if not count:
            continue
        if not _clean(patched) or len(patched.strip()) < max(1, int(len(final_translation.strip()) * 0.5)):
            patched = before
            continue
        replacements.append({"source": entry.source, "target": entry.target, "variant": entry.source, "kind": "source_residue"})
    for entry in _hard_glossary_entries_for_issues(issues, work_memory):
        if not entry.target or entry.target in patched:
            continue
        if not _source_present(source_text, entry, glossary_sources):
            continue
        for variant in _glossary_patch_variants(entry, target_locale):
            if variant not in patched:
                continue
            before = patched
            patched = patched.replace(variant, entry.target)
            if not _clean(patched) or len(patched.strip()) < max(1, int(len(final_translation.strip()) * 0.5)):
                patched = before
                continue
            replacements.append({"source": entry.source, "target": entry.target, "variant": variant, "kind": "missing_target_variant"})
        if entry.target in patched:
            continue
    return patched, {"attempted": True, "patched": patched != final_translation, "replacements": replacements}


def _maybe_apply_deterministic_glossary_patch(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None, issues: list[dict[str, Any]], iterations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if any(issue.get("priority") == "P0" for issue in issues):
        return final_translation, issues, _judge(issues), {"attempted": False, "patched": False, "replacements": [], "reason": "p0_present"}
    has_hard_glossary_issue = any(issue.get("code") == "glossary_consistency" and issue.get("autoRevisionEligible") for issue in issues)
    has_source_residue = bool(_hard_glossary_source_residue_entries(source_text, final_translation, work_memory, target_locale))
    if not has_hard_glossary_issue and not has_source_residue:
        return final_translation, issues, _judge(issues), {"attempted": False, "patched": False, "replacements": [], "reason": "no_hard_glossary_issue"}
    patched, patch_meta = deterministic_glossary_patch_pass(source_text, final_translation, target_locale, work_memory, issues)
    if not patch_meta.get("patched"):
        return final_translation, issues, _judge(issues), patch_meta
    patched_issues = _critic_issues(source_text=source_text, final_translation=patched, target_locale=target_locale, idiom_notes=idiom_notes, safety_metadata=safety_metadata, work_memory=work_memory)
    patched_judge = _judge(patched_issues)
    iterations.append({"iteration": len(iterations) + 1, "action": "Deterministic Glossary Patch", "critique": patched_issues, "judge": patched_judge, "patch": patch_meta})
    return patched, patched_issues, patched_judge, patch_meta


_CALLER_LABEL_KEYWORDS = (
    "어머니",
    "엄마",
    "아버지",
    "아빠",
    "팀장",
    "상사",
    "母",
    "お母さん",
    "父",
    "チーム長",
    "上司",
    "パク",
    "mother",
    "mom",
    "father",
    "team leader",
)
_STATUS_UI_KEYWORDS = (
    "관리자",
    "권한",
    "확인",
    "적합성",
    "판정",
    "사용자",
    "직업",
    "보상",
    "위험도",
    "상태",
    "시스템",
    "퀘스트",
    "管理者",
    "権限",
    "確認",
    "適合",
    "判定",
    "ユーザー",
    "職業",
    "報酬",
    "危険度",
    "状態",
    "システム",
    "クエスト",
    "admin",
    "authority",
    "checking",
    "user",
    "job",
    "reward",
    "risk",
    "status",
    "system",
)
_DOCUMENT_NOTICE_KEYWORDS = (
    "주소",
    "통지서",
    "기관",
    "공지",
    "안내",
    "住所",
    "通知",
    "機関",
    "公示",
    "案内",
    "address",
    "notice",
)
_KNOWN_KO_PERSON_TOKENS = ("도윤", "강도윤", "현우", "강현우", "팀장")
_KO_SURNAME_CHARS = frozenset(
    "김이박최정강조윤장임한오서신권황안송전홍유고문양손배조백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반라"
)
_KO_NAME_PARTICLES = ("은", "는", "이", "가", "을", "를", "에게", "한테", "와", "과", "도", "의")
_JA_PARTICLE_AFTER_KO_RE = re.compile(r"^[\s\u3000]*[はがをのにへとで、。！？]")
_TARGET_SCRIPT_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_MIXED_TOKEN_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3\u30fc\u30fbA-Za-z0-9]")
_COMMON_LOCATION_NOUN_SUFFIXES = (
    "\uc0c1\uac00", "\uc2dc\uc7a5", "\uac70\ub9ac", "\uace8\ubaa9", "\uac74\ubb3c",
    "\uc0ac\ubb34\uc2e4", "\ubcd1\uc6d0", "\ud559\uad50", "\ud68c\uc0ac", "\uad6c\uc5ed",
    "\uc9c0\uc5ed", "\ub9c8\uc744", "\ub3c4\uc2dc", "\ucc3d\uace0", "\uc8fc\ucc28\uc7a5",
    "\ud3b8\uc758\uc810", "\uc2dd\ub2f9", "\ubd84\uc2dd", "\uc218\uc120", "\uc5ed",
    "\ubc29", "\ubb38", "\uae38", "\uce35", "\ubcf5\ub3c4", "\uad11\uc7a5",
)
_NAME_RESIDUE_CATEGORIES = {"person", "alias", "place", "organization", "proper_noun", "character"}
_TERM_RESIDUE_CATEGORIES = {"genre_term", "term", "system_term", "skill", "honorific", "idiom"}


def _extract_bracket_blocks(text: str) -> list[dict[str, Any]]:
    blocks = []
    for match in _BRACKET_BLOCK_RE.finditer(text or ""):
        raw = match.group(0)
        content = raw[1:-1].strip()
        blocks.append({"text": raw, "content": content, "start": match.start(), "end": match.end(), "role": _bracket_role(content)})
    return blocks


def _bracket_role(content: str) -> str:
    lowered = (content or "").casefold()
    if any(token.casefold() in lowered for token in _STATUS_UI_KEYWORDS):
        return "status_system_ui"
    if any(token.casefold() in lowered for token in _CALLER_LABEL_KEYWORDS):
        return "caller_contact_label"
    if any(token.casefold() in lowered for token in _DOCUMENT_NOTICE_KEYWORDS):
        return "document_notice_address"
    return "unknown"


def _strip_ko_name_particle(token: str) -> tuple[str, str]:
    for particle in sorted(_KO_NAME_PARTICLES, key=len, reverse=True):
        if token.endswith(particle) and len(token) > len(particle) + 1:
            return token[: -len(particle)], particle
    return token, ""


def _looks_like_common_location_noun_residue(token: str, glossary_category: str = "") -> bool:
    raw = token or ""
    base, _particle = _strip_ko_name_particle(raw)
    if not raw or glossary_category in _NAME_RESIDUE_CATEGORIES:
        return False
    candidates = (raw, base) if base != raw else (raw,)
    return any(
        candidate in _COMMON_LOCATION_NOUN_SUFFIXES
        or any(candidate.endswith(suffix) and len(candidate) > len(suffix) for suffix in _COMMON_LOCATION_NOUN_SUFFIXES)
        for candidate in candidates
    )


def _looks_like_korean_person_name(token: str, context_after: str, glossary_category: str = "") -> bool:
    base, particle = _strip_ko_name_particle(token)
    if base in _KNOWN_KO_PERSON_TOKENS:
        return True
    if _looks_like_common_location_noun_residue(token, glossary_category):
        return False
    if not (2 <= len(base) <= 4):
        return False
    if base[0] not in _KO_SURNAME_CHARS:
        return False
    return bool(particle or _JA_PARTICLE_AFTER_KO_RE.match(context_after or ""))


def _mixed_script_residue_token(final_translation: str, start: int, end: int) -> dict[str, Any]:
    text = final_translation or ""
    hangul_text = text[start:end]
    if len(hangul_text) > 2:
        return {"text": hangul_text, "start": start, "end": end, "detected": False}
    left = start
    right = end
    while left > 0 and _TARGET_SCRIPT_CHAR_RE.fullmatch(text[left - 1]):
        left -= 1
    while right < len(text) and _TARGET_SCRIPT_CHAR_RE.fullmatch(text[right]):
        right += 1
    token = text[left:right]
    has_hangul = bool(_HANGUL_SPAN_RE.search(token))
    has_target_script = bool(_TARGET_SCRIPT_CHAR_RE.search(token))
    return {
        "text": token,
        "start": left,
        "end": right,
        "detected": bool(has_hangul and has_target_script and (left < start or right > end)),
    }


def _glossary_category_for_residue(token: str, work_memory: WorkMemory | None) -> tuple[str, str]:
    if not work_memory:
        return "", ""
    base, _particle = _strip_ko_name_particle(token)
    for entry in work_memory.approvedGlossary:
        surfaces = [entry.source, *entry.aliases]
        for surface in surfaces:
            source = _clean(surface)
            if not source:
                continue
            if token == source or base == source:
                return entry.category, source
    return "", ""


def _span_has_japanese_particle_after(final_translation: str, end: int) -> bool:
    return bool(_JA_PARTICLE_AFTER_KO_RE.match((final_translation or "")[end : end + 4]))


def _hangul_residue_span_classification(
    *,
    token: str,
    context: str,
    final_translation: str,
    start: int,
    end: int,
    work_memory: WorkMemory | None,
) -> dict[str, Any]:
    glossary_category, glossary_source = _glossary_category_for_residue(token, work_memory)
    has_jp_particle = _span_has_japanese_particle_after(final_translation, end)
    inside_bracket = "[" in context and "]" in context
    mixed_token = _mixed_script_residue_token(final_translation, start, end)
    reasons: list[str] = []
    category = "prose_residue"
    person_risk = False
    common_location_noun = _looks_like_common_location_noun_residue(token, glossary_category)

    if inside_bracket:
        category = "system_ui_residue"
        reasons.append("bracket_context")
    elif glossary_category in _NAME_RESIDUE_CATEGORIES:
        category = "name_residue"
        person_risk = True
        reasons.append(f"approved_glossary_category:{glossary_category}")
    elif mixed_token.get("detected") and len(_HANGUL_SPAN_RE.findall(token)) <= 1 and len(token) <= 2:
        category = "mixed_script_name_residue"
        person_risk = True
        reasons.append("mixed_script_partial_name_token")
    elif glossary_category in _TERM_RESIDUE_CATEGORIES:
        category = "genre_term_residue" if glossary_category == "genre_term" else "prose_residue"
        reasons.append(f"approved_glossary_category:{glossary_category}")
    elif common_location_noun:
        category = "genre_term_residue" if has_jp_particle else "prose_residue"
        reasons.append("common_location_noun_residue")
        if has_jp_particle:
            reasons.append("korean_noun_plus_japanese_particle_without_name_evidence")
    elif _looks_like_korean_person_name(token, (final_translation or "")[end : end + 4], glossary_category):
        category = "name_residue"
        person_risk = True
        reasons.append("korean_name_pattern")
    elif has_jp_particle:
        category = "genre_term_residue"
        reasons.append("korean_noun_plus_japanese_particle_without_name_evidence")
    else:
        reasons.append("hangul_prose_without_name_evidence")

    return {
        "personNameRisk": person_risk,
        "residueCategory": category,
        "jpParticleAttached": has_jp_particle,
        "glossaryCategory": glossary_category,
        "glossarySource": glossary_source,
        "classificationReasons": reasons,
        "mixedScriptNameResidueDetected": category == "mixed_script_name_residue",
        "partialNameResidueDetected": category == "mixed_script_name_residue",
        "commonNounResidueDetected": bool(common_location_noun and category in {"genre_term_residue", "prose_residue"}),
        "nameResidueFalsePositiveAvoided": bool(common_location_noun and category in {"genre_term_residue", "prose_residue"}),
        "repairAffectedToken": mixed_token.get("text") if mixed_token.get("detected") else token,
        "repairStart": mixed_token.get("start") if mixed_token.get("detected") else start,
        "repairEnd": mixed_token.get("end") if mixed_token.get("detected") else end,
    }


def _hangul_integrity_issues(final_translation: str, target_locale: str, work_memory: WorkMemory | None = None) -> list[dict[str, Any]]:
    if target_locale != "ko_ja":
        return []
    issues: list[dict[str, Any]] = []
    spans = []
    for match in _HANGUL_SPAN_RE.finditer(final_translation or ""):
        token = match.group(0)
        context = final_translation[max(0, match.start() - 8) : min(len(final_translation), match.end() + 8)]
        classification = _hangul_residue_span_classification(
            token=token,
            context=context,
            final_translation=final_translation,
            start=match.start(),
            end=match.end(),
            work_memory=work_memory,
        )
        span_start = int(classification.pop("repairStart", match.start()))
        span_end = int(classification.pop("repairEnd", match.end()))
        span_text = str(classification.get("repairAffectedToken") or token)
        if span_start != match.start() or span_end != match.end():
            context = final_translation[max(0, span_start - 8) : min(len(final_translation), span_end + 8)]
        spans.append({"text": span_text, "hangulText": token, "start": span_start, "end": span_end, "context": context, **classification})
    if spans:
        person_spans = [span["text"] for span in spans if span.get("personNameRisk")]
        message = "Japanese output retains Hangul text; review and localize or transliterate the remaining Korean."
        if person_spans:
            message = "Japanese output retains likely Korean person/name text; localize or transliterate it before delivery."
        issues.append(
            _issue(
                "P1",
                "hangul_residue_integrity",
                message,
                target_span=", ".join(span["text"] for span in spans[:8]),
                suggestion="Replace remaining Hangul with natural Japanese wording or transliteration; do not pass mixed Hangul/Kana output as deliverable.",
                auto=True,
                details={"spans": spans[:20], "personNameRisk": bool(person_spans)},
            )
        )
    return issues


def _bracket_integrity_issues(source_text: str, final_translation: str, target_locale: str, work_memory: WorkMemory | None = None) -> list[dict[str, Any]]:
    if target_locale != "ko_ja":
        return []
    source_blocks = _extract_bracket_blocks(source_text)
    target_blocks = _extract_bracket_blocks(final_translation)
    if not source_blocks and not target_blocks:
        return []
    issues: list[dict[str, Any]] = []
    if work_memory and len(target_blocks) > len(source_blocks):
        approved_targets = {entry.target for entry in work_memory.approvedGlossary if entry.target}
        filtered_target_blocks = [block for block in target_blocks if block.get("content") not in approved_targets]
        if len(filtered_target_blocks) == len(source_blocks):
            target_blocks = filtered_target_blocks
    details = {"sourceBlocks": source_blocks, "targetBlocks": target_blocks}
    if len(source_blocks) != len(target_blocks):
        issues.append(
            _issue(
                "P1",
                "bracket_block_count_mismatch",
                "Bracketed blocks were lost, duplicated, or inserted during Japanese translation.",
                source_span=", ".join(block["text"] for block in source_blocks[:8]),
                target_span=", ".join(block["text"] for block in target_blocks[:8]),
                suggestion="Restore bracketed UI/contact/document blocks to the source order; do not move system messages across scenes.",
                auto=True,
                details=details,
            )
        )
        return issues
    mismatches = []
    for index, (source_block, target_block) in enumerate(zip(source_blocks, target_blocks), start=1):
        source_role = source_block.get("role")
        target_role = target_block.get("role")
        if source_role != "unknown" and target_role != "unknown" and source_role != target_role:
            mismatches.append(
                {
                    "index": index,
                    "source": source_block,
                    "target": target_block,
                    "reason": "role_mismatch",
                }
            )
    source_first_status = next((i for i, block in enumerate(source_blocks) if block.get("role") == "status_system_ui"), None)
    target_first_status = next((i for i, block in enumerate(target_blocks) if block.get("role") == "status_system_ui"), None)
    if source_first_status is not None and target_first_status is not None and target_first_status < source_first_status:
        mismatches.append(
            {
                "index": target_first_status + 1,
                "sourceStatusIndex": source_first_status + 1,
                "targetStatusIndex": target_first_status + 1,
                "reason": "system_message_moved_earlier",
            }
        )
    if mismatches:
        first = mismatches[0]
        source_span = ((first.get("source") or {}).get("text") if isinstance(first.get("source"), dict) else "") or ""
        target_span = ((first.get("target") or {}).get("text") if isinstance(first.get("target"), dict) else "") or ""
        issues.append(
            _issue(
                "P1",
                "bracket_block_role_or_order_mismatch",
                "Bracketed block role/order changed during Japanese translation; a contact label, system UI message, or notice appears in the wrong slot.",
                source_span=source_span,
                target_span=target_span,
                suggestion="Keep bracketed blocks aligned to source order and scene role; fix only the misplaced/missing bracket blocks.",
                auto=True,
                details={**details, "mismatches": mismatches},
            )
        )
    return issues


def deterministic_integrity_issues(source_text: str, final_translation: str, target_locale: str, work_memory: WorkMemory | None = None) -> list[dict[str, Any]]:
    return [
        *_hangul_integrity_issues(final_translation, target_locale, work_memory),
        *_bracket_integrity_issues(source_text, final_translation, target_locale, work_memory),
    ]


def _format_bracket_block_list(blocks: list[dict[str, Any]]) -> str:
    if not blocks:
        return "- none"
    return "\n".join(f"{idx}. {block.get('text', '')}" for idx, block in enumerate(blocks, start=1))


_REVISION_SENTENCE_BOUNDARY_RE = re.compile(r"[\n\r\u3002\uff01\uff1f!?]")


def _revision_span_index(span: dict[str, Any], key: str, default: int = -1) -> int:
    try:
        return int(span.get(key, default))
    except (TypeError, ValueError):
        return default


def _revision_sentence_window(final_translation: str, span: dict[str, Any]) -> dict[str, Any]:
    if not final_translation:
        return {"start": 0, "end": 0, "text": ""}
    start = _revision_span_index(span, "start")
    end = _revision_span_index(span, "end")
    if start < 0 or end <= start or start >= len(final_translation):
        return {"start": 0, "end": min(len(final_translation), 600), "text": final_translation[:600]}
    left_match = None
    for match in _REVISION_SENTENCE_BOUNDARY_RE.finditer(final_translation, 0, start):
        left_match = match
    left = 0 if left_match is None else left_match.end()
    right_match = _REVISION_SENTENCE_BOUNDARY_RE.search(final_translation, end)
    right = len(final_translation) if right_match is None else right_match.end()
    return {"start": left, "end": right, "text": final_translation[left:right].strip()}


def _bracket_revision_context(source_text: str, final_translation: str, issues: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    mismatch = next(
        (issue for issue in issues if issue.get("code") == "bracket_block_count_mismatch" and issue.get("autoRevisionEligible")),
        None,
    )
    residue = next(
        (issue for issue in issues if issue.get("code") == "hangul_residue_integrity" and issue.get("autoRevisionEligible")),
        None,
    )
    parts: list[str] = []
    meta: dict[str, Any] = {}
    if mismatch:
        details = mismatch.get("details") or {}
        source_blocks = details.get("sourceBlocks") if isinstance(details.get("sourceBlocks"), list) else _extract_bracket_blocks(source_text)
        target_blocks = details.get("targetBlocks") if isinstance(details.get("targetBlocks"), list) else _extract_bracket_blocks(final_translation)
        parts.append("\n".join([
            "[BRACKET PRESERVING REVISION]",
            f"- source bracket block count: {len(source_blocks)}",
            "- source bracket block list:",
            _format_bracket_block_list(source_blocks),
            f"- target bracket block count: {len(target_blocks)}",
            "- target bracket block list:",
            _format_bracket_block_list(target_blocks),
            "- Preserve the same number and order of bracketed blocks in the Japanese target.",
            "- This is not a full rewrite request: restore/fix only bracketed contact, document, and system UI blocks while keeping the surrounding prose stable.",
            "- If the target has zero bracketed blocks, restore each source bracket as a localized Japanese bracket block at the corresponding scene position.",
            "- Do not copy Korean source bracket text unchanged into the target.",
            "- Examples: [박 팀장] => [パクチーム長]; [대한민국 헌터협회 자산관리국] => [大韓民国ハンター協会 資産管理局]; [서울특별시 중구 낙원동 지하상가 B-17구역] => [ソウル特別市 中区 ナクウォンドン 地下商店街 B-17区域]; [관리자 튜토리얼이 시작됩니다.] => [管理者チュートリアルが開始されます。]",
        ]))
        meta.update({"sourceBlockCount": len(source_blocks), "targetBlockCount": len(target_blocks), "sourceBlocks": source_blocks, "targetBlocks": target_blocks})
    if residue:
        spans = ((residue.get("details") or {}).get("spans") or [])[:20]
        residue_lines = [
            (
                f"{idx}. text={span.get('text', '')}; "
                f"start={_revision_span_index(span, 'start')}; "
                f"end={_revision_span_index(span, 'end')}; "
                f"sentenceWindow={_revision_sentence_window(final_translation, span).get('text', '')}"
            )
            for idx, span in enumerate(spans, start=1)
        ]
        parts.append("\n".join([
            "[HANGUL RESIDUE REVISION]",
            "- The Japanese target still contains Korean/Hangul spans. Use each detector start/end to rewrite the full sentenceWindow into natural Japanese.",
            "- Do not leave Korean prose, Korean particles, or Korean names in the Japanese output.",
            "- Keep already-correct Japanese prose stable.",
            "- The comma-joined targetSpan is diagnostic only; do not repair only that term list.",
            "- Hangul residue sentence windows:",
            "\n".join(residue_lines) if residue_lines else "- none",
        ]))
        meta["hangulResidueSpans"] = spans
    glossary_issues = [
        issue
        for issue in issues
        if issue.get("code") == "glossary_consistency" and issue.get("autoRevisionEligible")
    ][:20]
    if glossary_issues:
        glossary_lines = []
        for idx, issue in enumerate(glossary_issues, start=1):
            details = issue.get("details") or {}
            source = str(details.get("source") or issue.get("sourceSpan") or "").strip()
            target = str(details.get("target") or issue.get("targetSpan") or "").strip()
            aliases = details.get("aliases") if isinstance(details.get("aliases"), list) else []
            alias_text = f"; aliases={', '.join(str(alias) for alias in aliases[:5] if alias)}" if aliases else ""
            glossary_lines.append(f"{idx}. source={source}; requiredTarget={target}{alias_text}")
        parts.append("\n".join([
            "[APPROVED GLOSSARY REVISION]",
            "- These are approved hard glossary entries whose source appears in the Korean source but whose exact target is missing from the Japanese target.",
            "- Revise the corresponding Japanese sentence(s) so each requiredTarget appears exactly.",
            "- Treat spacing, middle dots, kana, and kanji forms as exact-match constraints; do not substitute near variants.",
            "- Do not append a glossary note or list; integrate the approved target naturally in the translation.",
            "- Approved glossary misses:",
            "\n".join(glossary_lines),
        ]))
        meta["glossaryRevisionTargets"] = glossary_lines
    return "\n\n".join(part for part in parts if part), meta


_KO_JA_SAFE_SIGNAGE_REPLACEMENTS: dict[str, str] = {
    "\uc218\uc120": "\u4fee\u7406",
    "\ubd84\uc2dd": "\u8efd\u98df",
    "\uc5f4\uc1e0": "\u9375",
    "\ubcf5\uc0ac": "\u8907\u88fd",
    "\ud734\ub300\ud3f0": "\u643a\u5e2f",
    "\ub9e4\uc785": "\u8cb7\u53d6",
    "\uc784\ub300": "\u8cc3\u8cb8",
    "\ubb38\uc758": "\u554f\u3044\u5408\u308f\u305b",
}
_SIGNAGE_OPENERS = "\u300e\u300c\u300a\u3008\u3010[('\"\u2018\u201c"
_SIGNAGE_CLOSERS = "\u300f\u300d\u300b\u3009\u3011])'\"\u2019\u201d"

_KO_JA_SYSTEM_UI_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\uc601\uc5ed \ubc29\uc5b4 \uc911", "\u9818\u57df\u9632\u885b\u4e2d"),
    ("\ubc29\uc5b4 \uc911", "\u9632\u885b\u4e2d"),
    ("\uad76\uc8fc\ub9bc", "\u98e2\u3048"),
    ("\uc704\ud5d8\ub3c4", "\u5371\u967a\u5ea6"),
    ("\uc5b4\uba38\ub2c8", "\u6bcd"),
    ("\uc0c1\ud0dc", "\u72b6\u614b"),
    ("\uc601\uc5ed", "\u9818\u57df"),
    ("\ubc29\uc5b4", "\u9632\u885b"),
    ("\ubd88\uc548", "\u4e0d\u5b89"),
    ("\ub0ae\uc74c", "\u4f4e"),
    ("\uc911\uac04", "\u4e2d"),
    ("\ub192\uc74c", "\u9ad8"),
)
_SYSTEM_UI_BRACKET_HINTS = (
    "\u72b6\u614b",
    "\u5371\u967a\u5ea6",
    "\u7ba1\u7406",
    "\u5831\u916c",
    "\u30c1\u30e5\u30fc\u30c8\u30ea\u30a2\u30eb",
    "\uc0c1\ud0dc",
    "\uc704\ud5d8\ub3c4",
    "\uad00\ub9ac",
    "\ubcf4\uc0c1",
    "\ud29c\ud1a0\ub9ac\uc5bc",
)
_KO_JA_KNOWN_PERSON_RESIDUE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\uac15\ub3c4\uc724", "\u30ab\u30f3\u30fb\u30c9\u30e6\u30f3"),
    ("\ucc28\ubbfc\ud601", "\u30c1\u30e3\u30fb\u30df\u30f3\u30d2\u30e7\u30af"),
    ("\ubbfc\ud558\ub9b0", "\u30df\u30f3\u30fb\u30cf\u30ea\u30f3"),
    ("\uc724\uc11c\ud558", "\u30e6\u30f3\u30fb\u30bd\u30cf"),
    ("\ud55c\uc7ac\ubbfc", "\u30cf\u30f3\u30fb\u30b8\u30a7\u30df\u30f3"),
    ("\ucca0\uc218", "\u30c1\u30e7\u30eb\u30b9"),
    ("\ub099\uc6d0\ub3d9", "\u30ca\u30af\u30a6\u30a9\u30f3\u30c9\u30f3"),
    ("\ub3c4\uc724", "\u30c9\u30e6\u30f3"),
)


def _is_system_ui_bracket_block(block: dict[str, Any]) -> bool:
    content = str(block.get("content") or "")
    if block.get("role") == "status_system_ui":
        return True
    if block.get("role") == "caller_contact_label" and any(term in content for term, _ in _KO_JA_SYSTEM_UI_REPLACEMENTS):
        return True
    if any(hint in content for hint in _SYSTEM_UI_BRACKET_HINTS):
        return True
    return "/" in content and bool(_HANGUL_RE.search(content)) and any(term in content for term, _ in _KO_JA_SYSTEM_UI_REPLACEMENTS)


def _is_safe_signage_label_context(text: str, start: int, end: int) -> bool:
    if start < 0 or end > len(text) or start >= end:
        return False
    window_start = max(0, start - 24)
    window_end = min(len(text), end + 24)
    before = text[window_start:start]
    after = text[end:window_end]
    opener_index = max(before.rfind(ch) for ch in _SIGNAGE_OPENERS)
    closer_candidates = [idx for idx in (after.find(ch) for ch in _SIGNAGE_CLOSERS) if idx >= 0]
    if opener_index < 0 or not closer_candidates:
        return False
    segment = before[opener_index + 1 :] + text[start:end] + after[: min(closer_candidates)]
    if "\n" in segment or len(segment.strip()) > 18:
        return False
    return True


def _replace_safe_signage_token(text: str, token: str, replacement: str) -> tuple[str, int]:
    output: list[str] = []
    cursor = 0
    count = 0
    for match in re.finditer(re.escape(token), text):
        output.append(text[cursor : match.start()])
        if _is_safe_signage_label_context(text, match.start(), match.end()):
            output.append(replacement)
            count += 1
        else:
            output.append(match.group(0))
        cursor = match.end()
    output.append(text[cursor:])
    return "".join(output), count


def _replace_system_ui_bracket_hangul(text: str) -> tuple[str, list[dict[str, str]]]:
    output: list[str] = []
    cursor = 0
    replacements: list[dict[str, str]] = []
    for match in _BRACKET_BLOCK_RE.finditer(text or ""):
        output.append(text[cursor : match.start()])
        raw = match.group(0)
        content = raw[1:-1]
        block = {"text": raw, "content": content.strip(), "start": match.start(), "end": match.end(), "role": _bracket_role(content)}
        if not _is_system_ui_bracket_block(block):
            output.append(raw)
            cursor = match.end()
            continue
        patched_content = content
        for source, target in _KO_JA_SYSTEM_UI_REPLACEMENTS:
            if source in patched_content:
                patched_content = patched_content.replace(source, target)
                replacements.append({"source": source, "target": target})
        output.append("[" + patched_content + "]")
        cursor = match.end()
    output.append(text[cursor:])
    return "".join(output), replacements


def _maybe_apply_deterministic_system_ui_hangul_patch(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None, issues: list[dict[str, Any]], iterations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if target_locale != "ko_ja" or any(issue.get("priority") == "P0" for issue in issues):
        return final_translation, issues, _judge(issues)
    if not any(issue.get("code") == "hangul_residue_integrity" and issue.get("autoRevisionEligible") for issue in issues):
        return final_translation, issues, _judge(issues)
    patched, replacements = _replace_system_ui_bracket_hangul(final_translation)
    if patched == final_translation or not replacements or not _clean(patched) or len(patched.strip()) < max(1, int(len(final_translation.strip()) * 0.5)):
        return final_translation, issues, _judge(issues)
    patched_issues = _critic_issues(source_text=source_text, final_translation=patched, target_locale=target_locale, idiom_notes=idiom_notes, safety_metadata=safety_metadata, work_memory=work_memory)
    patched_judge = _judge(patched_issues)
    iterations.append({"iteration": len(iterations) + 1, "action": "Deterministic System UI Hangul Residue Patch", "critique": patched_issues, "judge": patched_judge, "patch": {"replacements": replacements}})
    return patched, patched_issues, patched_judge


def _maybe_apply_deterministic_known_person_residue_patch(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None, issues: list[dict[str, Any]], iterations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if target_locale != "ko_ja" or any(issue.get("priority") == "P0" for issue in issues):
        return final_translation, issues, _judge(issues)
    residue_issues = [issue for issue in issues if issue.get("code") == "hangul_residue_integrity" and issue.get("autoRevisionEligible")]
    if not residue_issues:
        return final_translation, issues, _judge(issues)
    risky_tokens = {
        str(span.get("text") or "")
        for issue in residue_issues
        for span in ((issue.get("details") or {}).get("spans") or [])
        if span.get("personNameRisk")
    }
    patched = final_translation
    replacements: list[dict[str, str]] = []
    for source, target in _KO_JA_KNOWN_PERSON_RESIDUE_REPLACEMENTS:
        if not any(token == source or token.startswith(source) for token in risky_tokens):
            continue
        if not _contains_hard_glossary_source_surface(source_text, source, target_locale):
            continue
        before = patched
        entry = GlossaryEntry(source=source, target=target, category="person", priority="hard")
        patched, count = _replace_hard_glossary_source_residue(patched, entry, target_locale)
        if count:
            replacements.append({"source": source, "target": target, "count": str(count)})
        else:
            patched = before
    if patched == final_translation or not replacements or not _clean(patched) or len(patched.strip()) < max(1, int(len(final_translation.strip()) * 0.5)):
        return final_translation, issues, _judge(issues)
    patched_issues = _critic_issues(source_text=source_text, final_translation=patched, target_locale=target_locale, idiom_notes=idiom_notes, safety_metadata=safety_metadata, work_memory=work_memory)
    patched_judge = _judge(patched_issues)
    iterations.append({"iteration": len(iterations) + 1, "action": "Deterministic Known Person Residue Patch", "critique": patched_issues, "judge": patched_judge, "patch": {"replacements": replacements}})
    return patched, patched_issues, patched_judge


def _maybe_apply_deterministic_known_proper_noun_variant_patch(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None, issues: list[dict[str, Any]], iterations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if target_locale != "ko_ja" or any(issue.get("priority") == "P0" for issue in issues):
        return final_translation, issues, _judge(issues)
    patched = final_translation
    replacements: list[dict[str, str]] = []
    for (source, target), variants in _KNOWN_GLOSSARY_WRONG_VARIANTS.items():
        if source not in source_text or target in patched:
            continue
        for variant in variants:
            if variant and variant in patched:
                patched = patched.replace(variant, target)
                replacements.append({"source": source, "target": target, "variant": variant})
    if patched == final_translation or not replacements or not _clean(patched) or len(patched.strip()) < max(1, int(len(final_translation.strip()) * 0.5)):
        return final_translation, issues, _judge(issues)
    patched_issues = _critic_issues(source_text=source_text, final_translation=patched, target_locale=target_locale, idiom_notes=idiom_notes, safety_metadata=safety_metadata, work_memory=work_memory)
    patched_judge = _judge(patched_issues)
    iterations.append({"iteration": len(iterations) + 1, "action": "Deterministic Known Proper Noun Variant Patch", "critique": patched_issues, "judge": patched_judge, "patch": {"replacements": replacements}})
    return patched, patched_issues, patched_judge


def _maybe_apply_deterministic_hangul_residue_patch(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None, issues: list[dict[str, Any]], iterations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if target_locale != "ko_ja" or any(issue.get("priority") == "P0" for issue in issues):
        return final_translation, issues, _judge(issues)
    residue_issues = [issue for issue in issues if issue.get("code") == "hangul_residue_integrity" and issue.get("autoRevisionEligible")]
    if not residue_issues:
        return final_translation, issues, _judge(issues)
    patched = final_translation
    replacements: list[dict[str, str]] = []
    for issue in residue_issues:
        for span in (issue.get("details") or {}).get("spans") or []:
            token = str(span.get("text") or "")
            replacement = _KO_JA_SAFE_SIGNAGE_REPLACEMENTS.get(token)
            if not replacement or token not in source_text or token not in patched:
                continue
            patched, count = _replace_safe_signage_token(patched, token, replacement)
            if count:
                replacements.append({"source": token, "target": replacement})
    if patched == final_translation or not _clean(patched) or len(patched.strip()) < max(1, int(len(final_translation.strip()) * 0.5)):
        return final_translation, issues, _judge(issues)
    patched_issues = _critic_issues(source_text=source_text, final_translation=patched, target_locale=target_locale, idiom_notes=idiom_notes, safety_metadata=safety_metadata, work_memory=work_memory)
    patched_judge = _judge(patched_issues)
    iterations.append({"iteration": len(iterations) + 1, "action": "Deterministic Hangul Residue Patch", "critique": patched_issues, "judge": patched_judge, "patch": {"replacements": replacements}})
    return patched, patched_issues, patched_judge


def classify_translation_delivery(issues: list[dict[str, Any]], *, integrity_block: bool = False) -> tuple[str, str | None]:
    codes = {str(issue.get("code") or issue.get("type") or "") for issue in issues}
    has_review = any(issue.get("priority") in {"P1", "P2", "P3"} for issue in issues)
    has_p0 = any(issue.get("priority") == "P0" for issue in issues)
    if "blocked_translation_safety" in codes:
        return "blocked_translation_safety", "translation_safety_failed"
    if integrity_block or has_p0:
        return "blocked_translation_integrity", "translation_integrity_failed"
    if has_review:
        return "qa_warning", None
    return "deliverable", None


def _critic_issues(*, source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], safety_metadata: dict[str, Any] | None, work_memory: WorkMemory | None = None) -> list[dict[str, Any]]:
    metadata = safety_metadata or {}
    issues: list[dict[str, Any]] = []
    if not _clean(final_translation):
        issues.append(_issue("P0", "empty_translation", "Final translation is empty.", auto=True))
    if metadata.get("delivery_status") == "blocked_translation_safety":
        issues.append(_issue("P0", "blocked_translation_safety", "Translation safety blocked the output.", auto=True))
    issues.extend(deterministic_integrity_issues(source_text, final_translation, target_locale, work_memory))
    if _contains_system_artifact(final_translation):
        issues.append(_issue("P0", "system_message_missing", "System/debug marker appears in the translation.", auto=True))
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


def _review_cards_from_issues(issues: list[dict[str, Any]], idiom_notes: list[IdiomNote]) -> list[dict[str, Any]]:
    note_by_span = {n.sourceSpan: n for n in idiom_notes}
    cards = []
    for idx, issue in enumerate(issues, 1):
        if issue.get("priority") not in {"P1", "P2", "P3"}:
            continue
        note = note_by_span.get(str(issue.get("sourceSpan") or ""))
        cards.append({"id": f"v3-card-{idx}", "priority": issue.get("priority", "P1"), "status": "pending", "decisionType": issue.get("code", "review_item"), "sourceSpan": issue.get("sourceSpan", ""), "targetSpan": issue.get("targetSpan", ""), "currentTranslation": issue.get("targetSpan", ""), "explanation": issue.get("message", ""), "authorQuestion": "이 표현을 더 의역해도 되는지 확인해 주세요." if note else "이 표현의 의도와 톤을 확인해 주세요.", "suggestedActions": [issue.get("suggestion") or note.translatorNote] if (issue.get("suggestion") or note) else []})
    return cards


def run_translation_loop(source_text: str, target_locale: str, translator_guideline: str, editor_guideline: str, *, idiom_notes: list[IdiomNote] | None = None, max_iterations: int = 2, translate_once: Callable[[bool, int], tuple[str, dict[str, Any]]] | None = None, work_memory: Any = None) -> TranslationLoopResult:
    del translator_guideline, editor_guideline
    notes = idiom_notes or []
    memory = normalize_work_memory(work_memory, target_locale)
    max_rounds = max(1, min(int(max_iterations or 2), 2))
    iterations = []
    def call(strict: bool, attempt: int, revision_context: str = "") -> tuple[str, dict[str, Any]]:
        if translate_once is None:
            return _mock_literary_translation(source_text, target_locale, notes, work_memory=memory), {"mock_v3": True}
        try:
            return translate_once(strict, attempt, revision_context)  # type: ignore[misc]
        except TypeError:
            return translate_once(strict, attempt)
    final, metadata = call(False, 0)
    issues = _critic_issues(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory)
    judge = _judge(issues)
    iterations.append({"iteration": 1, "action": "Literary Translator", "critique": issues, "judge": judge})
    patch_meta = {"attempted": False, "patched": False, "replacements": [], "reason": "not_needed"}
    revision_attempted = False
    if judge["autoRevisionRequired"] and max_rounds > 1:
        revision_attempted = True
        revision_context, bracket_revision = _bracket_revision_context(source_text, final, issues)
        final = _mock_literary_translation(source_text, target_locale, notes, work_memory=memory) if translate_once is None else call(True, 1, revision_context)[0]
        metadata = {**metadata, "delivery_status": "deliverable", "v3_revision_strategy": "deterministic_integrity_retry"}
        issues = _critic_issues(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory)
        judge = _judge(issues)
        iterations.append({"iteration": 2, "action": "Deterministic QA Revision", "critique": issues, "judge": judge, "revisionScope": "Fix only hard glossary target mismatches, Hangul residue, and bracket/system-message integrity; preserve idioms, voice, and style unless directly affected.", "revisionContext": revision_context, "bracketRevision": bracket_revision})
    if revision_attempted:
        final, issues, judge = _maybe_apply_deterministic_system_ui_hangul_patch(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory, issues=issues, iterations=iterations)
        final, issues, judge = _maybe_apply_deterministic_known_person_residue_patch(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory, issues=issues, iterations=iterations)
        final, issues, judge = _maybe_apply_deterministic_hangul_residue_patch(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory, issues=issues, iterations=iterations)
        final, issues, judge, patch_meta = _maybe_apply_deterministic_glossary_patch(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory, issues=issues, iterations=iterations)
    final, issues, judge = _maybe_apply_deterministic_known_proper_noun_variant_patch(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory, issues=issues, iterations=iterations)
    final, issues, judge = _maybe_apply_deterministic_known_person_residue_patch(source_text=source_text, final_translation=final, target_locale=target_locale, idiom_notes=notes, safety_metadata=metadata, work_memory=memory, issues=issues, iterations=iterations)
    status, error_code = classify_translation_delivery(issues)
    return TranslationLoopResult("" if status.startswith("blocked_translation_") else final, iterations, judge, issues, _review_cards_from_issues(issues, notes), status, error_code)


def _glossary_rationale_items(final_translation: str, work_memory: WorkMemory | None) -> list[TranslationRationaleItem]:
    if not work_memory:
        return []
    items = []
    for entry in work_memory.approvedGlossary[:8]:
        if entry.target and entry.target in final_translation:
            items.append(TranslationRationaleItem(entry.source, entry.target, "terminology", "approved_glossary", "작품 내 용어 일관성을 위해 승인된 표기인 '{target}'을 사용했습니다.".format(target=entry.target)))
    return items


def write_translation_rationale(source_text: str, final_translation: str, target_locale: str, idiom_notes: list[IdiomNote], translator_guideline: str, editor_guideline: str, qa_issues: list[dict[str, Any]], work_memory: Any = None) -> TranslationRationale:
    del source_text, target_locale, translator_guideline, editor_guideline
    memory = normalize_work_memory(work_memory, target_locale="")
    blocked = not _clean(final_translation)
    items: list[TranslationRationaleItem] = []
    if not blocked:
        for note in idiom_notes[:6]:
            items.append(TranslationRationaleItem(note.sourceSpan, "", "idiom", "adaptive", "{span}은 {meaning}이라는 뜻이므로 이미지 직역보다 장면의 감정과 압박이 자연스럽게 전달되도록 처리했습니다.".format(span=note.sourceSpan, meaning=note.meaningKo)))
        items.extend(_glossary_rationale_items(final_translation, memory))
        if not items:
            items.append(TranslationRationaleItem("", "", "style", "balanced", "원문의 사건 진행과 감정선을 유지하면서 목표 언어 독자가 바로 읽을 수 있는 문장 흐름을 우선했습니다."))
    for issue in qa_issues[:2]:
        if issue.get("priority") != "P0":
            items.append(TranslationRationaleItem(str(issue.get("sourceSpan") or ""), "", "review", "defer_to_author_review", str(issue.get("message") or "검수자가 확인할 여지가 있는 표현입니다.")))
    literal = 35 if idiom_notes else 55
    return TranslationRationale("왜 이렇게 번역했는지", "번역이 안전 기준을 통과하지 못해 독자용 번역을 비웠습니다." if blocked else "원문의 의미를 보존하되 관용어와 장르 문체는 목표 언어에서 자연스럽게 읽히도록 조정했습니다.", "대사와 서술의 속도를 살리고, 과도한 직역보다 웹소설 독자의 몰입감을 우선합니다.", {"literal": literal, "adaptive": 100 - literal}, items[:8])


def _failure_signals(issues: list[dict[str, Any]]) -> list[str]:
    mapping = {"idiom_literal_risk_detected", "glossary_consistency", "glossary_forbidden_translation", "korean_residue_detected", "hangul_residue_integrity", "bracket_block_count_mismatch", "bracket_block_role_or_order_mismatch", "system_message_missing"}
    signals = []
    for issue in issues:
        code = str(issue.get("code") or issue.get("type") or "")
        if code in mapping and code not in signals:
            signals.append(code if code != "glossary_consistency" else "glossary_consistency_issue")
    return signals


def build_v3_literary_package(source_text: str, target_locale: str, *, genre: str = "Modern Korean web novel", work_memory: Any = None, max_iterations: int = 2, translate_once: Callable[[bool, int], tuple[str, dict[str, Any]]] | None = None, idiom_detection_mode: str = "rule") -> V3LiteraryPackageResult:
    memory = normalize_work_memory(work_memory, target_locale)
    mode = _clean(idiom_detection_mode).lower() or "rule"
    if mode not in _ALLOWED_IDIOM_MODES:
        mode = "rule"
    notes = detect_idiom_notes(source_text, target_locale, mode=mode)
    source_evidence = analyze_source_references(source_text, target_locale)
    rag = build_rag_packets(source_text, target_locale, genre, notes, work_memory=memory, source_evidence=source_evidence)
    guidelines = build_v3_guidelines(source_text, target_locale, genre, notes, rag)
    loop = run_translation_loop(source_text, target_locale, guidelines.translatorGuideline, guidelines.editorGuideline, idiom_notes=notes, max_iterations=max_iterations, translate_once=translate_once, work_memory=memory)
    rationale = write_translation_rationale(source_text, loop.finalTranslation, target_locale, notes, guidelines.translatorGuideline, guidelines.editorGuideline, loop.qaIssues, work_memory=memory)
    internal = {"idiomNotes": [asdict(n) for n in notes], "idiomDetection": {"mode": mode, "notes": [asdict(n) for n in notes], "ftEnabled": False}, "characterReferences": source_evidence.get("characterReferences") or [], "entityCandidates": source_evidence.get("entityCandidates") or [], "ragPackets": asdict(rag), "workMemory": asdict(memory) if memory else None, "guidelines": asdict(guidelines), "iterations": loop.iterations, "judge": loop.judge, "failureSignals": _failure_signals(loop.qaIssues), "maxIterations": min(max(1, int(max_iterations or 2)), 2), "maxRevisionPass": 1, "mockBoundaries": {"idiomDetector": "rule adapter by default; llm/ft adapters are placeholders", "sourceAnalyzer": "deterministic source-evidence adapter; no LLM call", "ragPackets": "static/mock packet builder", "workMemory": "in-memory payload only"}}
    internal["userVisibleErrorCode"] = loop.userVisibleErrorCode
    return V3LiteraryPackageResult("v3_literary_package", loop.deliveryStatus, loop.finalTranslation, rationale, loop.qaIssues, loop.authorReviewCards, internal, userVisibleErrorCode=loop.userVisibleErrorCode)
