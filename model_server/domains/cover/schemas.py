"""Cover 도메인 스키마 (스텁). TODO."""
from __future__ import annotations

from pydantic import BaseModel


class CoverPromptRequest(BaseModel):
    model_config = {"extra": "allow"}
