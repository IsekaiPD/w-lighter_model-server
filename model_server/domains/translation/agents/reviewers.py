"""번역 리뷰어 3종 (문체 / 자연스러움 / 문화안전).

세 리뷰어는 입출력 구조가 100% 동일하다(완전 통일, 결정 A):
- 입력: source_text, translation, rationale, translation_profile, source_analysis
- 출력: {summary, issues[]} — issue = {severity, source_span, target_span, problem, suggestion}

각 리뷰어는 관점(프롬프트)만 다르다. 공통 LLM 호출/파싱/mock 폴백은 BaseReviewer가 담당한다.
editor는 세 리뷰어의 issues[]를 동일하게 취합한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import PipelineConfig
from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_locale_constraints, load_register_guide
from ..text_processing.korean_output import koreanize_texts


# 공통 출력 스키마 (세 리뷰어 동일)
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "description": "이 관점 검수 결과의 한국어 요약."},
        "issues": {
            "type": "array",
            "description": "이 관점에서 발견한 문제 + 수정 제안. 문제 없으면 빈 배열.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "severity": {"type": "string", "description": "LOW | MEDIUM | HIGH | CRITICAL"},
                    "source_span": {"type": "string", "description": "근거가 되는 한국어 원문 구간(그대로 인용)."},
                    "target_span": {"type": "string", "description": "문제가 되는 번역문 구간(그대로 인용)."},
                    "problem": {"type": "string", "description": "무엇이 왜 문제인지 한국어로. (필요시 문제 종류도 여기 기술)"},
                    "suggestion": {"type": "string", "description": "대상 언어 수정 제안. 책임지기 어려우면 빈 문자열."},
                },
                "required": ["severity", "source_span", "target_span", "problem", "suggestion"],
            },
        },
    },
    "required": ["summary", "issues"],
}


@dataclass(slots=True)
class ReviewIssue:
    severity: str
    source_span: str
    target_span: str
    problem: str
    suggestion: str


@dataclass(slots=True)
class ReviewResult:
    perspective: str  # "voice" | "naturalness" | "cultural_safety"
    summary: str
    issues: list[ReviewIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def max_severity(self) -> str:
        order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        if not self.issues:
            return "NONE"
        return max(self.issues, key=lambda i: order.get((i.severity or "").upper(), 0)).severity.upper()


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
    # 하위 클래스가 채운다: {lang} 등을 format할 수 있는 관점별 지시문.
    PERSPECTIVE_PROMPT: str = ""

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
    ) -> ReviewResult:
        if self.config.mock:
            # mock: 문제 없음(빈 issues)으로 결정적 반환.
            return ReviewResult(perspective=self.perspective, summary=f"[MOCK {self.perspective}] 특이사항 없음.", issues=[])

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
                text={"format": {"type": "json_schema", "name": schema_name, "schema": REVIEW_SCHEMA, "strict": True}},
            )
            payload = json.loads(response.output_text)
            self._koreanize(payload)
            return self._from_payload(payload)
        except Exception:
            # 리뷰 실패가 파이프라인을 막지 않도록 빈 결과 반환.
            return ReviewResult(perspective=self.perspective, summary="", issues=[])

    def _build_perspective_prompt(self) -> str:
        """관점별 지시문을 만든다. 하위 클래스가 추가 컨텍스트(예: locale 제약)를 덧붙일 수 있다."""
        return self.PERSPECTIVE_PROMPT.format(lang=self.resources.target_language)

    def _koreanize(self, payload: dict[str, Any]) -> None:
        issues = payload.get("issues", []) or []
        texts = [payload.get("summary", "")] + [i.get("problem", "") for i in issues]
        translated = koreanize_texts(texts, model=self.config.review_model)
        payload["summary"] = translated[0]
        for i, t in zip(issues, translated[1:]):
            i["problem"] = t

    def _from_payload(self, payload: dict[str, Any]) -> ReviewResult:
        return ReviewResult(
            perspective=self.perspective,
            summary=payload.get("summary", ""),
            issues=[
                ReviewIssue(
                    severity=row.get("severity", ""),
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
- `summary` and `issues[].problem` MUST be written in Korean. Only `issues[].suggestion` may be in {target_language}.
- If there is no problem, return an empty `issues` array and set `summary` to the Korean text "특이사항 없음".
- At most 5 issues, each concise.
"""


class VoiceReviewer(BaseReviewer):
    perspective = "voice"
    PERSPECTIVE_PROMPT = (
        "You are a web-novel editor specializing in character-voice (speech style / personality) consistency. "
        "Check the following:\n"
        "- Whether each character's distinctive speech style/personality survives in the {lang} dialogue\n"
        "- Whether the emotional line and mood come through in {lang}\n"
        "- Consistency of each character's register (formal/informal, honorifics)\n"
        "- Lines where a character sounds out-of-character (OOC) in {lang}"
    )

    def _build_perspective_prompt(self) -> str:
        base = self.PERSPECTIVE_PROMPT.format(lang=self.resources.target_language)
        # 대상 언어가 register(존대/공손도)를 표현하는 방식을 알려준다. 현재 locale 것만 끼운다.
        guide = load_register_guide(self.resources.locale)
        if guide:
            base += "\n\nTarget-language register guidance:\n- " + guide
        return base


class NaturalnessReviewer(BaseReviewer):
    perspective = "naturalness"
    PERSPECTIVE_PROMPT = (
        "You are a translation editor who catches unnatural, literal translation. Check the following:\n"
        "- Whether idioms/metaphors are translated too literally into {lang}\n"
        "- Whether Korean sentence structure remains in {lang} and reads awkwardly\n"
        "- Whether culture-specific expressions are appropriately localized\n"
        "- Clear defects such as omissions, leftover Korean characters, or broken sentence boundaries\n"
        "Do not force a specific word choice; only raise an issue when the problem is concrete."
    )



class CulturalSafetyReviewer(BaseReviewer):
    perspective = "cultural_safety"
    PERSPECTIVE_PROMPT = (
        "You are a dedicated 'cultural safety' reviewer. Your ONLY job is to catch genuine cultural risks\n"
        "(taboos, discrimination, hate, political/religious/historical sensitivity, serious etiquette violations, etc.)\n"
        "that match the constraint table below.\n"
        "\n"
        "Must do:\n"
        "- Raise an issue only for expressions that concretely match a category in the 'locale constraints' below.\n"
        "- Do not over-soften intentionally rough or villainous dialogue. Flag only when there is a concrete risk.\n"
        "- In `problem`, state which constraint (category/ID) is triggered and why.\n"
        "\n"
        "Never flag (these are NOT your job):\n"
        "- Mere awkwardness, literal-translation feel, meme-like reading, or long/clunky phrasing — i.e. 'naturalness' issues\n"
        "- That a Korean cultural element is unfamiliar to {lang} readers or under-explained\n"
        "  (unfamiliar cultural elements are not explained in the body but handled by separate endnotes, so they are not a risk)\n"
        "Those belong to the naturalness reviewer; do not duplicate them here. If there is no risk, return an empty `issues` array."
    )

    def _build_perspective_prompt(self) -> str:
        base = self.PERSPECTIVE_PROMPT.format(lang=self.resources.target_language)
        # locale별 위험 카테고리 테이블(US01~US13 등)을 그대로 실어 판단 기준을 고정한다.
        try:
            constraints = load_locale_constraints(self.resources.locale)
        except Exception:
            constraints = ""
        if constraints:
            base += "\n\n[Locale constraints — flag only what matches a category in this table]\n" + constraints
        return base
