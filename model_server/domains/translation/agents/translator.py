from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any

from ..config import PipelineConfig
from ..text_processing.korean_output import koreanize_text
from ..infra.mock_adapters import translation_payload
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_runtime_prompt
from ..retrieval.retriever import IdiomRetriever, RetrievalResult


TRANSLATOR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "translation": {"type": "string"},
        "overview": {
            "type": "string",
            "description": "한국어 설명만 허용. 번역가가 이 장면을 어떻게/왜 그렇게 번역했는지에 대한 짧은 총평(번역가 노트).",
        },
    },
    "required": [
        "translation",
        "overview",
    ],
}


@dataclass(slots=True)
class TranslationDraft:
    translation: str
    overview: str
    raw_response: dict[str, Any]
    prompt_debug: dict[str, Any]


def _format_profile_context(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    if not profile:
        return ""
    return "\n".join(
        [
            "[TRANSLATION_PROFILE]",
            f"- tone: {profile.get('tone', '')}",
            f"- dialogue_style: {profile.get('dialogue_style', '')}",
            f"- narration_style: {profile.get('narration_style', '')}",
            f"- localization_level: {profile.get('localization_level', '')}",
            f"- proper_noun_policy: {profile.get('proper_noun_policy', '')}",
            f"- culture_policy: {profile.get('culture_policy', '')}",
            f"- do_not: {', '.join(profile.get('do_not') or [])}",
        ]
    ).strip()


def _format_source_analysis_context(analysis: dict[str, Any] | None) -> str:
    analysis = analysis or {}
    if not analysis:
        return ""
    return "\n".join(
        [
            "[SOURCE_ANALYSIS]",
            f"- summary: {analysis.get('summary', '')}",
            f"- scene_functions: {', '.join(analysis.get('scene_functions') or [])}",
            f"- emotions: {', '.join(analysis.get('emotions') or [])}",
            f"- idiom_candidates: {', '.join(analysis.get('idiom_candidates') or []) or 'none'}",
            f"- cultural_elements: {', '.join(analysis.get('cultural_elements') or []) or 'none'}",
            f"- speech_hints: {', '.join(analysis.get('speech_hints') or []) or 'none'}",
        ]
    ).strip()


class Translator:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()
        self.prompt_template = load_runtime_prompt("TRANSLATOR_PROMPT.md")
        self.common_korean_rule = load_runtime_prompt("COMMON_KOREAN_OUTPUT_RULE.md")

    def translate(
        self,
        source_text: str,
        retrievals: list[RetrievalResult],
        *,
        memory_context: str = "",
        translation_profile: dict[str, Any] | None = None,
        source_analysis: dict[str, Any] | None = None,
        include_rag_context: bool = True,
        strict_locale_retry: bool = False,
        retry_attempt: int = 0,
    ) -> TranslationDraft:
        if self.config.mock:
            payload = translation_payload(self.config, self.resources, source_text, retrievals)
            prompt = self._build_prompt(
                source_text=source_text,
                rag_context="",
                translation_profile=translation_profile,
                source_analysis=source_analysis,
                strict_locale_retry=strict_locale_retry,
            )
            prompt_debug = self._build_prompt_debug(
                prompt=prompt,
                route_source="retry" if strict_locale_retry else "override" if self.config.model_override_used else "profile",
                strict_locale_retry=strict_locale_retry,
                retry_attempt=retry_attempt,
            )
            return TranslationDraft(
                translation=payload["translation"],
                overview=payload["overview"],
                raw_response=payload["raw_response"],
                prompt_debug=prompt_debug,
            )

        client = get_openai_client()
        context = IdiomRetriever.build_context(retrievals) if include_rag_context else ""
        if memory_context.strip():
            if context.strip():
                context = "\n\n[작품 메모리 / 온톨로지 참고]\n" + memory_context.strip() + "\n\n[RAG 참고]\n" + context
            else:
                context = memory_context.strip()
        schema_name = f"{self.resources.locale}_translation".replace("-", "_")
        prompt = self._build_prompt(
            source_text=source_text,
            rag_context=context,
            translation_profile=translation_profile,
            source_analysis=source_analysis,
            strict_locale_retry=strict_locale_retry,
        )

        response = client.responses.create(
            model=self.config.translation_model,
            input=[
                {"role": "system", "content": self.resources.translator_system_prompt},
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": TRANSLATOR_JSON_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        payload["overview"] = koreanize_text(payload["overview"], model=self.config.review_model)
        prompt_debug = self._build_prompt_debug(
            prompt=prompt,
            route_source="retry" if strict_locale_retry else "override" if self.config.model_override_used else "profile",
            strict_locale_retry=strict_locale_retry,
            retry_attempt=retry_attempt,
        )
        return TranslationDraft(
            translation=payload["translation"],
            overview=payload["overview"],
            raw_response=payload,
            prompt_debug=prompt_debug,
        )

    def _build_prompt(
        self,
        *,
        source_text: str,
        rag_context: str,
        translation_profile: dict[str, Any] | None = None,
        source_analysis: dict[str, Any] | None = None,
        strict_locale_retry: bool = False,
    ) -> str:
        retry_block = ""
        if strict_locale_retry:
            retry_block = "\n\n[STRICT LOCALE RETRY]\n- Translate only into the target language.\n- Do not copy Korean source sentences.\n- Do not leave Korean sentence-level text in the output.\n- Keep proper nouns localized or transliterated when possible.\n- If approved hard glossary entries are provided, fix only the mismatched glossary surface forms and use the approved target exactly.\n- Fix only output integrity problems such as leftover Korean text or misplaced bracketed system/contact labels.\n- Restore bracketed blocks to the source scene order and role.\n- Do not unnecessarily change idiom handling, prose style, or character voice while fixing glossary or integrity problems.\n- Output translation only.\n- Do not add explanations, notes, or commentary."
        return self.prompt_template.format(
            common_korean_rule=self.common_korean_rule,
            source_language=self.resources.source_language,
            target_language=self.resources.target_language,
            source_text=source_text,
            rag_context=rag_context,
            retry_block=retry_block,
            translation_profile_context=_format_profile_context(translation_profile) or "- none",
            source_analysis_context=_format_source_analysis_context(source_analysis) or "- none",
        )

    def _build_prompt_debug(
        self,
        *,
        prompt: str,
        route_source: str,
        strict_locale_retry: bool = False,
        retry_attempt: int = 0,
    ) -> dict[str, Any]:
        system_message = self.resources.translator_system_prompt
        return {
            "prompt_template_id": "TRANSLATOR_PROMPT.md",
            "prompt_version": "runtime",
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "system_message_hash": hashlib.sha256(system_message.encode("utf-8")).hexdigest(),
            "user_message_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "target_locale": self.resources.locale,
            "target_language_name": self.resources.target_language,
            "translation_model": self.config.translation_model,
            "route_source": route_source,
            "strict_locale_retry": strict_locale_retry,
            "retry_attempt": retry_attempt,
            "retry_prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if strict_locale_retry else None,
        }
