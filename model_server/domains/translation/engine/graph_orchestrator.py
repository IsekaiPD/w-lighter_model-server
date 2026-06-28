from __future__ import annotations

import os
from dataclasses import asdict, replace
from typing import Annotated, Any, Callable, Literal, TypedDict

try:  # optional at runtime; requirements.txt includes langgraph for graph mode
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - exercised only when dependency is absent
    END = START = StateGraph = None

from .literary_package import (
    LiteraryPackageResult,
    normalize_work_memory,
    TranslationLoopResult,
    _failure_signals,
    _judge,
    _mock_literary_translation,
    _glossary_source_set,
    _source_present,
)
from ..text_processing.korean_output import (
    apply_unit_repairs,
    has_korean_residue,
    korean_residue_units,
)


GraphNodeName = Literal[
    "load_work_memory",
    "run_literary_translation",
    "review_voice",
    "review_naturalness",
    "review_cultural",
    "review_glossary",
    "aggregate_review",
    "revise_translation",
    "check_korean_residue",
    "retrieve_korean_culture_context",
    "write_reader_endnotes",
    "build_translation_package",
]


def _append_trace(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(left or []) + list(right or [])


def _last_write_str(left: str | None, right: str | None) -> str:
    # 병렬 노드(리뷰어 fan-out)가 같은 키에 써도 에러 없이 병합. 값은 노드 내부에서만 읽혀 병합 결과는 미사용.
    return right if right else (left or "")


class TranslationGraphState(TypedDict, total=False):
    request: dict[str, Any]
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
    draftTranslation: str
    draftMetadata: dict[str, Any]
    reviewFindings: Annotated[list[dict[str, Any]], _append_trace]
    aggregateReview: dict[str, Any]
    graphReviewTrace: Annotated[list[dict[str, Any]], _append_trace]
    finalTranslation: str
    annotationRetrievals: list[dict[str, Any]]
    readerEndnotes: list[dict[str, Any]]
    annotationTrace: dict[str, Any]
    translationPackage: LiteraryPackageResult
    glossaryCandidates: list[dict[str, Any]]  # glossary 리뷰어가 추출한 신규 용어 후보(승인 dedup 후)
    revisorDecisions: list[dict[str, Any]]    # 리바이저의 finding별 적용/기각 결정
    revisorSummary: str                       # 리바이저의 수정 방향성 짧은 평(revisor_summary)
    currentReviewerSummary: Annotated[str, _last_write_str]  # 리뷰 노드 내부 전달용(훅→trace row); 병렬 write 허용
    reviewSummaries: dict[str, Any]           # 관점별 LLM 총평 {reviewerType: summary} (aggregate_review 조립)
    maxIterations: int
    graphExecutionFrame: str
    _loop: Any
    graphTrace: Annotated[list[dict[str, Any]], _append_trace]
    annotationRetrievalHook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None
    revisorHook: Callable[[TranslationGraphState], dict[str, Any]] | None
    residueRepairHook: Callable[[TranslationGraphState, list[dict[str, Any]]], dict[int, str]] | None
    readerEndnoteWriterHook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None
    # LLM 리뷰어 hook: (state, reviewer_type) -> list[issue dict]. 없으면 결정론적 리뷰만.
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


def _graph_translate_once(
    *,
    source_text: str,
    target_locale: str,
    work_memory: Any,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None,
    strict: bool,
    attempt: int,
    revision_context: str,
) -> tuple[str, dict[str, Any]]:
    if translate_once is None:
        return _mock_literary_translation(source_text, target_locale, work_memory=work_memory), {"mock": True, "draftOverview": "목 모드: 번역가 노트(초벌)."}
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


_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
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


def _llm_reviewer_findings(state: TranslationGraphState, reviewer_type: str) -> list[dict[str, Any]]:
    """주입된 LLM 리뷰어 hook으로 advisory findings를 만든다.

    hook 시그니처: (state, reviewer_type) -> list[issue dict].
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
    findings = _llm_reviewer_findings(state, reviewer_type)
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
    if repair_required:
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


def revise_translation(state: TranslationGraphState) -> TranslationGraphState:
    """리바이저 원맨 체제: draft + reviewFindings를 취사선택 반영해 최종 번역문 + decisions 생성.

    리바이저 출력이 곧 최종본이다. 결과를 TranslationLoopResult로 담아 state["_loop"]에 넣으면,
    check_korean_residue가 한글 잔류만 수리하고 build_translation_package가 패키징한다.
    (재번역 수리 루프·차단 판정 없음 — 항상 deliverable, 리바이저 결과를 다시 덮어쓰지 않는다.)
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
    (차단 판정 없음 — 못 고쳐도 최종본으로 그대로 진행. final_integrity_check는 폐지됨.)
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
        "keyword": str(row.get("keyword") or row.get("sourceSpan") or "").strip(),
        "targetKeyword": str(row.get("targetKeyword") or "").strip(),
        "koreanNote": str(row.get("koreanNote") or "").strip(),
        "targetNote": str(row.get("targetNote") or row.get("note") or "").strip(),
        "targetSentence": str(row.get("targetSentence") or "").strip(),
    }


