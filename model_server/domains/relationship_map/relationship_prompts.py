from textwrap import dedent


SYSTEM_PROMPT = dedent(
    """
    너는 캐릭터 설정집을 읽고 HTML 인물 관계도에 들어갈 요약 데이터를 만드는 분석가다.
    관계도는 캐릭터 설정집에 적힌 정보만 근거로 삼는다.
    반드시 JSON만 반환한다.
    제공된 캐릭터 외 새 인물을 만들지 않는다.
    동일 인물의 별칭/호칭으로 보이는 항목은 중복 노드로 만들지 않는다.
    캐릭터 세부 설정에 없는 직업, 신분, 작위, 공식 직책, 계급은 추측하지 않는다.
    """
).strip()


def character_id(character: dict, index: int) -> str:
    raw_id = character.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        return f"char_{index}"
    raw = str(raw_id).strip()
    return raw if raw.startswith("char_") else f"char_{raw}"


def value(character: dict, key: str) -> str:
    return str(character.get(key) or "").strip()


def format_character_blocks(characters: list[dict]) -> str:
    blocks: list[str] = []
    for index, character in enumerate(characters, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[{index}] id={character_id(character, index)}",
                    f"이름: {value(character, 'char_name')}",
                    f"나이: {value(character, 'age') or '-'}",
                    f"성별: {value(character, 'gender') or '-'}",
                    f"작품 내 역할: {value(character, 'role') or '-'}",
                    f"관계도 표시 라벨: {value(character, 'profile_label') or '-'}",
                    f"관계 요약: {value(character, 'relationships') or '-'}",
                    f"외형: {value(character, 'appearance') or '-'}",
                    f"세부 설정: {value(character, 'detail_setting') or '-'}",
                ]
            )
        )
    return "\n\n".join(blocks)


def build_relation_extract_prompt(*, work_title: str, characters: list[dict], limit: int) -> str:
    return dedent(
        f"""
        [작품명]
        {work_title or '작품'}

        [캐릭터 설정집]
        {format_character_blocks(characters)}

        [반환 JSON 형식]
        {{
          "work_title": "작품명",
          "main_character": "중심 인물 이름",
          "summary": "관계도 상단에 들어갈 2~3문장 요약",
          "characters": [
            {{
              "id": "char_캐릭터ID",
              "name": "캐릭터명",
              "role": "관계도 카드에 표시할 작품 내 역할",
              "profile_label": "입력 캐릭터의 관계도 표시 라벨",
              "description": "관계도 카드용 한 줄 설명",
              "is_main": true,
              "importance": 1
            }}
          ],
          "groups": [
            {{
              "id": "group_001",
              "name": "소속/조직/팀명",
              "group_type": "team",
              "members": ["char_캐릭터ID"],
              "description": "그룹 설명",
              "importance": 1
            }}
          ],
          "relations": [
            {{
              "source": "char_출발캐릭터ID",
              "target": "char_도착캐릭터ID",
              "relation": "관계 라벨",
              "description": "관계 설명",
              "direction": "both",
              "style": "partnership",
              "importance": 1
            }}
          ],
          "warnings": ["추정 또는 제외 사유가 있을 때만 작성"]
        }}

        [기본 규칙]
        - characters는 제공된 캐릭터만 사용하고 최대 {limit}명이다.
        - 캐릭터 id는 반드시 입력에 제공된 char_ID 형식을 유지한다.
        - relations의 source/target은 characters의 id와 정확히 일치해야 한다.
        - 같은 두 캐릭터 사이의 관계는 중복으로 만들지 않는다.
        - A→B와 B→A가 모두 필요해 보이면 두 관계로 나누지 말고 하나의 관계로 합치고 direction=both로 작성한다.
        - 관계 라벨은 짧게, 관계 설명은 1~2문장으로 요약한다.
        - style은 romance, partnership, hierarchy, rivalry, mentorship, family, organization, neutral 중 하나만 사용한다.

        [role 작성 규칙]
        - role은 주인공/조력자/악역처럼 작품 내 기능을 짧게 쓴다.
        - role에 직업, 신분, 작위, 공식 직책, 계급을 억지로 넣지 않는다.

        [profile_label 작성 규칙]
        - profile_label은 관계도 카드 하단 표시용이다.
        - 입력의 "관계도 표시 라벨" 값이 있으면 그대로 사용한다.
        - 입력 라벨이 없을 때만 세부 설정에 명확히 적힌 직업, 신분, 작위, 공식 직책, 계급을 짧게 사용한다.
        - 세부 설정에 없는 정보는 추측해서 만들지 않는다.
        - 소속이나 가문 이름만 보고 소속 내 위치를 임의로 만들지 않는다.
        - "친구", "연인", "가족", "조력자", "악역"처럼 관계나 작품 내 역할을 profile_label로 쓰지 않는다.
        - "-", "기타", "인물", "등장인물", "주요 인물", "미상", "없음"은 사용하지 않는다.
        - 명확히 쓸 수 없으면 profile_label은 빈 문자열로 둔다.

        [direction 작성 규칙]
        - direction은 both 또는 one_way 중 하나만 사용한다.
        - direction은 관계의 "존재 여부"가 아니라 "행동/감정/권력의 방향"을 기준으로 판단한다.
        - one_way는 source가 target에게 일방적으로 행동하거나 영향을 주는 관계다.
          예: source가 target을 이용한다, 감시한다, 협박한다, 조종한다, 명령한다, 추적한다, 속인다, 배신한다, 짝사랑한다, 제물로 삼는다, 장기말로 쓴다.
        - both는 source와 target이 서로 주고받는 관계일 때만 사용한다.
          예: 서로 협력한다, 서로 대립한다, 서로 신뢰한다, 서로 거래한다, 서로 경쟁한다, 가족 관계가 서로의 감정/갈등으로 이어진다.
        - "A가 B를 이용한다/감시한다/협박한다/조종한다"처럼 한쪽의 행동만 확인되면 반드시 source=A, target=B, direction=one_way로 작성한다.
        - "A와 B가 서로 협력한다/대립한다/신뢰한다"처럼 상호 작용이 확인될 때만 direction=both로 작성한다.
        - 단순히 두 인물이 같은 문장에 함께 나온다는 이유로 both를 쓰지 않는다.
        """
    ).strip()
