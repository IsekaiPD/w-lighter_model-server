"""Character extract 도메인 서비스 (스텁).

TODO: 원문 → 등장인물 추출(LLM). 엔진 일부(character_extract.py, character_prompts.py) 복사됨.
통합초안 docs/이미지기능_추출설계_인계.md 참고(인물·관계 추출 설계).
"""
from __future__ import annotations


def status() -> dict:
    return {"domain": "character_extract", "status": "scaffold", "todo": "인물 추출 배선 (엔진 미완)"}
