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
COVER_PROMPT_MODEL = os.getenv("WLIGHTER_COVER_PROMPT_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))

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


def format_character_full_context(character: dict, index: int) -> str:
    name = value(character, "char_name") or f"인물 {index}"
    return "\n".join(
        [
            f"[{index}] {name}",
            f"- 역할: {value(character, 'role') or '-'}",
            f"- 직업/소속/정체성: {value(character, 'profile_label') or '-'}",
            f"- 성별/나이: {value(character, 'gender') or '-'} / {value(character, 'age') or '-'}",
            f"- 외형: {value(character, 'appearance') or '-'}",
            f"- 관계: {value(character, 'relationships') or '-'}",
            f"- 세부 설정/분위기: {value(character, 'detail_setting') or '-'}",
        ]
    )


def format_characters_for_cover(characters: list[dict], *, user_prompt: str = "") -> str:
    if not characters:
        return "캐릭터 설정집이 제공되지 않았습니다. 장르와 시놉시스의 분위기를 중심으로 표지를 구성합니다."

    indexed = [(index, character) for index, character in enumerate(characters, start=1) if isinstance(character, dict)]
    sorted_characters = sorted(indexed, key=lambda pair: character_priority(pair[1], pair[0]))
    default_visible_limit = 4 if is_group_cover_requested(user_prompt) else DEFAULT_VISIBLE_CHARACTER_LIMIT

    default_subjects = sorted_characters[:default_visible_limit]
    default_blocks = [
        format_visual_subject(character, output_index)
        for output_index, (_, character) in enumerate(default_subjects, start=1)
    ]
    all_character_blocks = [
        format_character_full_context(character, index)
        for index, character in indexed
    ]

    return "\n\n".join(
        [
            "[기본 표지 후보 인물]",
            "\n\n".join(default_blocks) or "기본 후보 인물 정보 없음.",
            "[전체 캐릭터 설정집]",
            "\n\n".join(all_character_blocks) if all_character_blocks else "전체 캐릭터 정보 없음.",
            "[캐릭터 선택 규칙]",
            "사용자 추가 요청에 특정 캐릭터 포함/제외/단독 등장 요청이 있으면 기본 후보보다 사용자 요청을 우선한다.",
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
        작품 장르: {genre.strip() or '장르 미입력'}

        [시놉시스 요약/원문]
        {synopsis.strip() or '시놉시스 미입력'}

        [캐릭터 설정집 기반 참고 정보]
        {character_context}

        [커버 구도 지시]
        - 이 이미지는 캐릭터 설정집 전체를 시각화하는 화면이 아니라 작품 판매용 표지다.
        - 사용자 추가 요청을 최우선으로 반영하되, 원작 설정/장르/시대/관계 구조를 바꾸지 않는다.
        - 사용자가 특정 캐릭터를 넣어달라고 하면 주인공/주연/조연 여부와 관계없이 보이는 인물로 포함한다.
        - 사용자가 특정 캐릭터만 나오게 요청하면 그 캐릭터만 보이는 인물로 사용한다.
        - 사용자가 특정 캐릭터를 제외해달라고 하면 그 캐릭터를 보이는 인물에서 제외한다.
        - 사용자가 단체 구도를 요청하지 않았다면 기본적으로 한 명의 중심 인물 또는 중심 페어 위주로 구성한다.
        - 추가 요청에 제목/문구 삽입 요청이 없으면 표지 안에는 작품명, 제목, 문구, 글자, 타이포그래피를 넣지 않는다.
        - 제목/문구는 사용자가 추가 요청에 정확한 텍스트를 직접 적고 표지에 넣어달라고 요청한 경우에만 넣는다.
        - 위치를 함께 적은 경우에는 가능한 한 해당 위치에 배치하고, 위치가 없으면 표지 구도에 어울리는 짧고 큰 제목 타이포그래피로 배치한다.
        - 원문 작품명은 표지 텍스트로 자동 삽입하지 않는다.
        - 말풍선, 긴 설명 문장, 로고, 워터마크, 실존 브랜드는 넣지 않는다.

        [국가별 커버 스타일: {get_country_label(country)}]
        {get_country_cover_prompt(country)}

        [사용자 추가 요청]
        {user_block}
        """
    ).strip()


def refine_cover_prompt_with_llm(*, client: OpenAI, base_prompt: str) -> str:
    """
    작품 데이터, 국가별 스타일, 캐릭터 설정집, 사용자 추가 요청을 기반으로
    이미지 생성 모델에 넘길 최종 프롬프트를 내부에서 작성한다.
    실패하면 기존 base_prompt를 반환해 커버 생성 흐름을 유지한다.
    """
    system_prompt = dedent(
        """
        You are an internal prompt writer for a web novel cover image generator.
        Read the source prompt and write one final English image-generation prompt.

        Core rules:
        - The user's additional request has the highest priority unless it breaks safety rules or contradicts the original story facts.
        - Do not invent new characters, relationships, genres, eras, costumes, locations, or story settings.
        - Preserve the original story setting, era, genre, character roles, relationship structure, and mood.
        - Country-market style may affect only cover presentation, composition, rendering, lighting, and market appeal.
        - If the user asks to include a specific character, include that character as a visible cover subject even if they are a supporting character.
        - If the user asks for only a specific character to appear, show only that character as the visible subject.
        - If the user asks to exclude a specific character, do not include that character as a visible subject.
        - If the user asks for a group composition, include the requested group or character set.
        - If no specific character composition is requested, use one main character or one strong focal pair based on the source prompt.
        - Do not automatically add cover title text.
        - Include title/text only when the user explicitly requested text insertion and provided the exact text.
        - If placement is provided, follow it as closely as possible.
        - If placement is not provided, place the exact text as short, large, simple cover typography in a visually appropriate area.
        - If there is no explicit text insertion request or no exact text, clearly instruct: no text, no title, no typography.
        - Keep the final prompt concise, visual, and directly usable by an image generation model.
        - Include negative instructions against fake letters, logos, watermarks, real brands, speech bubbles, long text, unsafe sexual content, excessive violence, and unsafe depictions of minors.
        - Return only the final image prompt. Do not include explanations, markdown, JSON, labels, or analysis.
        """
    ).strip()

    user_content = dedent(
        f"""
        Source prompt:
        {base_prompt}
        """
    ).strip()

    try:
        response = client.chat.completions.create(
            model=COVER_PROMPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )
        refined_prompt = (response.choices[0].message.content or "").strip()
        return refined_prompt or base_prompt
    except Exception:
        return base_prompt


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
    base_prompt = build_cover_prompt(
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
            "final_prompt": base_prompt,
            "model_name": IMAGE_MODEL,
            "size": IMAGE_SIZE,
            "quality": IMAGE_QUALITY,
            "output_format": IMAGE_FORMAT,
            "message": "dry_run=true이므로 이미지 생성 호출 없이 최종 프롬프트만 반환했습니다.",
            "ai_generated_notice": AI_GENERATED_NOTICE,
        }

    client = OpenAI()
    final_prompt = refine_cover_prompt_with_llm(client=client, base_prompt=base_prompt)
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
