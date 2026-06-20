"""독자용 각주(reader endnote) 작성 에이전트 (LLM 스텝).

v3 그래프 주석 갈래의 마지막 단계인 `write_reader_endnotes` 노드에 hook으로 주입된다.
kculture RAG(`AnnotationRetriever`)가 찾아낸 한국 문화 표현을, 해당 장면의 맥락에
자연스럽게 녹여 "목표 독자 언어"로 서술한 독자용 각주로 만든다.

- finalTranslation 은 절대 수정하지 않는다(각주는 별도 필드 readerEndnotes).
- 검색 결과가 없으면 LLM 을 호출하지 않고 빈 리스트를 반환한다(비용 가드).
- mock 모드에서는 결정적 각주를 만들어 테스트/스모크가 네트워크 없이 돈다.

LLM 호출 패턴은 agents/translator.py 를 따른다.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from ..config import PipelineConfig
from ..infra.openai_client import get_openai_client

# OpenAI structured output(strict) 스키마: 모든 필드 required + additionalProperties=false
ENDNOTE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["endnotes"],
    "properties": {
        "endnotes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sourceSpan", "targetSpan", "category", "note", "confidence"],
                "properties": {
                    "sourceSpan": {"type": "string", "description": "각주 대상이 되는 한국어 원문 표현"},
                    "targetSpan": {"type": "string", "description": "finalTranslation 안에서 그 표현에 해당하는 부분(없으면 빈 문자열)"},
                    "category": {"type": "string", "description": "예: korean_cultural_reference, food, custom, place"},
                    "note": {"type": "string", "description": "목표 독자 언어로 작성한, 장면 맥락에 녹인 독자용 각주 설명"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "You are a localization endnote writer for translated Korean web novels. "
    "Given Korean cultural expressions detected in the source text and the final translation, "
    "write short reader endnotes that explain each culture-specific term for a reader of the "
    "target language. Weave the explanation into the scene context naturally instead of giving a "
    "dry dictionary gloss. Never modify the translation itself. Only annotate genuinely "
    "culture-specific Korean references; skip generic words. Write each note in the target "
    "reader's language."
)


def _result_items(annotation_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """annotationRetrievals(dict 리스트)에서 payload(item)만 추린다."""
    items: list[dict[str, Any]] = []
    for row in annotation_results or []:
        item = row.get("item") if isinstance(row, dict) else None
        if isinstance(item, dict):
            items.append(item)
    return items


class EndnoteWriter:
    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self.resources = self.config.resolved_resources()

    def write(
        self,
        *,
        source_text: str,
        final_translation: str,
        annotation_results: list[dict[str, Any]],
        source_chunks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        items = _result_items(annotation_results)
        if not items:
            return []
        if self.config.mock:
            return self._mock_endnotes(items)

        candidates_block = "\n".join(
            f"{i}. keyword: {item.get('keyword_ko', '')}\n   context: {item.get('context_text', '')}"
            for i, item in enumerate(items, start=1)
        )
        prompt = "\n\n".join(
            [
                f"[TARGET_READER_LANGUAGE]\n{self.resources.target_language}",
                f"[KOREAN_CULTURAL_CANDIDATES]\n{candidates_block}",
                f"[SOURCE_TEXT]\n{source_text}",
                f"[FINAL_TRANSLATION]\n{final_translation}",
                "[TASK]\nWrite one endnote per candidate that genuinely needs explanation for the "
                "target reader. Set targetSpan to the matching phrase in FINAL_TRANSLATION when it "
                "exists, otherwise an empty string. Return JSON only.",
            ]
        )
        client = get_openai_client()
        response = client.responses.create(
            model=self.config.review_model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "reader_endnotes",
                    "schema": ENDNOTE_JSON_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        notes = payload.get("endnotes") or []
        return [note for note in notes if isinstance(note, dict)]

    @staticmethod
    def _mock_endnotes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for item in items:
            keyword = str(item.get("keyword_ko") or "").strip()
            context = str(item.get("context_text") or "").strip()
            if not keyword:
                continue
            notes.append(
                {
                    "sourceSpan": keyword,
                    "targetSpan": "",
                    "category": str(item.get("category") or "korean_cultural_reference"),
                    "note": context[:280] or f"Korean cultural reference: {keyword}",
                    "confidence": "medium",
                }
            )
        return notes


def build_reader_endnote_hook(writer: EndnoteWriter) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """v3 그래프 readerEndnoteWriterHook 용 클로저.

    state 에서 sourceText/finalTranslation/annotationRetrievals/sourceChunks 를 꺼내
    EndnoteWriter 로 각주를 작성한다. (그래프가 raw dict 리스트를 받아 정규화한다)
    """

    def _hook(state: dict[str, Any]) -> list[dict[str, Any]]:
        return writer.write(
            source_text=state.get("sourceText") or "",
            final_translation=state.get("finalTranslation") or "",
            annotation_results=state.get("annotationRetrievals") or [],
            source_chunks=state.get("sourceChunks") or [],
        )

    return _hook
