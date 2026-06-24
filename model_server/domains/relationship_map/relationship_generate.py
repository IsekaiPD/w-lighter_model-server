import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .relationship_prompts import SYSTEM_PROMPT, build_relation_extract_prompt

CURRENT_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=CURRENT_DIR.parent / ".env")

TEXT_MODEL = os.getenv("WLIGHTER_TEXT_MODEL", "gpt-5.4-mini")
RELATION_CHARACTER_LIMIT_DEFAULT = 20
RELATION_CHARACTER_LIMIT_MAX = 20

STYLE_COLORS = {
    "romance": "#b56b82",
    "partnership": "#6c8a62",
    "hierarchy": "#7562a0",
    "rivalry": "#c95b4a",
    "mentorship": "#8a6bbb",
    "family": "#b8844c",
    "organization": "#5d7c99",
    "neutral": "#b99b72",
}


def request_json(*, system_prompt: str, user_prompt: str, temperature: float = 0.15) -> dict:
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


def importance(value, default: int = 3) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, 5))


def direction(value) -> str:
    return "one_way" if str(value or "").strip() == "one_way" else "both"


def merge_text(existing: str, current: str, *, max_length: int) -> str:
    existing = text(existing)
    current = text(current)
    if not existing:
        return text(current, max_length)
    if not current or current in existing:
        return text(existing, max_length)
    return text(f"{existing} / {current}", max_length)


def merge_relation(existing: dict, current: dict) -> dict:
    same_order = existing.get("source") == current.get("source") and existing.get("target") == current.get("target")
    if existing.get("direction") == "both" or current.get("direction") == "both" or not same_order:
        existing["direction"] = "both"

    existing["relation"] = merge_text(existing.get("relation", ""), current.get("relation", ""), max_length=40)
    existing["description"] = merge_text(existing.get("description", ""), current.get("description", ""), max_length=240)

    if existing.get("style") == "neutral" and current.get("style") != "neutral":
        existing["style"] = current.get("style", "neutral")

    existing["importance"] = min(
        importance(existing.get("importance")),
        importance(current.get("importance")),
    )
    return existing


def character_id(character: dict, index: int) -> str:
    raw_id = character.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        raw_id = character.get("character_id")
    if raw_id is None or str(raw_id).strip() == "":
        return f"char_{index}"
    raw = str(raw_id).strip()
    return raw if raw.startswith("char_") else f"char_{raw}"


def value(character: dict, key: str) -> str:
    return str(character.get(key) or "").strip()


def normalize_input_characters(characters: list[dict], *, limit: int) -> list[dict]:
    results: list[dict] = []
    for index, character in enumerate(characters[:limit], start=1):
        if not isinstance(character, dict):
            continue
        name = value(character, "char_name")
        if not name:
            continue
        copied = dict(character)
        copied["id"] = character_id(character, index)
        results.append(copied)
    return results


