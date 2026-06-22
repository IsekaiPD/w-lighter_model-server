"""한글 잔류 수리 에이전트.

integrity 게이트가 finalTranslation에서 한글 포함 문장 단위({index, sentence})를 뽑아 넘기면,
이 에이전트가 원문을 근거로 그 문장들만 대상 언어로 고쳐 {index, fixed}로 돌려준다.
치환은 호출부가 `korean_output.apply_unit_repairs`(인덱스 기반)로 수행한다.
"""
from __future__ import annotations

import json
from typing import Any

from ..config import PipelineConfig
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_runtime_prompt


RESIDUE_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "repairs": {
            "type": "array",
            "description": "한글이 남아있던 문장 단위의 수정 결과. 고칠 게 없으면 빈 배열.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer", "description": "입력으로 받은 문장 단위의 index."},
                    "fixed": {"type": "string", "description": "한글을 제거하고 대상 언어로 옮긴 문장. 앞뒤 공백·구분자 보존."},
                },
                "required": ["index", "fixed"],
            },
        },
    },
    "required": ["repairs"],
}


class KoreanResidueRepairer:
    """한글 잔류 문장만 대상 언어로 고치는 에이전트. (index→fixed 매핑 반환)"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()

    def repair(self, *, source_text: str, units: list[dict[str, Any]]) -> dict[int, str]:
        """units = [{index, sentence}] → {index: fixed}. 실패/변경없음이면 빈 dict."""
        units = [u for u in (units or []) if str((u or {}).get("sentence") or "").strip()]
        if not units:
            return {}
        if self.config.mock:
            # mock: LLM 호출 없이 변경 없음(결정적).
            return {}
        try:
            client = get_openai_client()
            user = load_runtime_prompt("RESIDUE_REPAIR_PROMPT.md").format(
                target_language=self.resources.target_language,
                source_text=source_text,
                units_json=json.dumps(units, ensure_ascii=False, indent=2),
            )
            response = client.responses.create(
                model=self.config.review_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            f"You fix leftover Korean in a {self.resources.target_language} "
                            "web-novel translation. Return JSON only."
                        ),
                    },
                    {"role": "user", "content": user},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "korean_residue_repairs",
                        "schema": RESIDUE_REPAIR_SCHEMA,
                        "strict": True,
                    }
                },
            )
            payload = json.loads(response.output_text)
            result: dict[int, str] = {}
            for row in payload.get("repairs", []) or []:
                if isinstance(row, dict) and isinstance(row.get("index"), int):
                    result[int(row["index"])] = str(row.get("fixed") or "")
            return result
        except Exception:
            # 수리 실패가 파이프라인을 막지 않도록 변경 없음 반환(원문 유지).
            return {}
