import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from common.limits import MAX_CHARACTER_COUNT, MAX_SYNOPSIS

from .character_prompts import SYSTEM_PROMPT, build_character_extract_prompt

CURRENT_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=CURRENT_DIR.parent / ".env")

TEXT_MODEL = os.getenv("WLIGHTER_TEXT_MODEL", "gpt-5.4-mini")
CHARACTER_LIMIT_DEFAULT = 20
CHARACTER_LIMIT_MAX = MAX_CHARACTER_COUNT
SYNOPSIS_MAX_CHARS = MAX_SYNOPSIS

CHARACTER_FIELDS = [
    "char_name",
    "age",
    "role",
    "profile_label",
    "gender",
    "relationships",
    "appearance",
    "detail_setting",
]


def request_json(*, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict:
    client = OpenAI()
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def text(value, max_length: int | None = None) -> str:
    cleaned = str(value or "").strip()
    if max_length and len(cleaned) > max_length:
        return cleaned[:max_length].rstrip()
    return cleaned


BLOCKED_PROFILE_LABELS = {
    "-",
    "기타",
    "인물",
    "등장인물",
    "주요 인물",
    "미상",
    "없음",
    "주인공",
    "악역",
    "조력자",
    "친구",
    "연인",
    "가족",
}


def clean_profile_label(value: str | None, max_length: int = 80) -> str:
    label = text(value, max_length)
    if not label or label in BLOCKED_PROFILE_LABELS:
        return ""
    return label


def validate_character_request(*, synopsis: str, limit: int) -> None:
    if not synopsis or not synopsis.strip():
        raise ValueError("시놉시스가 비어 있습니다.")
    if len(synopsis) > SYNOPSIS_MAX_CHARS:
        raise ValueError(f"시놉시스는 최대 {SYNOPSIS_MAX_CHARS}자까지 입력할 수 있습니다.")
    if limit < 1 or limit > CHARACTER_LIMIT_MAX:
        raise ValueError(f"캐릭터 추출 개수는 1~{CHARACTER_LIMIT_MAX}명 사이여야 합니다.")


def normalize_character_item(item: dict) -> dict:
    normalized = {field: text(item.get(field)) for field in CHARACTER_FIELDS}
    normalized["char_name"] = text(normalized["char_name"], 30)
    normalized["age"] = text(normalized["age"], 10)
    normalized["role"] = text(normalized["role"], 10)
    normalized["profile_label"] = clean_profile_label(normalized["profile_label"], 80)
    normalized["gender"] = text(normalized["gender"], 10)
    normalized["relationships"] = text(normalized["relationships"], 500)
    normalized["appearance"] = text(normalized["appearance"], 300)
    normalized["detail_setting"] = text(normalized["detail_setting"], 1000)
    return normalized


def normalize_character_response(raw: dict, *, limit: int) -> list[dict]:
    characters = raw.get("characters") if isinstance(raw, dict) else []
    if not isinstance(characters, list):
        return []

    results: list[dict] = []
    seen_names: set[str] = set()
    for item in characters:
        if not isinstance(item, dict):
            continue
        normalized = normalize_character_item(item)
        name = normalized["char_name"]
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        results.append(normalized)
        if len(results) >= limit:
            break
    return results


def extract_characters(
    *,
    work_title: str,
    genre: str,
    synopsis: str,
    limit: int = CHARACTER_LIMIT_DEFAULT,
) -> dict:
    validate_character_request(synopsis=synopsis, limit=limit)
    prompt = build_character_extract_prompt(
        work_title=work_title,
        genre=genre,
        synopsis=synopsis,
        limit=limit,
    )
    raw = request_json(system_prompt=SYSTEM_PROMPT, user_prompt=prompt)
    characters = normalize_character_response(raw, limit=limit)
    return {
        "work_title": work_title,
        "genre": genre,
        "count": len(characters),
        "characters": characters,
    }
