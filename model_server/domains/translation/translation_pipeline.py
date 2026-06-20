"""번역 파이프라인 — 단일 오케스트레이터.

v3 문학 번역 그래프를 "순수 부품"만 조립해 실행하는 유일한 진입점이다.
다른 파이프라인(레거시/v2)을 import 하지 않는다. 하위 폴더의 부품만 조립한다:

- agents.direct_translator.DirectTranslator : 실제 번역 엔진(translate_once)
- retrieval.annotation_retriever.AnnotationRetriever : kculture 문화 주석 RAG
- agents.endnote_writer.EndnoteWriter : 검색된 문화 표현 -> 독자용 각주(LLM)
- v3_graph_orchestrator / v3_literary_package : 순수 v3 코어(그래프/스텝)

과거 `translation_pipeline.TranslationPipeline.run_v3_literary_package`가 god-object
위에서 하던 일을 여기로 옮기고, 비어 있던 문화 주석 hook 2개(retrieve/endnote)를 배선했다.
"""
from __future__ import annotations

from typing import Any, Callable

from .agents.direct_translator import DirectTranslator
from .agents.endnote_writer import EndnoteWriter, build_reader_endnote_hook
from .agents.reviewers import CulturalSafetyReviewer, NaturalnessReviewer, VoiceReviewer
from .config import PipelineConfig
from .retrieval.annotation_retriever import AnnotationRetriever
from .engine.graph_orchestrator import build_v3_graph_literary_package
from .engine.literary_package import V3LiteraryPackageResult


def build_annotation_retrieval_hook(
    retriever: AnnotationRetriever,
) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """v3 그래프 annotationRetrievalHook 용 클로저.

    원문 전체를 kculture RAG 로 검색해(임계치는 config.annotation_score_threshold)
    그래프 state 가 쓰는 dict 리스트로 변환한다.
    """

    def _hook(state: dict[str, Any]) -> list[dict[str, Any]]:
        source_text = state.get("sourceText") or ""
        if not source_text.strip():
            return []
        results = retriever.retrieve(source_text)
        return [
            {
                "item": result.item,
                "score": result.similarity_score,
                "source_id": result.item.get("source_id"),
                "keyword_ko": result.item.get("keyword_ko"),
            }
            for result in results
        ]

    return _hook


def _hard_glossary_context(work_memory: dict[str, Any] | None) -> str:
    """승인된 hard glossary 를 번역 프롬프트용 지침 텍스트로."""
    glossary_rows: list[dict[str, Any]] = []
    if isinstance(work_memory, dict):
        rows = work_memory.get("approvedGlossary") or work_memory.get("approved_glossary") or []
        if isinstance(rows, list):
            glossary_rows = [row for row in rows if isinstance(row, dict)]
    hard_lines: list[str] = []
    for row in glossary_rows:
        if str(row.get("priority") or "").strip().lower() != "hard":
            continue
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        if not source or not target:
            continue
        aliases = [str(alias).strip() for alias in (row.get("aliases") or []) if str(alias).strip()]
        alias_text = f" (aliases: {', '.join(aliases[:5])})" if aliases else ""
        hard_lines.append(f"- {source}{alias_text} => {target}")
    if not hard_lines:
        return ""
    return (
        "[APPROVED HARD GLOSSARY]\n"
        "Use each approved target exactly when its source or alias appears in the Korean source. "
        "On retry, fix only mismatched glossary surface forms and keep the rest of the translation stable.\n"
        + "\n".join(hard_lines[:30])
    )


# --- LLM 리뷰어 어댑터: reviewers.py 출력 -> v3 그래프 issue 형식으로 "API 조정" ---
_SECTION_LABELS = {"voice": "말투", "naturalness": "자연스러움", "cultural": "문화권 유의사항"}
_SEVERITY_TO_PRIORITY = {"CRITICAL": "P1", "HIGH": "P1", "MEDIUM": "P2", "LOW": "P3"}


def _review_issue_to_v3(reviewer_type: str, issue: Any) -> dict[str, Any]:
    severity = str(getattr(issue, "severity", "") or "").upper()
    return {
        "code": f"{reviewer_type}_review",
        "type": f"{reviewer_type}_review",
        # advisory: 절대 P0(차단)로 매핑하지 않는다. 카드로만 노출.
        "priority": _SEVERITY_TO_PRIORITY.get(severity, "P3"),
        "severity": severity,
        "message": getattr(issue, "problem", "") or "",
        "sourceSpan": getattr(issue, "source_span", "") or "",
        "targetSpan": getattr(issue, "target_span", "") or "",
        "suggestion": getattr(issue, "suggestion", "") or "",
        "reviewerType": reviewer_type,
        "section": reviewer_type,
        "sectionLabel": _SECTION_LABELS.get(reviewer_type, reviewer_type),
        "autoRevisionEligible": False,
    }


