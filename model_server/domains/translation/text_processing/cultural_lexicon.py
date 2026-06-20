from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import PipelineConfig


@dataclass(slots=True)
class CulturalTermMatch:
    id: str
    matched_text: str
    canonical_term: str
    category: list[str]
    core_explanation: str
    annotation_points: list[str]
    source_type: str
    review_status: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CulturalLexicon:
    """Keyword/alias matcher for curated Korean cultural annotation candidates."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.path = config.resolved_cultural_terms_path()
        self.items = self._load_items(self.path)

    @staticmethod
    def _load_items(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Cultural terms dataset must be a JSON list: {path}")
        return [row for row in data if isinstance(row, dict)]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[\W_]+", "", text or "").casefold()

    @classmethod
    def _contains_term(cls, source_text: str, term: str) -> bool:
        normalized_source = cls._normalize(source_text)
        normalized_term = cls._normalize(term)
        return bool(normalized_term and normalized_term in normalized_source)

    def lookup(self, source_text: str) -> list[CulturalTermMatch]:
        matches: list[CulturalTermMatch] = []
        seen_ids: set[str] = set()
        for item in self.items:
            terms = self._candidate_terms(item)
            matched_text = next((term for term in terms if self._contains_term(source_text, term)), "")
            item_id = str(item.get("id") or "").strip()
            if not matched_text or not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            matches.append(
                CulturalTermMatch(
                    id=item_id,
                    matched_text=matched_text,
                    canonical_term=str(item.get("term_ko") or terms[0] or matched_text),
                    category=[str(value) for value in item.get("category", []) if str(value).strip()],
                    core_explanation=str(item.get("core_explanation") or ""),
                    annotation_points=[
                        str(value) for value in item.get("annotation_points", []) if str(value).strip()
                    ],
                    source_type=str(item.get("source_type") or ""),
                    review_status=str(item.get("review_status") or ""),
                    confidence=str(item.get("confidence") or ""),
                )
            )
        return matches

    @staticmethod
    def _candidate_terms(item: dict[str, Any]) -> list[str]:
        terms: list[str] = []
        for key in ("terms", "aliases"):
            values = item.get(key) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                text = str(value).strip()
                if text and text not in terms:
                    terms.append(text)
        term_ko = str(item.get("term_ko") or "").strip()
        if term_ko and term_ko not in terms:
            terms.insert(0, term_ko)
        return terms

    @staticmethod
    def build_context(matches: list[CulturalTermMatch]) -> str:
        if not matches:
            return "[CULTURAL_LEXICON] no Korean cultural annotation candidates matched"

        blocks = ["[CULTURAL_LEXICON] Curated Korean cultural annotation candidates"]
        for index, match in enumerate(matches, start=1):
            points = "; ".join(match.annotation_points) or "-"
            category = ", ".join(match.category) or "-"
            blocks.append(
                "\n".join(
                    [
                        f"{index}. id: {match.id}",
                        f"   matched_text: {match.matched_text}",
                        f"   canonical_term: {match.canonical_term}",
                        f"   category: {category}",
                        f"   core_explanation: {match.core_explanation}",
                        f"   annotation_points: {points}",
                        f"   source_type: {match.source_type}",
                        f"   review_status: {match.review_status}",
                        f"   confidence: {match.confidence}",
                    ]
                )
            )
        return "\n".join(blocks)
