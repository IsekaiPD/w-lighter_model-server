"""번역 파이프라인 오케스트레이터.

문학 번역 그래프에 번역기·문화주석 RAG·각주 작성기·리뷰어를 조립해 실행하는 진입점.
"""
from __future__ import annotations

from typing import Any, Callable

from .agents.direct_translator import DirectTranslator
from .agents.endnote_writer import EndnoteWriter, build_reader_endnote_hook
from .agents.reviewers import CulturalSafetyReviewer, GlossaryReviewer, NaturalnessReviewer, VoiceReviewer
from .agents.revisor import RevisorAgent
from .agents.residue_repairer import KoreanResidueRepairer
from .config import PipelineConfig
from .retrieval.annotation_retriever import AnnotationRetriever
from .engine.graph_orchestrator import build_graph_literary_package
from .engine.literary_package import LiteraryPackageResult
from .glossary.store import normalize_category
from .text_processing.glossary_normalize import canonical_ko_key, light_text


def build_annotation_retrieval_hook(
    retriever: AnnotationRetriever,
) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """원문을 kculture RAG로 검색해 그래프 state용 dict 리스트로 변환한다."""

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


# 리뷰어 출력(reviewers.py) → 그래프 issue 형식 어댑터
_SECTION_LABELS = {"voice": "말투", "naturalness": "자연스러움", "cultural": "문화권 유의사항", "glossary": "용어집"}


def _review_issue_adapter(reviewer_type: str, issue: Any) -> dict[str, Any]:
    # advisory 전용: severity/priority 없이 사용자 취사선택 카드로만 다룬다.
    # (하류 _issue_priority가 priority 부재 시 P3로 폴백 → repair P0 트리거와 무관)
    return {
        "code": f"{reviewer_type}_review",
        "type": f"{reviewer_type}_review",
        "message": getattr(issue, "problem", "") or "",
        "sourceSpan": getattr(issue, "source_span", "") or "",
        "targetSpan": getattr(issue, "target_span", "") or "",
        "suggestion": getattr(issue, "suggestion", "") or "",
        "reviewerType": reviewer_type,
        "section": reviewer_type,
        "sectionLabel": _SECTION_LABELS.get(reviewer_type, reviewer_type),
        "autoRevisionEligible": False,
    }


def build_revisor_hook(revisor: RevisorAgent) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """draft + reviewFindings를 리바이저로 취사선택 반영 → {finalTranslation, decisions} 반환."""

    def _hook(state: dict[str, Any]) -> dict[str, Any]:
        result = revisor.revise(
            source_text=state.get("sourceText") or "",
            draft_translation=state.get("draftTranslation") or "",
            findings=state.get("reviewFindings") or [],
        )
        return {"finalTranslation": result.finalTranslation, "decisions": result.decisions, "summary": result.summary}

    return _hook


def build_residue_repair_hook(repairer: KoreanResidueRepairer) -> Callable[[dict[str, Any], list[dict[str, Any]]], dict[int, str]]:
    """한글 잔류 문장 단위({index, sentence})를 받아 {index: fixed}로 수리."""

    def _hook(state: dict[str, Any], units: list[dict[str, Any]]) -> dict[int, str]:
        return repairer.repair(source_text=state.get("sourceText") or "", units=units)

    return _hook


# glossary 신규 용어 후보 sanity 가드 — LLM이 인물/지명이 든 '문장'을 통째로 source로
# 인용하는 오류를 결정론적으로 차단한다(고유명사 용어만 통과). raw source(공백·부호 보존) 기준 평가.
_MAX_GLOSSARY_SOURCE_LEN = 20                                  # 원어 표면 길이 상한(고유명사는 보통 ≤8자)
_GLOSSARY_SOURCE_SENTENCE_PUNCT = tuple(".?!。？！…\"'“”")       # 문장종결/대사 신호
_MAX_GLOSSARY_SOURCE_EOJEOL = 3                                # 3어절까지 허용, 4↑은 구/문장으로 간주


def _looks_like_sentence(source: str) -> bool:
    """고유명사 후보 source가 문장·구절이면 True(→ 후보 제외).

    셋 중 하나라도 해당하면 문장으로 본다: ① 20자 초과 ② 문장종결부호/따옴표 포함 ③ 4어절 이상.
    정상 고유명사(짧음·부호 없음·≤3어절)는 모두 통과한다.
    """
    s = (source or "").strip()
    if not s:
        return True
    if len(s) > _MAX_GLOSSARY_SOURCE_LEN:
        return True
    if any(punct in s for punct in _GLOSSARY_SOURCE_SENTENCE_PUNCT):
        return True
    if len(s.split()) > _MAX_GLOSSARY_SOURCE_EOJEOL:
        return True
    return False


