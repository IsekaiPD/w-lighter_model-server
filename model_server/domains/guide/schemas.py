"""Guide 도메인 스키마 (스텁). TODO: /api/guide 요청/응답 Pydantic."""
from __future__ import annotations

from pydantic import BaseModel


class GuideRequest(BaseModel):
    model_config = {"extra": "allow"}
    # TODO: title/genre/synopsis/targetCountry 등
