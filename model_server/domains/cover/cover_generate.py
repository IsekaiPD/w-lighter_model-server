import os
from pathlib import Path
from textwrap import dedent

from dotenv import load_dotenv
from openai import OpenAI

from .cover_prompts import (
    COMMON_COVER_RULES,
    get_country_cover_prompt,
    get_country_label,
    normalize_country_code,
)

CURRENT_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=CURRENT_DIR.parent / ".env")

IMAGE_MODEL = os.getenv("WLIGHTER_IMAGE_MODEL", "gpt-image-2")
IMAGE_SIZE = os.getenv("WLIGHTER_IMAGE_SIZE", "1024x1536")
IMAGE_QUALITY = os.getenv("WLIGHTER_IMAGE_QUALITY", "medium")
IMAGE_FORMAT = os.getenv("WLIGHTER_IMAGE_FORMAT", "png")

USER_PROMPT_MAX_CHARS = 500
AI_GENERATED_NOTICE = "이 이미지는 AI로 생성된 이미지입니다. 이미지 안의 문구는 정확하지 않거나 일부 깨질 수 있습니다."
DEFAULT_VISIBLE_CHARACTER_LIMIT = 2

GROUP_COVER_HINT_KEYWORDS = [
    "단체",
    "여러 명",
    "여러명",
    "모든 인물",
    "전원",
    "군상",
    "주요 인물 모두",
]

BLOCKED_PROMPT_KEYWORDS = [
    "실존 인물",
    "유명인",
    "로고 그대로",
    "상표 그대로",
    "미성년자 선정",
]


def value(item: dict, key: str) -> str:
    return str(item.get(key) or "").strip()


def validate_user_prompt(user_prompt: str) -> None:
    if len(user_prompt or "") > USER_PROMPT_MAX_CHARS:
        raise ValueError(f"추가 요청 문구는 최대 {USER_PROMPT_MAX_CHARS}자까지 입력할 수 있습니다.")

    lowered = (user_prompt or "").lower()
    for keyword in BLOCKED_PROMPT_KEYWORDS:
        if keyword.lower() in lowered:
            raise ValueError(f"이미지 생성 요청에 사용할 수 없는 표현이 포함되어 있습니다: {keyword}")


def is_group_cover_requested(user_prompt: str) -> bool:
    prompt = user_prompt or ""
    return any(keyword in prompt for keyword in GROUP_COVER_HINT_KEYWORDS)


def character_priority(character: dict, index: int) -> tuple[int, int]:
    role = value(character, "role")
    relationships = value(character, "relationships")
    detail = value(character, "detail_setting")
    joined = f"{relationships} {detail}"

    score = 0
    if "주인공" in role:
        score += 100
    if "주연" in role:
        score += 80
    if "히로인" in role or "남주" in role or "여주" in role:
        score += 70
    if "중심" in joined or "핵심" in joined:
        score += 30
    if value(character, "appearance"):
        score += 10

    return -score, index


def format_visual_subject(character: dict, index: int) -> str:
    name = value(character, "char_name") or f"인물 {index}"
    return "\n".join(
        [
            f"[{index}] {name}",
            f"- 역할: {value(character, 'role') or '-'}",
            f"- 직업/소속/정체성: {value(character, 'profile_label') or '-'}",
            f"- 성별/나이: {value(character, 'gender') or '-'} / {value(character, 'age') or '-'}",
            f"- 외형: {value(character, 'appearance') or '-'}",
            f"- 표정/분위기 참고: {value(character, 'detail_setting') or '-'}",
        ]
    )


def format_reference_character(character: dict) -> str:
    name = value(character, "char_name")
    if not name:
        return ""

    parts = [
        value(character, "role"),
        value(character, "profile_label"),
        value(character, "relationships"),
    ]
    compact = " / ".join(part for part in parts if part)
    return f"- {name}: {compact}" if compact else f"- {name}"


