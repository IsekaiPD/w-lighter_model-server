from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import PipelineConfig
from ..text_processing.korean_output import koreanize_texts
from ..infra.mock_adapters import inspection_payload
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_inspector_prompt, load_locale_constraints, load_runtime_prompt


# Inspector는 전체 번역문을 다시 만들지 않는다. 검사 대상 번역에서 문제가 되는
# 구간만 span 단위로 보고한다. 출력은 {summary, issues[]} 구조 하나로 통일한다.
INSPECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "전체 검수 결과 한국어 요약. 어떤 유형의 문제가 있었는지/없었는지 간단히 정리한다.",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "severity": {
                        "type": "string",
                        "description": "LOW | MEDIUM | HIGH | CRITICAL 중 하나.",
                    },
                    "review_label": {
                        "type": "string",
                        "description": "Optional editorial label such as REVIEW, CRITICAL_REVIEW, or ADAPT_WITH_INTENT.",
                    },
                    "keep_intent": {
                        "type": "string",
                        "description": "Korean note describing what must be preserved if the line is revised.",
                    },
                    "context": {
                        "type": "string",
                        "description": "이 issue를 이해하는 데 필요한 최소 장면 정보(화자/청자/관계/분위기/말투). 한국어로 작성한다.",
                    },
                    "source_span": {
                        "type": "string",
                        "description": "문제 판단 근거가 되는 한국어 원문 구간을 그대로 가져온다.",
                    },
                    "translated_span": {
                        "type": "string",
                        "description": "검사 대상 번역문에서 문제가 되는 번역 구간을 그대로 가져온다.",
                    },
                    "problem": {
                        "type": "string",
                        "description": "해당 번역 span이 왜 문제인지 한국어로 설명한다.",
                    },
                    "suggested": {
                        "type": "string",
                        "description": "해당 span에 대한 대상 언어 대체 표현. 책임 있게 제안하기 어려우면 빈 문자열로 둔다.",
                    },
                },
                "required": [
                    "severity",
                    "review_label",
                    "keep_intent",
                    "context",
                    "source_span",
                    "translated_span",
                    "problem",
                    "suggested",
                ],
            },
        },
    },
    "required": ["summary", "issues"],
}


@dataclass(slots=True)
class InspectionIssue:
    severity: str
    context: str
    source_span: str
    translated_span: str
    problem: str
    suggested: str
    review_label: str = ""
    keep_intent: str = ""


@dataclass(slots=True)
class InspectionResult:
    summary: str
    issues: list[InspectionIssue]
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


class InspectionAgent:
    """Independent cultural/localization inspection agent for translated output."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()
        self.locale_constraints = load_locale_constraints(self.resources.locale)
        # 통합 프롬프트(검수 원칙 + 실행 틀)를 cultural_review/INSPECTOR_PROMPT.md 한 곳에서 로드.
        self.prompt_template = load_inspector_prompt(config)
        self.common_korean_rule = load_runtime_prompt("COMMON_KOREAN_OUTPUT_RULE.md")

    def inspect(
        self,
        *,
        source_text: str,
        draft_translation: str,
        translation_rationale: str = "",
        translation_memory: list[dict[str, Any]] | None = None,
        translation_profile: dict[str, Any] | None = None,
        source_analysis: dict[str, Any] | None = None,
    ) -> InspectionResult:
        if self.config.mock:
            payload = inspection_payload(self.resources, source_text, draft_translation)
            return self._result_from_payload(payload)

        client = get_openai_client()
        schema_name = f"{self.resources.locale}_inspection".replace("-", "_")
        prompt = self._build_prompt(
            source_text=source_text,
            draft_translation=draft_translation,
            translation_rationale=translation_rationale,
            translation_memory=translation_memory or [],
            translation_profile=translation_profile,
            source_analysis=source_analysis,
        )
        response = client.responses.create(
            model=self.config.review_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        f"You are an independent {self.resources.target_language} "
                        "localization inspection agent. Return JSON only. "
                        "All explanatory fields must be written in Korean. "
                        f"Only suggested target text may be in {self.resources.target_language}."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": INSPECTION_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        self._koreanize_payload(payload)
        return self._result_from_payload(payload)

    def _build_prompt(
        self,
        *,
        source_text: str,
        draft_translation: str,
        translation_rationale: str,
        translation_memory: list[dict[str, Any]],
        translation_profile: dict[str, Any] | None = None,
        source_analysis: dict[str, Any] | None = None,
    ) -> str:
        memory_json = json.dumps(translation_memory, ensure_ascii=False, indent=2)
        return self.prompt_template.format(
            common_korean_rule=self.common_korean_rule,
            locale_constraints=self.locale_constraints,
            source_language=self.resources.source_language,
            target_language=self.resources.target_language,
            source_text=source_text,
            draft_translation=draft_translation,
            translation_rationale=translation_rationale or "- none",
            memory_json=memory_json,
            translation_profile_context=_format_profile_context(translation_profile) or "- none",
            source_analysis_context=_format_source_analysis_context(source_analysis) or "- none",
        )

    def _koreanize_payload(self, payload: dict[str, Any]) -> None:
        # 한국어로 강제할 설명 필드: summary + 각 issue의 context/problem.
        # source_span(원문)·translated_span/suggested(대상 언어)는 번역하지 않는다.
        issues = payload.get("issues", []) or []
        texts: list[str] = [payload.get("summary", "")]
        for row in issues:
            texts.append(row.get("context", ""))
            texts.append(row.get("problem", ""))
            texts.append(row.get("keep_intent", ""))

        translated = koreanize_texts(texts, model=self.config.review_model)
        cursor = 0
        payload["summary"] = translated[cursor]
        cursor += 1
        for row in issues:
            row["context"] = translated[cursor]
            cursor += 1
            row["problem"] = translated[cursor]
            cursor += 1
            row["keep_intent"] = translated[cursor]
            cursor += 1

    @staticmethod
    def _result_from_payload(payload: dict[str, Any]) -> InspectionResult:
        return InspectionResult(
            summary=payload["summary"],
            issues=[
                InspectionIssue(
                    severity=row["severity"],
                    context=row["context"],
                    source_span=row["source_span"],
                    translated_span=row["translated_span"],
                    problem=row["problem"],
                    suggested=row["suggested"],
                    review_label=row.get("review_label", ""),
                    keep_intent=row.get("keep_intent", ""),
                )
                for row in payload.get("issues", [])
            ],
            raw_response=payload,
        )
