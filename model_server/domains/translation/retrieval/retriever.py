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
    # KURE 등 로컬 임베딩 모델은 로딩(메모리 적재)이 무거우므로 프로세스당 1회만 만든다.
    # 같은 모델명 요청은 이 캐시된 인스턴스(=encoder)를 재사용해 매 요청 재로딩을 막는다.
    return SentenceTransformerEmbeddingBackend(model)


def create_embedding_backend(config: PipelineConfig) -> EmbeddingBackend:
    if config.mock:
        return MockEmbeddingBackend()
    if config.embedding_model.startswith("text-embedding-"):
        return OpenAIEmbeddingBackend(config.embedding_model)
    # 모델명이 같으면 캐시된 백엔드(로딩 완료된 encoder)를 재사용한다.
    return _cached_st_backend(config.embedding_model)


# qdrant 클라이언트는 경로(또는 서버)당 1개만 만들어 공유한다.
# - 로컬 임베디드 모드: 같은 폴더를 여러 클라이언트가 열면 락 충돌이 나므로 공유 필수.
# - 서버 모드(도커): 같은 서버에 연결을 중복 생성할 필요가 없으므로 공유가 정석.
# 두 retriever(IdiomRetriever, AnnotationRetriever)가 각자 호출해도
# 같은 인스턴스를 받도록 모듈 레벨에서 캐시한다.
_QDRANT_CLIENT_CACHE: dict[str, Any] = {}


def make_qdrant_client(config: PipelineConfig):
    """qdrant 클라이언트(공유 인스턴스)를 반환한다. 현재는 로컬 임베디드 모드.

    TODO(도커 전환): 서버로 올릴 때는 아래 path= 한 줄을 url= 방식으로 교체.
        client = QdrantClient(url="http://localhost:6333")
      - 코드 변경은 이 한 줄뿐이지만, qdrant_local 컬렉션을 서버에 재적재하는
        작업은 별도로 필요하다.
      - 서버 전환이 끝나면, 아래 cache_key를 url 기준으로 바꾸면 된다.

    TODO(mock 구조 정리): config.mock=True 일 때 타는 레거시 JSON 경로
      (_load_items / _load_or_create_index 등)는 단위 테스트가 qdrant 없이
      돌도록 남겨둔 구조다. 도커 서버가 표준이 되어 테스트도 서버(또는 테스트용
      컬렉션)를 쓰게 되면 이 JSON 경로를 제거할 수 있다.
    """
    from qdrant_client import QdrantClient

    cache_key = str(config.resolved_qdrant_path())  # 도커 전환 시 url 문자열로 교체
    client = _QDRANT_CLIENT_CACHE.get(cache_key)
    if client is None:
        client = QdrantClient(path=cache_key)
        _QDRANT_CLIENT_CACHE[cache_key] = client
    return client


class ChunkingMixin:
    """쿼리 청킹 공통 로직. idiom/annotation retriever가 공유한다.

    config.chunk_strategy = "paragraph"(기본) | "sentence" 로 전략을 고른다.
    이전에는 idiom_retriever 안에만 있었으나, 두 검색이 동일 메커니즘을 쓰게 되어
    공통 토대(base)로 올렸다.
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
    """쿼리를 청킹하고 KURE로 임베딩한다. (chunks, vectors) 를 돌려준다.

    pipeline이 이 함수를 1회 호출해 두 검색(idiom/annotation)에 같은
    (chunks, vectors)를 넘기면, KURE 추론을 1회로 줄일 수 있다.
    backend/chunk_fn 을 인자로 받아 base가 특정 retriever에 의존하지 않게 한다.
    """
    chunks = chunk_fn(query)
    vectors = backend.embed(chunks)
    return chunks, vectors


# 하위 호환: 기존 `from .retriever import IdiomRetriever` 를 깨지 않기 위해 재노출.
# (IdiomRetriever 본체는 idiom_retriever.py 로 분리됨)
from .idiom_retriever import IdiomRetriever  # noqa: E402,F401
