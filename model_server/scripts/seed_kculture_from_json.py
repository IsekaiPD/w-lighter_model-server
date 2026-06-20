r"""kculture RAG JSON -> qdrant 컬렉션 시드 (재임베딩).

정본 JSON(kculture_rag_documents_reviewed.json)을 읽어 KURE-v1로 임베딩하고
qdrant `kculture` 컬렉션에 적재한다. 런타임 retriever와 동일한 임베딩 백엔드
(create_embedding_backend)·검색텍스트(build_annotation_search_text)를 재사용하므로
쿼리 시점 벡터와 정합이 보장된다.

payload는 라이브 쿼리 계약에 맞춰 평탄화한다:
  - source_id   : _retrieve_qdrant 의 dedup 키 (JSON의 id)
  - keyword_ko  : build_context 가 최상위에서 읽음 (JSON에선 metadata 안에 중첩 -> 끌어올림)
  - context_text: build_context 가 최상위에서 읽음

실행(앱 컨테이너 안 권장 — KURE 캐시·deps 재사용):
    docker compose exec app python scripts/seed_kculture_from_json.py
호스트(.venv)에서 돌릴 땐 QDRANT_URL=http://localhost:6333 로.

env:
    QDRANT_URL          대상 서버 (기본 http://qdrant:6333 = 컨테이너 내부 DNS)
    KCULTURE_JSON       소스 JSON (기본 domains/translation/data/annotation_rag/kculture_rag_documents_reviewed.json)
    KCULTURE_COLLECTION 컬렉션명 (기본 kculture)
"""
from __future__ import annotations

import json
import os
import sys
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# scripts/ 에서 직접 실행해도 앱 루트(domains 패키지)를 import 가능하게.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from domains.translation.config import PipelineConfig
from domains.translation.retrieval.annotation_retriever import build_annotation_search_text
from domains.translation.retrieval.retriever import create_embedding_backend

# source_id -> 안정적(idempotent) 포인트 id 변환용 고정 네임스페이스.
_NAMESPACE = uuid.UUID("6f9b2d44-3c2a-4e7a-9b1e-0a5c7d8e1f20")
BATCH = 256


def main() -> int:
    json_path = os.environ.get(
        "KCULTURE_JSON",
        "domains/translation/data/annotation_rag/kculture_rag_documents_reviewed.json",
    )
    url = os.environ.get("QDRANT_URL", "http://qdrant:6333")
    collection = os.environ.get("KCULTURE_COLLECTION", "kculture")

    if not os.path.exists(json_path):
        print(f"ERROR: JSON 없음: {json_path}", file=sys.stderr)
        return 2

    with open(json_path, encoding="utf-8") as f:
        data = [row for row in json.load(f) if isinstance(row, dict)]
    print(f"source records: {len(data)}  ({json_path})")

    # 런타임과 동일한 KURE 백엔드(mock=False 기본). embedding_text 우선 검색텍스트.
    config = PipelineConfig(locale="ko_ja")
    backend = create_embedding_backend(config)
    print(f"embedding model: {config.embedding_model}")

    texts = [build_annotation_search_text(item) for item in data]
    vectors = backend.embed(texts)  # L2 정규화된 ndarray
    dim = int(vectors.shape[1])
    print(f"embedded: {vectors.shape[0]} x {dim}")

    client = QdrantClient(url=url)
    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.create_collection(collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    points: list[PointStruct] = []
    for item, vec in zip(data, vectors):
        md = item.get("metadata") or {}
        source_id = item.get("id") or md.get("culture_id")
        payload = {
            "source_id": source_id,
            "embedding_text": item.get("embedding_text"),
            "context_text": item.get("context_text"),
            "keyword_ko": md.get("keyword_ko"),       # metadata -> 최상위 평탄화
            "category": md.get("category"),
            "culture_type_ko": md.get("culture_type_ko"),
            "culture_id": md.get("culture_id"),
        }
        pid = str(uuid.uuid5(_NAMESPACE, str(source_id)))
        points.append(PointStruct(id=pid, vector=vec.tolist(), payload=payload))

    for i in range(0, len(points), BATCH):
        client.upsert(collection, points=points[i : i + BATCH])
        print(f"upserted {min(i + BATCH, len(points))}/{len(points)} ...")

    final = client.get_collection(collection).points_count
    print(f"DONE - {collection} points={final}")
    return 0 if final == len(data) else 1


if __name__ == "__main__":
    raise SystemExit(main())
