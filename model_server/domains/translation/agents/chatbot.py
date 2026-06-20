from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from ..config import PipelineConfig
from ..infra.mock_adapters import chatbot_payload
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_runtime_prompt


CHATBOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "proposed_translation": {"type": "string"},
        "change_summary": {"type": "string"},
        "needs_user_confirmation": {"type": "boolean"},
    },
    "required": [
        "answer",
        "proposed_translation",
        "change_summary",
        "needs_user_confirmation",
    ],
}


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class ChatbotReply:
    answer: str
    proposed_translation: str
    change_summary: str
    needs_user_confirmation: bool
    raw_response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChatbotAgent:
    """Context-aware assistant for explaining and revising translation results."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()
        self.prompt_template = load_runtime_prompt("CHATBOT_PROMPT.md")

    def reply(
        self,
        *,
        user_message: str,
        source_text: str,
        draft_translation: str,
        reviewed_translation: str,
        translation_rationale: str = "",
        used_references: list[dict[str, Any]] | None = None,
        inspection_report: dict[str, Any] | None = None,
        reader_endnotes: list[dict[str, Any]] | None = None,
        work_title: str = "",
        episode_id: str = "",
        translation_memory: list[dict[str, Any]] | None = None,
        chat_history: list[ChatMessage | dict[str, str]] | None = None,
    ) -> ChatbotReply:
        if self.config.mock:
            payload = chatbot_payload(user_message, source_text, reviewed_translation)
            return ChatbotReply(
                answer=payload["answer"],
                proposed_translation=payload["proposed_translation"],
                change_summary=payload["change_summary"],
                needs_user_confirmation=payload["needs_user_confirmation"],
                raw_response=payload["raw_response"],
            )

        client = get_openai_client()
        schema_name = f"{self.resources.locale}_chatbot_reply".replace("-", "_")
        prompt = self._build_prompt(
            user_message=user_message,
            source_text=source_text,
            draft_translation=draft_translation,
            reviewed_translation=reviewed_translation,
            translation_rationale=translation_rationale,
            used_references=used_references or [],
            inspection_report=inspection_report or {},
            reader_endnotes=reader_endnotes or [],
            work_title=work_title,
            episode_id=episode_id,
            translation_memory=translation_memory or [],
            chat_history=chat_history or [],
        )
        response = client.responses.create(
            model=self.config.review_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a translation editing chatbot. Explain decisions, "
                        "propose revisions, and never claim changes are saved unless "
                        "the application confirms them. Return JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": CHATBOT_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        return ChatbotReply(
            answer=payload["answer"],
            proposed_translation=payload["proposed_translation"],
            change_summary=payload["change_summary"],
            needs_user_confirmation=payload["needs_user_confirmation"],
            raw_response=payload,
        )

    def _build_prompt(
        self,
        *,
        user_message: str,
        source_text: str,
        draft_translation: str,
        reviewed_translation: str,
        translation_rationale: str,
        used_references: list[dict[str, Any]],
        inspection_report: dict[str, Any],
        reader_endnotes: list[dict[str, Any]],
        work_title: str,
        episode_id: str,
        translation_memory: list[dict[str, Any]],
        chat_history: list[ChatMessage | dict[str, str]],
    ) -> str:
        normalized_history = [
            asdict(row) if isinstance(row, ChatMessage) else row for row in chat_history
        ]
        return self.prompt_template.format(
            locale=self.resources.locale,
            target_language=self.resources.target_language,
            source_language=self.resources.source_language,
            work_title=work_title or "- none",
            episode_id=episode_id or "- none",
            source_text=source_text,
            draft_translation=draft_translation,
            reviewed_translation=reviewed_translation,
            translation_rationale=translation_rationale or "- none",
            used_references_json=json.dumps(used_references, ensure_ascii=False, indent=2),
            inspection_report_json=json.dumps(inspection_report, ensure_ascii=False, indent=2),
            reader_endnotes_json=json.dumps(reader_endnotes, ensure_ascii=False, indent=2),
            translation_memory_json=json.dumps(translation_memory, ensure_ascii=False, indent=2),
            chat_history_json=json.dumps(normalized_history, ensure_ascii=False, indent=2),
            user_message=user_message,
        )