def build_reviewer_hook(reviewers: dict[str, Any]) -> Callable[[dict[str, Any], str], list[dict[str, Any]]]:
    """후보 번역을 voice/naturalness/cultural/glossary 리뷰어로 검토해 issue 리스트를 만든다.

    등록되지 않은 reviewer_type과 빈 번역은 빈 리스트를 반환한다.
    glossary 리뷰어에는 확정 승인 용어집(state["approvedGlossary"])을 함께 넘긴다.
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
            approved_glossary=state.get("approvedGlossary") if reviewer_type == "glossary" else None,
        )
        # 이 관점의 전체 평가 총평을 노드가 graphReviewTrace row에 실을 수 있도록 stash.
        # (노드별 working state라 병렬 충돌 없음; aggregate_review가 trace에서 모아 reviewSummaries 구성.)
        state["currentReviewerSummary"] = str(getattr(result, "summary", "") or "")
        if reviewer_type == "glossary":
            # 신규 용어 후보를 state로 표면화. 결정론적 정규화 후 dedup·export:
            # - dedup 비교: canonical_ko_key(공백·조사·NFC 변형을 하나로) — 이미 승인된 source 확실히 제외.
            # - 저장·표시값: light_text(공백·조사 보존). 비교키(canonical)를 그대로 표시하면 띄어쓰기가
            #   사라지므로(웹 노출 버그) 역할 분리: dedup=canonical / 저장·표시=light_text.
            # - 문장/구절이 source로 오는 LLM 오류는 _looks_like_sentence로 사전 차단(고유명사만 통과).
            approved_keys = {
                canonical_ko_key((row or {}).get("source") or "")
                for row in (state.get("approvedGlossary") or [])
            }
            approved_keys.discard("")
            fresh: list[dict[str, Any]] = []
            seen_keys: set[str] = set()
            for cand in (getattr(result, "candidates", None) or []):
                raw_source = str(cand.get("source") or "").strip()
                if _looks_like_sentence(raw_source):
                    continue  # 문장·구절·과길이 → 고유명사 후보 아님
                key = canonical_ko_key(raw_source)
                if not key or key in approved_keys or key in seen_keys:
                    continue  # 빈 키·이미 승인됨·이번 배치 내 중복 → 제외
                seen_keys.add(key)
                fresh.append(
                    {
                        "source": light_text(raw_source),  # 저장·표시값(공백 보존). 비교는 canonical(key).
                        "suggested_target": light_text(cand.get("suggested_target") or ""),
                        "category": normalize_category(cand.get("category") or ""),
                        "reason": str(cand.get("reason") or "").strip(),
                    }
                )
            if fresh:
                state["glossaryCandidates"] = fresh
        return [_review_issue_adapter(reviewer_type, issue) for issue in (result.issues or [])]

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
            "glossary": GlossaryReviewer(self.config),
        }
        self.revisor = RevisorAgent(self.config)
        self.residue_repairer = KoreanResidueRepairer(self.config)

    def run(
        self,
        source_text: str,
        *,
        genre: str = "Modern Korean web novel",
        work_memory: dict[str, Any] | None = None,
        max_iterations: int = 2,
        debug_capture_model_outputs: bool = False,
        debug_artifact_dir: str | None = None,
    ) -> LiteraryPackageResult:
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
            # 첫 번역가의 overview(번역가 노트)를 metadata에 실어 그래프→summary로 전달.
            return direct.final_translation, {**direct.metadata, "draftOverview": (direct.draft or {}).get("overview", "")}

        return build_graph_literary_package(
            source_text,
            self.config.resolved_resources().locale,
            genre=genre,
            work_memory=work_memory,
            max_iterations=max_iterations,
            translate_once=None if self.config.mock else translate_once,
            annotation_retrieval_hook=build_annotation_retrieval_hook(self.annotation_retriever),
            reader_endnote_writer_hook=build_reader_endnote_hook(self.endnote_writer),
            reviewer_hook=build_reviewer_hook(self.reviewers),
            revisor_hook=build_revisor_hook(self.revisor),
            residue_repair_hook=build_residue_repair_hook(self.residue_repairer),
        )

    # service가 호출하는 호환 별칭.
    def run_literary_package(
        self,
        source_text: str,
        *,
        genre: str = "Modern Korean web novel",
        work_memory: dict[str, Any] | None = None,
        max_iterations: int = 2,
        debug_capture_model_outputs: bool = False,
        debug_artifact_dir: str | None = None,
    ) -> LiteraryPackageResult:
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
) -> LiteraryPackageResult:
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
