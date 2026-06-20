"""Character extract 스키마 (스텁). TODO."""
from __future__ import annotations

from pydantic import BaseModel


class CharacterExtractRequest(BaseModel):
    model_config = {"extra": "allow"}
