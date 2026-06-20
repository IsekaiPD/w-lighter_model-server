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
    이 이미지는 작품을 대표하는 웹소설 표지 이미지다.
    캐릭터 설정집 전체를 나열하는 단체 일러스트가 아니다.
    원작의 인물 설정, 시대, 배경, 핵심 분위기는 유지한다.
    국가별 스타일은 표지의 표현 방식과 분위기에만 반영한다.
    캐릭터 설정집에 명시되지 않은 외형은 과하게 단정하지 않는다.
    기본 표지는 주인공 또는 핵심 인물 1명을 중심으로 잡고, 필요할 때만 2명까지 배치한다.
    사용자가 단체 구도나 여러 인물을 명시적으로 요청하지 않은 경우, 조연들은 화면에 직접 배치하지 말고 분위기와 갈등 참고용으로만 사용한다.
    실제 브랜드, 실제 로고, 실존 인물, 저작권 캐릭터를 사용하지 않는다.
    이미지 안에 제목, 문장, 말풍선, 워터마크, 로고 텍스트를 넣지 않는다.
    선정적 노출, 과도한 폭력, 미성년자 위험 표현은 피한다.
    표지 이미지는 세로형 커버 구도에 어울리게 구성한다.
    """
).strip()


COUNTRY_COVER_STYLE_PROMPTS = {
    "KR": dedent(
        """
        한국 웹소설 플랫폼 표지에 어울리는 세련된 디지털 일러스트 스타일로 표현한다.
        인물의 매력, 장르적 분위기, 한눈에 들어오는 중심 구도를 강조한다.
        지나치게 복잡한 배경보다 작품의 핵심 정서와 장르성이 즉시 전달되는 화면을 구성한다.
        """
    ).strip(),
    "US": dedent(
        """
        미국/영어권 웹소설 커버에 어울리는 현대 장르소설 표지 스타일로 표현한다.
        현실감 있는 인물 중심 구도, 선명한 실루엣, 영화적인 조명, 강한 감정 전달을 강조한다.
        배경은 복잡하게 만들지 말고, 작품의 분위기와 갈등이 한눈에 느껴지도록 구성한다.
        """
    ).strip(),
    "JP": dedent(
        """
        일본 웹소설/라이트노벨 커버에 어울리는 캐릭터 일러스트 스타일로 표현한다.
        캐릭터의 표정, 감정선, 자세가 분명하게 보이도록 인물 중심 구도를 사용한다.
        깔끔한 선화, 정돈된 배경, 선명하지만 과하지 않은 색감을 사용한다.
        특정 작품이나 작가의 화풍을 직접 모방하지 않고, 범용적인 캐릭터 일러스트 느낌으로 표현한다.
        """
    ).strip(),
    "CN": dedent(
        """
        중국 웹소설 표지에 어울리는 완성도 높은 디지털 일러스트 스타일로 표현한다.
        인물의 존재감, 서사적 긴장감, 성장과 갈등의 분위기를 강조한다.
        극적인 조명, 깊이감 있는 배경, 강한 주인공성을 느낄 수 있는 구도를 사용한다.
        과도하게 장식적이거나 선정적인 표현은 피하고, 세련된 웹소설 표지 느낌으로 구성한다.
        """
    ).strip(),
    "TH": dedent(
        """
        태국 웹픽션/드라마형 커버에 어울리는 감성적인 일러스트 스타일로 표현한다.
        인물의 감정선, 관계의 긴장감, 부드러운 분위기를 강조한다.
        따뜻한 조명, 섬세한 표정, 부드러운 색감, 감정이 전달되는 구도를 사용한다.
        화면 전체를 감성적인 웹픽션 표지처럼 구성한다.
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
