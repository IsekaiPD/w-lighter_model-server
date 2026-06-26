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
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "original": {"type": "string"},
                    "replacement": {"type": "string"},
                },
                "required": ["original", "replacement"],
            },
        },
        "change_summary": {"type": "string"},
        "needs_user_confirmation": {"type": "boolean"},
        "pending_action": {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["update_glossary", "add_glossary", "delete_glossary"],
                        },
                        "description": {"type": "string"},
                        "original_word": {"type": "string"},
                        "new_value": {"type": "string"},
                        "category": {"type": "string"},
                    },
                    "required": ["type", "description", "original_word", "new_value", "category"],
                },
                {"type": "null"},
            ]
        },
    },
    "required": [
        "answer",
        "edits",
        "change_summary",
        "needs_user_confirmation",
        "pending_action",
    ],
}

CHAT_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "explain",
                "evaluate",
                "review_help",
                "propose_edit",
                "confirm",
                "cancel",
                "glossary",
                "unrelated",
                "ambiguous",
            ],
        },
        "edit_scope": {
            "type": "string",
            "enum": ["current_translation", "glossary", "external_content", "unknown"],
        },
        "source_grounding": {
            "type": "string",
            "enum": ["grounded", "ungrounded", "unclear"],
        },
        "allow_pending_action": {"type": "boolean"},
        "allow_proposed_translation": {"type": "boolean"},
        "answer_strategy": {
            "type": "string",
            "enum": [
                "explain",
                "evaluate",
                "review_help",
                "propose_revision",
                "ask_clarification",
                "refuse_unrelated",
            ],
        },
        "reason": {"type": "string"},
    },
    "required": [
        "intent",
        "edit_scope",
        "source_grounding",
        "allow_pending_action",
        "allow_proposed_translation",
        "answer_strategy",
        "reason",
    ],
}


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class ChatbotReply:
    answer: str
    change_summary: str
    needs_user_confirmation: bool
    pending_action: dict[str, Any] | None
    edits: list[dict[str, Any]]
    raw_response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatIntentClassification:
    intent: str
    edit_scope: str
    source_grounding: str
    allow_pending_action: bool
    allow_proposed_translation: bool
    answer_strategy: str
    reason: str
    raw_response: dict[str, Any]

    def to_context(self) -> str:
        payload = {
            "intent": self.intent,
            "edit_scope": self.edit_scope,
            "source_grounding": self.source_grounding,
            "allow_pending_action": self.allow_pending_action,
            "allow_proposed_translation": self.allow_proposed_translation,
            "answer_strategy": self.answer_strategy,
            "reason": self.reason,
        }
        return json.dumps(payload, ensure_ascii=False)


def _clip_text(value: str, limit: int = 1600) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated]..."


