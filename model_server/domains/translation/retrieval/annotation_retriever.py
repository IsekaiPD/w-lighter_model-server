from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import PipelineConfig
from .retriever import ChunkingMixin, create_embedding_backend, l2_normalize, make_qdrant_client


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def build_annotation_search_text(item: dict[str, Any]) -> str:
    value = item.get("embedding_text")
    if isinstance(value, str) and value.strip():
        return value.strip()

    # Backward-compatible fallback for older annotation card shapes.
    chunks: list[str] = []
    for field in ("semantic_keywords", "cultural_explanation", "scenario", "when_to_annotate"):
        legacy_value = item.get(field)
        if isinstance(legacy_value, list):
            cleaned = _clean_list(legacy_value)
            if cleaned:
                chunks.append(f"{field}: {' | '.join(cleaned)}")
        elif isinstance(legacy_value, str) and legacy_value.strip():
            chunks.append(f"{field}: {legacy_value.strip()}")
    return "\n".join(chunks)


@dataclass(slots=True)
class AnnotationResult:
    item: dict[str, Any]
    score: float
    similarity_score: float
    trigger_boost: float
    final_score: float


class AnnotationRetriever(ChunkingMixin):
    """Retriever for Korean cultural annotation/note candidates.

    Unlike the translation RAG retriever, this does not recommend target-language
    equivalents; it retrieves source-side cultural context that may deserve an
    annotation depending on the target reader and source context.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.backend = create_embedding_backend(config)
        self._use_qdrant = not config.mock  # mock=테스트(JSON+가짜임베딩), 아니면 qdrant+KURE
        if self._use_qdrant:
            self._client = make_qdrant_client(config)
            self._collection = config.resolved_annotation_collection()
            return
        # ---- 레거시 JSON + numpy 경로 (mock=True 테스트 전용) ----
        self.dataset_path = config.resolved_annotation_dataset_path()
        self.cache_dir = config.resolved_embedding_cache_dir()
        self.items = self._load_items(self.dataset_path)
        self.search_texts = [build_annotation_search_text(item) for item in self.items]
        self.matrix = self._load_or_create_index()

    @staticmethod
    def _load_items(dataset_path: Path) -> list[dict[str, Any]]:
        if not dataset_path.exists():
            return []
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Annotation RAG dataset must be a JSON list: {dataset_path}")
        return [row for row in data if isinstance(row, dict)]

    def _cache_paths(self) -> tuple[Path, Path]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(
            f"{self.dataset_path.resolve()}::{self.config.embedding_model}::annotation-rag-v1".encode("utf-8")
        ).hexdigest()[:16]
        return self.cache_dir / f"{cache_key}.npy", self.cache_dir / f"{cache_key}.meta.json"

    def _load_or_create_index(self) -> np.ndarray:
        if not self.items:
            return np.zeros((0, 1), dtype=np.float32)
        if self.config.mock:
            return self.backend.embed(self.search_texts)

        matrix_path, meta_path = self._cache_paths()
        current_meta = {
            "dataset_path": str(self.dataset_path.resolve()),
            "dataset_mtime_ns": self.dataset_path.stat().st_mtime_ns,
            "embedding_model": self.config.embedding_model,
            "record_count": len(self.items),
            "search_strategy": "annotation-rag-v1",
        }
        if matrix_path.exists() and meta_path.exists():
            cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if cached_meta == current_meta:
                return np.load(matrix_path)

        matrix = self.backend.embed(self.search_texts)
        np.save(matrix_path, matrix)
        meta_path.write_text(json.dumps(current_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return matrix

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        return re.sub(r"[\W_]+", "", text).casefold()

    @classmethod
    def _trigger_match_boost(cls, item: dict[str, Any], query: str) -> float:
        """Deprecated compatibility hook — always 0.0.

        Ranking relies on embedding_text similarity only; returning 0.0 avoids
        hidden lexical boosts while keeping older callers working.
        """
        return 0.0

    def retrieve(self, query: str, top_k: int | None = None,
                 return_k: int | None = None) -> list[AnnotationResult]:
        """쿼리 문자열을 청킹+임베딩 후 검색한다. (하위호환용 단독 진입점)

        top_k    : 청크 1개당 가져올 후보 수. 기본 config.annotation_top_k
        return_k : 통합 후 최종 반환 상한. 기본 config.annotation_return_k
        청킹 전략은 config.chunk_strategy를 따른다.
        """
        chunks = self._chunk_query(query)
        chunk_vectors = self.backend.embed(chunks)
        return self.search(chunks, chunk_vectors, top_k, return_k)

    def search(self, chunks, chunk_vectors, top_k: int | None = None,
               return_k: int | None = None) -> list[AnnotationResult]:
        """미리 만들어진 (chunks, vectors)로 검색만 수행한다. (임베딩 공유 경로)"""
        top_k = top_k if top_k is not None else self.config.annotation_top_k
        return_k = return_k if return_k is not None else self.config.annotation_return_k
        if self._use_qdrant:
            return self._retrieve_qdrant(chunk_vectors, top_k, return_k)
        if not self.items:
            return []
        # ---- 레거시 JSON 경로: 청크별 best 점수 취합 ----
        n = len(self.items)
        best = np.full(n, -np.inf, dtype=np.float32)
        for query_vec in chunk_vectors:
            if self.matrix.shape[1] != query_vec.shape[0]:
                query_vec = l2_normalize(query_vec.reshape(1, -1))[0]
            sim = self.matrix @ query_vec
            best = np.maximum(best, sim)
        top_indices = np.argsort(best)[::-1][:return_k]
        results: list[AnnotationResult] = []
        for index in top_indices:
            if best[index] < self.config.annotation_score_threshold:
                break
            results.append(
                AnnotationResult(
                    item=self.items[index],
                    score=float(best[index]),
                    similarity_score=float(best[index]),
                    trigger_boost=0.0,
                    final_score=float(best[index]),
                )
            )
        return results

    def _retrieve_qdrant(self, chunk_vectors, top_k: int, return_k: int) -> list[AnnotationResult]:
        """kculture 컬렉션에서 청크별로 검색하고 payload 단위 best 점수만 취합."""
        best: dict[str, tuple[float, dict]] = {}
        for query_vec in chunk_vectors:
            hits = self._client.query_points(
                collection_name=self._collection,
                query=query_vec.tolist(),
                limit=top_k,
                with_payload=True,
                score_threshold=self.config.annotation_score_threshold,
            ).points
            for h in hits:
                payload = dict(h.payload or {})
                key = str(payload.get("source_id") or h.id)
                if key not in best or h.score > best[key][0]:
                    best[key] = (float(h.score), payload)
        ranked = sorted(best.values(), key=lambda x: x[0], reverse=True)[:return_k]
        results: list[AnnotationResult] = []
        for score, payload in ranked:
            results.append(
                AnnotationResult(
                    item=payload,
                    score=score,
                    similarity_score=score,
                    trigger_boost=0.0,
                    final_score=score,
                )
            )
        return results

    @staticmethod
    def build_context(results: list[AnnotationResult]) -> str:
        if not results:
            return "[ANNOTATION_RAG] no cultural annotation candidates matched"

        blocks = ["[ANNOTATION_RAG] Korean cultural annotation candidates"]
        for index, result in enumerate(results, start=1):
            item = result.item
            # LLM 에 넘길 정보만 선별: keyword 와 context(주석설명+번역가이드) 만.
            # (id, category, culture_type, 검색 점수는 분류 메타/노이즈라 제외)
            blocks.append(
                "\n".join(
                    [
                        f"{index}. keyword: {item.get('keyword_ko', '')}",
                        f"   context: {item.get('context_text', '')}",
                    ]
                )
            )
        return "\n".join(blocks)
