from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np

from ..config import PipelineConfig
from ..infra.openai_client import get_openai_client


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def build_search_text(item: dict[str, Any]) -> str:
    embedding_text = item.get("embedding_text")
    if isinstance(embedding_text, str) and embedding_text.strip():
        return embedding_text.strip()

    chunks: list[str] = []

    for field in ("ko_anchor_expression", "ko_expression"):
        values = item.get(field) or []
        if isinstance(values, list):
            cleaned = [str(value).strip() for value in values if str(value).strip()]
            if cleaned:
                chunks.append(f"{field}: {' | '.join(cleaned)}")

    if not chunks:
        value = item.get("meaning")
        if isinstance(value, str) and value.strip():
            chunks.append(f"meaning: {value.strip()}")

    return "\n".join(chunks)


@dataclass(slots=True)
class RetrievalResult:
    item: dict[str, Any]
    score: float
    similarity_score: float
    anchor_boost: float
    final_score: float


class EmbeddingBackend(Protocol):
    def embed(self, texts: Iterable[str]) -> np.ndarray: ...


class MockEmbeddingBackend:
    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def embed(self, texts: Iterable[str]) -> np.ndarray:
        rows = [self._embed_text(text) for text in texts]
        return l2_normalize(np.vstack(rows).astype(np.float32))

    def _embed_text(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        compact = (text or "").strip()
        if not compact:
            return vector
        grams = [compact[index:index + 3] for index in range(max(1, len(compact) - 2))]
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        return vector


class OpenAIEmbeddingBackend:
    def __init__(self, model: str, batch_size: int = 64):
        self.model = model
        self.batch_size = batch_size

    def embed(self, texts: Iterable[str]) -> np.ndarray:
        client = get_openai_client()
        vectors: list[list[float]] = []
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= self.batch_size:
                vectors.extend(self._embed_batch(client, batch))
                batch = []
        if batch:
            vectors.extend(self._embed_batch(client, batch))
        return l2_normalize(np.array(vectors, dtype=np.float32))

    def _embed_batch(self, client, batch: list[str]) -> list[list[float]]:
        response = client.embeddings.create(model=self.model, input=batch)
        return [row.embedding for row in response.data]


class SentenceTransformerEmbeddingBackend:
    """Local Hugging Face sentence-transformers backend for KURE-style models."""

    def __init__(self, model: str, batch_size: int = 64):
        self.model = model
        self.batch_size = batch_size
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised only without optional dependency in live mode.
            raise RuntimeError(
                "KURE embedding requires the optional 'sentence-transformers' package. "
                "Install project requirements before running live retrieval."
            ) from exc
        self.encoder = SentenceTransformer(model)

    def embed(self, texts: Iterable[str]) -> np.ndarray:
        rows = list(texts)
        if not rows:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = self.encoder.encode(
            rows,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


@lru_cache(maxsize=None)
def _cached_st_backend(model: str) -> "SentenceTransformerEmbeddingBackend":
    # 로컬 임베딩 모델은 로딩이 무거우므로 프로세스당 1회만 만들어 재사용한다.
    return SentenceTransformerEmbeddingBackend(model)


def create_embedding_backend(config: PipelineConfig) -> EmbeddingBackend:
    if config.mock:
        return MockEmbeddingBackend()
    if config.embedding_model.startswith("text-embedding-"):
        return OpenAIEmbeddingBackend(config.embedding_model)
    return _cached_st_backend(config.embedding_model)


# qdrant 클라이언트는 경로(또는 서버)당 1개만 만들어 공유한다.
# 임베디드 모드에서 같은 폴더를 여러 클라이언트가 열면 락 충돌이 나므로 공유가 필수.
_QDRANT_CLIENT_CACHE: dict[str, Any] = {}


def make_qdrant_client(config: PipelineConfig):
    """qdrant 클라이언트(공유 인스턴스)를 반환한다.

    config.qdrant_url(=env QDRANT_URL)이 있으면 서버 모드(url=, self-host 컨테이너),
    비면 임베디드 모드(path=, 로컬 폴더) 폴백 — 단위 테스트/오프라인 부팅용.
    cache_key를 url/path로 구분해 같은 대상엔 클라이언트 1개만 공유한다.

    TODO(mock 구조 정리): config.mock=True 일 때 타는 레거시 JSON 경로는 단위
      테스트가 qdrant 없이 돌도록 남겨둔 구조다. 테스트가 서버를 쓰게 되면 제거 가능.
    """
    from qdrant_client import QdrantClient

    url = (config.qdrant_url or "").strip()
    if url:
        cache_key = f"url::{url}"
        client = _QDRANT_CLIENT_CACHE.get(cache_key)
        if client is None:
            client = QdrantClient(url=url)
            _QDRANT_CLIENT_CACHE[cache_key] = client
        return client

    cache_key = f"path::{config.resolved_qdrant_path()}"
    client = _QDRANT_CLIENT_CACHE.get(cache_key)
    if client is None:
        client = QdrantClient(path=str(config.resolved_qdrant_path()))
        _QDRANT_CLIENT_CACHE[cache_key] = client
    return client


class ChunkingMixin:
    """쿼리 청킹 공통 로직. idiom/annotation retriever가 공유한다.

    config.chunk_strategy = "paragraph"(기본) | "sentence" 로 전략을 고른다.
    """

    # Kiwi 인스턴스는 생성 비용이 크므로 클래스 단위로 1회만 만들어 재사용한다.
    _kiwi_instance = None

    @staticmethod
    def _split_into_chunks(text: str, max_chars: int = 300, min_chars: int = 10) -> list[str]:
        """[paragraph 전략] 줄바꿈(\n) 기준으로 묶는다."""
        if len(text) <= max_chars:
            return [text]
        lines = [line.strip() for line in text.split("\n") if len(line.strip()) >= min_chars]
        if not lines:
            return [text]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if current_len + len(line) > max_chars and current:
                chunks.append(" ".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line)
        if current:
            chunks.append(" ".join(current))
        return chunks or [text]

    @classmethod
    def _get_kiwi(cls, kiwi_cls):
        if ChunkingMixin._kiwi_instance is None:
            ChunkingMixin._kiwi_instance = kiwi_cls()
        return ChunkingMixin._kiwi_instance

    @classmethod
    def _split_into_sentences(cls, text: str) -> list[str]:
        """[sentence 전략] Kiwi(kiwipiepy)로 문장 단위 분리. 미설치 시 paragraph 폴백."""
        try:
            from kiwipiepy import Kiwi
        except ImportError:
            return cls._split_into_chunks(text)
        kiwi = cls._get_kiwi(Kiwi)
        sentences = [s.text.strip() for s in kiwi.split_into_sents(text) if s.text.strip()]
        if not sentences:
            return cls._split_into_chunks(text)
        return sentences

    def _chunk_query(self, query: str) -> list[str]:
        """config.chunk_strategy 에 따라 청킹 방식을 선택한다."""
        strategy = getattr(self.config, "chunk_strategy", "paragraph")
        if strategy == "sentence":
            return self._split_into_sentences(query)
        return self._split_into_chunks(query)


def embed_query(backend: EmbeddingBackend, chunk_fn, query: str):
    """쿼리를 청킹하고 임베딩한다. (chunks, vectors) 를 돌려준다.

    두 검색(idiom/annotation)에 같은 (chunks, vectors)를 넘겨 임베딩 추론을 1회로 줄인다.
    """
    chunks = chunk_fn(query)
    vectors = backend.embed(chunks)
    return chunks, vectors


# 하위 호환: `from .retriever import IdiomRetriever` 를 깨지 않기 위해 재노출.
from .idiom_retriever import IdiomRetriever  # noqa: E402,F401
