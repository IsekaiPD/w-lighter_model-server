"""Pydantic schema에서 재사용하는 요청 검증 함수."""
from __future__ import annotations

from typing import Any

from common.limits import (
    MAX_CHARACTER_AGE,
    MAX_CHARACTER_APPEARANCE,
    MAX_CHARACTER_DETAIL,
    MAX_CHARACTER_GENDER,
    MAX_CHARACTER_NAME,
    MAX_CHARACTER_RELATIONSHIPS,
    MAX_CHARACTER_ROLE,
)


def _check_text_len(item: dict[str, Any], key: str, max_len: int, index: int) -> None:
    value = item.get(key)
    if value is None:
        return
    if len(str(value)) > max_len:
        raise ValueError(f"characters[{index}].{key} must be <= {max_len} characters")


def validate_character_dicts(
    characters: list[dict[str, Any]],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    """캐릭터 dict 목록의 개수와 ERD 기준 주요 필드 길이를 검사한다."""
    if len(characters) > max_items:
        raise ValueError(f"characters must contain at most {max_items} items")

    for idx, item in enumerate(characters):
        if not isinstance(item, dict):
            raise ValueError(f"characters[{idx}] must be an object")

        _check_text_len(item, "char_name", MAX_CHARACTER_NAME, idx)
        _check_text_len(item, "name", MAX_CHARACTER_NAME, idx)
        _check_text_len(item, "age", MAX_CHARACTER_AGE, idx)
        _check_text_len(item, "role", MAX_CHARACTER_ROLE, idx)
        _check_text_len(item, "gender", MAX_CHARACTER_GENDER, idx)
        _check_text_len(item, "relationships", MAX_CHARACTER_RELATIONSHIPS, idx)
        _check_text_len(item, "appearance", MAX_CHARACTER_APPEARANCE, idx)
        _check_text_len(item, "detail_setting", MAX_CHARACTER_DETAIL, idx)
        # profile_label은 별도 DB 컬럼 없이 detail_setting에 합쳐 저장되므로 같은 상한을 적용한다.
        _check_text_len(item, "profile_label", MAX_CHARACTER_DETAIL, idx)

    return characters
