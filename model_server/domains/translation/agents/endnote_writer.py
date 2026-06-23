"""독자용 각주(reader endnote) 작성 에이전트 (LLM 스텝).

v3 그래프 주석 갈래의 마지막 단계인 `write_reader_endnotes` 노드에 hook으로 주입된다.
kculture RAG(`AnnotationRetriever`)가 찾아낸 한국 문화 표현을, 해당 장면의 맥락에
자연스럽게 녹여 "목표 독자 언어"로 서술한 독자용 각주로 만든다.

- finalTranslation 은 절대 수정하지 않는다(각주는 별도 필드 readerEndnotes).
- 검색 결과가 없으면 LLM 을 호출하지 않고 빈 리스트를 반환한다(비용 가드).
- mock 모드에서는 결정적 각주를 만들어 네트워크 없이 검증한다.
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
                "required": ["keyword", "koreanNote", "targetNote"],
                "properties": {
                    "keyword": {"type": "string", "description": "각주 대상 한국 문화 키워드(한국어 표기)"},
                    "koreanNote": {"type": "string", "description": "장면 맥락에 녹인 한국어 각주 설명(작가/검수자가 의미 확인용)"},
                    "targetNote": {"type": "string", "description": "같은 내용을 대상 독자 언어로 쓴 각주"},
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "You are a localization endnote writer for translated Korean web novels. "
    "Given Korean cultural expressions detected in the source text, write short reader endnotes "
    "that explain each culture-specific term. For each item output three fields: `keyword` (the "
    "Korean cultural term), `koreanNote` (a Korean-language explanation woven into the scene "
    "context, so a Korean author/editor can verify the meaning), and `targetNote` (the SAME "
    "explanation written in the target reader's language). Weave the explanation into the scene "
    "naturally instead of a dry dictionary gloss. Only annotate genuinely culture-specific Korean "
    "references; skip generic words. These endnotes are an end-of-text list, so do not reference "
    "positions in the translation. Never modify the translation itself."
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
                "[TASK]\nWrite one endnote per candidate that genuinely needs a cultural "
                "explanation. For each, output `keyword`, `koreanNote` (Korean explanation), and "
                f"`targetNote` (the same content in {self.resources.target_language}). Skip "
                "candidates that don't need a note. Return JSON only.",
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
                    "keyword": keyword,
                    "koreanNote": context[:280] or f"한국 문화 표현: {keyword}",
                    "targetNote": context[:280] or f"Korean cultural reference: {keyword}",
                }
            )
        return notes


def build_reader_endnote_hook(writer: EndnoteWriter) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """v3 그래프 readerEndnoteWriterHook 용 클로저.

    state 에서 sourceText/finalTranslation/annotationRetrievals 를 꺼내
    EndnoteWriter 로 각주를 작성한다.
    """

    def _hook(state: dict[str, Any]) -> list[dict[str, Any]]:
        return writer.write(
            source_text=state.get("sourceText") or "",
            final_translation=state.get("finalTranslation") or "",
            annotation_results=state.get("annotationRetrievals") or [],
        )

    return _hook
