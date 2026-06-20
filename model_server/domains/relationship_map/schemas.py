"""Relationship map 스키마 (스텁). TODO."""
from __future__ import annotations

from pydantic import BaseModel


class RelationPromptRequest(BaseModel):
    model_config = {"extra": "allow"}
