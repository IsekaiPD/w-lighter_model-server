from __future__ import annotations

import re
from dataclasses import asdict
from typing import Annotated, Any, Callable, Literal, TypedDict

try:  # optional at runtime; requirements.txt includes langgraph for graph mode
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - exercised only when dependency is absent
    END = START = StateGraph = None

from .literary_package import (
    IdiomNote,
    V3LiteraryPackageResult,
    analyze_source_references,
    classify_translation_delivery,
    build_rag_packets,
    build_v3_guidelines,
    detect_idiom_notes,
    normalize_work_memory,
    run_translation_loop,
    write_translation_rationale,
    _critic_issues,
    _failure_signals,
    _judge,
    _mock_literary_translation,
    _maybe_apply_deterministic_known_person_residue_patch,
    _maybe_apply_deterministic_known_proper_noun_variant_patch,
    _review_cards_from_issues,
)


GraphNodeName = Literal[
    "normalize_input",
    "load_work_memory",
    "prepare_translation_context",
    "run_literary_translation",
    "deterministic_precheck",
    "review_voice",
    "review_naturalness",
    "review_cultural",
    "review_glossary",
    "review_integrity",
    "aggregate_review",
    "repair_or_accept",
    "final_integrity_check",
    "run_qa_and_repair",
    "chunk_source_text",
    "detect_annotation_candidates",
    "retrieve_korean_culture_context",
    "write_reader_endnotes",
    "filter_rank_endnotes",
    "align_endnotes_to_final_translation",
    "build_translation_package",
    "persist_result",
    "skip_persist",
    "capture_glossary_candidates",
    "skip_capture",
]


