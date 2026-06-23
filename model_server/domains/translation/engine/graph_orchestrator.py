from __future__ import annotations

import os
import re
from dataclasses import asdict, replace
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
    TranslationLoopResult,
    write_translation_rationale,
    _critic_issues,
    _failure_signals,
    _judge,
    _mock_literary_translation,
    _review_cards_from_issues,
    _glossary_source_set,
    _source_present,
)
from ..text_processing.korean_output import (
    apply_unit_repairs,
    has_korean_residue,
    korean_residue_units,
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
    "aggregate_review",
    "revise_translation",
    "check_korean_residue",
    "final_integrity_check",
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


def _last_write_str(left: str | None, right: str | None) -> str:
    # 병렬 노드(리뷰어 fan-out)가 같은 키에 써도 에러 없이 병합. 값은 노드 내부에서만 읽혀 병합 결과는 미사용.
    return right if right else (left or "")


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
    annotationRetrievals: list[dict[str, Any]]
    readerEndnotesDraft: list[dict[str, Any]]
    readerEndnotes: list[dict[str, Any]]
    annotationTrace: dict[str, Any]
    translationPackage: V3LiteraryPackageResult
    savedTranslationId: Any
    glossarySavedCount: int
    glossaryCandidateCapture: dict[str, Any]
    glossaryCandidates: list[dict[str, Any]]  # glossary 리뷰어가 추출한 신규 용어 후보(승인 dedup 후)
    revisorDecisions: list[dict[str, Any]]    # 리바이저의 finding별 적용/기각 결정
    revisorSummary: str                       # 리바이저의 수정 방향성 짧은 평(revisor_summary)
    currentReviewerSummary: Annotated[str, _last_write_str]  # 리뷰 노드 내부 전달용(훅→trace row); 병렬 write 허용
    reviewSummaries: dict[str, Any]           # 관점별 LLM 총평 {reviewerType: summary} (aggregate_review 조립)
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
    revisorHook: Callable[[TranslationGraphState], dict[str, Any]] | None
    residueRepairHook: Callable[[TranslationGraphState, list[dict[str, Any]]], dict[int, str]] | None
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
    # Confirm the active glossary deterministically: keep only entries whose
    # Korean source (or alias) actually appears in this episode's source text.
    # The fetch layer no longer caps the row count, so this presence filter —
    # not an arbitrary limit — is what bounds the list the reviewers and the
    # term-candidate dedup operate on downstream.
    fetched_count = len(memory.approvedGlossary) if memory else 0
    if memory and memory.approvedGlossary:
        source_text = state.get("sourceText") or ""
        glossary_sources = _glossary_source_set(memory)
        present = [
            entry
            for entry in memory.approvedGlossary
            if _source_present(source_text, entry, glossary_sources)
        ]
        memory = replace(memory, approvedGlossary=present)
    approved = [asdict(entry) for entry in memory.approvedGlossary] if memory else []
    state.update(
        {
            "workMemory": memory,
            "workMemorySource": source,
            "workMemoryFallbackReason": fallback_reason,
            "approvedGlossary": approved,
        }
    )
    return _trace(
        state,
        "load_work_memory",
        approvedGlossaryFetched=fetched_count,
        approvedGlossaryCount=len(approved),
    )


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
    # Produce the real initial draft here so the deterministic precheck and the
    # LLM reviewers downstream run against the actual translation rather than an
    # empty string.
    draft, metadata = _graph_translate_once(
        source_text=state["sourceText"],
        target_locale=state["targetLocale"],
        idiom_notes=state.get("idiomNotes") or [],
        work_memory=state.get("workMemory"),
        translate_once=translate_once,
        strict=False,
        attempt=1,
        revision_context="",
    )
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
        "summary": str(state.get("currentReviewerSummary") or ""),  # 이 관점 전체 평가 총평(LLM 리뷰어)
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
    """주입된 LLM 리뷰어 hook으로 advisory findings를 만든다.

    hook 시그니처: (state, reviewer_type) -> list[v3 issue dict].
    리뷰 실패가 그래프를 막지 않도록 예외는 빈 리스트로 흡수한다(fail-soft).
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
    return _review_by_codes(state, "cultural", "review_cultural")


def review_glossary(state: TranslationGraphState) -> TranslationGraphState:
    return _review_by_codes(state, "glossary", "review_glossary")


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
            "summary": str(row.get("summary") or ""),
        }
        for row in reviewer_trace
    ]
    # 리포트용: 관점별 LLM 총평 dict {reviewerType: summary}. fan-in 후라 모든 리뷰어 trace가 모임(병렬 안전).
    state["reviewSummaries"] = {
        str(row.get("reviewerType") or ""): str(row.get("summary") or "")
        for row in reviewer_trace
        if str(row.get("reviewerType") or "") and str(row.get("summary") or "").strip()
    }
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


def revise_translation(state: TranslationGraphState) -> TranslationGraphState:
    """리바이저 원맨 체제: draft + reviewFindings를 취사선택 반영해 최종 번역문 + decisions 생성.

    리바이저 출력이 곧 최종본이다. 결과를 TranslationLoopResult로 담아 state["_loop"]에 넣으면,
    final_integrity_check가 그 최종본을 검증(한글 잔류 시 차단)하고 build_translation_package가
    패키징한다. (재번역 수리 루프 없음 — 리바이저 결과를 다시 덮어쓰지 않는다.)
    리바이저 hook이 없거나 draft가 비면 draft를 그대로 최종본으로 둔다.
    """
    hook = state.get("revisorHook")
    draft = state.get("draftTranslation") or ""
    result: dict[str, Any] = {}
    if hook and draft.strip():
        try:
            result = hook(state) or {}
        except Exception:
            result = {}
    revised = str(result.get("finalTranslation") or "").strip() or draft
    decisions = [d for d in (result.get("decisions") or []) if isinstance(d, dict)]
    loop = TranslationLoopResult(
        finalTranslation=revised,
        iterations=[{"action": "revisor", "translation": revised, "metadata": {}}],
        judge=_judge([]),
        qaIssues=[],
        authorReviewCards=[],
        deliveryStatus="deliverable",
        userVisibleErrorCode=None,
    )
    state["_loop"] = loop
    state["draftTranslation"] = revised
    state["finalTranslation"] = revised
    state["revisorDecisions"] = decisions
    state["revisorSummary"] = str(result.get("summary") or "")
    return _trace(
        state,
        "revise_translation",
        decisionCount=len(decisions),
        finalTranslationChanged=(revised != draft),
    )


_RESIDUE_MAX_PASSES = 2


def check_korean_residue(state: TranslationGraphState) -> TranslationGraphState:
    """리바이저 최종본의 한글 잔류 검사 + 인덱스 기반 수리(최대 2패스).

    한글 포함 문장 단위를 뽑아 residueRepairHook으로 고치고 인덱스로 치환한다.
    hook이 없거나 더 못 고치면 멈추고, 2패스 초과면 남은 잔류는 그대로 둔다.
    (빈 출력 차단·잔류 잔존 시 차단 판정은 이후 final_integrity_check가 담당)
    """
    hook = state.get("residueRepairHook")
    final = state.get("finalTranslation") or ""
    passes = 0
    while passes < _RESIDUE_MAX_PASSES and has_korean_residue(final):
        units = korean_residue_units(final)
        if not units:
            break
        fixes: dict[int, str] = {}
        if hook:
            try:
                fixes = hook(state, units) or {}
            except Exception:
                fixes = {}
        if not fixes:
            break
        final = apply_unit_repairs(final, fixes)
        passes += 1
    state["finalTranslation"] = final
    loop = state.get("_loop")
    if loop is not None:
        loop.finalTranslation = final
    return _trace(
        state,
        "check_korean_residue",
        residuePasses=passes,
        residueRemaining=has_korean_residue(final),
    )


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
    # 말미 목록 스타일 미주 3필드: 한국 문화 키워드 / 한국어 미주 / 대상언어 미주.
    # (스팬·noteId·출처추적 제거 — 인라인 앵커링 안 함.)
    return {
        "keyword": str(row.get("keyword") or row.get("sourceSpan") or "").strip(),
        "koreanNote": str(row.get("koreanNote") or "").strip(),
        "targetNote": str(row.get("targetNote") or row.get("note") or "").strip(),
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
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for note in state.get("readerEndnotesDraft") or []:
        keyword = str(note.get("keyword") or "").strip()
        korean = str(note.get("koreanNote") or "").strip()
        target = str(note.get("targetNote") or "").strip()
        if not keyword or not korean or not target:
            continue  # 3필드 중 하나라도 비면 제거
        if keyword in seen:
            continue  # keyword 기준 dedup
        seen.add(keyword)
        kept.append({"keyword": keyword, "koreanNote": korean, "targetNote": target})
    state["readerEndnotes"] = kept
    trace = dict(state.get("annotationTrace") or {})
    trace["keptCount"] = len(kept)
    state["annotationTrace"] = trace
    return _trace(state, "filter_rank_endnotes", readerEndnotesCount=len(kept))


def align_endnotes_to_final_translation(state: TranslationGraphState) -> TranslationGraphState:
    if str(state.get("deliveryStatus") or "").startswith("blocked_translation_"):
        state["readerEndnotes"] = []
        return _trace(
            state,
            "align_endnotes_to_final_translation",
            readerEndnotesCount=0,
            blockedNoop=True,
            finalTranslationChanged=False,
        )
    # 말미 목록 스타일 미주 — 스팬 앵커링이 없어 노트별 변환은 없다.
    # A·B 분기 조인 지점으로만 유지하고, 차단 시(위)엔 미주를 비운다.
    return _trace(
        state,
        "align_endnotes_to_final_translation",
        readerEndnotesCount=len(state.get("readerEndnotes") or []),
        finalTranslationChanged=False,
    )


def _review_cards_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM 리뷰어 findings를 화면 검수항목 카드로 변환한다.

    section 태그가 있는 findings(voice/naturalness/cultural)만 카드로 만든다.
    결정론적 critic findings(section 없음)는 loop.authorReviewCards에서 처리되므로 제외한다.
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
        "reviewSummaries": state.get("reviewSummaries") or {},   # 관점별 LLM 총평 {voice/naturalness/cultural: summary}
        "revisorSummary": state.get("revisorSummary") or "",     # 리바이저 수정 방향성 짧은 평
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
    builder.add_node("aggregate_review", _as_langgraph_node(aggregate_review))
    builder.add_node("revise_translation", _as_langgraph_node(revise_translation))
    builder.add_node("check_korean_residue", _as_langgraph_node(check_korean_residue))
    builder.add_node("final_integrity_check", _as_langgraph_node(final_integrity_check))
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
    builder.add_edge("normalize_input", "retrieve_korean_culture_context")
    builder.add_edge("load_work_memory", "prepare_translation_context")
    builder.add_edge("prepare_translation_context", "run_literary_translation")
    builder.add_edge("run_literary_translation", "deterministic_precheck")
    builder.add_edge("deterministic_precheck", "review_voice")
    builder.add_edge("deterministic_precheck", "review_naturalness")
    builder.add_edge("deterministic_precheck", "review_cultural")
    builder.add_edge("deterministic_precheck", "review_glossary")
    builder.add_edge(["review_voice", "review_naturalness", "review_cultural", "review_glossary"], "aggregate_review")
    builder.add_edge("aggregate_review", "revise_translation")
    builder.add_edge("revise_translation", "check_korean_residue")
    builder.add_edge("check_korean_residue", "final_integrity_check")
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
    state = aggregate_review(state)
    state = revise_translation(state)
    state = check_korean_residue(state)
    state = retrieve_korean_culture_context(state)
    state = write_reader_endnotes(state)
    state = filter_rank_endnotes(state)
    state = final_integrity_check(state)
    state = align_endnotes_to_final_translation(state)
    state = build_translation_package(state)
    state = persist_result(state) if should_persist(state) else skip_persist(state)
    state = capture_glossary_candidates(state) if should_capture_glossary(state) else skip_capture(state)
    return state


def _graph_invoke_config() -> dict[str, Any]:
    """번역 1건 내부 fan-out(리뷰 4노드 등)의 동시 LLM 호출 상한.

    env `WLIGHTER_LLM_MAX_CONCURRENCY`(기본 4 = 리뷰 fan-out 전부 병렬). LangGraph는 동기 invoke에서도
    병렬 분기를 스레드풀로 동시 실행하고 이 값으로 동시 개수를 캡한다(실측 검증: 4→0.5s/2→1.0s/1→직렬).
    0 이하/파싱오류면 미설정(무제한). 범위는 "invoke 1건(=요청 1건)" 내부 — 서버 전체 캡은 §방법3(후속).
    """
    try:
        limit = int(os.getenv("WLIGHTER_LLM_MAX_CONCURRENCY", "4"))
    except ValueError:
        limit = 4
    return {"max_concurrency": limit} if limit > 0 else {}


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
        state = graph.invoke(state, config=_graph_invoke_config())
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
        # glossary 리뷰어가 추출한 신규 용어 후보(승인 용어집 dedup 후). translationReport.glossaryCandidates 의 원천.
        package.internal["glossaryCandidates"] = state.get("glossaryCandidates") or []
        package.internal["revisorDecisions"] = state.get("revisorDecisions") or []
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
    revisor_hook: Callable[[TranslationGraphState], dict[str, Any]] | None = None,
    residue_repair_hook: Callable[[TranslationGraphState, list[dict[str, Any]]], dict[int, str]] | None = None,
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
            "revisorHook": revisor_hook,
            "residueRepairHook": residue_repair_hook,
        },
        max_iterations=max_iterations,
        translate_once=translate_once,
    )
    return state["translationPackage"]
