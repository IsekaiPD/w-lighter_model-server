from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from ..config import PipelineConfig
from .retriever import (
    ChunkingMixin,
    EmbeddingBackend,
    RetrievalResult,
    build_search_text,
    create_embedding_backend,
    l2_normalize,
    make_qdrant_client,
)

_ANCHOR_SPLIT_RE = re.compile(r"[,\u3001，/·|]+")
_ANCHOR_MIN_LENGTH = 3
_ANCHOR_MAX_LENGTH = 24
_ANCHOR_EXPLANATION_MARKERS = (
    "남의 일",
    "관계나 일",
    "의미",
    "상황",
    "맥락",
    "표현",
    "설명",
    "때 참고",
    "의 뜻",
)


def normalize_anchor_key(anchor: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", (anchor or "")).casefold()


_MATCH_TYPE_SCORE = {"partial": 0.9, "normalized": 0.95, "exact": 1.0}
_MATCH_TYPE_CONFIDENCE = {"partial": "low", "normalized": "high", "exact": "high"}
_MATCH_TYPE_PRIORITY = {"partial": 0, "normalized": 1, "exact": 2}
_MERGED_MATCH_TYPE_PRIORITY = {"semantic": 0, "partial": 1, "normalized": 2, "exact": 3}
_SEMANTIC_ONLY_SCORE_FLOOR = 0.25
_PARTICLE_STRIP_RE = re.compile(r"[을를이가은는]")
_NORMALIZED_MATCH_ENDINGS = ("고", "는", "지", "았다", "었다", "게", "도록", "면", "니", "려", "으려", "은", "는지", "친", "린", "으십쇼")


def _clean_anchor_candidate(value: Any) -> str:
    return str(value or "").strip().strip("。．. ")


def _looks_like_explanation(text: str) -> bool:
    lowered = text.casefold()
    if len(text) > _ANCHOR_MAX_LENGTH:
        return True
    return any(marker in lowered for marker in _ANCHOR_EXPLANATION_MARKERS)


def _split_anchor_candidates(text: str) -> list[str]:
    return [_clean_anchor_candidate(part) for part in _ANCHOR_SPLIT_RE.split(text) if _clean_anchor_candidate(part)]


def _extract_embedding_anchor_region(embedding_text: str) -> str:
    text = (embedding_text or "").strip()
    if not text:
        return ""
    match = re.search(r"[.。．]", text)
    return text[: match.start()] if match else text


def _extract_context_anchor_region(context_text: str) -> str:
    text = (context_text or "").strip()
    if not text:
        return ""
    match = re.search(r"한국어 기준 표현\s*:\s*(.+)", text)
    return match.group(1).strip() if match else ""


def _resolve_source_id(payload: dict[str, Any], fallback: str | None = None) -> str:
    source_id = payload.get("source_id") or payload.get("id")
    if source_id:
        return str(source_id)
    if fallback:
        return fallback
    return "unknown-source"


def _anchor_head_from_text(text: str) -> str:
    region = _extract_embedding_anchor_region(text)
    candidates = _split_anchor_candidates(region)
    return candidates[0] if candidates else region.strip()


def _representative_anchor_from_payload(payload: dict[str, Any], anchor: str = "") -> str:
    if anchor and anchor.strip():
        return anchor.strip()
    anchors = extract_anchor_phrases(payload)
    if anchors:
        return anchors[0]
    embedding_text = payload.get("embedding_text")
    if isinstance(embedding_text, str) and embedding_text.strip():
        return _anchor_head_from_text(embedding_text)
    return ""


def extract_anchor_phrases(payload: dict[str, Any]) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()

    embedding_text = payload.get("embedding_text")
    if isinstance(embedding_text, str) and embedding_text.strip():
        for candidate in _split_anchor_candidates(_extract_embedding_anchor_region(embedding_text)):
            if len(candidate) < _ANCHOR_MIN_LENGTH or _looks_like_explanation(candidate):
                continue
            key = normalize_anchor_key(candidate)
            if key and key not in seen:
                seen.add(key)
                anchors.append(candidate)

    context_text = payload.get("context_text")
    if isinstance(context_text, str) and context_text.strip():
        context_region = _extract_context_anchor_region(context_text)
        for candidate in _split_anchor_candidates(context_region):
            if len(candidate) < _ANCHOR_MIN_LENGTH or _looks_like_explanation(candidate):
                continue
            key = normalize_anchor_key(candidate)
            if key and key not in seen:
                seen.add(key)
                anchors.append(candidate)

    return anchors


def build_anchor_index(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    anchor_index: dict[str, list[dict[str, Any]]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for fallback_index, payload in enumerate(items):
        if not isinstance(payload, dict):
            continue
        source_id = _resolve_source_id(payload, fallback=f"fallback-{fallback_index}")
        anchors = extract_anchor_phrases(payload)
        for anchor in anchors:
            anchor_key = normalize_anchor_key(anchor)
            pair_key = (source_id, anchor_key)
            if not anchor_key or pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            anchor_index.setdefault(anchor, []).append(
                {
                    "source_id": source_id,
                    "embedding_text": payload.get("embedding_text", ""),
                    "context_text": payload.get("context_text", ""),
                    "payload": payload,
                }
            )

    return anchor_index



def _anchor_base_form(anchor: str) -> str:
    compact = (anchor or "").strip()
    if compact.endswith("다"):
        return compact[:-1].strip()
    return compact



def _compact_match_text(text: str) -> str:
    return normalize_anchor_key(text)



def _strip_common_particles(text: str) -> str:
    return _PARTICLE_STRIP_RE.sub("", _compact_match_text(text))



def _build_normalized_anchor_pattern(anchor: str) -> re.Pattern[str] | None:
    base = _anchor_base_form(anchor)
    if not base:
        return None
    escaped = re.escape(base).replace(r"\ ", r"\s*")
    suffix = "(?:" + "|".join(re.escape(value) for value in _NORMALIZED_MATCH_ENDINGS) + ")"
    variants = [rf"{escaped}{suffix}"]

    if base.endswith("치"):
        ch_variant = re.escape((base[:-1] + "친")).replace(r"\ ", r"\s*")
        variants.append(rf"{ch_variant}(?!\w)")
    if base.endswith("리"):
        ri_variant = re.escape((base[:-1] + "린")).replace(r"\ ", r"\s*")
        variants.append(rf"{ri_variant}(?!\w)")

    pattern = "|".join(variants)
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)")



def _match_anchor_to_chunk(anchor: str, chunk: str) -> tuple[str, str] | None:
    anchor = (anchor or "").strip()
    chunk = (chunk or "")
    if not anchor or not chunk.strip():
        return None

    anchor_compact = _compact_match_text(anchor)
    chunk_compact = _compact_match_text(chunk)
    if anchor_compact and anchor_compact in chunk_compact:
        return ("exact", anchor)

    pattern = _build_normalized_anchor_pattern(anchor)
    if pattern is not None:
        matched = pattern.search(chunk)
        if matched:
            return ("normalized", matched.group(0))

    partial_anchor = _strip_common_particles(_anchor_base_form(anchor))
    partial_chunk = _strip_common_particles(chunk)
    if partial_anchor and partial_anchor in partial_chunk:
        return ("partial", anchor)

    return None


class IdiomRetriever(ChunkingMixin):
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.backend: EmbeddingBackend = create_embedding_backend(config)
        self.dataset_path = config.resolved_rag_dataset_path()
        self.augmentation_paths = tuple(config.resolved_idiom_augmentation_paths())
        self.cache_dir = config.resolved_embedding_cache_dir()
        base_items = self._load_items(self.dataset_path)
        augmentation_groups = [self._load_items(path) for path in self.augmentation_paths]
        self.items = self._merge_items(base_items, *augmentation_groups)
        self.search_texts = [build_search_text(item) for item in self.items]
        self.anchor_index = build_anchor_index(self.items)
        # qdrant 백엔드: 쿼리 임베딩만 필요하고, 벡터/문서는 qdrant가 보관한다.
        self._use_qdrant = not config.mock  # mock=테스트(JSON+가짜임베딩), 아니면 qdrant+KURE
        if self._use_qdrant:
            self._client = make_qdrant_client(config)
            self._collection = config.resolved_idiom_collection()
            return
        # ---- 레거시 JSON + numpy 경로 (mock=True 테스트 전용) ----
        self.matrix = self._load_or_create_index()

    @staticmethod
    def _load_items(dataset_path: Path) -> list[dict[str, Any]]:
        if not dataset_path.exists():
            raise FileNotFoundError(f"RAG dataset not found: {dataset_path}")
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"RAG dataset must be a JSON list: {dataset_path}")
        return data

    @staticmethod
    def _merge_items(*item_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for group in item_groups:
            for index, item in enumerate(group):
                if not isinstance(item, dict):
                    continue
                source_id = _resolve_source_id(item, fallback=f"fallback-{len(merged)}-{index}")
                if source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)
                merged.append(item)
        return merged

    def _cache_paths(self) -> tuple[Path, Path]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        augmentation_fingerprint_parts = [
            f"{path.resolve()}::{path.stat().st_mtime_ns}"
            for path in self.augmentation_paths
            if path.exists()
        ]
        augmentation_fingerprint = "||".join(augmentation_fingerprint_parts) if augmentation_fingerprint_parts else "none"
        cache_key = hashlib.sha256(
            f"{self.dataset_path.resolve()}::{self.dataset_path.stat().st_mtime_ns}::{augmentation_fingerprint}::{self.config.embedding_model}::{self.config.locale}::anchor-first-v1".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        return (
            self.cache_dir / f"{cache_key}.npy",
            self.cache_dir / f"{cache_key}.meta.json",
        )

    def _load_or_create_index(self) -> np.ndarray:
        if self.config.mock:
            return self.backend.embed(self.search_texts)

        matrix_path, meta_path = self._cache_paths()
        current_meta = {
            "dataset_path": str(self.dataset_path.resolve()),
            "dataset_mtime_ns": self.dataset_path.stat().st_mtime_ns,
            "augmentation_paths": [
                {
                    "path": str(path.resolve()),
                    "mtime_ns": path.stat().st_mtime_ns,
                }
                for path in self.augmentation_paths
                if path.exists()
            ],
            "embedding_model": self.config.embedding_model,
            "record_count": len(self.items),
            "locale": self.config.locale,
            "search_strategy": "anchor-first-v1",
        }

        if matrix_path.exists() and meta_path.exists():
            cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if cached_meta == current_meta:
                return np.load(matrix_path)

        matrix = self.backend.embed(self.search_texts)
        np.save(matrix_path, matrix)
        meta_path.write_text(json.dumps(current_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return matrix


    def find_anchor_matches(self, chunk: str) -> list[dict[str, Any]]:
        if not chunk.strip():
            return []

        best: dict[tuple[str, str], dict[str, Any]] = {}
        for anchor, entries in self.anchor_index.items():
            match = _match_anchor_to_chunk(anchor, chunk)
            if match is None:
                continue
            match_type, matched_phrase = match
            match_score = _MATCH_TYPE_SCORE[match_type]
            match_confidence = _MATCH_TYPE_CONFIDENCE.get(match_type, "low")
            normalized_anchor = normalize_anchor_key(anchor)
            for entry in entries:
                source_id = str(entry.get("source_id") or entry.get("payload", {}).get("source_id") or entry.get("payload", {}).get("id") or "unknown-source")
                dedup_key = (source_id, normalized_anchor)
                candidate = {
                    "source_id": source_id,
                    "embedding_text": entry.get("embedding_text", ""),
                    "context_text": entry.get("context_text", ""),
                    "payload": dict(entry.get("payload", {}) or {}),
                    "score": match_score,
                    "match_type": match_type,
                    "matched_phrase": matched_phrase,
                    "anchor": anchor,
                    "evidence_chunk": chunk,
                    "lexical_evidence": True,
                    "confidence": match_confidence,
                    "representative_anchor": anchor,
                    "dedup_anchor_key": normalize_anchor_key(anchor),
                }
                current = best.get(dedup_key)
                candidate_rank = (_MATCH_TYPE_PRIORITY[match_type], match_score)
                if current is None or candidate_rank > current["_rank"]:
                    candidate["_rank"] = candidate_rank
                    best[dedup_key] = candidate

        results = list(best.values())
        results.sort(key=lambda row: (-row["_rank"][0], -row["_rank"][1], row["source_id"], row["anchor"]))
        for row in results:
            row.pop("_rank", None)
        return results

    @staticmethod
    def _candidate_rank(candidate: dict[str, Any]) -> tuple[int, int, float]:
        return (
            _MERGED_MATCH_TYPE_PRIORITY.get(str(candidate.get("match_type", "")), -1),
            1 if candidate.get("evidence_chunk") else 0,
            float(candidate.get("score", 0.0)),
        )

    @staticmethod
    def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, float, str, str, str]:
        return (
            -_MERGED_MATCH_TYPE_PRIORITY.get(str(candidate.get("match_type", "")), -1),
            -(1 if candidate.get("evidence_chunk") else 0),
            -float(candidate.get("score", 0.0)),
            str(candidate.get("source_id", "")),
            str(candidate.get("anchor", "")),
            str(candidate.get("matched_phrase", "")),
        )

    def _build_result_candidate(
        self,
        payload: dict[str, Any],
        *,
        score: float,
        match_type: str,
        matched_phrase: str,
        anchor: str,
        evidence_chunk: str,
        similarity_score: float,
        anchor_boost: float,
        lexical_evidence: bool,
        confidence: str,
        representative_anchor: str = "",
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        source_id = _resolve_source_id(payload)
        representative_anchor = representative_anchor.strip() if representative_anchor else ""
        dedup_anchor_key = normalize_anchor_key(representative_anchor or anchor or _representative_anchor_from_payload(payload))
        if not dedup_anchor_key:
            dedup_anchor_key = normalize_anchor_key(source_id)
        if not representative_anchor:
            representative_anchor = _representative_anchor_from_payload(payload, anchor)
        item = dict(payload)
        item.update(
            {
                "source_id": source_id,
                "score": float(score),
                "similarity_score": float(similarity_score),
                "anchor_boost": float(anchor_boost),
                "final_score": float(score),
                "match_type": match_type,
                "matched_phrase": matched_phrase,
                "anchor": anchor,
                "evidence_chunk": evidence_chunk,
                "lexical_evidence": bool(lexical_evidence),
                "confidence": confidence,
                "representative_anchor": representative_anchor,
                "dedup_anchor_key": dedup_anchor_key,
            }
        )
        return {
            "source_id": source_id,
            "item": item,
            "score": float(score),
            "similarity_score": float(similarity_score),
            "anchor_boost": float(anchor_boost),
            "final_score": float(score),
            "match_type": match_type,
            "matched_phrase": matched_phrase,
            "anchor": anchor,
            "evidence_chunk": evidence_chunk,
            "lexical_evidence": bool(lexical_evidence),
            "confidence": confidence,
            "representative_anchor": representative_anchor,
            "dedup_anchor_key": dedup_anchor_key,
            "_rank": self._candidate_rank(
                {
                    "match_type": match_type,
                    "evidence_chunk": evidence_chunk,
                    "score": score,
                }
            ),
        }

    def _semantic_hits_for_chunk(
        self,
        chunk: str,
        chunk_vec: np.ndarray,
        top_k: int,
        semantic_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        semantic_threshold = self.config.score_threshold if semantic_threshold is None else semantic_threshold
        if self._use_qdrant:
            hits = self._client.query_points(
                collection_name=self._collection,
                query=chunk_vec.tolist(),
                limit=top_k,
                with_payload=True,
                score_threshold=semantic_threshold,
            ).points
            results: list[dict[str, Any]] = []
            for h in hits:
                payload = dict(h.payload or {})
                if "source_id" not in payload and h.id is not None:
                    payload["source_id"] = h.id
                representative_anchor = _representative_anchor_from_payload(payload)
                results.append(
                    self._build_result_candidate(
                        payload,
                        score=float(h.score),
                        match_type="semantic",
                        matched_phrase="",
                        anchor="",
                        evidence_chunk=chunk,
                        similarity_score=float(h.score),
                        anchor_boost=0.0,
                        lexical_evidence=False,
                        confidence="low",
                        representative_anchor=representative_anchor,
                    )
                )
            return results

        sim = self.matrix @ chunk_vec
        top_indices = np.argsort(sim)[::-1][:top_k]
        results = []
        for index in top_indices:
            score = float(sim[index])
            if score < semantic_threshold:
                break
            payload = self.items[index]
            representative_anchor = _representative_anchor_from_payload(payload)
            results.append(
                self._build_result_candidate(
                    payload,
                    score=score,
                    match_type="semantic",
                    matched_phrase="",
                    anchor="",
                    evidence_chunk=chunk,
                    similarity_score=score,
                    anchor_boost=0.0,
                    lexical_evidence=False,
                    confidence="low",
                    representative_anchor=representative_anchor,
                )
            )
        return results

    @staticmethod
    def _register_best_candidate(
        best: dict[str, dict[str, Any]],
        candidate: dict[str, Any],
    ) -> None:
        key = str(candidate.get("dedup_anchor_key") or candidate.get("source_id") or "unknown-source")
        current = best.get(key)
        if current is None or candidate["_rank"] > current["_rank"]:
            best[key] = candidate

    def _finalize_candidates(
        self,
        candidates: list[dict[str, Any]],
        return_k: int,
    ) -> list[RetrievalResult]:
        ranked = sorted(candidates, key=self._candidate_sort_key)[:return_k]
        return [
            RetrievalResult(
                item=candidate["item"],
                score=float(candidate["score"]),
                similarity_score=float(candidate["similarity_score"]),
                anchor_boost=float(candidate["anchor_boost"]),
                final_score=float(candidate["final_score"]),
            )
            for candidate in ranked
        ]

    def retrieve(self, query: str, top_k: int | None = None,
                 return_k: int | None = None) -> list[RetrievalResult]:
        """쿼리 문자열을 청킹+임베딩 후 검색한다. (단독 사용 경로)

        top_k    : 청크 1개당 가져올 후보 수. 기본 config.idiom_top_k
        return_k : 통합 후 최종 반환 상한. 기본 config.idiom_return_k
        쿼리를 미리 임베딩해 공유할 때는 search()를 직접 쓴다.
        """
        chunks = self._chunk_query(query)
        chunk_vectors = self.backend.embed(chunks)
        return self.search(chunks, chunk_vectors, top_k, return_k)

    def search(self, chunks, chunk_vectors, top_k: int | None = None,
               return_k: int | None = None) -> list[RetrievalResult]:
        """미리 만들어진 (chunks, vectors)로 검색만 수행한다. (임베딩 공유 경로)"""
        top_k = top_k if top_k is not None else self.config.idiom_top_k
        return_k = return_k if return_k is not None else self.config.idiom_return_k
        best: dict[str, dict[str, Any]] = {}

        for chunk, chunk_vec in zip(chunks, chunk_vectors):
            lexical_hits = self.find_anchor_matches(chunk)
            semantic_threshold = self.config.score_threshold
            if lexical_hits:
                semantic_threshold = max(self.config.score_threshold, _SEMANTIC_ONLY_SCORE_FLOOR)
            semantic_hits = self._semantic_hits_for_chunk(chunk, chunk_vec, top_k, semantic_threshold)
            for hit in lexical_hits:
                payload = dict(hit.get("payload") or {})
                if not payload:
                    payload = {
                        "source_id": hit.get("source_id", ""),
                        "embedding_text": hit.get("embedding_text", ""),
                        "context_text": hit.get("context_text", ""),
                    }
                representative_anchor = str(hit.get("representative_anchor") or hit.get("anchor") or _representative_anchor_from_payload(payload))
                candidate = self._build_result_candidate(
                    payload,
                    score=float(hit["score"]),
                    match_type=str(hit["match_type"]),
                    matched_phrase=str(hit["matched_phrase"]),
                    anchor=str(hit["anchor"]),
                    evidence_chunk=str(hit["evidence_chunk"]),
                    similarity_score=0.0,
                    anchor_boost=float(hit["score"]),
                    lexical_evidence=True,
                    confidence=str(hit.get("confidence", "low")),
                    representative_anchor=representative_anchor,
                )
                self._register_best_candidate(best, candidate)
            for candidate in semantic_hits:
                self._register_best_candidate(best, candidate)

        return self._finalize_candidates(list(best.values()), return_k)

    def _retrieve_qdrant(
        self, chunks: list[str], chunk_vectors: np.ndarray, top_k: int, return_k: int
    ) -> list[RetrievalResult]:
        """qdrant 컬렉션의 시맨틱 결과만 뽑는 하위 호환 경로."""
        best: dict[str, dict[str, Any]] = {}
        for chunk, chunk_vec in zip(chunks, chunk_vectors):
            for candidate in self._semantic_hits_for_chunk(chunk, chunk_vec, top_k, self.config.score_threshold):
                self._register_best_candidate(best, candidate)
        return self._finalize_candidates(list(best.values()), return_k)

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        return re.sub(r"[\W_]+", "", text).casefold()

    @classmethod
    def _has_exact_phrase_match(cls, query: str, phrases: list[str]) -> bool:
        normalized_query = cls._normalize_match_text(query)
        for phrase in phrases:
            normalized_phrase = cls._normalize_match_text(str(phrase))
            if normalized_phrase and normalized_phrase in normalized_query:
                return True
        return False

    @classmethod
    def _lexical_match_boost(cls, item: dict[str, Any], query: str) -> float:
        # The KURE-ready embedding_text/context_text datasets intentionally rely
        # on semantic score only. Legacy ko_anchor_expression rows keep the old
        # exact-match boost for backwards-compatible tests and custom datasets.
        if item.get("embedding_text") and item.get("context_text"):
            return 0.0

        anchor_phrases = [str(value).strip() for value in item.get("ko_anchor_expression") or [] if str(value).strip()]
        if cls._has_exact_phrase_match(query, anchor_phrases):
            return 1.0

        expression_phrases = [str(value).strip() for value in item.get("ko_expression") or [] if str(value).strip()]
        if cls._has_exact_phrase_match(query, expression_phrases):
            return 0.35

        return 0.0

    @staticmethod
    def _render_result_block(index: int, result: RetrievalResult, *, debug: bool = False) -> str:
        item = result.item
        context_text = item.get("context_text")
        embedding_text = item.get("embedding_text")
        description = ""
        if isinstance(context_text, str) and context_text.strip():
            description = context_text.strip()
        elif isinstance(embedding_text, str) and embedding_text.strip():
            description = embedding_text.strip()

        lines = [
            f"{index}. source_id: {item.get('source_id', '')}",
            f"   anchor: {item.get('anchor', '')}",
            f"   matched_phrase: {item.get('matched_phrase', '')}",
            f"   match_type: {item.get('match_type', '')}",
            f"   confidence: {item.get('confidence', '')}",
            f"   lexical_evidence: {item.get('lexical_evidence', False)}",
            f"   evidence_chunk: {item.get('evidence_chunk', '')}",
        ]
        if description:
            lines.append(f"   {'debug_description' if debug else 'description'}: {description}")
        if debug:
            lines.extend(
                [
                    f"   context_text: {context_text or ''}",
                    f"   embedding_text: {embedding_text or ''}",
                    f"   score: {result.score:.4f}",
                    f"   similarity_score: {result.similarity_score:.4f}",
                    f"   anchor_boost: {result.anchor_boost:.4f}",
                    f"   final_score: {result.final_score:.4f}",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def build_context(results: list[RetrievalResult]) -> str:
        rendered = [
            IdiomRetriever._render_result_block(index, result)
            for index, result in enumerate(results, start=1)
            if (
                str(result.item.get("confidence", "")) == "high"
                or str(result.item.get("match_type", "")) in {"exact", "normalized"}
            )
        ]
        if not rendered:
            return ""
        return "\n".join(["[RAG] Korean-idiom reference matches", *rendered])

    @staticmethod
    def build_debug_context(results: list[RetrievalResult]) -> str:
        if not results:
            return "[RAG-DEBUG] no reference matches"

        rendered = [
            IdiomRetriever._render_result_block(index, result, debug=True)
            for index, result in enumerate(results, start=1)
        ]
        return "\n".join(["[RAG-DEBUG] Korean-idiom reference matches", *rendered])
