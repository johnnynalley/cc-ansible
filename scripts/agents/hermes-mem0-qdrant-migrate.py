#!/usr/bin/env python3
"""Copy or locally re-embed Mem0 points into a native Hermes collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import numbers
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


CAMEL_TO_SNAKE = {
    "userId": "user_id",
    "agentId": "agent_id",
    "runId": "run_id",
    "actorId": "actor_id",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
}


class MigrationError(RuntimeError):
    """Raised when a source or target cannot be migrated without ambiguity."""


class QdrantClient:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        allow_missing: bool = False,
    ) -> dict[str, Any] | None:
        payload = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["api-key"] = self.api_key
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code == 404:
                return None
            raise MigrationError(f"qdrant-http-{exc.code}:{method}:{path}") from exc
        except urllib.error.URLError as exc:
            raise MigrationError(f"qdrant-unreachable:{method}:{path}") from exc
        if len(raw) > 16 * 1024 * 1024:
            raise MigrationError(f"qdrant-response-too-large:{method}:{path}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MigrationError(f"qdrant-invalid-json:{method}:{path}") from exc
        if not isinstance(value, dict):
            raise MigrationError(f"qdrant-invalid-response:{method}:{path}")
        return value

    def collection(self, name: str) -> dict[str, Any] | None:
        encoded = urllib.parse.quote(name, safe="")
        return self.request("GET", f"/collections/{encoded}", allow_missing=True)

    def count(self, name: str) -> int:
        encoded = urllib.parse.quote(name, safe="")
        response = self.request(
            "POST", f"/collections/{encoded}/points/count", {"exact": True}
        )
        try:
            count = response["result"]["count"]  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise MigrationError(f"qdrant-count-invalid:{name}") from exc
        if not isinstance(count, int) or count < 0:
            raise MigrationError(f"qdrant-count-invalid:{name}")
        return count

    def points(
        self, name: str, batch_size: int, *, with_vector: bool = True
    ) -> Iterator[list[dict[str, Any]]]:
        encoded = urllib.parse.quote(name, safe="")
        offset: Any = None
        previous_offset: Any = object()
        while True:
            body: dict[str, Any] = {
                "limit": batch_size,
                "with_payload": True,
                "with_vector": with_vector,
            }
            if offset is not None:
                body["offset"] = offset
            response = self.request(
                "POST", f"/collections/{encoded}/points/scroll", body
            )
            try:
                result = response["result"]  # type: ignore[index]
                rows = result["points"]
                next_offset = result.get("next_page_offset")
            except (KeyError, TypeError) as exc:
                raise MigrationError(f"qdrant-scroll-invalid:{name}") from exc
            if not isinstance(rows, list) or not all(
                isinstance(row, dict) for row in rows
            ):
                raise MigrationError(f"qdrant-scroll-invalid:{name}")
            if rows:
                yield rows
            if next_offset is None:
                return
            if next_offset == previous_offset or next_offset == offset:
                raise MigrationError(f"qdrant-scroll-stalled:{name}")
            previous_offset = offset
            offset = next_offset

    def snapshot(self, name: str) -> str:
        encoded = urllib.parse.quote(name, safe="")
        response = self.request("POST", f"/collections/{encoded}/snapshots")
        try:
            snapshot = response["result"]["name"]  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise MigrationError(f"qdrant-snapshot-invalid:{name}") from exc
        if not isinstance(snapshot, str) or not snapshot:
            raise MigrationError(f"qdrant-snapshot-invalid:{name}")
        return snapshot

    def create_collection(
        self,
        name: str,
        vectors: Any,
        sparse_vectors: dict[str, Any] | None = None,
    ) -> None:
        encoded = urllib.parse.quote(name, safe="")
        body = {"vectors": vectors}
        if sparse_vectors is not None:
            body["sparse_vectors"] = sparse_vectors
        self.request("PUT", f"/collections/{encoded}", body)

    def upsert(self, name: str, points: list[dict[str, Any]]) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self.request(
            "PUT",
            f"/collections/{encoded}/points?wait=true",
            {"points": points},
        )

    def create_payload_index(self, name: str, field_name: str) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self.request(
            "PUT",
            f"/collections/{encoded}/index?wait=true",
            {"field_name": field_name, "field_schema": "keyword"},
        )


class OllamaClient:
    """Minimal client for the local Ollama embedding endpoint."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def embed(self, model: str, texts: list[str], dimensions: int) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise MigrationError("embedding-input-invalid")
        body = json.dumps(
            {"model": model, "input": texts}, separators=(",", ":")
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                raw = response.read(64 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            raise MigrationError(f"ollama-http-{exc.code}:embed") from exc
        except urllib.error.URLError as exc:
            raise MigrationError("ollama-unreachable:embed") from exc
        if len(raw) > 64 * 1024 * 1024:
            raise MigrationError("ollama-response-too-large:embed")
        try:
            value = json.loads(raw)
            embeddings = value["embeddings"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MigrationError("ollama-invalid-response:embed") from exc
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise MigrationError("ollama-embedding-count-mismatch")
        result: list[list[float]] = []
        for vector in embeddings:
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise MigrationError("ollama-embedding-dimension-mismatch")
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in vector
            ):
                raise MigrationError("ollama-embedding-value-invalid")
            result.append([float(value) for value in vector])
        return result


class FastembedSparseEncoder:
    """Lazy local BM25 encoder matching Mem0's Qdrant hybrid-search schema."""

    def __init__(self, model: str) -> None:
        try:
            from fastembed import SparseTextEmbedding
        except ImportError as exc:
            raise MigrationError("fastembed-dependency-missing") from exc
        try:
            self._model = SparseTextEmbedding(model_name=model)
        except Exception as exc:
            raise MigrationError("sparse-model-initialization-failed") from exc

    def embed(self, texts: list[str]) -> list[dict[str, list[int] | list[float]]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise MigrationError("sparse-input-invalid")
        try:
            embeddings = list(self._model.embed(texts))
        except Exception as exc:
            raise MigrationError("sparse-embedding-failed") from exc
        if len(embeddings) != len(texts):
            raise MigrationError("sparse-embedding-count-mismatch")
        return [canonical_sparse_vector(value) for value in embeddings]


def transformed_payload(
    payload: dict[str, Any], user_id: str, agent_id: str
) -> dict[str, Any]:
    result = dict(payload)
    source_user_id = legacy_user_id(result)
    for old, new in CAMEL_TO_SNAKE.items():
        if old not in result:
            continue
        if new in result and result[new] != result[old]:
            raise MigrationError(f"payload-identity-conflict:{old}:{new}")
        result[new] = result.pop(old)
    if source_user_id != user_id:
        existing_source = result.get("openclaw_user_id")
        if existing_source not in (None, source_user_id):
            raise MigrationError("payload-source-user-id-conflict")
        result["openclaw_user_id"] = source_user_id
    result["user_id"] = user_id
    result["agent_id"] = agent_id
    return result


def legacy_user_id(payload: dict[str, Any]) -> str:
    values = {
        value
        for key in ("userId", "user_id")
        if isinstance((value := payload.get(key)), str) and value
    }
    if len(values) != 1:
        raise MigrationError("payload-source-user-id-invalid")
    return values.pop()


def selected_payload(
    payload: dict[str, Any],
    *,
    source_normalized: bool,
    user_id: str,
    agent_id: str,
    included_user_ids: set[str],
) -> dict[str, Any] | None:
    if source_normalized:
        if payload.get("user_id") != user_id or payload.get("agent_id") != agent_id:
            return None
        return dict(payload)
    if legacy_user_id(payload) not in included_user_ids:
        return None
    return transformed_payload(payload, user_id, agent_id)


def canonical_sparse_vector(value: Any) -> dict[str, list[int] | list[float]]:
    indices = getattr(value, "indices", None)
    values = getattr(value, "values", None)
    if isinstance(value, dict):
        indices = value.get("indices")
        values = value.get("values")
    if hasattr(indices, "tolist"):
        indices = indices.tolist()
    if hasattr(values, "tolist"):
        values = values.tolist()
    if not isinstance(indices, list) or not isinstance(values, list):
        raise MigrationError("sparse-vector-invalid")
    if len(indices) != len(values):
        raise MigrationError("sparse-vector-invalid")
    if any(
        not isinstance(index, numbers.Integral)
        or isinstance(index, bool)
        or index < 0
        for index in indices
    ):
        raise MigrationError("sparse-vector-index-invalid")
    normalized_indices = [int(index) for index in indices]
    if len(set(normalized_indices)) != len(normalized_indices):
        raise MigrationError("sparse-vector-index-invalid")
    if any(
        not isinstance(item, numbers.Real)
        or isinstance(item, bool)
        or not math.isfinite(item)
        for item in values
    ):
        raise MigrationError("sparse-vector-value-invalid")
    pairs = sorted(
        zip(normalized_indices, (float(item) for item in values), strict=True),
        key=lambda pair: pair[0],
    )
    return {
        "indices": [index for index, _ in pairs],
        "values": [item for _, item in pairs],
    }


def dense_vector(point: dict[str, Any], dimensions: int) -> list[float]:
    vector = point.get("vector")
    if isinstance(vector, dict):
        vector = vector.get("")
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise MigrationError("target-vector-dimension-mismatch")
    if any(
        not isinstance(item, (int, float))
        or isinstance(item, bool)
        or not math.isfinite(item)
        for item in vector
    ):
        raise MigrationError("target-vector-value-invalid")
    return [float(item) for item in vector]


def hybrid_vector(
    point: dict[str, Any],
    sparse: dict[str, list[int] | list[float]],
    dimensions: int,
) -> dict[str, Any]:
    return {"": dense_vector(point, dimensions), "bm25": sparse}


def transformed_point(
    point: dict[str, Any],
    user_id: str,
    agent_id: str,
    *,
    vector: list[float] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    point_id = point.get("id")
    source_vector = point.get("vector") if vector is None else vector
    payload = point.get("payload")
    if not isinstance(point_id, (str, int)):
        raise MigrationError("point-id-invalid")
    if not isinstance(payload, dict):
        raise MigrationError("point-payload-invalid")
    if not isinstance(source_vector, (list, dict)):
        raise MigrationError("point-vector-invalid")
    return {
        "id": point_id,
        "vector": source_vector,
        "payload": transformed_payload(payload, user_id, agent_id),
    }


@dataclass(frozen=True)
class Digest:
    scanned: int
    count: int
    sha256: str


def collection_digest(
    client: QdrantClient,
    name: str,
    batch_size: int,
    *,
    transform: bool,
    user_id: str,
    agent_id: str,
    included_user_ids: set[str],
    source_normalized: bool = False,
    include_vector: bool = True,
    required_vector_dimensions: int | None = None,
    require_hybrid: bool = False,
) -> Digest:
    digest = hashlib.sha256()
    scanned = 0
    count = 0
    for rows in client.points(
        name, batch_size, with_vector=(include_vector or require_hybrid)
    ):
        for raw in rows:
            scanned += 1
            if transform:
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    raise MigrationError("point-payload-invalid")
                normalized_payload = selected_payload(
                    payload,
                    source_normalized=source_normalized,
                    user_id=user_id,
                    agent_id=agent_id,
                    included_user_ids=included_user_ids,
                )
                if normalized_payload is None:
                    continue
                point = digest_point(
                    raw,
                    normalized_payload,
                    include_vector=include_vector,
                    required_vector_dimensions=required_vector_dimensions,
                    require_hybrid=require_hybrid,
                )
            else:
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    raise MigrationError("point-payload-invalid")
                point = digest_point(
                    raw,
                    payload,
                    include_vector=include_vector,
                    required_vector_dimensions=required_vector_dimensions,
                    require_hybrid=require_hybrid,
                )
            digest.update(
                json.dumps(
                    point,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            )
            digest.update(b"\n")
            count += 1
    return Digest(scanned=scanned, count=count, sha256=digest.hexdigest())


def canonical_point(point: dict[str, Any]) -> dict[str, Any]:
    point_id = point.get("id")
    vector = point.get("vector")
    payload = point.get("payload")
    if not isinstance(point_id, (str, int)):
        raise MigrationError("point-id-invalid")
    if not isinstance(payload, dict):
        raise MigrationError("point-payload-invalid")
    if not isinstance(vector, (list, dict)):
        raise MigrationError("point-vector-invalid")
    return {"id": point_id, "vector": vector, "payload": payload}


def digest_point(
    point: dict[str, Any],
    payload: dict[str, Any],
    *,
    include_vector: bool,
    required_vector_dimensions: int | None,
    require_hybrid: bool = False,
) -> dict[str, Any]:
    point_id = point.get("id")
    if not isinstance(point_id, (str, int)):
        raise MigrationError("point-id-invalid")
    result: dict[str, Any] = {"id": point_id, "payload": payload}
    if require_hybrid:
        vector = point.get("vector")
        if not isinstance(vector, dict) or set(vector) != {"", "bm25"}:
            raise MigrationError("target-hybrid-vector-invalid")
        dense_vector(point, required_vector_dimensions or 0)
        canonical_sparse_vector(vector["bm25"])
    if not include_vector:
        return result
    vector = point.get("vector")
    if not isinstance(vector, (list, dict)):
        raise MigrationError("point-vector-invalid")
    if required_vector_dimensions is not None and not require_hybrid:
        dense_vector(point, required_vector_dimensions)
    result["vector"] = vector
    return result


def memory_text(payload: dict[str, Any]) -> str:
    value = payload.get("data")
    if not isinstance(value, str) or not value.strip():
        raise MigrationError("memory-data-invalid")
    return value


def source_vectors(info: dict[str, Any], source: str) -> Any:
    try:
        vectors = info["result"]["config"]["params"]["vectors"]
    except (KeyError, TypeError) as exc:
        raise MigrationError(f"qdrant-vectors-invalid:{source}") from exc
    if not isinstance(vectors, dict) or not vectors:
        raise MigrationError(f"qdrant-vectors-invalid:{source}")
    return vectors


def vector_dimensions(vectors: Any, collection: str) -> int:
    if not isinstance(vectors, dict):
        raise MigrationError(f"qdrant-vectors-invalid:{collection}")
    size = vectors.get("size")
    if not isinstance(size, int) or size < 1:
        raise MigrationError(f"qdrant-vector-size-invalid:{collection}")
    return size


def require_reembed_target_vectors(
    info: dict[str, Any], target: str, dimensions: int
) -> None:
    vectors = source_vectors(info, target)
    if vectors.get("size") != dimensions or vectors.get("distance") != "Cosine":
        raise MigrationError("reembed-target-vector-config-mismatch")


def require_hybrid_target_vectors(
    info: dict[str, Any], target: str, dimensions: int
) -> None:
    require_reembed_target_vectors(info, target, dimensions)
    try:
        sparse_vectors = info["result"]["config"]["params"]["sparse_vectors"]
    except (KeyError, TypeError) as exc:
        raise MigrationError(f"qdrant-sparse-vectors-invalid:{target}") from exc
    if not isinstance(sparse_vectors, dict) or "bm25" not in sparse_vectors:
        raise MigrationError("hybrid-target-sparse-config-mismatch")
    bm25 = sparse_vectors["bm25"]
    if not isinstance(bm25, dict) or str(bm25.get("modifier", "")).lower() != "idf":
        raise MigrationError("hybrid-target-sparse-config-mismatch")
    try:
        payload_schema = info["result"]["payload_schema"]
    except (KeyError, TypeError) as exc:
        raise MigrationError(f"qdrant-payload-schema-invalid:{target}") from exc
    if not isinstance(payload_schema, dict) or any(
        not isinstance(payload_schema.get(field), dict)
        or payload_schema[field].get("data_type") != "keyword"
        for field in ("user_id", "agent_id", "run_id", "actor_id")
    ):
        raise MigrationError("hybrid-target-payload-index-mismatch")


def migrate(
    args: argparse.Namespace,
    client: QdrantClient,
    ollama: OllamaClient | None = None,
    sparse_encoder: FastembedSparseEncoder | None = None,
) -> dict[str, Any]:
    if args.empty_target:
        if (
            args.source is not None
            or args.include_user_id
            or args.source_normalized
            or not args.reembed
            or not args.hybrid
        ):
            raise MigrationError("empty-target-boundary-invalid")
        if args.embedding_dimensions < 1:
            raise MigrationError("embedding-dimensions-invalid")
        target_info = client.collection(args.target)
        if target_info is not None:
            require_hybrid_target_vectors(
                target_info, args.target, args.embedding_dimensions
            )
            if client.count(args.target) != 0:
                raise MigrationError("empty-target-nonempty")
            return {
                "status": "already-initialized",
                "mode": "apply" if args.apply else "dry-run",
                "sourceCount": 0,
                "selectedCount": 0,
                "excludedCount": 0,
                "targetCount": 0,
                "digest": hashlib.sha256(b"").hexdigest(),
                "embeddingModel": args.embedding_model,
                "embeddingDimensions": args.embedding_dimensions,
                "hybrid": True,
                "sparseModel": args.sparse_model,
                "emptyTarget": True,
            }
        result = {
            "status": "ready",
            "mode": "dry-run",
            "sourceCount": 0,
            "selectedCount": 0,
            "excludedCount": 0,
            "targetCount": 0,
            "wouldCreateTarget": True,
            "digest": hashlib.sha256(b"").hexdigest(),
            "embeddingModel": args.embedding_model,
            "embeddingDimensions": args.embedding_dimensions,
            "hybrid": True,
            "sparseModel": args.sparse_model,
            "emptyTarget": True,
        }
        if not args.apply:
            return result
        client.create_collection(
            args.target,
            {"size": args.embedding_dimensions, "distance": "Cosine"},
            {"bm25": {"modifier": "idf"}},
        )
        for field_name in ("user_id", "agent_id", "run_id", "actor_id"):
            client.create_payload_index(args.target, field_name)
        created = client.collection(args.target)
        if created is None:
            raise MigrationError("empty-target-create-failed")
        require_hybrid_target_vectors(created, args.target, args.embedding_dimensions)
        if client.count(args.target) != 0:
            raise MigrationError("empty-target-verification-failed")
        result.update({"status": "initialized", "mode": "apply"})
        return result

    if args.source is None:
        raise MigrationError("source-collection-required")
    if args.source == args.target:
        raise MigrationError("source-and-target-must-differ")
    source_info = client.collection(args.source)
    if source_info is None:
        raise MigrationError("source-collection-missing")
    vectors = source_vectors(source_info, args.source)
    source_dimensions = vector_dimensions(vectors, args.source)
    if args.reembed:
        if args.embedding_dimensions < 1:
            raise MigrationError("embedding-dimensions-invalid")
        if not args.embedding_model:
            raise MigrationError("embedding-model-required")
        vectors = {"size": args.embedding_dimensions, "distance": "Cosine"}
    elif args.hybrid and source_dimensions != args.embedding_dimensions:
        raise MigrationError("hybrid-source-vector-config-mismatch")
    included_user_ids = set(args.include_user_id)
    if not args.source_normalized and not included_user_ids:
        raise MigrationError("included-user-id-required")
    source_count = client.count(args.source)
    source_digest = collection_digest(
        client,
        args.source,
        args.batch_size,
        transform=True,
        user_id=args.user_id,
        agent_id=args.agent_id,
        included_user_ids=included_user_ids,
        source_normalized=args.source_normalized,
        include_vector=not (args.reembed or args.hybrid),
    )
    if source_count != source_digest.scanned:
        raise MigrationError("source-count-changed-during-scan")

    target_info = client.collection(args.target)
    if args.hybrid and target_info is not None:
        require_hybrid_target_vectors(
            target_info, args.target, args.embedding_dimensions
        )
    elif args.reembed and target_info is not None:
        require_reembed_target_vectors(
            target_info, args.target, args.embedding_dimensions
        )
    target_count = 0 if target_info is None else client.count(args.target)
    if target_count:
        target_digest = collection_digest(
            client,
            args.target,
            args.batch_size,
            transform=False,
            user_id=args.user_id,
            agent_id=args.agent_id,
            included_user_ids=included_user_ids,
            include_vector=not (args.reembed or args.hybrid),
            required_vector_dimensions=(
                args.embedding_dimensions if (args.reembed or args.hybrid) else None
            ),
            require_hybrid=args.hybrid,
        )
        if (
            source_digest.count != target_digest.count
            or source_digest.sha256 != target_digest.sha256
        ):
            raise MigrationError("nonempty-target-does-not-match-source")
        result = {
            "status": "already-migrated",
            "mode": "apply" if args.apply else "dry-run",
            "sourceCount": source_count,
            "selectedCount": source_digest.count,
            "excludedCount": source_count - source_digest.count,
            "targetCount": target_count,
            "digest": source_digest.sha256,
        }
        if args.reembed:
            result.update(
                {
                    "embeddingModel": args.embedding_model,
                    "embeddingDimensions": args.embedding_dimensions,
                }
            )
        if args.hybrid:
            result.update({"hybrid": True, "sparseModel": args.sparse_model})
        return result

    if args.reembed or args.hybrid:
        if ollama is None:
            ollama = OllamaClient(args.ollama_url) if args.reembed else None
        probe_text: str | None = None
        for rows in client.points(args.source, args.batch_size, with_vector=False):
            for row in rows:
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    raise MigrationError("point-payload-invalid")
                if selected_payload(
                    payload,
                    source_normalized=args.source_normalized,
                    user_id=args.user_id,
                    agent_id=args.agent_id,
                    included_user_ids=included_user_ids,
                ) is not None:
                    probe_text = memory_text(payload)
                    break
            if probe_text is not None:
                break
        if probe_text is None:
            raise MigrationError("selected-source-empty")
        if args.reembed:
            assert ollama is not None
            ollama.embed(args.embedding_model, [probe_text], args.embedding_dimensions)
        if args.hybrid:
            if sparse_encoder is None:
                sparse_encoder = FastembedSparseEncoder(args.sparse_model)
            sparse_encoder.embed([probe_text])

    if not args.apply:
        result = {
            "status": "ready",
            "mode": "dry-run",
            "sourceCount": source_count,
            "selectedCount": source_digest.count,
            "excludedCount": source_count - source_digest.count,
            "targetCount": target_count,
            "wouldCreateTarget": target_info is None,
            "digest": source_digest.sha256,
        }
        if args.reembed:
            result.update(
                {
                    "embeddingModel": args.embedding_model,
                    "embeddingDimensions": args.embedding_dimensions,
                }
            )
        if args.hybrid:
            result.update({"hybrid": True, "sparseModel": args.sparse_model})
        return result

    snapshot = client.snapshot(args.source)
    if target_info is None:
        client.create_collection(
            args.target,
            vectors,
            {"bm25": {"modifier": "idf"}} if args.hybrid else None,
        )
        if args.hybrid:
            for field_name in ("user_id", "agent_id", "run_id", "actor_id"):
                client.create_payload_index(args.target, field_name)
    for rows in client.points(
        args.source, args.batch_size, with_vector=not args.reembed
    ):
        selected_rows: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload")
            if not isinstance(payload, dict):
                raise MigrationError("point-payload-invalid")
            if selected_payload(
                payload,
                source_normalized=args.source_normalized,
                user_id=args.user_id,
                agent_id=args.agent_id,
                included_user_ids=included_user_ids,
            ) is not None:
                selected_rows.append(row)
        for start in range(0, len(selected_rows), args.embedding_batch_size):
            batch = selected_rows[start : start + args.embedding_batch_size]
            if not args.reembed and not args.hybrid:
                selected = [
                    transformed_point(row, args.user_id, args.agent_id)
                    for row in batch
                ]
                if selected:
                    client.upsert(args.target, selected)
                continue
            if args.reembed:
                assert ollama is not None
                texts = [memory_text(row["payload"]) for row in batch]
                embedded = ollama.embed(
                    args.embedding_model, texts, args.embedding_dimensions
                )
                dense_vectors = embedded
            else:
                dense_vectors = [dense_vector(row, args.embedding_dimensions) for row in batch]
            sparse_vectors = None
            if args.hybrid:
                assert sparse_encoder is not None
                sparse_vectors = [
                    canonical_sparse_vector(vector)
                    for vector in sparse_encoder.embed(
                        [memory_text(row["payload"]) for row in batch]
                    )
                ]
            selected = []
            for index, row in enumerate(batch):
                payload = row.get("payload")
                assert isinstance(payload, dict)
                normalized_payload = selected_payload(
                    payload,
                    source_normalized=args.source_normalized,
                    user_id=args.user_id,
                    agent_id=args.agent_id,
                    included_user_ids=included_user_ids,
                )
                assert normalized_payload is not None
                vector: list[float] | dict[str, Any] = dense_vectors[index]
                if sparse_vectors is not None:
                    vector = {"": dense_vectors[index], "bm25": sparse_vectors[index]}
                point_id = row.get("id")
                if not isinstance(point_id, (str, int)):
                    raise MigrationError("point-id-invalid")
                selected.append(
                    {"id": point_id, "vector": vector, "payload": normalized_payload}
                )
            if selected:
                client.upsert(args.target, selected)

    final_count = client.count(args.target)
    final_digest = collection_digest(
        client,
        args.target,
        args.batch_size,
        transform=False,
        user_id=args.user_id,
        agent_id=args.agent_id,
        included_user_ids=included_user_ids,
        include_vector=not (args.reembed or args.hybrid),
        required_vector_dimensions=(
            args.embedding_dimensions if (args.reembed or args.hybrid) else None
        ),
        require_hybrid=args.hybrid,
    )
    if (
        final_count != source_digest.count
        or final_digest.count != source_digest.count
        or final_digest.sha256 != source_digest.sha256
    ):
        raise MigrationError("target-verification-failed")
    result = {
        "status": "migrated",
        "mode": "apply",
        "sourceCount": source_count,
        "selectedCount": source_digest.count,
        "excludedCount": source_count - source_digest.count,
        "targetCount": final_count,
        "digest": final_digest.sha256,
        "sourceSnapshot": snapshot,
    }
    if args.reembed:
        result.update(
            {
                "embeddingModel": args.embedding_model,
                "embeddingDimensions": args.embedding_dimensions,
            }
        )
    if args.hybrid:
        result.update({"hybrid": True, "sparseModel": args.sparse_model})
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    value.add_argument("--api-key")
    value.add_argument("--source")
    value.add_argument("--target", required=True)
    value.add_argument("--user-id", required=True)
    value.add_argument("--agent-id", required=True)
    value.add_argument("--include-user-id", action="append", default=[])
    value.add_argument("--source-normalized", action="store_true")
    value.add_argument("--batch-size", type=int, default=128)
    value.add_argument("--reembed", action="store_true")
    value.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    value.add_argument("--embedding-model", default="qwen3-embedding:0.6b")
    value.add_argument("--embedding-dimensions", type=int, default=1024)
    value.add_argument("--embedding-batch-size", type=int, default=32)
    value.add_argument("--hybrid", action="store_true")
    value.add_argument("--sparse-model", default="Qdrant/bm25")
    value.add_argument("--empty-target", action="store_true")
    value.add_argument("--apply", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.batch_size < 1 or args.batch_size > 256:
        print("mem0-migration-error:batch-size-out-of-range", file=sys.stderr)
        return 2
    if args.embedding_batch_size < 1 or args.embedding_batch_size > 64:
        print("mem0-migration-error:embedding-batch-size-out-of-range", file=sys.stderr)
        return 2
    try:
        result = migrate(args, QdrantClient(args.qdrant_url, args.api_key))
    except MigrationError as exc:
        print(f"mem0-migration-error:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
