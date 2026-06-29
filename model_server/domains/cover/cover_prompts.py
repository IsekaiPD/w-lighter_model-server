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
    Country-specific style should create visible differences in composition, background density, rendering texture, typography treatment, and character framing, while preserving the original story setting.
    Do not change the story setting, genre, costume logic, character roles, or relationship structure because of the country style.
    The genre, synopsis, and user request have priority over country-specific color tendencies.
    Do not over-define character appearance when it is not specified in the character sheet.
    Unless the user explicitly requests a group composition, focus on one main character or one strong focal pair.
    Supporting characters should be used as context for mood and conflict, not placed prominently unless requested.
    If the user requests cover text, try to place it as short, large, simple cover typography.
    Cover text may be inaccurate or visually inconsistent because it is AI-generated.
    Do not generate speech bubbles, long sentences, fake letters, logos, watermarks, real brands, real people, or copyrighted characters.
    Avoid explicit nudity, excessive violence, and dangerous depiction of minors.
    """
).strip()


COUNTRY_COVER_STYLE_PROMPTS = {
    "KR": dedent(
        """
        Style: polished Korean web novel platform cover.
        Use a clean, commercial digital illustration style optimized for a mobile web novel thumbnail.
        Keep the main character or main pair large, attractive, and immediately readable.
        Use clear facial appeal, polished lighting, and a balanced character-focused composition.
        Keep the background supportive and organized; it should show genre mood without overpowering the characters.
        Avoid excessive decorative density, overly complex scenery, and unclear silhouettes.
        If cover text is requested, place it in a clean, readable title area, usually center-lower or upper area depending on the composition.
        The result should feel sleek, modern, commercial, and easy to understand at small size on a Korean web novel platform.
        """
    ).strip(),

    "US": dedent(
        """
        Style: American or English-language commercial genre-fiction cover.
        Use a mature cinematic book-cover or streaming-poster direction rather than a cute character-poster look.
        Prioritize strong silhouettes, dramatic lighting, symbolic props, atmospheric tension, and a clear genre hook.
        Characters may be slightly more realistic in proportion and expression, with less ornamental beauty-shot framing.
        Use deeper shadows, controlled contrast, and a poster-like focal structure.
        The background can be atmospheric and symbolic, but should not become a crowded fantasy illustration.
        If cover text is requested, make the typography feel like a commercial fantasy, action, romance, or thriller book cover: bold, readable, and integrated into the composition.
        Avoid overly anime-like expressions, excessive sparkle effects, and decorative light-novel framing.
        """
    ).strip(),

    "JP": dedent(
        """
        Style: Japanese web novel or light novel inspired character cover.
        Make the cover clearly character-focused, with expressive faces, readable poses, clean linework, and a strong emotional relationship between the main character or main pair.
        Keep the background simpler, flatter, or more softly blurred than a grand Chinese fantasy cover.
        Avoid making the scene feel like a vast Chinese wuxia landscape poster; reduce excessive mountain depth, palace scale, heavy atmospheric realism, and ornate scenic density unless the story absolutely requires it.
        Use tidy color design, clean contours, controlled highlights, and a light-novel-like illustration finish.
        Character emotion, relationship tension, and visual readability should matter more than environmental scale.
        If cover text is requested, place it as a clean Japanese light-novel style title treatment, usually in the upper or side area with enough blank space.
        Do not imitate a specific artist, existing manga, anime, or light novel title.
        """
    ).strip(),

    "CN": dedent(
        """
        Style: high-quality Chinese web novel cover illustration.
        Emphasize grand story scale, strong protagonist presence, dramatic atmosphere, and polished digital painting.
        Use deeper environmental space, layered mountains, mist, cliffs, old architecture, sect scenery, palace silhouettes, battlefield ruins, or other setting elements when they match the story.
        Make the composition feel more expansive and cinematic than the Japanese version, with stronger background depth and a more imposing sense of world.
        Characters can wear more ornate or elegant costume details when supported by the story setting, but do not change the original costume logic.
        Use rich lighting, atmospheric haze, refined fabric detail, and strong vertical cover drama.
        If cover text is requested, use a bold Chinese title treatment that can feel calligraphic, vertical, or monumental, while keeping it readable.
        Avoid making the result look like a Japanese light novel cover with a mostly blank background and overly cute character framing.
        """
    ).strip(),

    "TH": dedent(
        """
        Style: commercial Thai mobile web fiction cover, especially romance or drama platform covers.
        Apply the style through relationship-focused composition, character appeal, facial emotion, and platform-friendly presentation; do not change the story setting, era, costume logic, genre, or character roles.
        Emphasize the main couple or emotional lead character with a glamorous but slightly hand-rendered digital illustration look.
        Use clean contour lines, mature natural facial proportions, soft matte coloring, subtle brush texture, and a polished mobile-cover layout.
        Reduce excessive glossy highlights, shiny 3D-rendered surfaces, overly ornate Chinese fantasy scenery, and heavy cinematic darkness unless the story requires it.
        Backgrounds should support emotional mood rather than dominate the image; relationship tension should be easy to read at thumbnail size.
        Avoid overly cute proportions, oversized sparkling eyes, tourist-landmark imagery, fake letters, logos, and watermarks.
        If cover text is requested, keep it large, simple, and platform-cover friendly, without long decorative text blocks.
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