def build_reviewer_hook(reviewers: dict[str, Any]) -> Callable[[dict[str, Any], str], list[dict[str, Any]]]:
    """v3 그래프 reviewerHook: (state, reviewer_type) -> list[v3 issue dict].

    advisory — voice/naturalness/cultural 만 LLM 리뷰(그 외 reviewer_type은 빈 리스트).
    현 후보 번역(draftTranslation)을 리뷰한다. mock 모드면 reviewer가 빈 결과를 낸다.
    """

    def _hook(state: dict[str, Any], reviewer_type: str) -> list[dict[str, Any]]:
        reviewer = reviewers.get(reviewer_type)
        if reviewer is None:
            return []
        translation = state.get("draftTranslation") or state.get("finalTranslation") or ""
        if not translation.strip():
            return []
        result = reviewer.review(
            source_text=state.get("sourceText") or "",
            translation=translation,
            rationale="",
            translation_profile=None,
            source_analysis=state.get("sourceAnalysis"),
        )
        return [_review_issue_to_v3(reviewer_type, issue) for issue in (result.issues or [])]

    return _hook


class TranslationPipeline:
    """단일 번역 파이프라인. config(locale/mock)로 구성하고 run() 한 번으로 실행."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self.direct_translator = DirectTranslator(self.config)
        self.annotation_retriever = AnnotationRetriever(self.config)
        self.endnote_writer = EndnoteWriter(self.config)
        self.reviewers = {
            "voice": VoiceReviewer(self.config),
            "naturalness": NaturalnessReviewer(self.config),
            "cultural": CulturalSafetyReviewer(self.config),
        }

    def run(
        self,
        source_text: str,
        *,
        genre: str = "Modern Korean web novel",
        work_memory: dict[str, Any] | None = None,
        max_iterations: int = 2,
        debug_capture_model_outputs: bool = False,
        debug_artifact_dir: str | None = None,
    ) -> V3LiteraryPackageResult:
        memory_context = _hard_glossary_context(work_memory)

        def translate_once(strict_locale_retry: bool, retry_attempt: int, revision_context: str = "") -> tuple[str, dict[str, Any]]:
            combined = memory_context
            if revision_context.strip():
                combined = (combined + "\n\n" if combined.strip() else "") + revision_context.strip()
            if "GRAPH TARGETED SMALL PROSE RESIDUE FALLBACK" in revision_context:
                attempt_name = "targeted_repair_fallback"
            elif "GRAPH STRICT CLEAN FINAL FALLBACK" in revision_context:
                attempt_name = "strict_clean_fallback"
            elif "GRAPH TARGETED SMALL PROSE RESIDUE REPAIR" in revision_context:
                attempt_name = "targeted_repair"
            elif "GRAPH CLEAN FULL TRANSLATOR RETRY" in revision_context:
                attempt_name = "graph_clean_full_translator_retry"
            elif revision_context.strip():
                attempt_name = "deterministic_revision"
            else:
                attempt_name = "initial_translation"
            direct = self.direct_translator.translate_once(
                source_text,
                memory_context=combined,
                strict_locale_retry=strict_locale_retry,
                retry_attempt=retry_attempt,
                debug_capture={
                    "enabled": debug_capture_model_outputs,
                    "artifactDir": debug_artifact_dir,
                    "attemptName": attempt_name,
                    "promptPreview": combined,
                },
            )
            return direct.final_translation, direct.metadata

        return build_v3_graph_literary_package(
            source_text,
            self.config.resolved_resources().locale,
            genre=genre,
            work_memory=work_memory,
            max_iterations=max_iterations,
            translate_once=None if self.config.mock else translate_once,
            annotation_retrieval_hook=build_annotation_retrieval_hook(self.annotation_retriever),
            reader_endnote_writer_hook=build_reader_endnote_hook(self.endnote_writer),
            reviewer_hook=build_reviewer_hook(self.reviewers),
        )

    # 기존 backend 호출부 호환 별칭 (translation_service 가 이 이름으로 호출).
    def run_v3_literary_package(
        self,
        source_text: str,
        *,
        genre: str = "Modern Korean web novel",
        work_memory: dict[str, Any] | None = None,
        max_iterations: int = 2,
        debug_capture_model_outputs: bool = False,
        debug_artifact_dir: str | None = None,
    ) -> V3LiteraryPackageResult:
        return self.run(
            source_text,
            genre=genre,
            work_memory=work_memory,
            max_iterations=max_iterations,
            debug_capture_model_outputs=debug_capture_model_outputs,
            debug_artifact_dir=debug_artifact_dir,
        )


def run_translation(
    source_text: str,
    *,
    config: PipelineConfig | None = None,
    genre: str = "Modern Korean web novel",
    work_memory: dict[str, Any] | None = None,
    max_iterations: int = 2,
    debug_capture_model_outputs: bool = False,
    debug_artifact_dir: str | None = None,
) -> V3LiteraryPackageResult:
    """편의 함수: 1회성 호출용. (반복 호출은 TranslationPipeline 인스턴스 재사용 권장)"""
    pipeline = TranslationPipeline(config)
    return pipeline.run(
        source_text,
        genre=genre,
        work_memory=work_memory,
        max_iterations=max_iterations,
        debug_capture_model_outputs=debug_capture_model_outputs,
        debug_artifact_dir=debug_artifact_dir,
    )
