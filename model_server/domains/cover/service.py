"""Cover 도메인 서비스 (스텁).

TODO: 표지 프롬프트/생성. 엔진 일부(cover_generate.py, cover_prompts.py) 복사돼 있음.
기존 api_server.py의 /api/cover-prompt, /api/generate-cover-image + backend cover_plan_service/image_service 참고.
"""
from __future__ import annotations


def status() -> dict:
    return {"domain": "cover", "status": "scaffold", "todo": "cover prompt/generate 배선 (엔진 미완)"}
