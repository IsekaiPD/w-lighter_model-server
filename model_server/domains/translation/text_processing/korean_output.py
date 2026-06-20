from __future__ import annotations

import json
import re
from typing import Iterable

from ..infra.openai_client import get_openai_client
from ..infra.prompt_loader import load_runtime_prompt


KOREAN_TRANSLATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "translations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["translations"],
}


def has_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))


def looks_like_explanation(text: str) -> bool:
    return bool(re.search(r"[A-Za-zぁ-んァ-ン一-龯]", text or ""))


def needs_korean(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and not has_hangul(stripped) and looks_like_explanation(stripped)


def koreanize_texts(texts: Iterable[str], *, model: str) -> list[str]:
    originals = list(texts)
    indexes = [idx for idx, text in enumerate(originals) if needs_korean(text)]
    if not indexes:
        return originals

    targets = [originals[idx] for idx in indexes]
    client = get_openai_client()
    prompt = load_runtime_prompt("KOREAN_OUTPUT_PROMPT.md").format(
        targets_json=json.dumps(targets, ensure_ascii=False, indent=2)
    )
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You translate UI explanation text into Korean. Return JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "korean_explanation_translations",
                "schema": KOREAN_TRANSLATION_SCHEMA,
                "strict": True,
            }
        },
    )
    payload = json.loads(response.output_text)
    translations = payload.get("translations", [])
    if len(translations) != len(targets):
        return originals

    result = originals[:]
    for idx, translated in zip(indexes, translations):
        result[idx] = translated
    return result


def koreanize_text(text: str, *, model: str) -> str:
    return koreanize_texts([text], model=model)[0]


def korean_char_ratio(text: str) -> float:
    """공백을 제외한 글자 중 완성형 한글(가~힣)의 비중. 0.0~1.0."""
    han = sum(1 for ch in text if "가" <= ch <= "힣")
    total = sum(1 for ch in text if not ch.isspace())
    return han / total if total else 0.0


def is_korean_source(text: str, threshold: float = 0.5) -> bool:
    """원문이 한국어인지 판정. 한글 비중이 threshold 이상이면 True.

    기존엔 '한글이 하나라도 있으면 통과'(한·영 혼용/영문에 한글 한 글자도 통과)였으나,
    비중 기반으로 바꿔 실질적으로 한국어인 원문만 통과시킨다. 기본 임계값 0.5.
    8000자 기준 계산 ~1ms로 번역 비용 대비 무시 가능.
    """
    return korean_char_ratio(text) >= threshold