def write_reader_endnotes(state: TranslationGraphState) -> TranslationGraphState:
    # LLM 미주 작성 + 결정적 후처리(정규화·dedup·필수필드 검증)를 한 노드에서 끝낸다.
    hook = state.get("readerEndnoteWriterHook")
    notes = hook(state) if hook else []
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for index, note in enumerate(notes or []):
        if not isinstance(note, dict):
            continue
        row = _normalize_reader_endnote(note, index)
        keyword = row["keyword"]
        # 필수 4필드(keyword·targetKeyword·koreanNote·targetNote) 중 하나라도 비면 제거.
        # targetSentence는 best-effort라 비어도 통과.
        if not keyword or not row["targetKeyword"] or not row["koreanNote"] or not row["targetNote"]:
            continue
        if keyword in seen:
            continue  # keyword 기준 dedup
        seen.add(keyword)
        kept.append(row)
    state["readerEndnotes"] = kept
    trace = dict(state.get("annotationTrace") or {})
    trace["keptCount"] = len(kept)
    state["annotationTrace"] = trace
    return _trace(state, "write_reader_endnotes", readerEndnotesCount=len(kept))


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
                "id": f"review-card-{index}",
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
    memory = state.get("workMemory")
    internal = {
        "workMemory": asdict(memory) if memory else None,
        "iterations": loop.iterations,
        "judge": loop.judge,
        "failureSignals": _failure_signals(loop.qaIssues),
        "graphReviewTrace": state.get("graphReviewTrace") or [],
        "reviewFindings": state.get("reviewFindings") or [],
        "aggregateReview": state.get("aggregateReview") or {},
        "reviewSummaries": state.get("reviewSummaries") or {},   # 관점별 LLM 총평 {voice/naturalness/cultural: summary}
        "revisorSummary": state.get("revisorSummary") or "",     # 리바이저 수정 방향성 짧은 평
        "maxIterations": min(max(1, int(state.get("maxIterations") or 2)), 2),
        "maxRevisionPass": 1,
        "readerEndnotes": state.get("readerEndnotes") or [],
        "annotationTrace": state.get("annotationTrace") or {"chunkCount": 0, "candidateCount": 0, "retrievalCount": 0, "keptCount": 0},
        "graphOrchestrator": {
            "enabled": True,
            "executionFrame": state.get("graphExecutionFrame") or "stategraph_compatible",
            "nodes": [row["node"] for row in state.get("graphTrace", [])],
        },
        "mockBoundaries": {
            "workMemory": "in-memory payload only",
            "readerEndnotes": "annotation branch adapter/stub unless hooks provide retrieval-backed notes",
        },
    }
    # 첫 번역가 overview(번역가 노트) → translationReport.summary "번역가:" 줄의 실데이터 원천.
    internal["draftOverview"] = str((state.get("draftMetadata") or {}).get("draftOverview") or "")
    # 결정론적 critic 카드 + LLM 리뷰어(말투/자연스러움/문화) 카드 합류.
    author_review_cards = list(loop.authorReviewCards) + _review_cards_from_findings(state.get("reviewFindings") or [])
    package = LiteraryPackageResult(
        "literary_package",
        loop.finalTranslation,
        loop.qaIssues,
        author_review_cards,
        internal,
        readerEndnotes=state.get("readerEndnotes") or [],
    )
    state["translationPackage"] = package
    return _trace(state, "build_translation_package", readerEndnotesCount=len(package.readerEndnotes))


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
    builder.add_node("load_work_memory", _as_langgraph_node(load_work_memory))
    builder.add_node("run_literary_translation", _as_langgraph_node(run_literary_translation, translate_once=translate_once))
    builder.add_node("review_voice", _as_langgraph_node(review_voice))
    builder.add_node("review_naturalness", _as_langgraph_node(review_naturalness))
    builder.add_node("review_cultural", _as_langgraph_node(review_cultural))
    builder.add_node("review_glossary", _as_langgraph_node(review_glossary))
    builder.add_node("aggregate_review", _as_langgraph_node(aggregate_review))
    builder.add_node("revise_translation", _as_langgraph_node(revise_translation))
    builder.add_node("check_korean_residue", _as_langgraph_node(check_korean_residue))
    builder.add_node("retrieve_korean_culture_context", _as_langgraph_node(retrieve_korean_culture_context))
    builder.add_node("write_reader_endnotes", _as_langgraph_node(write_reader_endnotes))
    builder.add_node("build_translation_package", _as_langgraph_node(build_translation_package))

    builder.add_edge(START, "load_work_memory")
    builder.add_edge("load_work_memory", "run_literary_translation")
    # retrieve는 sourceText만 쓰므로 번역과 병렬(같은 superstep).
    builder.add_edge("load_work_memory", "retrieve_korean_culture_context")
    builder.add_edge("run_literary_translation", "review_voice")
    builder.add_edge("run_literary_translation", "review_naturalness")
    builder.add_edge("run_literary_translation", "review_cultural")
    builder.add_edge("run_literary_translation", "review_glossary")
    builder.add_edge(["review_voice", "review_naturalness", "review_cultural", "review_glossary"], "aggregate_review")
    builder.add_edge("aggregate_review", "revise_translation")
    builder.add_edge("revise_translation", "check_korean_residue")
    # write는 최종 번역문(check_korean_residue)+검색결과(retrieve)가 둘 다 끝난 뒤 실행.
    builder.add_edge(["check_korean_residue", "retrieve_korean_culture_context"], "write_reader_endnotes")
    builder.add_edge("write_reader_endnotes", "build_translation_package")
    builder.add_edge("build_translation_package", END)
    return builder.compile(name="literary_package_graph")