def normalize_relation_data(raw: dict, *, work_title: str, input_characters: list[dict], limit: int) -> dict:
    source_characters = normalize_input_characters(input_characters, limit=limit)
    allowed_ids = {item["id"] for item in source_characters}
    by_id = {item["id"]: item for item in source_characters}

    raw_characters = raw.get("characters") if isinstance(raw, dict) else []
    if not isinstance(raw_characters, list):
        raw_characters = []

    characters: list[dict] = []
    seen: set[str] = set()
    for item in raw_characters:
        if not isinstance(item, dict):
            continue
        item_id = text(item.get("id"))
        if item_id not in allowed_ids or item_id in seen:
            continue
        original = by_id[item_id]
        characters.append(
            {
                "id": item_id,
                "name": text(item.get("name")) or value(original, "char_name"),
                "role": text(item.get("role"), 20) or value(original, "role"),
                "profile_label": clean_profile_label(value(original, "profile_label"), 80) or clean_profile_label(item.get("profile_label"), 80),
                "description": text(item.get("description"), 120),
                "is_main": bool(item.get("is_main")),
                "importance": importance(item.get("importance")),
            }
        )
        seen.add(item_id)
        if len(characters) >= limit:
            break

    if not characters:
        for index, original in enumerate(source_characters):
            characters.append(
                {
                    "id": original["id"],
                    "name": value(original, "char_name"),
                    "role": value(original, "role"),
                    "profile_label": clean_profile_label(value(original, "profile_label"), 80),
                    "description": value(original, "detail_setting")[:120],
                    "is_main": index == 0,
                    "importance": 1 if index == 0 else 3,
                }
            )

    if not any(item.get("is_main") for item in characters) and characters:
        characters[0]["is_main"] = True

    valid_ids = {item["id"] for item in characters}

    raw_relations = raw.get("relations") if isinstance(raw, dict) else []
    if not isinstance(raw_relations, list):
        raw_relations = []

    relation_by_pair: dict[tuple[str, str], dict] = {}
    relation_order: list[tuple[str, str]] = []

    for item in raw_relations:
        if not isinstance(item, dict):
            continue
        source = text(item.get("source"))
        target = text(item.get("target"))
        if source not in valid_ids or target not in valid_ids or source == target:
            continue

        style = text(item.get("style")) or "neutral"
        if style not in STYLE_COLORS:
            style = "neutral"

        current_relation = {
            "source": source,
            "target": target,
            "relation": text(item.get("relation"), 40),
            "description": text(item.get("description"), 240),
            "direction": direction(item.get("direction")),
            "style": style,
            "importance": importance(item.get("importance")),
        }
        pair_key = tuple(sorted((source, target)))

        if pair_key not in relation_by_pair:
            relation_by_pair[pair_key] = current_relation
            relation_order.append(pair_key)
            continue

        relation_by_pair[pair_key] = merge_relation(relation_by_pair[pair_key], current_relation)

    relations = [relation_by_pair[key] for key in relation_order]

    raw_groups = raw.get("groups") if isinstance(raw, dict) else []
    if not isinstance(raw_groups, list):
        raw_groups = []

    groups: list[dict] = []
    for index, item in enumerate(raw_groups, start=1):
        if not isinstance(item, dict):
            continue
        members = [member for member in item.get("members", []) if member in valid_ids]
        if not members:
            continue
        groups.append(
            {
                "id": text(item.get("id")) or f"group_{index:03d}",
                "name": text(item.get("name"), 60),
                "group_type": text(item.get("group_type"), 30),
                "members": members,
                "description": text(item.get("description"), 200),
                "importance": importance(item.get("importance")),
            }
        )

    warnings = raw.get("warnings") if isinstance(raw, dict) and isinstance(raw.get("warnings"), list) else []
    main = next((item for item in characters if item.get("is_main")), characters[0] if characters else {})

    return {
        "work_title": text(raw.get("work_title") if isinstance(raw, dict) else "") or work_title,
        "main_character": text(raw.get("main_character") if isinstance(raw, dict) else "") or main.get("name", ""),
        "summary": text(raw.get("summary") if isinstance(raw, dict) else "", 300),
        "characters": characters,
        "groups": groups,
        "relations": relations,
        "warnings": [text(item, 160) for item in warnings if text(item)],
    }


def generate_relation_data(
    *,
    work_title: str,
    characters: list[dict],
    limit: int = RELATION_CHARACTER_LIMIT_DEFAULT,
) -> dict:
    if limit < 1 or limit > RELATION_CHARACTER_LIMIT_MAX:
        raise ValueError(f"관계도 캐릭터 수는 1~{RELATION_CHARACTER_LIMIT_MAX}명 사이여야 합니다.")

    normalized_characters = normalize_input_characters(characters, limit=limit)
    if not normalized_characters:
        raise ValueError("관계도를 생성할 캐릭터 설정집이 비어 있습니다.")

    prompt = build_relation_extract_prompt(
        work_title=work_title,
        characters=normalized_characters,
        limit=limit,
    )
    raw = request_json(system_prompt=SYSTEM_PROMPT, user_prompt=prompt)
    return normalize_relation_data(
        raw,
        work_title=work_title,
        input_characters=normalized_characters,
        limit=limit,
    )
