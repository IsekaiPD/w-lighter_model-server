import os
import re
import logging
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
COVER_PROMPT_MODEL = os.getenv("WLIGHTER_COVER_PROMPT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

logger = logging.getLogger(__name__)
LOG_COVER_PROMPT = os.getenv("WLIGHTER_LOG_COVER_PROMPT", "false").lower() == "true"

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


TITLE_INSERTION_KEYWORDS = [
    "제목",
    "작품명",
    "타이틀",
    "표지 문구",
    "문구",
    "글자",
    "텍스트",
]

TITLE_TRANSLATION_KEYWORDS = [
    "번역",
    "번역해서",
    "영어로",
    "일본어로",
    "중국어로",
    "태국어로",
    "현지어로",
]

TEXT_INSERTION_ACTION_KEYWORDS = [
    "넣어",
    "넣고",
    "추가",
    "표시",
    "삽입",
    "써줘",
    "적어줘",
    "넣어줘",
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



def is_text_insertion_requested(user_prompt: str) -> bool:
    prompt = user_prompt or ""
    has_text_keyword = any(keyword in prompt for keyword in TITLE_INSERTION_KEYWORDS)
    has_action_keyword = any(keyword in prompt for keyword in TEXT_INSERTION_ACTION_KEYWORDS)
    return has_text_keyword and has_action_keyword


def is_title_translation_requested(user_prompt: str) -> bool:
    prompt = user_prompt or ""
    return is_text_insertion_requested(prompt) and any(keyword in prompt for keyword in TITLE_TRANSLATION_KEYWORDS)


def extract_quoted_cover_text(user_prompt: str) -> str:
    """
    사용자가 표지에 넣을 정확한 문구를 따옴표로 직접 제공한 경우에만 추출한다.
    일반 명령문인 '제목 넣어줘'가 표지 문구로 오인되는 것을 막기 위한 보조 함수다.
    """
    prompt = user_prompt or ""
    if not is_text_insertion_requested(prompt):
        return ""

    patterns = [
        r'"([^"\n]{1,80})"',
        r"'([^'\n]{1,80})'",
        r"“([^”\n]{1,80})”",
        r"‘([^’\n]{1,80})’",
        r"「([^」\n]{1,80})」",
        r"『([^』\n]{1,80})』",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            return match.group(1).strip()
    return ""


def build_text_insertion_rules(*, work_title: str, user_prompt: str, has_user_prompt: bool, target_country: str = "") -> str:
    title = (work_title or "").strip()
    country = normalize_country_code(target_country) if target_country else ""
    explicit_text = extract_quoted_cover_text(user_prompt)
    wants_text = is_text_insertion_requested(user_prompt)
    wants_translation = is_title_translation_requested(user_prompt)

    if not has_user_prompt:
        return dedent(
            """
            - 사용자 추가 요청이 비어 있으므로 표지 안에는 작품명, 제목, 문구, 글자, 타이포그래피를 넣지 않는다.
            - 원문 작품명은 표지 텍스트로 자동 삽입하지 않는다.
            - 글자가 없는 순수 커버 일러스트 이미지만 생성한다.
            """
        ).strip()

    if explicit_text:
        return dedent(
            f"""
            - 사용자가 표지에 넣을 정확한 문구를 따옴표로 직접 제공했다.
            - 표지에 넣을 수 있는 텍스트는 정확히 "{explicit_text}" 하나뿐이다.
            - 허용된 문구를 한 글자도 번역, 의역, 로마자화, 영어 제목화, 현지어 제목화하지 않는다.
            - 사용자 요청 문장 전체를 표지 텍스트로 사용하지 않는다.
            - 작품 제목을 자동 번역하거나 새 제목을 만들지 않는다.
            - 위치를 함께 적은 경우에는 가능한 한 해당 위치에 배치한다.
            - 위치를 적지 않은 경우에는 표지 구도에 어울리는 짧고 큰 제목 타이포그래피로 배치한다.
            """
        ).strip()

    if wants_text and title:
        translation_note = (
            "- 사용자가 제목 번역을 요청했더라도 현재 단계에서는 제목을 새로 번역하지 않는다. 번역 제목이 별도 값으로 제공되지 않았으므로 원문 작품 제목만 사용한다."
            if wants_translation
            else "- 사용자가 제목/작품명/타이틀 삽입을 요청했으므로 원문 작품 제목만 사용한다."
        )
        return dedent(
            f"""
            {translation_note}
            - 표지에 넣을 수 있는 텍스트는 정확히 "{title}" 하나뿐이다.
            - 허용된 제목을 한 글자도 번역, 의역, 로마자화, 영어 제목화, 현지어 제목화하지 않는다.
            - "제목 넣어줘", "타이틀 넣어줘", "작품명 넣어줘", "제목 번역해서 넣어줘" 같은 요청 문구 자체를 이미지 안에 절대 쓰지 않는다.
            - 작품 제목을 임의로 번역하거나 의역하거나 새 제목으로 바꾸지 않는다.
            - 대상 국가가 JP, CN, TH, KR이어도 정확히 허용된 제목만 복사하고 영어 제목을 새로 만들지 않는다.
            - 위치를 함께 적은 경우에는 가능한 한 해당 위치에 배치한다.
            - 위치를 적지 않은 경우에는 표지 구도에 어울리는 짧고 큰 제목 타이포그래피로 배치한다.
            """
        ).strip()

    if wants_text and not title:
        return dedent(
            """
            - 사용자가 제목/작품명/타이틀 삽입을 요청했지만 작품 제목 값이 비어 있다.
            - 넣을 실제 제목이 없으므로 표지 안에는 제목, 문구, 글자, 타이포그래피를 넣지 않는다.
            - "제목 넣어줘", "타이틀 넣어줘", "작품명 넣어줘", "제목 번역해서 넣어줘" 같은 요청 문구 자체를 이미지 안에 절대 쓰지 않는다.
            - 작품 제목을 임의로 만들거나 번역하지 않는다.
            """
        ).strip()

    return dedent(
        """
        - 사용자 추가 요청은 이미지 연출 요청으로만 반영한다.
        - 표지에 넣을 정확한 제목/문구 삽입 요청이 없으므로 표지 안에는 제목, 문구, 글자, 타이포그래피를 넣지 않는다.
        - 사용자 요청 문장 자체를 표지 텍스트로 사용하지 않는다.
        - 원문 작품명은 표지 텍스트로 자동 삽입하지 않는다.
        """
    ).strip()


def character_priority(character: dict, index: int) -> tuple[int, int]:
    role = value(character, "role")
    relationships = value(character, "relationships")
    detail = value(character, "detail_setting")
    profile_label = value(character, "profile_label")
    joined = f"{relationships} {detail} {profile_label}"

    score = 0
    if "주연" in role:
        score += 100
    elif "조연" in role:
        score += 50
    elif "단역" in role:
        score += 10

    if "주인공" in joined or "히로인" in joined or "남주" in joined or "여주" in joined:
        score += 40
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
    has_user_prompt = bool((user_prompt or "").strip())
    text_insertion_rules = build_text_insertion_rules(
        work_title=work_title,
        user_prompt=user_prompt,
        has_user_prompt=has_user_prompt,
        target_country=country,
    )

    return dedent(
        f"""
        {COMMON_COVER_RULES}

        [작품 정보]
        작품 제목: {work_title.strip() or '제목 미입력'}
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
        - 사용자 추가 요청에는 이미지 연출 요청과, 필요한 경우 표지에 넣을 제목/문구가 함께 포함될 수 있다.
        {text_insertion_rules}
        - 그 외 내용은 분위기, 구도, 배경, 소품, 인물 외형 요청으로 반영한다.
        - 표지 텍스트를 넣는 경우에도 짧고 크게 배치하되, AI 생성 특성상 글자가 정확하지 않거나 깨질 수 있다.
        - 말풍선, 긴 설명 문장, 로고, 워터마크, 실존 브랜드는 넣지 않는다.

        [국가별 커버 스타일: {get_country_label(country)}]
        {get_country_cover_prompt(country)}

        [사용자 추가 요청]
        {user_block}
        """
    ).strip()


def refine_cover_prompt_with_llm(*, client: OpenAI, base_prompt: str) -> str:
    """
    이미지 모델에 넘기기 전, 내부 텍스트 LLM으로 커버 프롬프트를 정리한다.
    실패 시 기존 base_prompt를 그대로 반환해서 커버 생성 흐름을 막지 않는다.
    """
    system_prompt = dedent(
        """
        You are an internal prompt refiner for a web novel cover image generator.
        Rewrite the given source prompt into one clear final English prompt for the image generation model.

        Rules:
        - Do not invent new story settings, characters, relationships, costumes, genres, or locations.
        - Preserve the original story setting, era, genre, character roles, and mood.
        - Country-market style may affect only presentation, composition, rendering, lighting, and market appeal.
        - Do not automatically add cover title text.
        - Include cover title/text only when the source prompt explicitly permits one exact text string.
        - If the source prompt says the only allowed cover text is a quoted string, copy exactly that string and no other text.
        - Never translate, romanize, paraphrase, localize, rewrite, or convert the allowed cover text into an English title.
        - For JP, CN, TH, and KR targets, never create an English title unless that exact English text is the only allowed cover text provided by the user.
        - Do not treat directive phrases such as "제목 넣어줘", "타이틀 넣어줘", "작품명 넣어줘", "제목 번역해서 넣어줘", "add title", or "put the title" as cover text.
        - If the source prompt permits the original work title as cover text, use that original work title exactly as provided.
        - Do not translate, localize, paraphrase, or invent a title unless the source prompt already provides the exact translated title text as the only allowed cover text.
        - If placement is provided, follow it as closely as possible.
        - If placement is not provided, place the text as short, large, simple cover typography in a visually appropriate area.
        - If the source prompt does not explicitly permit one exact text string, clearly instruct: no text, no title, no typography.
        - Keep the prompt concise, visual, and directly usable by an image generation model.
        - Include negative instructions for fake letters, logos, watermarks, real brands, speech bubbles, long text, and unsafe content.
        - Return only the final image prompt. Do not include explanations, markdown, JSON, or labels.
        """
    ).strip()

    user_content = dedent(
        f"""
        Source cover prompt:
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

    if LOG_COVER_PROMPT:
        logger.info("cover final image prompt:\n%s", final_prompt)

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