def _run_compatible_runner(
    state: TranslationGraphState,
    *,
    max_iterations: int,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None,
) -> TranslationGraphState:
    state["graphExecutionFrame"] = "stategraph_compatible"
    state = load_work_memory(state)
    state = run_literary_translation(state, translate_once=translate_once)
    state = review_voice(state)
    state = review_naturalness(state)
    state = review_cultural(state)
    state = review_glossary(state)
    state = aggregate_review(state)
    state = revise_translation(state)
    state = check_korean_residue(state)
    state = retrieve_korean_culture_context(state)
    state = write_reader_endnotes(state)
    state = build_translation_package(state)
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


def build_graph_literary_package(
    source_text: str,
    target_locale: str,
    *,
    genre: str = "Modern Korean web novel",
    work_memory: Any = None,
    max_iterations: int = 2,
    translate_once: Callable[..., tuple[str, dict[str, Any]]] | None = None,
    annotation_retrieval_hook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None = None,
    reader_endnote_writer_hook: Callable[[TranslationGraphState], list[dict[str, Any]]] | None = None,
    reviewer_hook: Callable[[TranslationGraphState, str], list[dict[str, Any]]] | None = None,
    revisor_hook: Callable[[TranslationGraphState], dict[str, Any]] | None = None,
    residue_repair_hook: Callable[[TranslationGraphState, list[dict[str, Any]]], dict[int, str]] | None = None,
) -> LiteraryPackageResult:
    state = run_graph_orchestrator(
        {
            "request": {"sourceText": source_text, "targetLocale": target_locale, "mode": "literary_package", "genre": genre},
            "sourceText": source_text,
            "targetLocale": target_locale,
            "genre": genre,
            "workMemory": work_memory,
            "workMemorySource": "request_payload" if work_memory is not None else "none",
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
