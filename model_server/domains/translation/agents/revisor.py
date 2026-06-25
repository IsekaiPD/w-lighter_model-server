"""리바이저(Revisor) 에이전트.

draft 번역 + 리뷰어 findings(voice·naturalness·cultural·glossary)를 받아,
취사선택해 최종 번역문을 만들고 각 finding의 적용/보류 결정을 함께 돌려준다.
- voice·naturalness·cultural : 취사선택(보류 가능, 사유 기록)
- glossary                    : 항상 applied(거부 불가 — 승인 용어집 일관성 강제)

반환 decisions[]는 inspectionReport(전체)·챗봇 핸드오프의 공통 원천. 웹은 cultural만 필터해 문화리스크로 표시.
그래프 배선은 별도(이 파일은 독립 부품).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..config import PipelineConfig
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_runtime_prompt


REVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "finalTranslation": {"type": "string", "description": "리뷰 결정을 반영한 최종 번역문 전체."},
        "summary": {"type": "string", "description": "이번 수정의 방향성에 대한 2~3문장 짧은 평(한국어). 어떤 기조로 고쳤는지."},
        "decisions": {
            "type": "array",
            "description": "각 finding에 대한 적용/보류 결정. finding 1건당 1개.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "reviewerType": {"type": "string", "description": "voice | naturalness | cultural | glossary"},
                    "sourceSpan": {"type": "string", "description": "원래 finding의 한국어 원문 구간."},
                    "targetSpan": {"type": "string", "description": "원래 finding의 번역문 구간."},
                    "problem": {"type": "string", "description": "원래 지적 내용(한국어)."},
                    "action": {"type": "string", "description": "applied | deferred (glossary는 항상 applied)."},
                    "reason": {"type": "string", "description": "적용/보류 사유(한국어)."},
                    "revisedSpan": {"type": "string", "description": "적용 시 바뀐 번역 구간, 보류면 빈 문자열."},
                },
                "required": ["reviewerType", "sourceSpan", "targetSpan", "problem", "action", "reason", "revisedSpan"],
            },
        },
    },
    "required": ["finalTranslation", "summary", "decisions"],
}


@dataclass(slots=True)
class RevisionResult:
    finalTranslation: str
    summary: str = ""  # 수정 방향성 짧은 평(revisor_summary)
    decisions: list[dict[str, Any]] = field(default_factory=list)


def _compact_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """reviewFindings(issue dict) → 리바이저 프롬프트용 간결 뷰."""
    compact: list[dict[str, Any]] = []
    for finding in findings:
        compact.append(
            {
                "reviewerType": str(finding.get("reviewerType") or ""),
                "sourceSpan": str(finding.get("sourceSpan") or ""),
                "targetSpan": str(finding.get("targetSpan") or ""),
                "problem": str(finding.get("message") or finding.get("problem") or ""),
                "suggestion": str(finding.get("suggestion") or ""),
            }
        )
    return compact


class RevisorAgent:
    """리뷰 findings를 취사선택해 최종 번역문 + decisions를 생성하는 에이전트."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()

    def revise(
        self,
        *,
        source_text: str,
        draft_translation: str,
        findings: list[dict[str, Any]] | None = None,
    ) -> RevisionResult:
        findings = [f for f in (findings or []) if isinstance(f, dict)]
        # mock 또는 빈 draft: 변경 없이 draft 그대로(결정적).
        if self.config.mock or not (draft_translation or "").strip():
            return RevisionResult(finalTranslation=draft_translation, decisions=[])
        try:
            client = get_openai_client()
            user = load_runtime_prompt("REVISOR_PROMPT.md").format(
                target_language=self.resources.target_language,
                source_text=source_text,
                draft_translation=draft_translation,
                findings_json=json.dumps(_compact_findings(findings), ensure_ascii=False, indent=2),
            )
            response = client.responses.create(
                model=self.config.translation_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            f"You are the final reviser for a {self.resources.target_language} "
                            "web-novel translation. Return JSON only. All reasons must be Korean."
                        ),
                    },
                    {"role": "user", "content": user},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "translation_revision",
                        "schema": REVISOR_SCHEMA,
                        "strict": True,
                    }
                },
            )
            payload = json.loads(response.output_text)
            return self._from_payload(payload, fallback=draft_translation)
        except Exception:
            # 수정 실패가 파이프라인을 막지 않도록 draft를 최종본으로 사용.
            return RevisionResult(finalTranslation=draft_translation, decisions=[])

    def _from_payload(self, payload: dict[str, Any], *, fallback: str) -> RevisionResult:
        final = str(payload.get("finalTranslation") or "").strip() or fallback
        decisions: list[dict[str, Any]] = []
        for row in payload.get("decisions", []) or []:
            if not isinstance(row, dict):
                continue
            decisions.append(
                {
                    "reviewerType": str(row.get("reviewerType") or ""),
                    "sourceSpan": str(row.get("sourceSpan") or ""),
                    "targetSpan": str(row.get("targetSpan") or ""),
                    "problem": str(row.get("problem") or ""),
                    "action": str(row.get("action") or ""),
                    "reason": str(row.get("reason") or ""),
                    "revisedSpan": str(row.get("revisedSpan") or ""),
                }
            )
        return RevisionResult(finalTranslation=final, summary=str(payload.get("summary") or ""), decisions=decisions)
