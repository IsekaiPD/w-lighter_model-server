"""HTML helpers for guide modules."""

from html import escape
from typing import Any


def esc(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


__all__ = ["esc"]