def _append_trace(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(left or []) + list(right or [])


class TranslationGraphState(TypedDict, total=False):
    request: dict[str, Any]
    normalizedRequest: dict[str, Any]
    targetCountry: str | None
    targetLocale: str
    workId: Any
    episodeId: Any
    sourceText: str
    title: str
    genre: str
    workMemory: Any
    workMemorySource: str
    workMemoryFallbackReason: str
    approvedGlossary: list[dict[str, Any]]
    sourceAnalysis: dict[str, Any]
    idiomNotes: list[IdiomNote]
    translatorBrief: dict[str, Any]
    editorEvidence: dict[str, Any]
    rationaleEvidence: dict[str, Any]
    guidelines: dict[str, str]
    draftTranslation: str
    draftMetadata: dict[str, Any]
    deterministicPrecheckIssues: list[dict[str, Any]]
    reviewFindings: Annotated[list[dict[str, Any]], _append_trace]
    aggregateReview: dict[str, Any]
    graphReviewTrace: Annotated[list[dict[str, Any]], _append_trace]
    finalIntegrityCheck: dict[str, Any]
    finalTranslation: str
    qaIssues: list[dict[str, Any]]
    deliveryStatus: str
    repairTrace: list[dict[str, Any]]
    revisionHistory: list[dict[str, Any]]
    graphRepairTrace: list[dict[str, Any]]
    sourceChunks: list[dict[str, Any]]
    annotationCandidates: list[dict[str, Any]]
    annotationRetrievals: list[dict[str, Any]]
    readerEndnotesDraft: list[dict[str, Any]]
    readerEndnotes: list[dict[str, Any]]
    annotationTrace: dict[str, Any]
    translationPackage: V3LiteraryPackageResult
    savedTranslationId: Any
    glossarySavedCount: int
    glossaryCandidateCapture: dict[str, Any]
    maxIterations: int
    graphExecutionFrame: str
    _ragPackets: Any
    _guidelinesObject: Any
    _loop: Any
    errors: list[dict[str, Any]]
    graphTrace: Annotated[list[dict[str, Any]], _append_trace]
    persistHook: Callable[[TranslationGraphState], dict[str, Any]] | None
    captureHook: Callable[[TranslationGraphState], dict[str, Any]] | None
    annotationCandidateHook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None
    annotationRetrievalHook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None
    readerEndnoteWriterHook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None
    # LLM 리뷰어 hook: (state, reviewer_type) -> list[v3 issue dict]. 없으면 결정론적 리뷰만.
    reviewerHook: Callable[[TranslationGraphState, str], list[dict[str, Any]]] | None


def _trace(state: TranslationGraphState, node: GraphNodeName, **data: Any) -> TranslationGraphState:
    row = {
        "node": node,
        "status": data.pop("status", "finished"),
        "skipped": bool(data.pop("skipped", False)),
    }
    row["started"] = True
    row["finished"] = row["status"] == "finished"
    row.update(data)
    state.setdefault("graphTrace", []).append(row)
    return state


def normalize_input(state: TranslationGraphState) -> TranslationGraphState:
    request = dict(state.get("request") or {})
    source_text = str(state.get("sourceText") or request.get("sourceText") or request.get("source_text") or "").strip()
    target_locale = str(state.get("targetLocale") or request.get("targetLocale") or request.get("target_locale") or "ko_ja").strip()
    genre = str(state.get("genre") or request.get("genre") or request.get("workGenre") or "Modern Korean web novel")
    normalized = {
        "sourceText": source_text,
        "targetLocale": target_locale,
        "targetCountry": state.get("targetCountry") or request.get("targetCountry") or request.get("target_country"),
        "mode": request.get("mode") or request.get("pipeline") or "v3_literary_package",
        "title": state.get("title") or request.get("title") or "",
        "genre": genre,
        "workId": state.get("workId", request.get("workId") or request.get("work_id")),
        "episodeId": state.get("episodeId", request.get("episodeId") or request.get("episode_id")),
        "saveTranslationResult": bool(request.get("saveTranslationResult") or request.get("save_translation_result")),
        "captureGlossaryCandidates": bool(request.get("captureGlossaryCandidates") or request.get("capture_glossary_candidates")),
    }
    state.update(
        {
            "normalizedRequest": normalized,
            "sourceText": source_text,
            "targetLocale": target_locale,
            "targetCountry": normalized["targetCountry"],
            "title": normalized["title"],
            "genre": genre,
            "workId": normalized["workId"],
            "episodeId": normalized["episodeId"],
        }
    )
    return _trace(state, "normalize_input")


def load_work_memory(state: TranslationGraphState) -> TranslationGraphState:
    request = state.get("request") or {}
    work_memory = state.get("workMemory")
    source = state.get("workMemorySource") or "none"
    fallback_reason = state.get("workMemoryFallbackReason") or ""
    if work_memory is None:
        request_memory = request.get("workMemory") or request.get("work_memory")
        if isinstance(request_memory, dict):
            work_memory = request_memory
            source = "request_payload"
    memory = normalize_work_memory(work_memory, state["targetLocale"])
    approved = [asdict(entry) for entry in memory.approvedGlossary] if memory else []
    state.update(
        {
            "workMemory": memory,
            "workMemorySource": source,
            "workMemoryFallbackReason": fallback_reason,
            "approvedGlossary": approved,
        }
    )
    return _trace(state, "load_work_memory", approvedGlossaryCount=len(approved))


def prepare_translation_context(state: TranslationGraphState) -> TranslationGraphState:
    notes = detect_idiom_notes(state["sourceText"], state["targetLocale"])
    source_analysis = analyze_source_references(state["sourceText"], state["targetLocale"])
    rag = build_rag_packets(
        state["sourceText"],
        state["targetLocale"],
        state.get("genre") or "Modern Korean web novel",
        notes,
        work_memory=state.get("workMemory"),
        source_evidence=source_analysis,
    )
    guidelines = build_v3_guidelines(
        state["sourceText"],
        state["targetLocale"],
        state.get("genre") or "Modern Korean web novel",
        notes,
        rag,
    )
    state.update(
        {
            "idiomNotes": notes,
            "sourceAnalysis": source_analysis,
            "translatorBrief": rag.translatorBrief,
            "editorEvidence": rag.editorEvidence,
            "rationaleEvidence": rag.rationaleEvidence,
            "guidelines": asdict(guidelines),
            "_ragPackets": rag,
            "_guidelinesObject": guidelines,
        }
    )
    return _trace(state, "prepare_translation_context")


def _graph_translate_once(
    *,
    source_text: str,
    target_locale: str,
    idiom_notes: list[IdiomNote],
    work_memory: Any,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None,
    strict: bool,
    attempt: int,
    revision_context: str,
) -> tuple[str, dict[str, Any]]:
    if translate_once is None:
        return _mock_literary_translation(source_text, target_locale, idiom_notes, work_memory=work_memory), {"mock_v3": True}
    try:
        return translate_once(strict, attempt, revision_context)  # type: ignore[misc]
    except TypeError:
        return translate_once(strict, attempt)


def run_literary_translation(
    state: TranslationGraphState,
    *,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> TranslationGraphState:
    if translate_once is None:
        draft, metadata = _graph_translate_once(
            source_text=state["sourceText"],
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            work_memory=state.get("workMemory"),
            translate_once=None,
            strict=False,
            attempt=1,
            revision_context="",
        )
    else:
        # Keep external/model translator calls centralized in repair_or_accept so
        # graph reviewer structure does not perturb established retry ordering.
        draft, metadata = "", {"draft_deferred_to": "repair_or_accept"}
    state["draftTranslation"] = draft
    state["draftMetadata"] = dict(metadata or {})
    return _trace(
        state,
        "run_literary_translation",
        draftAvailable=bool(draft.strip()),
        draftDeferred=not bool(draft.strip()),
        metadataKeys=sorted(str(key) for key in (metadata or {}).keys() if str(key) not in {"api_key", "password", "secret"}),
    )


def _hangul_residue_issue(issues: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (issue for issue in issues if issue.get("code") == "hangul_residue_integrity" and issue.get("autoRevisionEligible")),
        None,
    )


def _hangul_residue_spans(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue = _hangul_residue_issue(issues)
    spans = (issue.get("details") or {}).get("spans") if issue else []
    return list(spans or [])


def _hangul_residue_category(issues: list[dict[str, Any]], final_translation: str = "") -> str:
    spans = _hangul_residue_spans(issues)
    if not spans:
        return "none"
    partial_categories = {"mixed_script_name_residue", "partial_name_residue"}
    has_partial_name = any(span.get("residueCategory") in partial_categories or span.get("partialNameResidueDetected") for span in spans)
    has_name = any((span.get("residueCategory") == "name_residue") or (span.get("personNameRisk") and span.get("residueCategory") not in {"genre_term_residue", "prose_residue", "system_ui_residue", *partial_categories}) for span in spans)
    has_genre = any(span.get("residueCategory") == "genre_term_residue" for span in spans)
    has_prose = any((span.get("residueCategory") in {"genre_term_residue", "prose_residue"}) or (not span.get("personNameRisk") and span.get("residueCategory") != "system_ui_residue") for span in spans)
    has_system = any(span.get("residueCategory") == "system_ui_residue" or ("[" in str(span.get("context") or "") and "]" in str(span.get("context") or "")) for span in spans)
    if has_system and not has_prose and not has_name and not has_partial_name:
        return "system_ui_residue"
    if has_partial_name and not has_prose and not has_system:
        return "mixed_script_name_residue"
    if has_name and not has_prose and not has_system and not has_partial_name:
        return "name_residue"
    if has_genre and not has_name and not has_system and not has_partial_name:
        return "genre_term_residue"
    if has_prose and not has_name and not has_system and not has_partial_name:
        return "prose_residue"
    return "mixed"


_GRAPH_HANGUL_CHAR_RE = re.compile(r"[\uac00-\ud7a3]")
_GRAPH_TARGET_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_SENTENCE_LEFT_BOUNDARY_RE = re.compile(r"[\n\r\u3002\uff01\uff1f!?]")
_SENTENCE_RIGHT_BOUNDARY_RE = re.compile(r"[\n\r\u3002\uff01\uff1f!?]")


def _graph_nonspace(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _graph_script_ratio(text: str, pattern: re.Pattern[str]) -> float:
    compact = _graph_nonspace(text)
    if not compact:
        return 0.0
    return sum(1 for char in compact if pattern.match(char)) / len(compact)


def _graph_integrity_metrics(source_text: str, final_translation: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    source_compact = _graph_nonspace(source_text)
    target_compact = _graph_nonspace(final_translation)
    source_prefix = source_compact[:200]
    target_prefix = target_compact[:200]
    prefix_len = min(len(source_prefix), len(target_prefix), 200)
    source_prefix_match_200 = bool(prefix_len >= 40 and source_prefix[:prefix_len] == target_prefix[:prefix_len])
    residual_hangul_ratio = _graph_script_ratio(final_translation, _GRAPH_HANGUL_CHAR_RE)
    target_script_ratio = _graph_script_ratio(final_translation, _GRAPH_TARGET_SCRIPT_RE)
    metadata = metadata or {}
    source_copy_suspected = bool(
        metadata.get("source_copy_status") == "fail"
        or source_prefix_match_200
        or (len(target_compact) >= 80 and residual_hangul_ratio >= 0.25 and target_script_ratio < 0.45)
    )
    return {
        "source_prefix_match_200": source_prefix_match_200,
        "sourceCopyDetected": source_copy_suspected,
        "residualHangulRatio": round(residual_hangul_ratio, 4),
        "targetScriptRatio": round(target_script_ratio, 4),
    }


def _has_general_body_hangul_residue(issues: list[dict[str, Any]], final_translation: str = "") -> bool:
    spans = _hangul_residue_spans(issues)
    if not spans:
        return False
    if _hangul_residue_category(issues, final_translation) == "system_ui_residue":
        return False
    first_500_spans = [span for span in spans if int(span.get("start") or 0) < 500]
    hangul_char_count = sum(len(str(span.get("text") or "")) for span in spans)
    residual_hangul_ratio = _graph_script_ratio(final_translation, _GRAPH_HANGUL_CHAR_RE)
    return (
        len(spans) >= 10
        or len(first_500_spans) >= 8
        or hangul_char_count >= 30
        or (hangul_char_count >= 17 and residual_hangul_ratio >= 0.02)
    )


def _has_prose_hangul_residue(issues: list[dict[str, Any]], final_translation: str = "") -> bool:
    spans = _hangul_residue_spans(issues)
    if not spans:
        return False
    category = _hangul_residue_category(issues, final_translation)
    if category in {"system_ui_residue", "name_residue"}:
        return False
    repairable_categories = {"genre_term_residue", "prose_residue", "mixed_script_name_residue", "partial_name_residue"}
    return any(
        span.get("residueCategory") in repairable_categories
        or span.get("partialNameResidueDetected")
        or span.get("mixedScriptNameResidueDetected")
        or (not span.get("personNameRisk") and span.get("residueCategory") != "system_ui_residue")
        for span in spans
    )


def _hangul_char_count_from_spans(spans: list[dict[str, Any]]) -> int:
    return sum(len(_GRAPH_HANGUL_CHAR_RE.findall(str(span.get("text") or ""))) for span in spans)


def _is_bracket_or_system_context(span: dict[str, Any]) -> bool:
    context = str(span.get("context") or "")
    start = int(span.get("start") or -1)
    end = int(span.get("end") or -1)
    if start < 0 or end < 0:
        span_text = str(span.get("text") or "")
        span_index = context.find(span_text) if span_text else -1
        if span_index < 0:
            return False
        before = context[:span_index]
        after = context[span_index + len(span_text) :]
        return "[" in before[-40:] and "]" in after[:40]
    # Conservative local check: residue embedded inside a short bracket-like UI
    # label is system/UI residue, not general prose targeted-repair input.
    before = context[: max(0, context.find(str(span.get("text") or "")))]
    after_index = context.find(str(span.get("text") or ""))
    after = context[after_index + len(str(span.get("text") or "")) :] if after_index >= 0 else ""
    return "[" in before[-40:] and "]" in after[:40]


def _small_prose_residue_evidence(
    *,
    issues: list[dict[str, Any]],
    final_translation: str,
    source_text: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    spans = _hangul_residue_spans(issues)
    category = _hangul_residue_category(issues, final_translation)
    metrics = _graph_integrity_metrics(source_text, final_translation, metadata)
    hangul_char_count = _hangul_char_count_from_spans(spans)
    repairable_categories = {"genre_term_residue", "prose_residue", "mixed_script_name_residue", "partial_name_residue"}
    repair_spans = [
        span
        for span in spans
        if span.get("residueCategory") in repairable_categories
        or span.get("partialNameResidueDetected")
        or span.get("mixedScriptNameResidueDetected")
        or (not span.get("personNameRisk") and span.get("residueCategory") != "system_ui_residue")
    ]
    non_name_spans = [span for span in repair_spans if span.get("residueCategory") not in {"mixed_script_name_residue", "partial_name_residue"}]
    partial_name_spans = [span for span in repair_spans if span.get("residueCategory") in {"mixed_script_name_residue", "partial_name_residue"} or span.get("partialNameResidueDetected") or span.get("mixedScriptNameResidueDetected")]
    genre_spans = [span for span in non_name_spans if span.get("residueCategory") == "genre_term_residue" or span.get("jpParticleAttached")]
    system_like_spans = [span for span in spans if _is_bracket_or_system_context(span)]
    name_false_positive_avoided = any(
        "korean_noun_plus_japanese_particle_without_name_evidence" in (span.get("classificationReasons") or [])
        or span.get("nameResidueFalsePositiveAvoided")
        or (span.get("jpParticleAttached") and span.get("residueCategory") in {"genre_term_residue", "prose_residue"})
        for span in non_name_spans
    )
    detected = bool(
        spans
        and repair_spans
        and category in {"prose_residue", "genre_term_residue", "mixed_script_name_residue", "partial_name_residue", "mixed"}
        and not system_like_spans
        and not metrics["sourceCopyDetected"]
        and not metrics["source_prefix_match_200"]
        and not _has_general_body_hangul_residue(issues, final_translation)
        and 0 < hangul_char_count <= 16
        and 0 < len(repair_spans) <= 3
        and metrics["residualHangulRatio"] <= 0.10
        and metrics["targetScriptRatio"] >= 0.45
    )
    return {
        "detected": detected,
        "spanCount": len(repair_spans),
        "proseSpanCount": len(non_name_spans),
        "genreTermSpanCount": len(genre_spans),
        "hangulCharCount": hangul_char_count,
        "residualHangulRatio": metrics["residualHangulRatio"],
        "targetScriptRatio": metrics["targetScriptRatio"],
        "sourceCopyDetected": metrics["sourceCopyDetected"],
        "source_prefix_match_200": metrics["source_prefix_match_200"],
        "bulkProseResidueDetected": _has_general_body_hangul_residue(issues, final_translation),
        "hangulResidueCategory": category,
        "smallGenreTermResidueDetected": bool(detected and genre_spans),
        "mixedScriptNameResidueDetected": bool(detected and partial_name_spans and any(span.get("mixedScriptNameResidueDetected") or span.get("residueCategory") == "mixed_script_name_residue" for span in partial_name_spans)),
        "partialNameResidueDetected": bool(detected and partial_name_spans),
        "commonNounResidueDetected": bool(detected and any(span.get("commonNounResidueDetected") for span in non_name_spans)),
        "nameResidueFalsePositiveAvoided": bool(name_false_positive_avoided),
        "repairAffectedToken": ", ".join(str(span.get("repairAffectedToken") or span.get("text") or "") for span in repair_spans[:3]),
    }


def _coerce_span_index(span: dict[str, Any], key: str, default: int = -1) -> int:
    try:
        return int(span.get(key, default))
    except (TypeError, ValueError):
        return default


def _target_sentence_window(final_translation: str, span: dict[str, Any]) -> dict[str, Any]:
    """Return the actual target sentence containing the Hangul residue span.

    The QA issue targetSpan is only a diagnostic comma-joined term list; the
    repair target must instead be the sentence window at the detector's
    start/end offsets in finalTranslation so replacement can be index-based.
    """
    if not final_translation:
        return {"start": 0, "end": 0, "text": ""}
    start = _coerce_span_index(span, "start")
    end = _coerce_span_index(span, "end")
    if start < 0 or end <= start or start >= len(final_translation):
        context = str(span.get("context") or "")
        span_text = str(span.get("text") or span.get("hangulText") or "")
        if context and span_text:
            context_index = final_translation.find(context)
            span_index = context.find(span_text)
            if context_index >= 0 and span_index >= 0:
                start = context_index + span_index
                end = start + len(span_text)
        if start < 0 or end <= start or start >= len(final_translation):
            return {"start": 0, "end": min(len(final_translation), 600), "text": final_translation[:600]}
    end = min(end, len(final_translation))
    left_match = None
    for match in _SENTENCE_LEFT_BOUNDARY_RE.finditer(final_translation, 0, start):
        left_match = match
    left = 0 if left_match is None else left_match.end()
    right_match = _SENTENCE_RIGHT_BOUNDARY_RE.search(final_translation, end)
    right = len(final_translation) if right_match is None else right_match.end()
    return {"start": left, "end": right, "text": final_translation[left:right].strip()}


def _merge_target_sentence_windows(final_translation: str, spans: list[dict[str, Any]]) -> dict[str, Any]:
    windows = [_target_sentence_window(final_translation, span) for span in spans]
    windows = [window for window in windows if str(window.get("text") or "").strip()]
    if not windows:
        return {"start": 0, "end": min(len(final_translation), 600), "text": final_translation[:600]}
    start = min(int(window["start"]) for window in windows)
    end = max(int(window["end"]) for window in windows)
    return {"start": start, "end": end, "text": final_translation[start:end].strip()}


def _strip_code_fence(text: str) -> str:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    return candidate


def _extract_window_repair_candidate(original: str, window: dict[str, Any], repaired_output: str) -> str:
    candidate = _strip_code_fence(repaired_output)
    if not candidate:
        return ""
    start = int(window.get("start") or 0)
    end = int(window.get("end") or start)
    prefix = original[:start]
    suffix = original[end:]
    # Backward-compatible guard: if a model returns the full translation despite
    # the sentence-window prompt, extract the changed window and still apply it
    # by the original detector offsets.
    if prefix and candidate.startswith(prefix) and (not suffix or candidate.endswith(suffix)):
        suffix_len = len(suffix)
        return candidate[len(prefix) : len(candidate) - suffix_len if suffix_len else len(candidate)].strip()
    if suffix and candidate.endswith(suffix):
        return candidate[: -len(suffix)].strip()
    if prefix and candidate.startswith(prefix):
        return candidate[len(prefix) :].strip()
    return candidate


def _replace_target_sentence_window(original: str, window: dict[str, Any], repaired_window: str) -> str:
    start = max(0, min(len(original), int(window.get("start") or 0)))
    end = max(start, min(len(original), int(window.get("end") or start)))
    replacement = _strip_code_fence(repaired_window)
    return original[:start] + replacement + original[end:]


def _local_target_context(final_translation: str, span: dict[str, Any]) -> str:
    if not final_translation:
        return ""
    return str(_target_sentence_window(final_translation, span).get("text") or "")[:600]


def _source_context_for_targeted_repair(source_text: str) -> str:
    # Do not include full long source text in trace; the prompt can use a bounded
    # source excerpt as local context when exact alignment is unavailable.
    return (source_text or "").strip()[:900]


def _format_approved_glossary_for_repair(state: TranslationGraphState, limit: int = 24) -> str:
    glossary = state.get("approvedGlossary") or []
    rows: list[str] = []
    for entry in glossary[:limit]:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source") or "").strip()
        target = str(entry.get("target") or "").strip()
        if source and target:
            rows.append(f"- {source} => {target}")
    return "\n".join(rows) if rows else "- none"


def _graph_targeted_small_residue_context(
    state: TranslationGraphState,
    *,
    final_translation: str,
    issues: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> str:
    spans = _hangul_residue_spans(issues)[:3]
    repair_window = _merge_target_sentence_windows(final_translation, spans)
    affected = []
    for index, span in enumerate(spans, start=1):
        window = _target_sentence_window(final_translation, span)
        affected.append(
            "\n".join(
                [
                    f"{index}. residualSpan={str(span.get('text') or '')}",
                    f"   residueCategory={str(span.get('residueCategory') or '')}",
                    f"   detectorStart={_coerce_span_index(span, 'start')}",
                    f"   detectorEnd={_coerce_span_index(span, 'end')}",
                    f"   sentenceWindowStart={window.get('start')}",
                    f"   sentenceWindowEnd={window.get('end')}",
                    f"   repairAffectedToken={str(span.get('repairAffectedToken') or span.get('text') or '')}",
                    f"   mixedScriptNameResidueDetected={bool(span.get('mixedScriptNameResidueDetected'))}",
                    f"   partialNameResidueDetected={bool(span.get('partialNameResidueDetected'))}",
                    f"   sentenceWindow={window.get('text') or ''}",
                ]
            )
        )
    return "\n".join(
        [
            "[GRAPH TARGETED SMALL PROSE RESIDUE REPAIR]",
            f"- targetLocale: {state.get('targetLocale') or 'ko_ja'}",
            "- The Japanese translation still contains a few Korean/Hangul prose, genre-term, or mixed-script partial-name residues.",
            "- Rewrite only the affected Japanese sentence or short local paragraph into natural Japanese.",
            "- For mixed-script partial-name residue, repair the whole affected token using the approved glossary/name map first; if absent, use natural Japanese name notation from context.",
            "- Do not change unrelated sentences.",
            "- Do not copy Korean prose.",
            "- Do not leave Korean words, Korean particles, or Korean sentence fragments.",
            "- Preserve web novel pacing and tone.",
            "- Preserve bracket/system UI blocks exactly in count and order.",
            "- Preserve approved glossary/name map terms.",
            "- Return only the repaired sentence window text shown under [repair sentence window].",
            "- Do not return the full translation.",
            "- No explanation.",
            "",
            "[small residue evidence]",
            f"- residualHangulCharCount: {evidence.get('hangulCharCount')}",
            f"- residualHangulRatio: {evidence.get('residualHangulRatio')}",
            f"- affectedSpanCount: {evidence.get('spanCount')}",
            f"- smallGenreTermResidueDetected: {bool(evidence.get('smallGenreTermResidueDetected'))}",
            f"- mixedScriptNameResidueDetected: {bool(evidence.get('mixedScriptNameResidueDetected'))}",
            f"- partialNameResidueDetected: {bool(evidence.get('partialNameResidueDetected'))}",
            f"- commonNounResidueDetected: {bool(evidence.get('commonNounResidueDetected'))}",
            f"- repairAffectedToken: {evidence.get('repairAffectedToken') or ''}",
            f"- mixedScriptNameResidueDetected: {bool(evidence.get('mixedScriptNameResidueDetected'))}",
            f"- partialNameResidueDetected: {bool(evidence.get('partialNameResidueDetected'))}",
            f"- commonNounResidueDetected: {bool(evidence.get('commonNounResidueDetected'))}",
            f"- repairAffectedToken: {evidence.get('repairAffectedToken') or ''}",
            "",
            "[affected target spans]",
            "\n".join(affected) if affected else "- none",
            "",
            "[repair sentence window]",
            f"start={repair_window.get('start')} end={repair_window.get('end')}",
            str(repair_window.get("text") or ""),
            "",
            "[current full target translation for context only; do not return this full text]",
            final_translation[:6000],
            "",
            "[bounded source context]",
            _source_context_for_targeted_repair(state.get("sourceText") or ""),
            "",
            "[approved glossary/name map]",
            _format_approved_glossary_for_repair(state),
        ]
    )


def _graph_targeted_small_residue_fallback_context(
    state: TranslationGraphState,
    *,
    final_translation: str,
    issues: list[dict[str, Any]],
    evidence: dict[str, Any],
    failed_reason: str,
) -> str:
    spans = _hangul_residue_spans(issues)[:3]
    repair_window = _merge_target_sentence_windows(final_translation, spans)
    affected = []
    for index, span in enumerate(spans, start=1):
        window = _target_sentence_window(final_translation, span)
        affected.append(
            "\n".join(
                [
                    f"{index}. residualSpan={str(span.get('text') or '')}",
                    f"   residueCategory={str(span.get('residueCategory') or '')}",
                    f"   detectorStart={_coerce_span_index(span, 'start')}",
                    f"   detectorEnd={_coerce_span_index(span, 'end')}",
                    f"   sentenceWindowStart={window.get('start')}",
                    f"   sentenceWindowEnd={window.get('end')}",
                    f"   sentenceWindow={window.get('text') or ''}",
                ]
            )
        )
    return "\n".join(
        [
            "[GRAPH TARGETED SMALL PROSE RESIDUE FALLBACK]",
            f"- Previous targeted repair failed for: {failed_reason or 'hangul_residue_remaining'}.",
            "- This is the final allowed targeted fallback attempt; do not perform another retry.",
            "- Repair only the affected Japanese sentence or short local paragraph listed below.",
            "- Do not rewrite unrelated sentences or append commentary.",
            "- Do not copy Korean source prose.",
            "- Do not leave Korean/Hangul words, Korean particles, or mixed Hangul/Kana residue.",
            "- If a residual term is unknown, render it naturally in Japanese prose rather than preserving Hangul.",
            "- Preserve bracket/system UI block count and order exactly.",
            "- Preserve web novel pacing, dialogue tone, and paragraph flow.",
            "- Preserve approved glossary/name map terms.",
            "- Return only the repaired sentence window text shown under [repair sentence window].",
            "- Do not return the full translation.",
            "- No explanation.",
            "",
            "[small residue evidence before fallback]",
            f"- residualHangulCharCount: {evidence.get('hangulCharCount')}",
            f"- residualHangulRatio: {evidence.get('residualHangulRatio')}",
            f"- affectedSpanCount: {evidence.get('spanCount')}",
            f"- smallGenreTermResidueDetected: {bool(evidence.get('smallGenreTermResidueDetected'))}",
            "",
            "[affected target spans]",
            "\n".join(affected) if affected else "- none",
            "",
            "[repair sentence window]",
            f"start={repair_window.get('start')} end={repair_window.get('end')}",
            str(repair_window.get("text") or ""),
            "",
            "[current full target translation for context only; do not return this full text]",
            final_translation[:6000],
            "",
            "[bounded source context]",
            _source_context_for_targeted_repair(state.get("sourceText") or ""),
            "",
            "[approved glossary/name map]",
            _format_approved_glossary_for_repair(state),
        ]
    )


def _graph_integrity_failure_type(*, source_copy_detected: bool, prose_residue_detected: bool) -> str:
    if source_copy_detected and prose_residue_detected:
        return "source_copy_and_prose_residue"
    if source_copy_detected:
        return "source_copy"
    if prose_residue_detected:
        return "prose_residue"
    return "none"


def _graph_filter_non_hangul_residue_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        if issue.get("code") != "hangul_residue_integrity":
            filtered.append(issue)
            continue
        details = dict(issue.get("details") or {})
        spans = list(details.get("spans") or [])
        real_spans = [span for span in spans if _GRAPH_HANGUL_CHAR_RE.search(str(span.get("text") or ""))]
        if not real_spans:
            continue
        cloned = dict(issue)
        cloned["targetSpan"] = ", ".join(str(span.get("text") or "") for span in real_spans[:8])
        cloned["details"] = {**details, "spans": real_spans[:20], "personNameRisk": any(span.get("residueCategory") == "name_residue" or span.get("personNameRisk") for span in real_spans)}
        filtered.append(cloned)
    return filtered


def _graph_failure_category(delivery_status: str, issues: list[dict[str, Any]]) -> str:
    if delivery_status == "blocked_translation_safety":
        return "safety"
    if delivery_status == "blocked_translation_integrity" or any(issue.get("code") == "hangul_residue_integrity" for issue in issues):
        return "integrity"
    if delivery_status == "qa_warning":
        return "qa_warning"
    return "none"


def _debug_artifact_summary(metadata: dict[str, Any] | None, *, candidate_discarded: bool = False, discard_reason: str = "") -> dict[str, Any]:
    artifact = dict((metadata or {}).get("debug_artifact") or {})
    if not artifact:
        return {
            "debugArtifactDir": None,
            "rawOutputPath": None,
            "parsedCandidatePath": None,
            "metricsPath": None,
            "fallbackApplied": False,
            "candidateDiscarded": candidate_discarded,
            "discardReason": discard_reason,
        }
    summary = {
        "debugArtifactDir": artifact.get("debugArtifactDir"),
        "rawOutputPath": artifact.get("rawOutputPath"),
        "parsedCandidatePath": artifact.get("parsedCandidatePath"),
        "metricsPath": artifact.get("metricsPath"),
        "promptPreviewPath": artifact.get("promptPreviewPath"),
        "promptMetadataPath": artifact.get("promptMetadataPath"),
        "fallbackApplied": bool(artifact.get("fallbackApplied")),
        "fallbackReason": artifact.get("fallbackReason") or "",
        "candidateDiscarded": bool(candidate_discarded or artifact.get("candidateDiscarded")),
        "discardReason": discard_reason or artifact.get("discardReason") or "",
    }
    return summary


_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_REVIEWER_ISSUE_CODES = {
    "voice": {"character_voice", "dialogue_tone", "honorific_register"},
    "naturalness": {"idiom_literal_risk_detected", "awkward_literal_translation", "webnovel_style"},
    "cultural": {"cultural_context_needed", "reader_endnote_candidate"},
    "glossary": {"glossary_consistency", "glossary_forbidden_translation", "name_residue", "terminology_consistency"},
    "integrity": {
        "empty_translation",
        "blocked_translation_safety",
        "hangul_residue_integrity",
        "korean_residue_detected",
        "bracket_block_count_mismatch",
        "bracket_block_role_or_order_mismatch",
        "system_message_missing",
    },
}


def _issue_priority(issue: dict[str, Any]) -> str:
    priority = str(issue.get("priority") or "P3")
    return priority if priority in _PRIORITY_RANK else "P3"


def _max_priority(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "none"
    return min((_issue_priority(issue) for issue in issues), key=lambda value: _PRIORITY_RANK.get(value, 9))


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for issue in issues:
        key = (
            str(issue.get("code") or issue.get("type") or ""),
            str(issue.get("sourceSpan") or ""),
            str(issue.get("targetSpan") or ""),
            str(issue.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(issue))
    return sorted(deduped, key=lambda issue: _PRIORITY_RANK.get(_issue_priority(issue), 9))


def _finding_from_issue(reviewer_type: str, issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "reviewerType": reviewer_type,
        "code": issue.get("code") or issue.get("type") or "review_finding",
        "priority": _issue_priority(issue),
        "message": issue.get("message") or "",
        "sourceSpan": issue.get("sourceSpan") or "",
        "targetSpan": issue.get("targetSpan") or "",
        "suggestion": issue.get("suggestion") or "",
        "autoRevisionEligible": bool(issue.get("autoRevisionEligible")),
        "issue": dict(issue),
    }


def _record_review_trace(
    state: TranslationGraphState,
    *,
    node: GraphNodeName,
    reviewer_type: str,
    findings: list[dict[str, Any]],
) -> TranslationGraphState:
    issues = [dict(finding.get("issue") or {}) for finding in findings]
    row = {
        "node": node,
        "reviewerType": reviewer_type,
        "issueCount": len(findings),
        "maxSeverity": _max_priority(issues),
        "repairRequired": any(bool(issue.get("autoRevisionEligible")) or _issue_priority(issue) == "P0" for issue in issues),
        "finalTranslationChanged": False,
        "deliveryStatusChanged": False,
        "findings": findings,
    }
    # Return reducer-friendly deltas without mutating the incoming list objects.
    # LangGraph parallel reviewer branches share the pre-branch state snapshot;
    # in-place append/extend makes the shallow "before" snapshot see the same
    # list mutation, so _node_delta concludes there is no new review payload.
    state["graphReviewTrace"] = list(state.get("graphReviewTrace") or []) + [row]
    state["reviewFindings"] = list(state.get("reviewFindings") or []) + list(findings)
    return _trace(state, node, **{key: value for key, value in row.items() if key != "node"})


def deterministic_precheck(state: TranslationGraphState) -> TranslationGraphState:
    metadata = _graph_sanitize_integrity_metadata(state.get("draftMetadata") or {})
    issues = _critic_issues(
        source_text=state["sourceText"],
        final_translation=state.get("draftTranslation") or "",
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata={**metadata, "delivery_status": metadata.get("delivery_status") or "deliverable"},
        work_memory=state.get("workMemory"),
    )
    issues = _graph_filter_non_hangul_residue_issues(issues)
    state["deterministicPrecheckIssues"] = issues
    return _trace(
        state,
        "deterministic_precheck",
        issueCount=len(issues),
        maxSeverity=_max_priority(issues),
        finalTranslationChanged=False,
        deliveryStatusChanged=False,
    )


def _llm_reviewer_findings(state: TranslationGraphState, reviewer_type: str) -> list[dict[str, Any]]:
    """주입된 LLM 리뷰어 hook을 호출해 (advisory) findings를 만든다.

    hook은 (state, reviewer_type) -> list[v3 issue dict]. 리뷰 실패가 그래프를 막지
    않도록 예외는 빈 리스트로 흡수한다(reviewers.py의 fail-soft와 동일 철학).
    """
    hook = state.get("reviewerHook")
    if hook is None:
        return []
    try:
        raw_issues = hook(state, reviewer_type) or []
    except Exception:
        return []
    return [_finding_from_issue(reviewer_type, issue) for issue in raw_issues if isinstance(issue, dict)]


def _review_by_codes(state: TranslationGraphState, reviewer_type: str, node: GraphNodeName) -> TranslationGraphState:
    codes = _REVIEWER_ISSUE_CODES[reviewer_type]
    issues = [
        issue
        for issue in state.get("deterministicPrecheckIssues") or []
        if str(issue.get("code") or issue.get("type") or "") in codes
    ]
    findings = [_finding_from_issue(reviewer_type, issue) for issue in issues]
    findings += _llm_reviewer_findings(state, reviewer_type)
    return _record_review_trace(state, node=node, reviewer_type=reviewer_type, findings=findings)


def review_voice(state: TranslationGraphState) -> TranslationGraphState:
    return _review_by_codes(state, "voice", "review_voice")


def review_naturalness(state: TranslationGraphState) -> TranslationGraphState:
    return _review_by_codes(state, "naturalness", "review_naturalness")


def review_cultural(state: TranslationGraphState) -> TranslationGraphState:
    findings: list[dict[str, Any]] = []
    if state.get("annotationCandidates"):
        findings.append(
            {
                "reviewerType": "cultural",
                "code": "reader_endnote_candidate",
                "priority": "P2",
                "message": "Annotation branch produced reader-endnote candidates.",
                "sourceSpan": "",
                "targetSpan": "",
                "suggestion": "Keep readerEndnotes separate from finalTranslation.",
                "autoRevisionEligible": False,
                "issue": {
                    "code": "reader_endnote_candidate",
                    "priority": "P2",
                    "message": "Annotation branch produced reader-endnote candidates.",
                    "autoRevisionEligible": False,
                },
            }
        )
    issues = [
        issue
        for issue in state.get("deterministicPrecheckIssues") or []
        if str(issue.get("code") or issue.get("type") or "") in _REVIEWER_ISSUE_CODES["cultural"]
    ]
    findings.extend(_finding_from_issue("cultural", issue) for issue in issues)
    findings += _llm_reviewer_findings(state, "cultural")
    return _record_review_trace(state, node="review_cultural", reviewer_type="cultural", findings=findings)


def review_glossary(state: TranslationGraphState) -> TranslationGraphState:
    return _review_by_codes(state, "glossary", "review_glossary")


def review_integrity(state: TranslationGraphState) -> TranslationGraphState:
    return _review_by_codes(state, "integrity", "review_integrity")


def aggregate_review(state: TranslationGraphState) -> TranslationGraphState:
    findings = list(state.get("reviewFindings") or [])
    reviewer_trace = list(state.get("graphReviewTrace") or [])
    reviewer_summaries = [
        {
            "node": row.get("node"),
            "reviewerType": row.get("reviewerType"),
            "issueCount": int(row.get("issueCount") or 0),
            "maxSeverity": row.get("maxSeverity") or "none",
            "repairRequired": bool(row.get("repairRequired")),
        }
        for row in reviewer_trace
    ]
    issues = _dedupe_issues([dict(finding.get("issue") or {}) for finding in findings if finding.get("issue")])
    repair_required = any(_issue_priority(issue) == "P0" or bool(issue.get("autoRevisionEligible")) for issue in issues)
    integrity_required = any(str(issue.get("code") or "") in _REVIEWER_ISSUE_CODES["integrity"] for issue in issues)
    glossary_required = any(str(issue.get("code") or "") in _REVIEWER_ISSUE_CODES["glossary"] for issue in issues)
    if integrity_required:
        repair_strategy = "integrity_guarded_repair"
    elif glossary_required:
        repair_strategy = "glossary_guarded_repair"
    elif repair_required:
        repair_strategy = "central_repair"
    else:
        repair_strategy = "accept_or_light_review"
    state["aggregateReview"] = {
        "issueCount": len(issues),
        "maxSeverity": _max_priority(issues),
        "repairRequired": repair_required,
        "repairStrategy": repair_strategy,
        "qaIssueCandidates": issues,
        "reviewerSummaries": reviewer_summaries,
        "reviewerIssueCounts": {
            str(summary.get("reviewerType") or summary.get("node") or "unknown"): int(summary.get("issueCount") or 0)
            for summary in reviewer_summaries
        },
        "finalTranslationChanged": False,
        "deliveryStatusChanged": False,
    }
    return _trace(
        state,
        "aggregate_review",
        aggregateIssueCount=len(issues),
        maxSeverity=state["aggregateReview"]["maxSeverity"],
        repairRequired=repair_required,
        repairStrategy=repair_strategy,
        finalTranslationChanged=False,
        deliveryStatusChanged=False,
    )


def _graph_sanitize_integrity_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(metadata or {})
    if data.get("delivery_status") != "blocked_translation_safety":
        return data
    integrity_failure = (
        data.get("residual_hangul_status") == "fail"
        or data.get("source_copy_status") == "fail"
        or data.get("locale_adherence_status") == "fail"
    )
    explicit_safety_signal = any(
        data.get(key)
        for key in (
            "provider_safety_refusal",
            "policy_refusal",
            "safety_refusal",
            "content_policy_block",
            "provider_policy_block",
        )
    )
    if integrity_failure and not explicit_safety_signal:
        data["delivery_status"] = "deliverable"
        data["user_visible_error_code"] = None
        data["graph_integrity_metadata_downgraded_from_safety"] = True
    return data


def _graph_clean_retranslation_context(integrity_failure_type: str) -> str:
    return "\n".join(
        [
            "[GRAPH CLEAN FULL TRANSLATOR RETRY]",
            f"- Integrity failure type: {integrity_failure_type}.",
            "- Output Japanese only.",
            "- Do not copy Korean prose.",
            "- Translate every Korean sentence into natural Japanese.",
            "- Preserve bracket/system UI block count and order.",
            "- Preserve web novel pacing and dialogue tone.",
            "- Do not append readerEndnotes into finalTranslation.",
            "- Keep finalTranslation as translation text only.",
        ]
    )


def _graph_strict_clean_fallback_context(integrity_failure_type: str) -> str:
    return "\n".join(
        [
            "[GRAPH STRICT CLEAN FINAL FALLBACK]",
            f"- Previous clean full retry was discarded for: {integrity_failure_type}.",
            "- This is the final allowed fallback attempt; do not perform another retry.",
            "- Output only the complete Japanese translation.",
            "- Do not copy Korean source prose, Korean sentence order artifacts, or mixed Hangul/Kana residue.",
            "- If a term is unknown, translate it naturally in Japanese prose rather than leaving Korean text.",
            "- The output must not begin with the same source prefix or reproduce the Korean source.",
            "- Preserve bracket/system UI block count and order exactly.",
            "- Preserve web novel pacing, dialogue tone, and paragraph flow.",
            "- Do not append readerEndnotes, annotations, commentary, markdown, or explanations into finalTranslation.",
            "- Keep finalTranslation as translation text only.",
        ]
    )


def _targeted_repair_failure_reason(
    *,
    final_translation: str,
    issues: list[dict[str, Any]],
    metrics: dict[str, Any],
    before_target_script_ratio: float,
) -> str:
    if not final_translation.strip():
        return "empty_translation"
    if metrics.get("sourceCopyDetected"):
        return "source_copy_regression"
    if any(issue.get("code") in {"bracket_block_count_mismatch", "bracket_block_role_or_order_mismatch", "system_message_missing"} for issue in issues):
        return "bracket_or_system_block_regression"
    if _has_prose_hangul_residue(issues, final_translation):
        return "hangul_residue_remaining"
    if float(metrics.get("targetScriptRatio") or 0.0) + 0.02 < before_target_script_ratio:
        return "target_script_ratio_regression"
    return ""


def _maybe_targeted_repair_small_prose_residue(
    state: TranslationGraphState,
    *,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None,
    final: str,
    issues: list[dict[str, Any]],
    metadata: dict[str, Any],
    base_attempt: int,
    clean_retry_succeeded: bool,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], bool]:
    loop = state.get("_loop")
    if loop is None:
        return final, issues, metadata, False
    evidence = _small_prose_residue_evidence(
        issues=issues,
        final_translation=final,
        source_text=state.get("sourceText") or "",
        metadata=metadata,
    )
    if not evidence["detected"]:
        return final, issues, metadata, False
    repair_window = _merge_target_sentence_windows(final, _hangul_residue_spans(issues)[:3])
    context = _graph_targeted_small_residue_context(state, final_translation=final, issues=issues, evidence=evidence)
    attempt = base_attempt + 1
    repaired_window_output, repair_metadata = _graph_translate_once(
        source_text=state["sourceText"],
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        work_memory=state.get("workMemory"),
        translate_once=translate_once,
        strict=True,
        attempt=attempt,
        revision_context=context,
    )
    repaired_window = _extract_window_repair_candidate(final, repair_window, repaired_window_output)
    repaired = _replace_target_sentence_window(final, repair_window, repaired_window)
    sanitized_repair_metadata = _graph_sanitize_integrity_metadata(repair_metadata)
    repaired_issues = _critic_issues(
        source_text=state["sourceText"],
        final_translation=repaired,
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata={**sanitized_repair_metadata, "delivery_status": sanitized_repair_metadata.get("delivery_status") or "deliverable"},
        work_memory=state.get("workMemory"),
    )
    repaired_issues = _graph_filter_non_hangul_residue_issues(repaired_issues)
    repaired_judge = _judge(repaired_issues)
    repaired, repaired_issues, repaired_judge = _maybe_apply_deterministic_known_person_residue_patch(
        source_text=state["sourceText"],
        final_translation=repaired,
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata=sanitized_repair_metadata,
        work_memory=state.get("workMemory"),
        issues=repaired_issues,
        iterations=loop.iterations,
    )
    repaired, repaired_issues, repaired_judge = _maybe_apply_deterministic_known_proper_noun_variant_patch(
        source_text=state["sourceText"],
        final_translation=repaired,
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata=sanitized_repair_metadata,
        work_memory=state.get("workMemory"),
        issues=repaired_issues,
        iterations=loop.iterations,
    )
    repaired_issues = _graph_filter_non_hangul_residue_issues(repaired_issues)
    repaired_judge = _judge(repaired_issues)
    after_metrics = _graph_integrity_metrics(state.get("sourceText") or "", repaired, sanitized_repair_metadata)
    failure_reason = _targeted_repair_failure_reason(
        final_translation=repaired,
        issues=repaired_issues,
        metrics=after_metrics,
        before_target_script_ratio=float(evidence.get("targetScriptRatio") or 0.0),
    )
    succeeded = failure_reason == ""
    after_spans = _hangul_residue_spans(repaired_issues)
    trace_row = {
        "action": "targeted_small_prose_residue_repair",
        "attempt": attempt,
        "hangulResidueCategory": evidence["hangulResidueCategory"],
        "smallProseResidueDetected": True,
        "smallGenreTermResidueDetected": bool(evidence.get("smallGenreTermResidueDetected")),
        "mixedScriptNameResidueDetected": bool(evidence.get("mixedScriptNameResidueDetected")),
        "partialNameResidueDetected": bool(evidence.get("partialNameResidueDetected")),
        "commonNounResidueDetected": bool(evidence.get("commonNounResidueDetected")),
        "nameResidueFalsePositiveAvoided": bool(evidence.get("nameResidueFalsePositiveAvoided")),
        "repairAffectedToken": evidence.get("repairAffectedToken") or "",
        "targetedRepairAttempted": True,
        "targetedRepairSucceeded": succeeded,
        "targetedRepairFailedReason": failure_reason,
        "residualHangulCharCountBefore": evidence["hangulCharCount"],
        "residualHangulCharCountAfter": _hangul_char_count_from_spans(after_spans),
        "residualHangulRatioBefore": evidence["residualHangulRatio"],
        "residualHangulRatioAfter": after_metrics["residualHangulRatio"],
        "targetedRepairAffectedSpanCount": evidence["spanCount"],
        "repairAffectedSpanCount": evidence["spanCount"],
        "targetedRepairWindowStart": repair_window.get("start"),
        "targetedRepairWindowEnd": repair_window.get("end"),
        "targetedRepairWindowText": repair_window.get("text") or "",
        "targetedRepairReturnedFullTranslation": _strip_code_fence(repaired_window_output) != repaired_window,
        "hangulResidueSpanCount": len(after_spans),
        "hangulResidueCategoryAfter": _hangul_residue_category(repaired_issues, repaired),
        "sourceCopyDetected": bool(after_metrics["sourceCopyDetected"]),
        "proseResidueDetected": _has_prose_hangul_residue(repaired_issues, repaired),
        "bulkProseResidueDetected": _has_general_body_hangul_residue(repaired_issues, repaired),
        "cleanTranslatorRetryAttempted": True,
        "cleanTranslatorRetrySucceeded": clean_retry_succeeded,
        "fullRetranslationRetryAttempted": True,
        "fullRetranslationRetrySucceeded": clean_retry_succeeded,
        "strictCleanFallbackAttempted": False,
        "strictCleanFallbackSucceeded": False,
        "strictCleanFallbackFailedReason": "",
        "strictCleanFallbackDiscardReason": "",
        "strictCleanFallbackSourceCopyDetected": False,
        "strictCleanFallbackTargetScriptRatio": None,
        "strictCleanFallbackResidualHangulRatio": None,
        "strictCleanFallbackRawOutputPath": None,
        "strictCleanFallbackParsedCandidatePath": None,
        "strictCleanFallbackMetricsPath": None,
        "targetedRepairFallbackAttempted": False,
        "targetedRepairFallbackSucceeded": False,
        "targetedRepairFallbackFailedReason": "",
        "targetedRepairFallbackDiscardReason": "",
        "targetedRepairFallbackResidualHangulRatioBefore": None,
        "targetedRepairFallbackResidualHangulRatioAfter": None,
        "targetedRepairFallbackTargetScriptRatio": None,
        "targetedRepairFallbackRawOutputPath": None,
        "targetedRepairFallbackParsedCandidatePath": None,
        "targetedRepairFallbackMetricsPath": None,
        "finalFallbackAttemptCount": 0,
        "targetedRepairRevisionScope": "Targeted LLM repair for a few remaining Korean/Hangul prose residue spans; preserve unrelated translation and bracket/system UI blocks.",
        "residualHangulRatio": after_metrics["residualHangulRatio"],
        "targetScriptRatio": after_metrics["targetScriptRatio"],
        "source_prefix_match_200": after_metrics["source_prefix_match_200"],
        "source_copy_suspected": after_metrics["sourceCopyDetected"],
        **_debug_artifact_summary(
            sanitized_repair_metadata,
            candidate_discarded=not succeeded,
            discard_reason=failure_reason,
        ),
    }
    if succeeded:
        loop.iterations.append(
            {
                "iteration": attempt,
                "action": "Graph Targeted Small Prose Residue Repair",
                "critique": repaired_issues,
                "judge": repaired_judge,
                "revisionScope": trace_row["targetedRepairRevisionScope"],
                "revisionContext": context,
                "metadata": repair_metadata,
            }
        )
        loop.qaIssues = repaired_issues
        loop.judge = repaired_judge
        loop.authorReviewCards = _review_cards_from_issues(repaired_issues, state.get("idiomNotes") or [])
        loop.deliveryStatus, loop.userVisibleErrorCode = classify_translation_delivery(repaired_issues, integrity_block=False)
        loop.finalTranslation = repaired
        trace_row.update(
            {
                "deliveryStatus": loop.deliveryStatus,
                "qaIssueCount": len(repaired_issues),
                "integrityFailureType": "none",
                "failureCategory": _graph_failure_category(loop.deliveryStatus, repaired_issues),
                "finalDeliveryStatus": loop.deliveryStatus,
            }
        )
        state["graphRepairTrace"] = list(state.get("graphRepairTrace") or []) + [trace_row]
        return repaired, repaired_issues, sanitized_repair_metadata, True
    fallback_evidence = _small_prose_residue_evidence(
        issues=repaired_issues,
        final_translation=repaired,
        source_text=state.get("sourceText") or "",
        metadata=sanitized_repair_metadata,
    )
    fallback_allowed = bool(
        fallback_evidence["detected"]
        and fallback_evidence.get("hangulResidueCategory") in {"prose_residue", "genre_term_residue", "mixed_script_name_residue", "partial_name_residue"}
        and not fallback_evidence.get("sourceCopyDetected")
        and not fallback_evidence.get("bulkProseResidueDetected")
        and not any(row.get("targetedRepairFallbackAttempted") for row in state.get("graphRepairTrace") or [])
    )
    if fallback_allowed:
        fallback_attempt = attempt + 1
        fallback_window = _merge_target_sentence_windows(repaired, _hangul_residue_spans(repaired_issues)[:3])
        fallback_context = _graph_targeted_small_residue_fallback_context(
            state,
            final_translation=repaired,
            issues=repaired_issues,
            evidence=fallback_evidence,
            failed_reason=failure_reason,
        )
        fallback_window_output, fallback_metadata = _graph_translate_once(
            source_text=state["sourceText"],
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            work_memory=state.get("workMemory"),
            translate_once=translate_once,
            strict=True,
            attempt=fallback_attempt,
            revision_context=fallback_context,
        )
        fallback_window_repair = _extract_window_repair_candidate(repaired, fallback_window, fallback_window_output)
        fallback_final = _replace_target_sentence_window(repaired, fallback_window, fallback_window_repair)
        sanitized_fallback_metadata = _graph_sanitize_integrity_metadata(fallback_metadata)
        fallback_issues = _critic_issues(
            source_text=state["sourceText"],
            final_translation=fallback_final,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata={
                **sanitized_fallback_metadata,
                "delivery_status": sanitized_fallback_metadata.get("delivery_status") or "deliverable",
            },
            work_memory=state.get("workMemory"),
        )
        fallback_issues = _graph_filter_non_hangul_residue_issues(fallback_issues)
        fallback_judge = _judge(fallback_issues)
        fallback_final, fallback_issues, fallback_judge = _maybe_apply_deterministic_known_person_residue_patch(
            source_text=state["sourceText"],
            final_translation=fallback_final,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata=sanitized_fallback_metadata,
            work_memory=state.get("workMemory"),
            issues=fallback_issues,
            iterations=loop.iterations,
        )
        fallback_final, fallback_issues, fallback_judge = _maybe_apply_deterministic_known_proper_noun_variant_patch(
            source_text=state["sourceText"],
            final_translation=fallback_final,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata=sanitized_fallback_metadata,
            work_memory=state.get("workMemory"),
            issues=fallback_issues,
            iterations=loop.iterations,
        )
        fallback_issues = _graph_filter_non_hangul_residue_issues(fallback_issues)
        fallback_judge = _judge(fallback_issues)
        fallback_metrics = _graph_integrity_metrics(state.get("sourceText") or "", fallback_final, sanitized_fallback_metadata)
        fallback_failure_reason = _targeted_repair_failure_reason(
            final_translation=fallback_final,
            issues=fallback_issues,
            metrics=fallback_metrics,
            before_target_script_ratio=float(fallback_evidence.get("targetScriptRatio") or 0.0),
        )
        fallback_residual_hangul_count = _hangul_char_count_from_spans(_hangul_residue_spans(fallback_issues))
        if fallback_residual_hangul_count or float(fallback_metrics.get("residualHangulRatio") or 0.0) > 0.0:
            fallback_failure_reason = fallback_failure_reason or "hangul_residue_remaining"
        fallback_status, fallback_error = classify_translation_delivery(fallback_issues, integrity_block=False)
        fallback_succeeded = fallback_failure_reason == "" and not fallback_status.startswith("blocked_translation_")
        fallback_discard_reason = "" if fallback_succeeded else (fallback_failure_reason or _graph_failure_category(fallback_status, fallback_issues))
        fallback_artifact = _debug_artifact_summary(
            sanitized_fallback_metadata,
            candidate_discarded=not fallback_succeeded,
            discard_reason=fallback_discard_reason,
        )
        trace_row.update(
            {
                "targetedRepairFallbackAttempted": True,
                "targetedRepairFallbackSucceeded": fallback_succeeded,
                "targetedRepairFallbackFailedReason": "" if fallback_succeeded else fallback_discard_reason,
                "targetedRepairFallbackDiscardReason": fallback_discard_reason,
                "targetedRepairFallbackResidualHangulRatioBefore": fallback_evidence["residualHangulRatio"],
                "targetedRepairFallbackResidualHangulRatioAfter": fallback_metrics["residualHangulRatio"],
                "targetedRepairFallbackTargetScriptRatio": fallback_metrics["targetScriptRatio"],
                "targetedRepairFallbackRawOutputPath": fallback_artifact.get("rawOutputPath"),
                "targetedRepairFallbackParsedCandidatePath": fallback_artifact.get("parsedCandidatePath"),
                "targetedRepairFallbackMetricsPath": fallback_artifact.get("metricsPath"),
                "targetedRepairFallbackWindowStart": fallback_window.get("start"),
                "targetedRepairFallbackWindowEnd": fallback_window.get("end"),
                "finalFallbackAttemptCount": 1,
            }
        )
        loop.iterations.append(
            {
                "iteration": fallback_attempt,
                "action": "Graph Targeted Small Prose Residue Fallback",
                "critique": fallback_issues,
                "judge": fallback_judge,
                "revisionScope": "Final one-shot targeted fallback for small prose or genre-term Hangul residue after targeted repair failure; repair only affected local target context.",
                "revisionContext": fallback_context,
                "metadata": fallback_metadata,
            }
        )
        if fallback_succeeded:
            loop.qaIssues = fallback_issues
            loop.judge = fallback_judge
            loop.authorReviewCards = _review_cards_from_issues(fallback_issues, state.get("idiomNotes") or [])
            loop.deliveryStatus = fallback_status
            loop.userVisibleErrorCode = fallback_error
            loop.finalTranslation = fallback_final
            trace_row.update(
                {
                    "deliveryStatus": loop.deliveryStatus,
                    "qaIssueCount": len(fallback_issues),
                    "hangulResidueSpanCount": len(_hangul_residue_spans(fallback_issues)),
                    "hangulResidueCategoryAfter": _hangul_residue_category(fallback_issues, fallback_final),
                    "integrityFailureType": "none",
                    "sourceCopyDetected": False,
                    "proseResidueDetected": _has_prose_hangul_residue(fallback_issues, fallback_final),
                    "bulkProseResidueDetected": False,
                    "residualHangulCharCountAfter": fallback_residual_hangul_count,
                    "residualHangulRatioAfter": fallback_metrics["residualHangulRatio"],
                    "residualHangulRatio": fallback_metrics["residualHangulRatio"],
                    "targetScriptRatio": fallback_metrics["targetScriptRatio"],
                    "source_prefix_match_200": fallback_metrics["source_prefix_match_200"],
                    "source_copy_suspected": fallback_metrics["sourceCopyDetected"],
                    "failureCategory": _graph_failure_category(loop.deliveryStatus, fallback_issues),
                    "finalDeliveryStatus": loop.deliveryStatus,
                }
            )
            state["graphRepairTrace"] = list(state.get("graphRepairTrace") or []) + [trace_row]
            return fallback_final, fallback_issues, sanitized_fallback_metadata, True
    # Failed targeted repair is non-destructive: keep the clean-retry output so
    # a small residual integrity warning can remain deliverable when possible.
    kept_metrics = _graph_integrity_metrics(state.get("sourceText") or "", final, metadata)
    trace_row.update(
        {
            "deliveryStatus": loop.deliveryStatus,
            "qaIssueCount": len(issues),
            "integrityFailureType": "none",
            "targetedRepairOutputSourceCopyDetected": bool(after_metrics["sourceCopyDetected"]),
            "targetedRepairOutputProseResidueDetected": _has_prose_hangul_residue(repaired_issues, repaired),
            "targetedRepairOutputBulkProseResidueDetected": _has_general_body_hangul_residue(repaired_issues, repaired),
            "sourceCopyDetected": bool(kept_metrics["sourceCopyDetected"]),
            "proseResidueDetected": _has_prose_hangul_residue(issues, final),
            "bulkProseResidueDetected": _has_general_body_hangul_residue(issues, final),
            "residualHangulRatio": kept_metrics["residualHangulRatio"],
            "targetScriptRatio": kept_metrics["targetScriptRatio"],
            "source_prefix_match_200": kept_metrics["source_prefix_match_200"],
            "source_copy_suspected": kept_metrics["sourceCopyDetected"],
            "failureCategory": _graph_failure_category(loop.deliveryStatus, issues),
            "finalDeliveryStatus": loop.deliveryStatus,
        }
    )
    state["graphRepairTrace"] = list(state.get("graphRepairTrace") or []) + [trace_row]
    return final, issues, metadata, False


def _maybe_retry_graph_body_hangul_residue(
    state: TranslationGraphState,
    *,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None,
) -> None:
    if state.get("targetLocale") != "ko_ja":
        return
    initial_metadata = {}
    loop = state.get("_loop")
    if loop is not None and loop.iterations:
        initial_metadata = dict(loop.iterations[-1].get("metadata") or {})
    initial_metrics = _graph_integrity_metrics(state.get("sourceText") or "", state.get("finalTranslation") or "", initial_metadata)
    prose_residue_detected = _has_prose_hangul_residue(state.get("qaIssues") or [], state.get("finalTranslation") or "")
    initial_small_residue_evidence = _small_prose_residue_evidence(
        issues=state.get("qaIssues") or [],
        final_translation=state.get("finalTranslation") or "",
        source_text=state.get("sourceText") or "",
        metadata=initial_metadata,
    )
    source_copy_detected = bool(initial_metrics["sourceCopyDetected"])
    bulk_prose_residue_detected = _has_general_body_hangul_residue(state.get("qaIssues") or [], state.get("finalTranslation") or "")
    if (
        initial_small_residue_evidence["detected"]
        and not source_copy_detected
        and not bulk_prose_residue_detected
        and state.get("finalTranslation")
    ):
        loop = state.get("_loop")
        if loop is not None:
            _maybe_targeted_repair_small_prose_residue(
                state,
                translate_once=translate_once,
                final=state.get("finalTranslation") or "",
                issues=state.get("qaIssues") or [],
                metadata=initial_metadata,
                base_attempt=len(loop.iterations),
                clean_retry_succeeded=False,
            )
        return
    integrity_failure_type = _graph_integrity_failure_type(
        source_copy_detected=source_copy_detected,
        prose_residue_detected=prose_residue_detected,
    )
    if integrity_failure_type == "none":
        return
    loop = state.get("_loop")
    if loop is None:
        return
    context = _graph_clean_retranslation_context(integrity_failure_type)
    attempt = len(loop.iterations) + 1
    final, metadata = _graph_translate_once(
        source_text=state["sourceText"],
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        work_memory=state.get("workMemory"),
        translate_once=translate_once,
        strict=True,
        attempt=attempt,
        revision_context=context,
    )
    sanitized_metadata = _graph_sanitize_integrity_metadata(metadata)
    issues = _critic_issues(
        source_text=state["sourceText"],
        final_translation=final,
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata={**sanitized_metadata, "delivery_status": sanitized_metadata.get("delivery_status") or "deliverable"},
        work_memory=state.get("workMemory"),
    )
    issues = _graph_filter_non_hangul_residue_issues(issues)
    judge = _judge(issues)
    final, issues, judge = _maybe_apply_deterministic_known_person_residue_patch(
        source_text=state["sourceText"],
        final_translation=final,
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata=sanitized_metadata,
        work_memory=state.get("workMemory"),
        issues=issues,
        iterations=loop.iterations,
    )
    final, issues, judge = _maybe_apply_deterministic_known_proper_noun_variant_patch(
        source_text=state["sourceText"],
        final_translation=final,
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        safety_metadata=sanitized_metadata,
        work_memory=state.get("workMemory"),
        issues=issues,
        iterations=loop.iterations,
    )
    filtered_retry_issues = _graph_filter_non_hangul_residue_issues(issues)
    if filtered_retry_issues != issues:
        issues = filtered_retry_issues
        judge = _judge(issues)
    retry_metrics = _graph_integrity_metrics(state.get("sourceText") or "", final, sanitized_metadata)
    retry_any_prose_residue_detected = _has_prose_hangul_residue(issues, final)
    retry_bulk_prose_residue_detected = _has_general_body_hangul_residue(issues, final)
    retry_source_copy_detected = bool(retry_metrics["sourceCopyDetected"])
    retry_failure_type = _graph_integrity_failure_type(
        source_copy_detected=retry_source_copy_detected,
        prose_residue_detected=retry_bulk_prose_residue_detected,
    )
    retry_row = {
        "iteration": attempt,
        "action": "Graph Clean Full Translator Retry",
        "critique": issues,
        "judge": judge,
        "revisionScope": "Clean full Japanese-only retranslation from source text for source-copy or general prose Hangul residue; preserve bracket blocks and do not append annotations.",
        "revisionContext": context,
        "metadata": metadata,
    }
    loop.iterations.append(retry_row)
    loop.qaIssues = issues
    loop.judge = judge
    loop.authorReviewCards = _review_cards_from_issues(issues, state.get("idiomNotes") or [])
    loop.deliveryStatus, loop.userVisibleErrorCode = classify_translation_delivery(issues, integrity_block=retry_failure_type != "none")
    loop.finalTranslation = "" if loop.deliveryStatus.startswith("blocked_translation_") else final
    small_residue_evidence = _small_prose_residue_evidence(
        issues=issues,
        final_translation=final,
        source_text=state.get("sourceText") or "",
        metadata=sanitized_metadata,
    )
    clean_retry_succeeded = retry_failure_type == "none" and loop.deliveryStatus != "blocked_translation_integrity"
    clean_candidate_discarded = bool(loop.deliveryStatus.startswith("blocked_translation_"))
    clean_discard_reason = retry_failure_type if clean_candidate_discarded else ""
    trace_row = {
        "action": "clean_full_translator_retry",
        "attempt": attempt,
        "deliveryStatus": loop.deliveryStatus,
        "qaIssueCount": len(issues),
        "hangulResidueSpanCount": len(_hangul_residue_spans(issues)),
        "hangulResidueCategory": _hangul_residue_category(issues, final),
        "integrityFailureType": retry_failure_type if retry_failure_type != "none" else integrity_failure_type,
        "sourceCopyDetected": retry_source_copy_detected,
        "proseResidueDetected": retry_any_prose_residue_detected,
        "bulkProseResidueDetected": retry_bulk_prose_residue_detected,
        "smallProseResidueDetected": bool(small_residue_evidence["detected"]),
        "smallGenreTermResidueDetected": bool(small_residue_evidence.get("smallGenreTermResidueDetected")),
        "nameResidueFalsePositiveAvoided": bool(small_residue_evidence.get("nameResidueFalsePositiveAvoided")),
        "targetedRepairAttempted": False,
        "targetedRepairSucceeded": False,
        "targetedRepairFailedReason": "",
        "residualHangulCharCountBefore": small_residue_evidence["hangulCharCount"],
        "residualHangulCharCountAfter": small_residue_evidence["hangulCharCount"],
        "residualHangulRatioBefore": small_residue_evidence["residualHangulRatio"],
        "residualHangulRatioAfter": small_residue_evidence["residualHangulRatio"],
        "targetedRepairAffectedSpanCount": small_residue_evidence["spanCount"],
        "cleanTranslatorRetryAttempted": True,
        "cleanTranslatorRetrySucceeded": clean_retry_succeeded,
        "residualHangulRatio": retry_metrics["residualHangulRatio"],
        "targetScriptRatio": retry_metrics["targetScriptRatio"],
        "source_prefix_match_200": retry_metrics["source_prefix_match_200"],
        "source_copy_suspected": retry_metrics["sourceCopyDetected"],
        "fullRetranslationRetryAttempted": True,
        "fullRetranslationRetrySucceeded": clean_retry_succeeded,
        "strictCleanFallbackAttempted": False,
        "strictCleanFallbackSucceeded": False,
        "strictCleanFallbackFailedReason": "",
        "strictCleanFallbackDiscardReason": "",
        "strictCleanFallbackSourceCopyDetected": False,
        "strictCleanFallbackTargetScriptRatio": None,
        "strictCleanFallbackResidualHangulRatio": None,
        "strictCleanFallbackRawOutputPath": None,
        "strictCleanFallbackParsedCandidatePath": None,
        "strictCleanFallbackMetricsPath": None,
        "targetedRepairFallbackAttempted": False,
        "targetedRepairFallbackSucceeded": False,
        "targetedRepairFallbackFailedReason": "",
        "targetedRepairFallbackDiscardReason": "",
        "targetedRepairFallbackResidualHangulRatioBefore": None,
        "targetedRepairFallbackResidualHangulRatioAfter": None,
        "targetedRepairFallbackTargetScriptRatio": None,
        "finalFallbackAttemptCount": 0,
        "failureCategory": _graph_failure_category(loop.deliveryStatus, issues),
        "finalDeliveryStatus": loop.deliveryStatus,
        **_debug_artifact_summary(sanitized_metadata, candidate_discarded=clean_candidate_discarded, discard_reason=clean_discard_reason),
    }
    if not clean_retry_succeeded and retry_failure_type in {"source_copy", "prose_residue", "source_copy_and_prose_residue"}:
        fallback_attempt = attempt + 1
        fallback_context = _graph_strict_clean_fallback_context(retry_failure_type)
        fallback_final, fallback_metadata = _graph_translate_once(
            source_text=state["sourceText"],
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            work_memory=state.get("workMemory"),
            translate_once=translate_once,
            strict=True,
            attempt=fallback_attempt,
            revision_context=fallback_context,
        )
        sanitized_fallback_metadata = _graph_sanitize_integrity_metadata(fallback_metadata)
        fallback_issues = _critic_issues(
            source_text=state["sourceText"],
            final_translation=fallback_final,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata={
                **sanitized_fallback_metadata,
                "delivery_status": sanitized_fallback_metadata.get("delivery_status") or "deliverable",
            },
            work_memory=state.get("workMemory"),
        )
        fallback_issues = _graph_filter_non_hangul_residue_issues(fallback_issues)
        fallback_judge = _judge(fallback_issues)
        fallback_final, fallback_issues, fallback_judge = _maybe_apply_deterministic_known_person_residue_patch(
            source_text=state["sourceText"],
            final_translation=fallback_final,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata=sanitized_fallback_metadata,
            work_memory=state.get("workMemory"),
            issues=fallback_issues,
            iterations=loop.iterations,
        )
        fallback_final, fallback_issues, fallback_judge = _maybe_apply_deterministic_known_proper_noun_variant_patch(
            source_text=state["sourceText"],
            final_translation=fallback_final,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata=sanitized_fallback_metadata,
            work_memory=state.get("workMemory"),
            issues=fallback_issues,
            iterations=loop.iterations,
        )
        fallback_issues = _graph_filter_non_hangul_residue_issues(fallback_issues)
        fallback_judge = _judge(fallback_issues)
        fallback_metrics = _graph_integrity_metrics(state.get("sourceText") or "", fallback_final, sanitized_fallback_metadata)
        fallback_source_copy_detected = bool(fallback_metrics["sourceCopyDetected"])
        fallback_bulk_prose_residue_detected = _has_general_body_hangul_residue(fallback_issues, fallback_final)
        fallback_failure_type = _graph_integrity_failure_type(
            source_copy_detected=fallback_source_copy_detected,
            prose_residue_detected=fallback_bulk_prose_residue_detected,
        )
        fallback_status, fallback_error = classify_translation_delivery(
            fallback_issues,
            integrity_block=fallback_failure_type != "none",
        )
        fallback_succeeded = fallback_failure_type == "none" and not fallback_status.startswith("blocked_translation_")
        fallback_discard_reason = "" if fallback_succeeded else (fallback_failure_type if fallback_failure_type != "none" else _graph_failure_category(fallback_status, fallback_issues))
        fallback_artifact = _debug_artifact_summary(
            sanitized_fallback_metadata,
            candidate_discarded=not fallback_succeeded,
            discard_reason=fallback_discard_reason,
        )
        trace_row.update(
            {
                "strictCleanFallbackAttempted": True,
                "strictCleanFallbackSucceeded": fallback_succeeded,
                "strictCleanFallbackFailedReason": "" if fallback_succeeded else fallback_discard_reason,
                "strictCleanFallbackDiscardReason": fallback_discard_reason,
                "strictCleanFallbackSourceCopyDetected": fallback_source_copy_detected,
                "strictCleanFallbackTargetScriptRatio": fallback_metrics["targetScriptRatio"],
                "strictCleanFallbackResidualHangulRatio": fallback_metrics["residualHangulRatio"],
                "strictCleanFallbackRawOutputPath": fallback_artifact.get("rawOutputPath"),
                "strictCleanFallbackParsedCandidatePath": fallback_artifact.get("parsedCandidatePath"),
                "strictCleanFallbackMetricsPath": fallback_artifact.get("metricsPath"),
                "finalFallbackAttemptCount": 1,
            }
        )
        loop.iterations.append(
            {
                "iteration": fallback_attempt,
                "action": "Graph Strict Clean Final Fallback",
                "critique": fallback_issues,
                "judge": fallback_judge,
                "revisionScope": "Final one-shot strict Japanese-only full retranslation after a source-copy or bulk prose-residue clean retry failure; preserve bracket blocks and do not append annotations.",
                "revisionContext": fallback_context,
                "metadata": fallback_metadata,
            }
        )
        if fallback_succeeded:
            loop.qaIssues = fallback_issues
            loop.judge = fallback_judge
            loop.authorReviewCards = _review_cards_from_issues(fallback_issues, state.get("idiomNotes") or [])
            loop.deliveryStatus = fallback_status
            loop.userVisibleErrorCode = fallback_error
            loop.finalTranslation = fallback_final
            trace_row.update(
                {
                    "deliveryStatus": loop.deliveryStatus,
                    "qaIssueCount": len(fallback_issues),
                    "hangulResidueSpanCount": len(_hangul_residue_spans(fallback_issues)),
                    "hangulResidueCategory": _hangul_residue_category(fallback_issues, fallback_final),
                    "sourceCopyDetected": False,
                    "proseResidueDetected": _has_prose_hangul_residue(fallback_issues, fallback_final),
                    "bulkProseResidueDetected": False,
                    "residualHangulCharCountAfter": _hangul_char_count_from_spans(_hangul_residue_spans(fallback_issues)),
                    "residualHangulRatioAfter": fallback_metrics["residualHangulRatio"],
                    "residualHangulRatio": fallback_metrics["residualHangulRatio"],
                    "targetScriptRatio": fallback_metrics["targetScriptRatio"],
                    "source_prefix_match_200": fallback_metrics["source_prefix_match_200"],
                    "source_copy_suspected": fallback_metrics["sourceCopyDetected"],
                    "failureCategory": _graph_failure_category(loop.deliveryStatus, fallback_issues),
                    "finalDeliveryStatus": loop.deliveryStatus,
                }
            )
        else:
            loop.finalTranslation = ""
            loop.deliveryStatus = "blocked_translation_integrity"
            loop.userVisibleErrorCode = "translation_integrity_failed"
            trace_row.update(
                {
                    "deliveryStatus": loop.deliveryStatus,
                    "failureCategory": "integrity",
                    "finalDeliveryStatus": loop.deliveryStatus,
                }
            )
    state["graphRepairTrace"] = list(state.get("graphRepairTrace") or []) + [trace_row]
    if clean_retry_succeeded and loop.finalTranslation and retry_any_prose_residue_detected:
        _maybe_targeted_repair_small_prose_residue(
            state,
            translate_once=translate_once,
            final=final,
            issues=issues,
            metadata=sanitized_metadata,
            base_attempt=attempt,
            clean_retry_succeeded=clean_retry_succeeded,
        )


def repair_or_accept(
    state: TranslationGraphState,
    *,
    max_iterations: int = 2,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> TranslationGraphState:
    guidelines = state.get("_guidelinesObject")
    draft_translation = state.get("draftTranslation") or ""
    draft_metadata = dict(state.get("draftMetadata") or {})

    def _translate_with_existing_draft(strict: bool, attempt: int, revision_context: str = "") -> tuple[str, dict[str, Any]]:
        if attempt == 1 and not revision_context.strip() and draft_translation:
            return draft_translation, dict(draft_metadata)
        return _graph_translate_once(
            source_text=state["sourceText"],
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            work_memory=state.get("workMemory"),
            translate_once=translate_once,
            strict=strict,
            attempt=attempt,
            revision_context=revision_context,
        )

    loop = run_translation_loop(
        state["sourceText"],
        state["targetLocale"],
        guidelines.translatorGuideline if guidelines else "",
        guidelines.editorGuideline if guidelines else "",
        idiom_notes=state.get("idiomNotes") or [],
        max_iterations=max_iterations,
        translate_once=_translate_with_existing_draft,
        work_memory=state.get("workMemory"),
    )
    filtered_issues = _graph_filter_non_hangul_residue_issues(loop.qaIssues)
    if filtered_issues != loop.qaIssues:
        loop.qaIssues = filtered_issues
        loop.judge = _judge(filtered_issues)
        loop.authorReviewCards = _review_cards_from_issues(filtered_issues, state.get("idiomNotes") or [])
        loop.deliveryStatus, loop.userVisibleErrorCode = classify_translation_delivery(filtered_issues)
        if loop.deliveryStatus.startswith("blocked_translation_"):
            loop.finalTranslation = ""
    state.update(
        {
            "finalTranslation": loop.finalTranslation,
            "draftTranslation": loop.iterations[0].get("translation", "") if loop.iterations else "",
            "qaIssues": loop.qaIssues,
            "deliveryStatus": loop.deliveryStatus,
            "repairTrace": loop.iterations,
            "revisionHistory": loop.iterations,
            "_loop": loop,
        }
    )
    _maybe_retry_graph_body_hangul_residue(state, translate_once=translate_once)
    loop = state["_loop"]
    state.update(
        {
            "finalTranslation": loop.finalTranslation,
            "qaIssues": loop.qaIssues,
            "deliveryStatus": loop.deliveryStatus,
            "repairTrace": loop.iterations,
            "revisionHistory": loop.iterations,
        }
    )
    retry_trace = (state.get("graphRepairTrace") or [])[-1] if state.get("graphRepairTrace") else {}
    graph_repair_changed = any(
        row.get("cleanTranslatorRetrySucceeded")
        or row.get("targetedRepairSucceeded")
        or row.get("targetedRepairFallbackSucceeded")
        or row.get("strictCleanFallbackSucceeded")
        for row in state.get("graphRepairTrace") or []
    )
    final_changed = (bool(state.get("draftTranslation")) and (state.get("draftTranslation") or "") != loop.finalTranslation) or graph_repair_changed
    return _trace(
        state,
        "repair_or_accept",
        deliveryStatus=loop.deliveryStatus,
        qaIssueCount=len(loop.qaIssues),
        aggregateIssueCount=(state.get("aggregateReview") or {}).get("issueCount", 0),
        repairStrategy=(state.get("aggregateReview") or {}).get("repairStrategy", "central_repair"),
        repairRequired=(state.get("aggregateReview") or {}).get("repairRequired", False),
        finalTranslationChanged=final_changed,
        hangulResidueSpanCount=len(_hangul_residue_spans(loop.qaIssues)),
        hangulResidueCategory=_hangul_residue_category(loop.qaIssues, loop.finalTranslation),
        integrityFailureType=retry_trace.get("integrityFailureType") or "none",
        sourceCopyDetected=bool(retry_trace.get("sourceCopyDetected")),
        proseResidueDetected=bool(retry_trace.get("proseResidueDetected")),
        cleanTranslatorRetryAttempted=bool(retry_trace.get("cleanTranslatorRetryAttempted")),
        cleanTranslatorRetrySucceeded=bool(retry_trace.get("cleanTranslatorRetrySucceeded")),
        residualHangulRatio=retry_trace.get("residualHangulRatio", _graph_integrity_metrics(state.get("sourceText") or "", loop.finalTranslation, {})["residualHangulRatio"]),
        targetScriptRatio=retry_trace.get("targetScriptRatio", _graph_integrity_metrics(state.get("sourceText") or "", loop.finalTranslation, {})["targetScriptRatio"]),
        fullRetranslationRetryAttempted=bool(retry_trace.get("fullRetranslationRetryAttempted")),
        fullRetranslationRetrySucceeded=bool(retry_trace.get("fullRetranslationRetrySucceeded")),
        strictCleanFallbackAttempted=bool(retry_trace.get("strictCleanFallbackAttempted")),
        strictCleanFallbackSucceeded=bool(retry_trace.get("strictCleanFallbackSucceeded")),
        strictCleanFallbackFailedReason=retry_trace.get("strictCleanFallbackFailedReason", ""),
        targetedRepairFallbackAttempted=bool(retry_trace.get("targetedRepairFallbackAttempted")),
        targetedRepairFallbackSucceeded=bool(retry_trace.get("targetedRepairFallbackSucceeded")),
        targetedRepairFallbackFailedReason=retry_trace.get("targetedRepairFallbackFailedReason", ""),
        targetedRepairFallbackDiscardReason=retry_trace.get("targetedRepairFallbackDiscardReason", ""),
        targetedRepairFallbackResidualHangulRatioBefore=retry_trace.get("targetedRepairFallbackResidualHangulRatioBefore"),
        targetedRepairFallbackResidualHangulRatioAfter=retry_trace.get("targetedRepairFallbackResidualHangulRatioAfter"),
        targetedRepairFallbackTargetScriptRatio=retry_trace.get("targetedRepairFallbackTargetScriptRatio"),
        finalFallbackAttemptCount=int(retry_trace.get("finalFallbackAttemptCount") or 0),
        failureCategory=_graph_failure_category(loop.deliveryStatus, loop.qaIssues),
        finalDeliveryStatus=loop.deliveryStatus,
    )


def run_qa_and_repair(
    state: TranslationGraphState,
    *,
    max_iterations: int = 2,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> TranslationGraphState:
    return repair_or_accept(state, max_iterations=max_iterations, translate_once=translate_once)


def final_integrity_check(state: TranslationGraphState) -> TranslationGraphState:
    loop = state["_loop"]
    metadata: dict[str, Any] = {}
    if loop.iterations:
        metadata = dict(loop.iterations[-1].get("metadata") or {})
    if loop.deliveryStatus.startswith("blocked_translation_"):
        issues = list(loop.qaIssues or [])
    else:
        sanitized_metadata = _graph_sanitize_integrity_metadata(metadata)
        issues = _critic_issues(
            source_text=state["sourceText"],
            final_translation=loop.finalTranslation,
            target_locale=state["targetLocale"],
            idiom_notes=state.get("idiomNotes") or [],
            safety_metadata={
                **sanitized_metadata,
                "delivery_status": sanitized_metadata.get("delivery_status") or loop.deliveryStatus or "deliverable",
            },
            work_memory=state.get("workMemory"),
        )
        issues = _dedupe_issues(_graph_filter_non_hangul_residue_issues(issues))
    integrity_metrics = _graph_integrity_metrics(state.get("sourceText") or "", loop.finalTranslation, metadata)
    integrity_block = bool(integrity_metrics.get("sourceCopyDetected") or _has_general_body_hangul_residue(issues, loop.finalTranslation))
    final_status, final_error = classify_translation_delivery(issues, integrity_block=integrity_block)
    if loop.deliveryStatus == "blocked_translation_safety":
        final_status = "blocked_translation_safety"
        final_error = "translation_safety_failed"
    elif loop.deliveryStatus == "blocked_translation_integrity":
        final_status = "blocked_translation_integrity"
        final_error = "translation_integrity_failed"
    if final_status != loop.deliveryStatus or issues != loop.qaIssues:
        loop.qaIssues = issues
        loop.judge = _judge(issues)
        loop.authorReviewCards = _review_cards_from_issues(issues, state.get("idiomNotes") or [])
        loop.deliveryStatus = final_status
        loop.userVisibleErrorCode = final_error
        if loop.deliveryStatus.startswith("blocked_translation_"):
            loop.finalTranslation = ""
    state.update(
        {
            "finalTranslation": loop.finalTranslation,
            "qaIssues": loop.qaIssues,
            "deliveryStatus": loop.deliveryStatus,
            "repairTrace": loop.iterations,
            "revisionHistory": loop.iterations,
            "finalIntegrityCheck": {
                "issueCount": len(loop.qaIssues),
                "finalDeliveryStatus": loop.deliveryStatus,
                "failureCategory": _graph_failure_category(loop.deliveryStatus, loop.qaIssues),
                "sourceCopyDetected": bool(integrity_metrics.get("sourceCopyDetected")),
                "hangulResidueSpanCount": len(_hangul_residue_spans(loop.qaIssues)),
                "hangulResidueCategory": _hangul_residue_category(loop.qaIssues, loop.finalTranslation),
                "readerEndnotesAppended": any(
                    str(note.get("note") or "") and str(note.get("note") or "") in (loop.finalTranslation or "")
                    for note in state.get("readerEndnotes") or []
                ),
            },
        }
    )
    return _trace(
        state,
        "final_integrity_check",
        issueCount=len(loop.qaIssues),
        finalDeliveryStatus=loop.deliveryStatus,
        failureCategory=_graph_failure_category(loop.deliveryStatus, loop.qaIssues),
        finalTranslationChanged=False,
        readerEndnotesAppended=state["finalIntegrityCheck"]["readerEndnotesAppended"],
    )


def chunk_source_text(state: TranslationGraphState) -> TranslationGraphState:
    source = state.get("sourceText") or ""
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", source) if part.strip()]
    if not paragraphs and source.strip():
        paragraphs = [source.strip()]
    chunks = [
        {
            "chunkId": f"episode-{state.get('episodeId') or 'unknown'}-p{index + 1}",
            "text": paragraph,
            "index": index,
        }
        for index, paragraph in enumerate(paragraphs)
    ]
    state["sourceChunks"] = chunks
    state["annotationTrace"] = {"chunkCount": len(chunks), "candidateCount": 0, "retrievalCount": 0, "keptCount": 0}
    return _trace(state, "chunk_source_text", chunkCount=len(chunks))


def detect_annotation_candidates(state: TranslationGraphState) -> TranslationGraphState:
    hook = state.get("annotationCandidateHook")
    if hook:
        candidates = hook(state)
    else:
        candidates = []
    state["annotationCandidates"] = list(candidates or [])
    trace = dict(state.get("annotationTrace") or {})
    trace["candidateCount"] = len(state["annotationCandidates"])
    state["annotationTrace"] = trace
    return _trace(state, "detect_annotation_candidates", candidateCount=len(state["annotationCandidates"]))


def retrieve_korean_culture_context(state: TranslationGraphState) -> TranslationGraphState:
    hook = state.get("annotationRetrievalHook")
    if hook:
        retrievals = hook(state)
    else:
        retrievals = []
    state["annotationRetrievals"] = list(retrievals or [])
    trace = dict(state.get("annotationTrace") or {})
    trace["retrievalCount"] = len(state["annotationRetrievals"])
    state["annotationTrace"] = trace
    return _trace(state, "retrieve_korean_culture_context", retrievalCount=len(state["annotationRetrievals"]))


def _normalize_reader_endnote(row: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "noteId": int(row.get("noteId") or index + 1),
        "sourceSpan": str(row.get("sourceSpan") or ""),
        "targetSpan": str(row.get("targetSpan") or ""),
        "category": str(row.get("category") or "webnovel_genre_convention"),
        "note": str(row.get("note") or ""),
        "sourceChunkId": str(row.get("sourceChunkId") or ""),
        "retrievalRefs": list(row.get("retrievalRefs") or []),
        "confidence": str(row.get("confidence") or "medium"),
    }


def write_reader_endnotes(state: TranslationGraphState) -> TranslationGraphState:
    hook = state.get("readerEndnoteWriterHook")
    if hook:
        notes = hook(state)
    else:
        notes = []
    state["readerEndnotesDraft"] = [_normalize_reader_endnote(note, index) for index, note in enumerate(notes or []) if isinstance(note, dict)]
    return _trace(state, "write_reader_endnotes", readerEndnotesDraftCount=len(state["readerEndnotesDraft"]))


def filter_rank_endnotes(state: TranslationGraphState) -> TranslationGraphState:
    seen: set[tuple[str, str, str]] = set()
    kept: list[dict[str, Any]] = []
    for note in state.get("readerEndnotesDraft") or []:
        if not note.get("sourceSpan") or not note.get("note"):
            continue
        key = (str(note.get("sourceSpan")), str(note.get("category")), str(note.get("note")))
        if key in seen:
            continue
        seen.add(key)
        kept.append({**note, "noteId": len(kept) + 1})
    state["readerEndnotes"] = kept
    trace = dict(state.get("annotationTrace") or {})
    trace["keptCount"] = len(kept)
    state["annotationTrace"] = trace
    return _trace(state, "filter_rank_endnotes", readerEndnotesCount=len(kept))


def align_endnotes_to_final_translation(state: TranslationGraphState) -> TranslationGraphState:
    final_translation = state.get("finalTranslation") or ""
    if str(state.get("deliveryStatus") or "").startswith("blocked_translation_"):
        state["readerEndnotes"] = []
        return _trace(
            state,
            "align_endnotes_to_final_translation",
            readerEndnotesCount=0,
            blockedNoop=True,
            finalTranslationChanged=False,
        )
    aligned: list[dict[str, Any]] = []
    for note in state.get("readerEndnotes") or []:
        target_span = str(note.get("targetSpan") or "")
        aligned_note = dict(note)
        aligned_note["targetSpanFound"] = bool(target_span and target_span in final_translation)
        aligned.append(aligned_note)
    state["readerEndnotes"] = aligned
    return _trace(
        state,
        "align_endnotes_to_final_translation",
        readerEndnotesCount=len(aligned),
        finalTranslationChanged=False,
    )


def _review_cards_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM 리뷰어 findings(reviewFindings)를 화면 검수항목용 카드로 변환한다.

    section 태그가 있는 findings(=LLM 리뷰어: voice/naturalness/cultural)만 카드로 만든다.
    결정론적 critic findings(section 없음)는 loop.authorReviewCards 쪽에서 이미 처리되므로 제외.
    화면은 card.section 으로 '말투/자연스러움/문화권 유의사항' 소제목 그룹을 만든다(advisory).
    """
    cards: list[dict[str, Any]] = []
    for index, finding in enumerate(findings or [], start=1):
        issue = finding.get("issue") or {}
        section = issue.get("section")
        if not section:
            continue
        suggestion = finding.get("suggestion") or issue.get("suggestion") or ""
        cards.append(
            {
                "id": f"v3-review-card-{index}",
                "priority": finding.get("priority") or "P2",
                "status": "pending",
                "section": section,
                "sectionLabel": issue.get("sectionLabel") or section,
                "reviewerType": finding.get("reviewerType") or section,
                "severity": issue.get("severity") or "",
                "decisionType": finding.get("code") or "review_item",
                "sourceSpan": finding.get("sourceSpan") or "",
                "targetSpan": finding.get("targetSpan") or "",
                "currentTranslation": finding.get("targetSpan") or "",
                "explanation": finding.get("message") or "",
                "suggestion": suggestion,
                "authorQuestion": "이 검수 의견을 반영할지 확인해 주세요.",
                "suggestedActions": [suggestion] if suggestion else [],
            }
        )
    return cards


def build_translation_package(state: TranslationGraphState) -> TranslationGraphState:
    loop = state["_loop"]
    guidelines = state["_guidelinesObject"]
    notes = state.get("idiomNotes") or []
    rag = state["_ragPackets"]
    rationale = write_translation_rationale(
        state["sourceText"],
        loop.finalTranslation,
        state["targetLocale"],
        notes,
        guidelines.translatorGuideline,
        guidelines.editorGuideline,
        loop.qaIssues,
        work_memory=state.get("workMemory"),
    )
    source_analysis = state.get("sourceAnalysis") or {}
    memory = state.get("workMemory")
    internal = {
        "idiomNotes": [asdict(n) for n in notes],
        "idiomDetection": {"mode": "rule", "notes": [asdict(n) for n in notes], "ftEnabled": False},
        "characterReferences": source_analysis.get("characterReferences") or [],
        "entityCandidates": source_analysis.get("entityCandidates") or [],
        "ragPackets": asdict(rag),
        "workMemory": asdict(memory) if memory else None,
        "guidelines": asdict(guidelines),
        "iterations": loop.iterations,
        "judge": loop.judge,
        "failureSignals": _failure_signals(loop.qaIssues),
        "graphReviewTrace": state.get("graphReviewTrace") or [],
        "reviewFindings": state.get("reviewFindings") or [],
        "aggregateReview": state.get("aggregateReview") or {},
        "finalIntegrityCheck": state.get("finalIntegrityCheck") or {},
        "graphRepairTrace": state.get("graphRepairTrace") or [],
        "maxIterations": min(max(1, int(state.get("maxIterations") or 2)), 2),
        "maxRevisionPass": 1,
        "readerEndnotes": state.get("readerEndnotes") or [],
        "annotationTrace": state.get("annotationTrace") or {"chunkCount": 0, "candidateCount": 0, "retrievalCount": 0, "keptCount": 0},
        "graphOrchestrator": {
            "enabled": True,
            "executionFrame": state.get("graphExecutionFrame") or "stategraph_compatible",
            "nodes": [row["node"] for row in state.get("graphTrace", [])],
        },
        "userVisibleErrorCode": loop.userVisibleErrorCode,
        "mockBoundaries": {
            "idiomDetector": "rule adapter by default; llm/ft adapters are placeholders",
            "sourceAnalyzer": "deterministic source-evidence adapter; no LLM call",
            "ragPackets": "static/mock packet builder",
            "workMemory": "in-memory payload only",
            "readerEndnotes": "annotation branch adapter/stub unless hooks provide retrieval-backed notes",
        },
    }
    # 결정론적 critic 카드 + LLM 리뷰어(말투/자연스러움/문화) 카드 합류.
    author_review_cards = list(loop.authorReviewCards) + _review_cards_from_findings(state.get("reviewFindings") or [])
    package = V3LiteraryPackageResult(
        "v3_literary_package",
        loop.deliveryStatus,
        loop.finalTranslation,
        rationale,
        loop.qaIssues,
        author_review_cards,
        internal,
        readerEndnotes=state.get("readerEndnotes") or [],
        userVisibleErrorCode=loop.userVisibleErrorCode,
    )
    state["translationPackage"] = package
    return _trace(state, "build_translation_package", readerEndnotesCount=len(package.readerEndnotes))


def should_persist(state: TranslationGraphState) -> bool:
    request = state.get("normalizedRequest") or {}
    package = state.get("translationPackage")
    return bool(
        request.get("saveTranslationResult")
        and package
        and not package.deliveryStatus.startswith("blocked_translation_")
        and package.finalTranslation.strip()
    )


def persist_result(state: TranslationGraphState) -> TranslationGraphState:
    hook = state.get("persistHook")
    result = hook(state) if hook else {"enabled": bool((state.get("normalizedRequest") or {}).get("saveTranslationResult")), "saved": False, "reason": "no_persist_hook"}
    result.setdefault("scope", "graph_orchestrator_pre_service_persistence")
    state["savedTranslationId"] = result.get("savedTranslationId") or result.get("translation_id")
    package = state.get("translationPackage")
    if package:
        package.internal["translationPersistence"] = result
    return _trace(state, "persist_result", saved=bool(result.get("saved")), savedTranslationId=state.get("savedTranslationId"))


def skip_persist(state: TranslationGraphState) -> TranslationGraphState:
    package = state.get("translationPackage")
    if package:
        package.internal["translationPersistence"] = {
            "enabled": bool((state.get("normalizedRequest") or {}).get("saveTranslationResult")),
            "saved": False,
            "skipped": True,
            "scope": "graph_orchestrator_pre_service_persistence",
            "reason": "service_layer_handles_http_persistence_when_no_graph_hook_is_installed",
        }
    return _trace(state, "skip_persist", skipped=True)


def should_capture_glossary(state: TranslationGraphState) -> bool:
    request = state.get("normalizedRequest") or {}
    package = state.get("translationPackage")
    return bool(request.get("captureGlossaryCandidates") and request.get("workId") is not None and state.get("targetLocale") and package and not package.deliveryStatus.startswith("blocked_translation_"))


def capture_glossary_candidates(state: TranslationGraphState) -> TranslationGraphState:
    hook = state.get("captureHook")
    result = hook(state) if hook else {"enabled": bool((state.get("normalizedRequest") or {}).get("captureGlossaryCandidates")), "savedCount": 0, "reason": "no_capture_hook"}
    state["glossaryCandidateCapture"] = result
    state["glossarySavedCount"] = int(result.get("savedCount") or 0)
    package = state.get("translationPackage")
    if package:
        package.internal["glossaryCandidateCapture"] = result
    return _trace(state, "capture_glossary_candidates", savedCount=state["glossarySavedCount"])


def skip_capture(state: TranslationGraphState) -> TranslationGraphState:
    result = {"enabled": bool((state.get("normalizedRequest") or {}).get("captureGlossaryCandidates")), "skipped": True}
    state["glossaryCandidateCapture"] = result
    package = state.get("translationPackage")
    if package:
        package.internal["glossaryCandidateCapture"] = result
    return _trace(state, "skip_capture", skipped=True)


def _node_delta(before: TranslationGraphState, after: TranslationGraphState, trace_start: int) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key, value in after.items():
        if key in {"graphTrace", "graphReviewTrace", "reviewFindings"}:
            new_trace = list((after.get("graphTrace") or [])[trace_start:])
            if key == "graphReviewTrace":
                new_trace = list((after.get("graphReviewTrace") or [])[len(before.get("graphReviewTrace") or []):])
            elif key == "reviewFindings":
                new_trace = list((after.get("reviewFindings") or [])[len(before.get("reviewFindings") or []):])
            if new_trace:
                delta[key] = new_trace
            continue
        if key not in before or before.get(key) != value:
            delta[key] = value
    return delta


def _as_langgraph_node(func: Callable[..., TranslationGraphState], **kwargs: Any) -> Callable[[TranslationGraphState], dict[str, Any]]:
    def _runner(state: TranslationGraphState) -> dict[str, Any]:
        working: TranslationGraphState = dict(state)
        # LangGraph reducers merge returned graphTrace deltas. If a node mutates
        # the incoming trace list in-place, the reducer sees both the in-place
        # append and the returned delta, which duplicates every node record.
        working["graphTrace"] = list(state.get("graphTrace") or [])
        working["graphReviewTrace"] = list(state.get("graphReviewTrace") or [])
        working["reviewFindings"] = list(state.get("reviewFindings") or [])
        trace_start = len(working.get("graphTrace") or [])
        before: TranslationGraphState = dict(working)
        after = func(working, **kwargs)
        return _node_delta(before, after, trace_start)

    return _runner


def _build_stategraph(max_iterations: int, translate_once: Callable[..., tuple[str, dict[str, Any]]] | None):
    if StateGraph is None or START is None or END is None:
        return None
    builder = StateGraph(TranslationGraphState)
    builder.add_node("normalize_input", _as_langgraph_node(normalize_input))
    builder.add_node("load_work_memory", _as_langgraph_node(load_work_memory))
    builder.add_node("prepare_translation_context", _as_langgraph_node(prepare_translation_context))
    builder.add_node("run_literary_translation", _as_langgraph_node(run_literary_translation, translate_once=translate_once))
    builder.add_node("deterministic_precheck", _as_langgraph_node(deterministic_precheck))
    builder.add_node("review_voice", _as_langgraph_node(review_voice))
    builder.add_node("review_naturalness", _as_langgraph_node(review_naturalness))
    builder.add_node("review_cultural", _as_langgraph_node(review_cultural))
    builder.add_node("review_glossary", _as_langgraph_node(review_glossary))
    builder.add_node("review_integrity", _as_langgraph_node(review_integrity))
    builder.add_node("aggregate_review", _as_langgraph_node(aggregate_review))
    builder.add_node(
        "repair_or_accept",
        _as_langgraph_node(repair_or_accept, max_iterations=max_iterations, translate_once=translate_once),
    )
    builder.add_node("final_integrity_check", _as_langgraph_node(final_integrity_check))
    builder.add_node("chunk_source_text", _as_langgraph_node(chunk_source_text))
    builder.add_node("detect_annotation_candidates", _as_langgraph_node(detect_annotation_candidates))
    builder.add_node("retrieve_korean_culture_context", _as_langgraph_node(retrieve_korean_culture_context))
    builder.add_node("write_reader_endnotes", _as_langgraph_node(write_reader_endnotes))
    builder.add_node("filter_rank_endnotes", _as_langgraph_node(filter_rank_endnotes))
    builder.add_node("align_endnotes_to_final_translation", _as_langgraph_node(align_endnotes_to_final_translation))
    builder.add_node("build_translation_package", _as_langgraph_node(build_translation_package))
    builder.add_node("persist_result", _as_langgraph_node(persist_result))
    builder.add_node("skip_persist", _as_langgraph_node(skip_persist))
    builder.add_node("capture_glossary_candidates", _as_langgraph_node(capture_glossary_candidates))
    builder.add_node("skip_capture", _as_langgraph_node(skip_capture))

    builder.add_edge(START, "normalize_input")
    builder.add_edge("normalize_input", "load_work_memory")
    builder.add_edge("normalize_input", "chunk_source_text")
    builder.add_edge("load_work_memory", "prepare_translation_context")
    builder.add_edge("prepare_translation_context", "run_literary_translation")
    builder.add_edge("run_literary_translation", "deterministic_precheck")
    builder.add_edge("deterministic_precheck", "review_voice")
    builder.add_edge("deterministic_precheck", "review_naturalness")
    builder.add_edge("deterministic_precheck", "review_cultural")
    builder.add_edge("deterministic_precheck", "review_glossary")
    builder.add_edge("deterministic_precheck", "review_integrity")
    builder.add_edge(["review_voice", "review_naturalness", "review_cultural", "review_glossary", "review_integrity"], "aggregate_review")
    builder.add_edge("aggregate_review", "repair_or_accept")
    builder.add_edge("repair_or_accept", "final_integrity_check")
    builder.add_edge("chunk_source_text", "detect_annotation_candidates")
    builder.add_edge("detect_annotation_candidates", "retrieve_korean_culture_context")
    builder.add_edge("retrieve_korean_culture_context", "write_reader_endnotes")
    builder.add_edge("write_reader_endnotes", "filter_rank_endnotes")
    builder.add_edge(["final_integrity_check", "filter_rank_endnotes"], "align_endnotes_to_final_translation")
    builder.add_edge("align_endnotes_to_final_translation", "build_translation_package")
    builder.add_conditional_edges("build_translation_package", should_persist, {True: "persist_result", False: "skip_persist"})
    builder.add_conditional_edges("persist_result", should_capture_glossary, {True: "capture_glossary_candidates", False: "skip_capture"})
    builder.add_conditional_edges("skip_persist", should_capture_glossary, {True: "capture_glossary_candidates", False: "skip_capture"})
    builder.add_edge("capture_glossary_candidates", END)
    builder.add_edge("skip_capture", END)
    return builder.compile(name="v3_literary_package_graph")


def _run_compatible_runner(
    state: TranslationGraphState,
    *,
    max_iterations: int,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None,
) -> TranslationGraphState:
    state["graphExecutionFrame"] = "stategraph_compatible"
    state = normalize_input(state)
    state = load_work_memory(state)
    state = prepare_translation_context(state)
    state = run_literary_translation(state, translate_once=translate_once)
    state = deterministic_precheck(state)
    state = review_voice(state)
    state = review_naturalness(state)
    state = review_cultural(state)
    state = review_glossary(state)
    state = review_integrity(state)
    state = aggregate_review(state)
    state = chunk_source_text(state)
    state = detect_annotation_candidates(state)
    state = retrieve_korean_culture_context(state)
    state = write_reader_endnotes(state)
    state = filter_rank_endnotes(state)
    state = repair_or_accept(state, max_iterations=max_iterations, translate_once=translate_once)
    state = final_integrity_check(state)
    state = align_endnotes_to_final_translation(state)
    state = build_translation_package(state)
    state = persist_result(state) if should_persist(state) else skip_persist(state)
    state = capture_glossary_candidates(state) if should_capture_glossary(state) else skip_capture(state)
    return state


def run_graph_orchestrator(
    state: TranslationGraphState,
    *,
    max_iterations: int = 2,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> TranslationGraphState:
    state["maxIterations"] = max_iterations
    state.setdefault("errors", [])
    graph = _build_stategraph(max_iterations, translate_once)
    if graph is not None:
        state["graphExecutionFrame"] = "langgraph_stategraph"
        state = graph.invoke(state)
    else:
        state = _run_compatible_runner(state, max_iterations=max_iterations, translate_once=translate_once)
    package = state.get("translationPackage")
    if package:
        package.internal["graphTrace"] = state.get("graphTrace", [])
        package.internal["graphReviewTrace"] = state.get("graphReviewTrace", [])
        package.internal["reviewFindings"] = state.get("reviewFindings", [])
        package.internal["aggregateReview"] = state.get("aggregateReview", {})
        package.internal["finalIntegrityCheck"] = state.get("finalIntegrityCheck", {})
        package.internal["graphOrchestrator"]["executionFrame"] = state.get("graphExecutionFrame") or "stategraph_compatible"
        package.internal["readerEndnotes"] = package.readerEndnotes
        package.internal["annotationTrace"] = state.get("annotationTrace") or {"chunkCount": 0, "candidateCount": 0, "retrievalCount": 0, "keptCount": 0}
    return state


def build_v3_graph_literary_package(
    source_text: str,
    target_locale: str,
    *,
    genre: str = "Modern Korean web novel",
    work_memory: Any = None,
    max_iterations: int = 2,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None = None,
    annotation_candidate_hook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None = None,
    annotation_retrieval_hook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None = None,
    reader_endnote_writer_hook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None = None,
    reviewer_hook: Callable[[TranslationGraphState, str], list[dict[str, Any]]] | None = None,
) -> V3LiteraryPackageResult:
    state = run_graph_orchestrator(
        {
            "request": {"sourceText": source_text, "targetLocale": target_locale, "mode": "v3_literary_package", "genre": genre},
            "sourceText": source_text,
            "targetLocale": target_locale,
            "genre": genre,
            "workMemory": work_memory,
            "workMemorySource": "request_payload" if work_memory is not None else "none",
            "annotationCandidateHook": annotation_candidate_hook,
            "annotationRetrievalHook": annotation_retrieval_hook,
            "readerEndnoteWriterHook": reader_endnote_writer_hook,
            "reviewerHook": reviewer_hook,
        },
        max_iterations=max_iterations,
        translate_once=translate_once,
    )
    return state["translationPackage"]