class ChatIntentClassifier:
    """Small-model intent guard for translation chat actions."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()
        self.prompt_template = load_runtime_prompt("CHATBOT_INTENT_PROMPT.md")

    def classify(
        self,
        *,
        user_message: str,
        source_text: str,
        draft_translation: str,
        reviewed_translation: str,
        chat_history: list[ChatMessage | dict[str, str]] | None = None,
        pending_action: dict[str, Any] | None = None,
        action_context: str = "",
    ) -> ChatIntentClassification:
        if self.config.mock:
            return self._mock_classification(user_message)

        client = get_openai_client()
        schema_name = f"{self.resources.locale}_chat_intent".replace("-", "_")
        prompt = self._build_prompt(
            user_message=user_message,
            source_text=source_text,
            draft_translation=draft_translation,
            reviewed_translation=reviewed_translation,
            chat_history=chat_history or [],
            pending_action=pending_action,
            action_context=action_context,
        )
        response = client.responses.create(
            model=self.config.chat_intent_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You classify translation-review chat intent. "
                        "Return compact JSON only and never draft translations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": CHAT_INTENT_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        return ChatIntentClassification(
            intent=payload["intent"],
            edit_scope=payload["edit_scope"],
            source_grounding=payload["source_grounding"],
            allow_pending_action=bool(payload["allow_pending_action"]),
            allow_proposed_translation=bool(payload["allow_proposed_translation"]),
            answer_strategy=payload["answer_strategy"],
            reason=payload.get("reason", ""),
            raw_response=payload,
        )

    def _mock_classification(self, user_message: str) -> ChatIntentClassification:
        text = str(user_message or "")
        if any(cue in text for cue in ("왜", "어떻게", "어때", "무슨")):
            payload = {
                "intent": "explain",
                "edit_scope": "unknown",
                "source_grounding": "unclear",
                "allow_pending_action": False,
                "allow_proposed_translation": False,
                "answer_strategy": "explain",
                "reason": "mock explanation intent",
            }
        elif any(cue in text for cue in ("수정", "바꿔", "다듬", "추가", "넣어")):
            payload = {
                "intent": "propose_edit",
                "edit_scope": "current_translation",
                "source_grounding": "unclear",
                "allow_pending_action": True,
                "allow_proposed_translation": True,
                "answer_strategy": "propose_revision",
                "reason": "mock edit intent",
            }
        else:
            payload = {
                "intent": "ambiguous",
                "edit_scope": "unknown",
                "source_grounding": "unclear",
                "allow_pending_action": False,
                "allow_proposed_translation": False,
                "answer_strategy": "ask_clarification",
                "reason": "mock ambiguous intent",
            }
        return ChatIntentClassification(raw_response=payload, **payload)

    def _build_prompt(
        self,
        *,
        user_message: str,
        source_text: str,
        draft_translation: str,
        reviewed_translation: str,
        chat_history: list[ChatMessage | dict[str, str]],
        pending_action: dict[str, Any] | None,
        action_context: str,
    ) -> str:
        normalized_history = [
            asdict(row) if isinstance(row, ChatMessage) else row for row in chat_history
        ]
        return self.prompt_template.format(
            locale=self.resources.locale,
            target_language=self.resources.target_language,
            source_language=self.resources.source_language,
            source_text=_clip_text(source_text),
            draft_translation=_clip_text(draft_translation),
            reviewed_translation=_clip_text(reviewed_translation),
            chat_history_json=json.dumps(normalized_history[-4:], ensure_ascii=False, indent=2),
            pending_action_json=json.dumps(pending_action, ensure_ascii=False, indent=2),
            action_context=action_context or "- none",
            user_message=user_message,
        )


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
        inspection_report: list[dict[str, Any]] | None = None,
        reader_endnotes: list[dict[str, Any]] | None = None,
        work_title: str = "",
        episode_id: str = "",
        translation_memory: list[dict[str, Any]] | None = None,
        chat_history: list[ChatMessage | dict[str, str]] | None = None,
        action_context: str = "",
    ) -> ChatbotReply:
        if self.config.mock:
            payload = chatbot_payload(user_message, source_text, reviewed_translation)
            return ChatbotReply(
                answer=payload["answer"],
                change_summary=payload["change_summary"],
                needs_user_confirmation=payload["needs_user_confirmation"],
                pending_action=None,
                edits=payload.get("edits") or [],
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
            inspection_report=inspection_report or [],
            reader_endnotes=reader_endnotes or [],
            work_title=work_title,
            episode_id=episode_id,
            translation_memory=translation_memory or [],
            chat_history=chat_history or [],
            action_context=action_context,
        )
        response = client.responses.create(
            model=self.config.review_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a translation editing chatbot. Explain decisions, "
                        "propose revisions, and never claim changes are saved unless "
                        "the application confirms them. "
                        "Always reply in polite Korean 존댓말 (해요체/합니다체); never use 반말, "
                        "even if the user does, and keep the register consistent across turns. "
                        "Return JSON only."
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
            change_summary=payload["change_summary"],
            needs_user_confirmation=payload["needs_user_confirmation"],
            pending_action=payload.get("pending_action"),
            edits=payload.get("edits") or [],
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
        inspection_report: list[dict[str, Any]],
        reader_endnotes: list[dict[str, Any]],
        work_title: str,
        episode_id: str,
        translation_memory: list[dict[str, Any]],
        chat_history: list[ChatMessage | dict[str, str]],
        action_context: str = "",
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
            action_context=action_context or "- none",
            user_message=user_message,
        )
