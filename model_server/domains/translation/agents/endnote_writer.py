"""독자용 각주(reader endnote) 작성 에이전트 (LLM 스텝).

그래프 주석 갈래의 마지막 단계인 `write_reader_endnotes` 노드에 hook으로 주입된다.
kculture RAG(`AnnotationRetriever`)가 찾아낸 한국 문화 표현을, 해당 장면의 맥락에
자연스럽게 녹여 "목표 독자 언어"로 서술한 독자용 각주로 만든다.

- finalTranslation 은 절대 수정하지 않는다(각주는 별도 필드 readerEndnotes).
- 검색 결과가 없으면 LLM 을 호출하지 않고 빈 리스트를 반환한다(비용 가드).
- mock 모드에서는 결정적 각주를 만들어 네트워크 없이 검증한다.
"""
from __future__ import annotations

import json
import re
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
                "required": ["keyword", "targetKeyword", "koreanNote", "targetNote", "targetSentence"],
                "properties": {
                    "keyword": {"type": "string", "description": "각주 대상 한국 문화 키워드(한국어 표기)"},
                    "targetKeyword": {"type": "string", "description": "키워드를 최종 번역문에 나온 표면형 그대로 쓴 대상언어 표기(A). 본문에 별도 단어로 안 나오면 가장 자연스러운 대상언어 표기"},
                    "koreanNote": {"type": "string", "description": "장면 맥락에 녹인 한국어 각주 설명(작가/검수자가 의미 확인용)"},
                    "targetNote": {"type": "string", "description": "같은 내용을 대상 독자 언어로 쓴 각주"},
                    "targetSentence": {"type": "string", "description": "이 키워드가 들어간 최종 번역문 문장을 그대로(verbatim) 복사. 번역문에 안 나오면 빈 문자열"},
                },
            },
        }
    },
}

# 대상언어(JA/EN/CN/TH 등) 문장 분리용 best-effort 정규식: 문장부호/줄바꿈 뒤에서 끊는다.
# (Kiwi는 한국어 전용이라 번역문엔 안 맞음 → 가벼운 범용 분리로 충분.)
_TARGET_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？…\n])\s+")


def _split_target_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _TARGET_SENTENCE_SPLIT_RE.split(text or "") if part.strip()]
    if parts:
        return parts
    stripped = (text or "").strip()
    return [stripped] if stripped else []


def _locate_target_sentence(term: str, final_translation: str) -> str:
    """term(A)이 최종 번역문에 그대로 있으면 그 term이 든 문장을 돌려준다(best-effort). 없으면 ""."""
    term = (term or "").strip()
    final = final_translation or ""
    if not term or term not in final:
        return ""
    for sentence in _split_target_sentences(final):
        if term in sentence:
            return sentence
    return ""

_SYSTEM_PROMPT = (
    "You are a localization endnote writer for translated Korean web novels. "
    "Given Korean cultural expressions detected in the source text, write short reader endnotes "
    "that explain each culture-specific term. For each item output five fields: "
    "`keyword` (the Korean cultural term); "
    "`targetKeyword` (the term as it ACTUALLY appears in the FINAL_TRANSLATION — copy the exact "
    "surface form used there, especially for names/places that follow an approved glossary; if the "
    "term is not rendered as a distinct word, give the most natural target-language rendering of the "
    "keyword); "
    "`koreanNote` (a Korean-language explanation woven into the scene context, so a Korean "
    "author/editor can verify the meaning); "
    "`targetNote` (the SAME explanation written in the target reader's language); and "
    "`targetSentence` (copy, VERBATIM, the single sentence from the FINAL_TRANSLATION that contains "
    "this term; if the term does not appear in the translation, return an empty string). "
    "Weave the explanation into the scene naturally instead of a dry dictionary gloss. Only annotate "
    "genuinely culture-specific Korean references; skip generic words. The endnotes are an end-of-text "
    "list shown as `targetKeyword: targetNote`; `targetSentence` is used only to match an endnote to "
    "its sentence, not to insert inline markers. Never modify the translation itself."
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
            return self._mock_endnotes(items, final_translation)

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
                "explanation. For each, output `keyword`, `targetKeyword` (the term as written in "
                "FINAL_TRANSLATION), `koreanNote` (Korean explanation), "
                f"`targetNote` (the same content in {self.resources.target_language}), and "
                "`targetSentence` (the verbatim FINAL_TRANSLATION sentence containing the term, or "
                '"" if absent). Skip candidates that don\'t need a note. Return JSON only.',
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
        return self._finalize_notes(notes, final_translation)

    @staticmethod
    def _finalize_notes(notes: list[Any], final_translation: str) -> list[dict[str, Any]]:
        """LLM 출력 정리 + targetSentence 검증.

        targetSentence는 '실제 번역문의 verbatim substring'일 때만 신뢰한다(환각 방어).
        아니면 targetKeyword(A)로 문장을 재탐색하고, 그래도 없으면 ""로 둔다(best-effort).
        """
        final = final_translation or ""
        cleaned: list[dict[str, Any]] = []
        for note in notes:
            if not isinstance(note, dict):
                continue
            keyword = str(note.get("keyword") or "").strip()
            target_keyword = str(note.get("targetKeyword") or "").strip()
            korean_note = str(note.get("koreanNote") or "").strip()
            target_note = str(note.get("targetNote") or "").strip()
            llm_sentence = str(note.get("targetSentence") or "").strip()
            if llm_sentence and llm_sentence in final:
                target_sentence = llm_sentence
            else:
                target_sentence = _locate_target_sentence(target_keyword or keyword, final)
            cleaned.append(
                {
                    "keyword": keyword,
                    "targetKeyword": target_keyword,
                    "koreanNote": korean_note,
                    "targetNote": target_note,
                    "targetSentence": target_sentence,
                }
            )
        return cleaned

    @staticmethod
    def _mock_endnotes(items: list[dict[str, Any]], final_translation: str = "") -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for item in items:
            keyword = str(item.get("keyword_ko") or "").strip()
            context = str(item.get("context_text") or "").strip()
            if not keyword:
                continue
            notes.append(
                {
                    "keyword": keyword,
                    "targetKeyword": keyword,  # mock: 대상언어 표기 대신 키워드 그대로(네트워크 없이 결정적)
                    "koreanNote": context[:280] or f"한국 문화 표현: {keyword}",
                    "targetNote": context[:280] or f"Korean cultural reference: {keyword}",
                    "targetSentence": _locate_target_sentence(keyword, final_translation),
                }
            )
        return notes


def build_reader_endnote_hook(writer: EndnoteWriter) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """그래프 readerEndnoteWriterHook 용 클로저.

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
