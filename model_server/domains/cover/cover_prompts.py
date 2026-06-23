from textwrap import dedent


TARGET_COUNTRY_LABELS = {
    "KR": "한국",
    "US": "미국/영어권",
    "CN": "중국",
    "JP": "일본",
    "TH": "태국",
}


COMMON_COVER_RULES = dedent(
    """
    This image is a vertical web novel cover illustration representing the story.
    It is not a group illustration that lists every character in the character sheet.
    Preserve the original character roles, era, setting, world, genre, and core story mood.
    Country-specific style should affect only cover presentation, rendering, composition, lighting, and market appeal.
    Do not change the story setting, genre, costume logic, character roles, or relationship structure because of the country style.
    The genre, synopsis, and user request have priority over country-specific color tendencies.
    Do not over-define character appearance when it is not specified in the character sheet.
    Unless the user explicitly requests a group composition, focus on one main character or one strong focal pair.
    Supporting characters should be used as context for mood and conflict, not placed prominently unless requested.
    Leave some natural empty space where title typography can be added later.
    Do not generate readable title text, sentences, speech bubbles, fake letters, logos, watermarks, real brands, real people, or copyrighted characters.
    Avoid explicit nudity, excessive violence, and dangerous depiction of minors.
    """
).strip()


COUNTRY_COVER_STYLE_PROMPTS = {
    "KR": dedent(
        """
        Style: polished Korean web novel platform cover.
        Use a clean commercial digital illustration style with a strong character-focused composition.
        Prioritize clear protagonist appeal, readable genre mood, and emotional expression that works well as a mobile thumbnail.
        Keep the background organized and supportive rather than overly crowded.
        The cover should feel sleek, modern, accessible, and immediately understandable on a Korean web novel platform.
        """
    ).strip(),

    "US": dedent(
        """
        Style: American or English-language commercial genre-fiction cover.
        Use a more mature cinematic cover direction with realistic character proportions, clear silhouette, strong focal point, and dramatic movie-poster lighting.
        Make the conflict, danger, romance, fantasy, or genre mood readable at a glance.
        Keep the background atmospheric but not cluttered, and avoid cute character-poster presentation.
        The result should feel like a professional commercial book or web fiction cover for an English-speaking market.
        """
    ).strip(),

    "JP": dedent(
        """
        Style: Japanese web novel or light novel inspired character cover.
        Use character-focused composition, clean line art, expressive faces, readable poses, and tidy color design.
        Make the main character or main pair visually appealing and emotionally clear.
        Use bright or controlled colors only when they match the story mood.
        Do not imitate a specific artist or existing title; keep it as a general Japanese character-cover convention.
        """
    ).strip(),

    "CN": dedent(
        """
        Style: high-quality Chinese web novel cover illustration.
        Emphasize strong protagonist presence, dramatic storytelling, rich atmosphere, and polished digital painting.
        Use deeper background depth, elegant lighting, and a more ornate or cinematic sense of scale when it fits the story.
        Keep the main character visually dominant even when the background, costume, or effects are detailed.
        Avoid excessive decoration, messy visual density, or sexualized presentation.
        """
    ).strip(),

    "TH": dedent(
        """
        Style: commercial Thai mobile web fiction cover, especially romance or drama platform covers.
        Apply the style through cover presentation, character appeal, composition, and rendering; do not change the story setting, era, costume logic, genre, or character roles.
        Use relationship-focused character composition, glamorous stylized leads, fashion-editorial styling, and a thumbnail-friendly vertical layout.
        Use a polished but slightly hand-rendered digital illustration style with clean contour lines, subtle brush texture, soft matte coloring, and mature natural facial proportions.
        Reduce excessive glossy highlights, airbrushed gloss, and shiny 3D-rendered surfaces.
        Do not automatically add backgrounds, costumes, school elements, fantasy elements, or genre elements that are not present in the story request.
        Avoid overly cute proportions, oversized sparkling eyes, cartoonish simplification, fake letters, logos, watermarks, and tourist-landmark imagery.
        Let the story mood decide the lighting and colors; do not force bright or warm colors for dark, tragic, thriller, revenge, or serious stories.
        If an engineer character appears, a subtle red shirt can be used as their outfit detail, without overriding the overall Thai-style cover composition.
        """
    ).strip(),
}


def normalize_country_code(target_country: str) -> str:
    country = (target_country or "").strip().upper()
    if country not in TARGET_COUNTRY_LABELS:
        allowed = ", ".join(TARGET_COUNTRY_LABELS)
        raise ValueError(f"지원하지 않는 국가 코드입니다: {target_country}. allowed={allowed}")
    return country


def get_country_label(target_country: str) -> str:
    return TARGET_COUNTRY_LABELS[normalize_country_code(target_country)]


def get_country_cover_prompt(target_country: str) -> str:
    return COUNTRY_COVER_STYLE_PROMPTS[normalize_country_code(target_country)]
