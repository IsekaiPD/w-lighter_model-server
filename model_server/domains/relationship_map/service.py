"""Relationship map 도메인 서비스 (스텁).

TODO: 인물 관계도 추출/생성. 엔진 일부(relationship_generate.py, relationship_html.py,
relationship_prompts.py) 복사돼 있음. 기존 /api/relation-prompt, /api/generate-relation-image 참고.
"""
from __future__ import annotations


def status() -> dict:
    return {"domain": "relationship_map", "status": "scaffold", "todo": "relation prompt/generate 배선 (엔진 미완)"}
