"""번역 리뷰어 4종 (문체 / 자연스러움 / 문화안전 / 용어집).

voice·naturalness·cultural 세 리뷰어는 출력이 {issues[]} 로 동일하다.
glossary 리뷰어는 일관성 검수(issues[])에 더해 **신규 용어 후보(candidates[])** 도 함께 반환한다.
- issue     = {source_span, target_span, problem, suggestion}
- candidate = {source, suggested_target, category, reason}

각 리뷰어는 관점(프롬프트)만 다르다. 관점 프롬프트는 prompts/review/*.md 로 외부화하고
load_review_prompt(perspective)로 로드한다. 공통 LLM 호출/파싱/mock 폴백은 BaseReviewer가 담당한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import PipelineConfig
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_locale_constraints, load_register_guide, load_review_prompt
from ..text_processing.korean_output import koreanize_texts


# 공통 출력 스키마 (세 리뷰어 동일)
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "description": "이 관점에서 번역 전체에 대한 2~3문장 총평(한국어). 문제 유무와 전반적 인상을 요약."},
        "issues": {
            "type": "array",
            "description": "이 관점에서 발견한 문제 + 수정 제안. 문제 없으면 빈 배열.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_span": {"type": "string", "description": "근거가 되는 한국어 원문 구간(그대로 인용)."},
                    "target_span": {"type": "string", "description": "문제가 되는 번역문 구간(그대로 인용)."},
                    "problem": {"type": "string", "description": "무엇이 왜 문제인지 한국어로. (필요시 문제 종류도 여기 기술)"},
                    "suggestion": {"type": "string", "description": "대상 언어 수정 제안. 책임지기 어려우면 빈 문자열."},
                },
                "required": ["source_span", "target_span", "problem", "suggestion"],
            },
        },
    },
    "required": ["summary", "issues"],
}


# glossary 리뷰어 전용 스키마: 공통(summary/issues)에 신규 용어 후보(candidates)를 추가.
GLOSSARY_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issues": REVIEW_SCHEMA["properties"]["issues"],
        "candidates": {
            "type": "array",
            "description": "원문에 등장하지만 승인 용어집에 없는, 회차 간 일관 표기가 필요한 신규 용어 후보. 없으면 빈 배열.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source": {"type": "string", "description": "한국어 원문 표기(그대로 인용)."},
                    "suggested_target": {"type": "string", "description": "제안하는 대상 언어 표기."},
                    "category": {"type": "string", "description": "person | place | organization 중 하나."},
                    "reason": {"type": "string", "description": "왜 용어집 후보인지 한국어로."},
                },
                "required": ["source", "suggested_target", "category", "reason"],
            },
        },
    },
    "required": ["issues", "candidates"],
}


@dataclass(slots=True)
class ReviewIssue:
    source_span: str
    target_span: str
    problem: str
    suggestion: str


@dataclass(slots=True)
class ReviewResult:
    perspective: str  # "voice" | "naturalness" | "cultural_safety" | "glossary"
    summary: str = ""  # 이 관점의 전체 평가 총평(한국어). glossary는 미사용("").
    issues: list[ReviewIssue] = field(default_factory=list)
    # glossary 리뷰어만 채운다(원문 등장·승인 용어집에 없는 신규 용어 후보). 나머지는 항상 빈 리스트.
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fmt_profile(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    if not profile:
        return "- none"
    keys = ["tone", "dialogue_style", "narration_style", "culture_policy"]
    return "\n".join(f"- {k}: {profile.get(k, '')}" for k in keys)


def _fmt_analysis(analysis: dict[str, Any] | None) -> str:
    analysis = analysis or {}
    if not analysis:
        return "- none"
    return f"- summary: {analysis.get('summary', '')}"


class BaseReviewer:
    """관점만 다른 리뷰어들의 공통 베이스. LLM 호출/파싱/mock 폴백을 담당."""

    perspective: str = "base"
    SCHEMA: dict[str, Any] = REVIEW_SCHEMA  # 하위 클래스가 다른 스키마로 교체 가능(glossary).

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resources = config.resolved_resources()

    def review(
        self,
        *,
        source_text: str,
        translation: str,
        rationale: str = "",
        translation_profile: dict[str, Any] | None = None,
        source_analysis: dict[str, Any] | None = None,
        approved_glossary: list[dict[str, Any]] | None = None,
    ) -> ReviewResult:
        if self.config.mock:
            # mock: 문제 없음(빈 issues)으로 결정적 반환.
            return ReviewResult(perspective=self.perspective, issues=[])

        try:
            client = get_openai_client()
            schema_name = f"{self.resources.locale}_{self.perspective}_review".replace("-", "_")
            user = _USER_TEMPLATE.format(
                perspective_prompt=self._build_perspective_prompt(),
                source_language=self.resources.source_language,
                target_language=self.resources.target_language,
                source_text=source_text,
                translation=translation,
                rationale=rationale or "- none",
                profile=_fmt_profile(translation_profile),
                analysis=_fmt_analysis(source_analysis),
            )
            extra = self._extra_user_context(approved_glossary=approved_glossary)
            if extra:
                user = f"{user}\n{extra}"
            response = client.responses.create(
                model=self.config.review_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            f"You are an independent {self.resources.target_language} web-novel reviewer. "
                            "Return JSON only. All explanatory fields must be Korean. "
                            f"Only `suggestion` may be in {self.resources.target_language}."
                        ),
                    },
                    {"role": "user", "content": user},
                ],
                text={"format": {"type": "json_schema", "name": schema_name, "schema": self.SCHEMA, "strict": True}},
            )
            payload = json.loads(response.output_text)
            self._koreanize(payload)
            return self._from_payload(payload)
        except Exception:
            # 리뷰 실패가 파이프라인을 막지 않도록 빈 결과 반환.
            return ReviewResult(perspective=self.perspective, issues=[])

    def _build_perspective_prompt(self) -> str:
        """관점별 지시문을 만든다. prompts/review/*.md 에서 로드하고 {lang}을 채운다.

        하위 클래스가 추가 컨텍스트(예: locale 제약)를 덧붙일 수 있다.
        """
        return load_review_prompt(self.perspective).format(lang=self.resources.target_language)

    def _extra_user_context(self, *, approved_glossary: list[dict[str, Any]] | None = None) -> str:
        """user 메시지 끝에 덧붙일 관점별 추가 데이터(기본 없음).

        GlossaryReviewer가 승인 용어집을 주입하는 데 쓴다.
        """
        return ""

    def _koreanize(self, payload: dict[str, Any]) -> None:
        issues = payload.get("issues", []) or []
        problems = [i.get("problem", "") for i in issues]
        if not problems:
            return
        translated = koreanize_texts(problems, model=self.config.review_model)
        for i, t in zip(issues, translated):
            i["problem"] = t

    def _from_payload(self, payload: dict[str, Any]) -> ReviewResult:
        return ReviewResult(
            perspective=self.perspective,
            summary=str(payload.get("summary") or ""),
            issues=[
                ReviewIssue(
                    source_span=row.get("source_span", ""),
                    target_span=row.get("target_span", ""),
                    problem=row.get("problem", ""),
                    suggestion=row.get("suggestion", ""),
                )
                for row in payload.get("issues", []) or []
            ],
        )


_USER_TEMPLATE = """{perspective_prompt}

Source ({source_language}):
{source_text}

Translation ({target_language}):
{translation}

Translator note (rationale):
{rationale}

Translation profile:
{profile}

Source analysis:
{analysis}

Output rules:
- JSON only. Do not create fields outside the schema.
- `summary` (when present in the schema — voice/naturalness/cultural): 이 관점에서 번역 전체에 대한 2~3문장 한국어 총평. 문제 유무와 전반적 인상을 요약.
- `issues[].problem` MUST be written in Korean. Only `issues[].suggestion` may be in {target_language}.
- If there is no problem, return an empty `issues` array (but still write `summary`).
- At most 5 issues, each concise.
"""


class VoiceReviewer(BaseReviewer):
    perspective = "voice"

    def _build_perspective_prompt(self) -> str:
        base = super()._build_perspective_prompt()
        # 대상 언어가 register(존대/공손도)를 표현하는 방식을 알려준다. 현재 locale 것만 끼운다.
        guide = load_register_guide(self.resources.locale)
        if guide:
            base += "\n\nTarget-language register guidance:\n- " + guide
        return base


class NaturalnessReviewer(BaseReviewer):
    perspective = "naturalness"



class CulturalSafetyReviewer(BaseReviewer):
    perspective = "cultural_safety"

    def _build_perspective_prompt(self) -> str:
        base = super()._build_perspective_prompt()
        # locale별 위험 카테고리 테이블(US01~US13 등)을 그대로 실어 판단 기준을 고정한다.
        try:
            constraints = load_locale_constraints(self.resources.locale)
        except Exception:
            constraints = ""
        if constraints:
            base += "\n\n[Locale constraints — flag only what matches a category in this table]\n" + constraints
        return base


class GlossaryReviewer(BaseReviewer):
    perspective = "glossary"
    SCHEMA = GLOSSARY_REVIEW_SCHEMA

    def _from_payload(self, payload: dict[str, Any]) -> ReviewResult:
        # 공통(summary/issues) 파싱 후 신규 용어 후보(candidates)를 추가로 채운다.
        result = super()._from_payload(payload)
        result.candidates = [
            {
                "source": str(row.get("source") or "").strip(),
                "suggested_target": str(row.get("suggested_target") or "").strip(),
                "category": str(row.get("category") or "").strip(),
                "reason": str(row.get("reason") or "").strip(),
            }
            for row in (payload.get("candidates") or [])
            if isinstance(row, dict) and str(row.get("source") or "").strip()
        ]
        return result

    def _extra_user_context(self, *, approved_glossary: list[dict[str, Any]] | None = None) -> str:
        # 승인 용어집(원문 등장으로 확정된 항목)을 user 메시지에 실어 일관성 검수 기준을 고정한다.
        rows = approved_glossary or []
        lines: list[str] = []
        for row in rows[:50]:
            source = str(row.get("source") or "").strip()
            target = str(row.get("target") or "").strip()
            if source and target:
                lines.append(f"- {source} => {target}")
        if not lines:
            return ""
        return (
            "[Approved glossary — verify the translation uses each approved target term "
            "wherever its Korean source appears]\n" + "\n".join(lines)
        )