def format_characters_for_cover(characters: list[dict], *, user_prompt: str = "") -> str:
    if not characters:
        return "캐릭터 설정집이 제공되지 않았습니다. 작품 제목, 장르, 시놉시스의 분위기를 중심으로 표지를 구성합니다."

    indexed = [(index, character) for index, character in enumerate(characters, start=1) if isinstance(character, dict)]
    sorted_characters = sorted(indexed, key=lambda pair: character_priority(pair[1], pair[0]))
    visible_limit = 4 if is_group_cover_requested(user_prompt) else DEFAULT_VISIBLE_CHARACTER_LIMIT

    visual_subjects = sorted_characters[:visible_limit]
    reference_characters = sorted_characters[visible_limit:]

    visual_blocks = [
        format_visual_subject(character, output_index)
        for output_index, (_, character) in enumerate(visual_subjects, start=1)
    ]
    reference_lines = [
        line
        for _, character in reference_characters
        if (line := format_reference_character(character))
    ]

    return "\n\n".join(
        [
            "[커버에 직접 등장시킬 핵심 인물]",
            "\n\n".join(visual_blocks) or "직접 등장시킬 인물 정보 없음.",
            "[직접 등장시키지 말고 분위기/갈등 참고용으로만 사용할 인물]",
            "\n".join(reference_lines) if reference_lines else "추가 참고 인물 없음.",
        ]
    )


def build_cover_prompt(
    *,
    work_title: str,
    genre: str,
    synopsis: str,
    characters: list[dict],
    target_country: str,
    user_prompt: str = "",
) -> str:
    country = normalize_country_code(target_country)
    validate_user_prompt(user_prompt)
    character_context = format_characters_for_cover(characters, user_prompt=user_prompt)
    user_block = (user_prompt or "").strip() or "별도 추가 요청 없음."

    return dedent(
        f"""
        {COMMON_COVER_RULES}

        [작품 정보]
        작품명: {work_title.strip() or '제목 미입력'}
        작품 장르: {genre.strip() or '장르 미입력'}

        [시놉시스 요약/원문]
        {synopsis.strip() or '시놉시스 미입력'}

        [캐릭터 설정집 기반 참고 정보]
        {character_context}

        [커버 구도 지시]
        - 이 이미지는 캐릭터 설정집 전체를 시각화하는 화면이 아니라 작품 판매용 표지다.
        - 위의 "커버에 직접 등장시킬 핵심 인물"만 화면에 인물로 배치한다.
        - "참고용 인물"은 관계, 갈등, 분위기를 잡는 데만 사용하고 화면에 직접 등장시키지 않는다.
        - 사용자가 단체 구도를 명시하지 않았다면 인물 수를 늘리지 않는다.
        - 사용자 추가 요청에는 표지에 넣고 싶은 문구와 이미지 연출 요청이 함께 포함될 수 있다.
        - 따옴표 안의 짧은 문구, 작품 제목처럼 보이는 문구, "문구는 ~" 형태의 요청은 표지 텍스트로 반영을 시도한다.
        - 그 외 내용은 분위기, 구도, 배경, 소품, 인물 외형 요청으로 반영한다.
        - 표지 텍스트는 짧고 크게 배치하되, AI 생성 특성상 글자가 정확하지 않거나 깨질 수 있다.
        - 말풍선, 긴 설명 문장, 로고, 워터마크, 실존 브랜드는 넣지 않는다.

        [국가별 커버 스타일: {get_country_label(country)}]
        {get_country_cover_prompt(country)}

        [사용자 추가 요청]
        {user_block}
        """
    ).strip()


def generate_cover_image(
    *,
    work_title: str,
    genre: str,
    synopsis: str,
    characters: list[dict],
    target_country: str,
    user_prompt: str = "",
    dry_run: bool = False,
) -> dict:
    country = normalize_country_code(target_country)
    final_prompt = build_cover_prompt(
        work_title=work_title,
        genre=genre,
        synopsis=synopsis,
        characters=characters,
        target_country=country,
        user_prompt=user_prompt,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "target_country": country,
            "image_base64": "",
            "final_prompt": final_prompt,
            "model_name": IMAGE_MODEL,
            "size": IMAGE_SIZE,
            "quality": IMAGE_QUALITY,
            "output_format": IMAGE_FORMAT,
            "message": "dry_run=true이므로 이미지 생성 호출 없이 최종 프롬프트만 반환했습니다.",
            "ai_generated_notice": AI_GENERATED_NOTICE,
        }

    client = OpenAI()
    response = client.images.generate(
        model=IMAGE_MODEL,
        prompt=final_prompt,
        size=IMAGE_SIZE,
        quality=IMAGE_QUALITY,
        output_format=IMAGE_FORMAT,
        n=1,
    )

    return {
        "status": "success",
        "target_country": country,
        "image_base64": response.data[0].b64_json or "",
        "final_prompt": final_prompt,
        "model_name": IMAGE_MODEL,
        "size": IMAGE_SIZE,
        "quality": IMAGE_QUALITY,
        "output_format": IMAGE_FORMAT,
        "message": "표지 이미지가 생성되었습니다.",
        "ai_generated_notice": AI_GENERATED_NOTICE,
    }
