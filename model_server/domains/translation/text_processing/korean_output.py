from __future__ import annotations

import json
import re
from typing import Any, Iterable

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
    """원문이 한국어인지 판정. 한글 비중이 threshold(기본 0.5) 이상이면 True."""
    return korean_char_ratio(text) >= threshold


# ------------------------------------------------------------------ #
# 한글 잔류 검출 / 인덱스 기반 수리 (integrity 게이트용)
# ------------------------------------------------------------------ #
# 문장 끝 구분자/개행 '뒤'에서 분할(zero-width lookbehind) → 구분자·공백 보존.
# 따라서 ``"".join(split_into_units(t)) == t`` (가역적). 인덱스 치환의 안정성 근거.
_UNIT_SPLIT_RE = re.compile(r"(?<=[.!?。！？…\n])")


def split_into_units(text: str) -> list[str]:
    """번역문을 문장 단위로 분할하되 구분자·공백을 보존(재조립 시 원문 복원)."""
    if not text:
        return []
    return _UNIT_SPLIT_RE.split(text)


def has_korean_residue(text: str) -> bool:
    """번역문(본문)에 한글이 1자라도 남아있으면 True. (readerEndnotes는 별개라 무관)"""
    return has_hangul(text or "")


def korean_residue_units(text: str) -> list[dict[str, Any]]:
    """한글이 포함된 문장 단위만 {index, sentence}로 반환. index는 split_into_units 기준."""
    return [
        {"index": idx, "sentence": unit}
        for idx, unit in enumerate(split_into_units(text))
        if has_hangul(unit)
    ]


def apply_unit_repairs(text: str, repairs: dict[int, str]) -> str:
    """split_into_units 인덱스 기준으로 해당 unit을 fixed로 치환 후 재조립.

    문자열 검색이 아니라 인덱스 치환이라 'problem 문자열 매칭 실패' 위험이 없다.
    """
    if not repairs:
        return text
    units = split_into_units(text)
    for index, fixed in repairs.items():
        if isinstance(index, int) and 0 <= index < len(units):
            units[index] = fixed
    return "".join(units)
