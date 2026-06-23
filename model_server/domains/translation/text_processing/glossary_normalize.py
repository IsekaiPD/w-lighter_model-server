"""glossary 후보(glossaryCandidate)용 결정론적 정규화 헬퍼.

두 종류로 나뉜다 (적용 대상이 다름):
- `canonical_ko_key` : **한국어 source 정규형.** 같은 이름의 표면 변형(공백·조사·NFC 차이)을 하나로
  모은다. dedup 비교키와 저장값 둘 다 이걸로 통일한다 → "비교에서 같다고 본 건 저장도 같게".
- `light_text`       : **외국어 target(및 일반 텍스트)용 경량 위생.** NFC + 앞뒤 공백 제거 + 내부
  연속공백 1칸. 한국어 조사 로직이 안 맞는 외국어 표기(영·중·일·태)에 쓴다.

원칙: 한국어 source는 canonical로 비교=저장 통일(일관·깨끗한 저장값).
"""

from __future__ import annotations

import unicodedata

# 이름 뒤에 흔히 붙는 조사. 긴 것부터 검사하려고 길이순 정렬은 호출부에서 처리.
_KO_NAME_PARTICLES = (
    "으로",
    "에게",
    "한테",
    "부터",
    "까지",
    "에서",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "도",
    "만",
    "로",
    "에",
    "아",
    "야",
)
_KO_NAME_PARTICLES_BY_LEN = tuple(sorted(_KO_NAME_PARTICLES, key=len, reverse=True))


def _strip_one_ko_particle(token: str) -> str:
    """끝 조사 1개만 제거. 과다제거 가드: 남는 본체가 최소 2글자가 되도록 보장.

    예) "철수가"→"철수", "에게"가 붙은 "민수에게"→"민수". 단 "수도"(2글자)는 "도"로 끝나도
    `len > len(particle)+1`이 거짓이라 깎지 않음(2글자 이름/지명 보호).
    """
    for particle in _KO_NAME_PARTICLES_BY_LEN:
        if token.endswith(particle) and len(token) > len(particle) + 1:
            return token[: -len(particle)]
    return token


def canonical_ko_key(text: str) -> str:
    """dedup 비교용 정규 키: NFC + 모든 공백 제거 + 조사 반복 제거.

    멱등(idempotent): 정규형을 다시 넣어도 그대로다.
    """
    s = unicodedata.normalize("NFC", str(text or ""))
    s = "".join(s.split())  # 모든 공백(띄어쓰기) 제거
    prev = None
    while s and s != prev:  # "철수에게는"처럼 조사가 겹쳐 붙은 경우 반복
        prev = s
        s = _strip_one_ko_particle(s)
    return s


def light_text(text: str) -> str:
    """저장값용 경량 정규화: NFC + 앞뒤 trim + 내부 연속공백 1칸.

    언어 불문(한국어/영·중·일·태) 공통으로 안전하다. 조사 제거 같은 언어별 처리는 하지 않는다.
    """
    s = unicodedata.normalize("NFC", str(text or "")).strip()
    return " ".join(s.split())
