#!/usr/bin/env python3
"""Copy OpenClaw Mem0 points into a Hermes-compatible Qdrant collection."""

from __future__ import annotations

import argparse
import hashlib
import json
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

    def points(self, name: str, batch_size: int) -> Iterator[list[dict[str, Any]]]:
        encoded = urllib.parse.quote(name, safe="")
        offset: Any = None
        previous_offset: Any = object()
        while True:
            body: dict[str, Any] = {
                "limit": batch_size,
                "with_payload": True,
                "with_vector": True,
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

    def create_collection(self, name: str, vectors: Any) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self.request("PUT", f"/collections/{encoded}", {"vectors": vectors})

    def upsert(self, name: str, points: list[dict[str, Any]]) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self.request(
            "PUT",
            f"/collections/{encoded}/points?wait=true",
            {"points": points},
        )


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


def transformed_point(
    point: dict[str, Any], user_id: str, agent_id: str
) -> dict[str, Any]:
    point_id = point.get("id")
    vector = point.get("vector")
    payload = point.get("payload")
    if not isinstance(point_id, (str, int)):
        raise MigrationError("point-id-invalid")
    if not isinstance(payload, dict):
        raise MigrationError("point-payload-invalid")
    if not isinstance(vector, (list, dict)):
        raise MigrationError("point-vector-invalid")
    return {
        "id": point_id,
        "vector": vector,
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
) -> Digest:
    digest = hashlib.sha256()
    scanned = 0
    count = 0
    for rows in client.points(name, batch_size):
        for raw in rows:
            scanned += 1
            if transform:
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    raise MigrationError("point-payload-invalid")
                if legacy_user_id(payload) not in included_user_ids:
                    continue
                point = transformed_point(raw, user_id, agent_id)
            else:
                point = canonical_point(raw)
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


def source_vectors(info: dict[str, Any], source: str) -> Any:
    try:
        vectors = info["result"]["config"]["params"]["vectors"]
    except (KeyError, TypeError) as exc:
        raise MigrationError(f"qdrant-vectors-invalid:{source}") from exc
    if not isinstance(vectors, dict) or not vectors:
        raise MigrationError(f"qdrant-vectors-invalid:{source}")
    return vectors


def migrate(args: argparse.Namespace, client: QdrantClient) -> dict[str, Any]:
    if args.source == args.target:
        raise MigrationError("source-and-target-must-differ")
    source_info = client.collection(args.source)
    if source_info is None:
        raise MigrationError("source-collection-missing")
    vectors = source_vectors(source_info, args.source)
    included_user_ids = set(args.include_user_id)
    if not included_user_ids:
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
    )
    if source_count != source_digest.scanned:
        raise MigrationError("source-count-changed-during-scan")

    target_info = client.collection(args.target)
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
        )
        if (
            source_digest.count != target_digest.count
            or source_digest.sha256 != target_digest.sha256
        ):
            raise MigrationError("nonempty-target-does-not-match-source")
        return {
            "status": "already-migrated",
            "mode": "apply" if args.apply else "dry-run",
            "sourceCount": source_count,
            "selectedCount": source_digest.count,
            "excludedCount": source_count - source_digest.count,
            "targetCount": target_count,
            "digest": source_digest.sha256,
        }

    if not args.apply:
        return {
            "status": "ready",
            "mode": "dry-run",
            "sourceCount": source_count,
            "selectedCount": source_digest.count,
            "excludedCount": source_count - source_digest.count,
            "targetCount": target_count,
            "wouldCreateTarget": target_info is None,
            "digest": source_digest.sha256,
        }

    snapshot = client.snapshot(args.source)
    if target_info is None:
        client.create_collection(args.target, vectors)
    for rows in client.points(args.source, args.batch_size):
        selected: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload")
            if not isinstance(payload, dict):
                raise MigrationError("point-payload-invalid")
            if legacy_user_id(payload) in included_user_ids:
                selected.append(transformed_point(row, args.user_id, args.agent_id))
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
    )
    if (
        final_count != source_digest.count
        or final_digest.count != source_digest.count
        or final_digest.sha256 != source_digest.sha256
    ):
        raise MigrationError("target-verification-failed")
    return {
        "status": "migrated",
        "mode": "apply",
        "sourceCount": source_count,
        "selectedCount": source_digest.count,
        "excludedCount": source_count - source_digest.count,
        "targetCount": final_count,
        "digest": final_digest.sha256,
        "sourceSnapshot": snapshot,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    value.add_argument("--api-key")
    value.add_argument("--source", required=True)
    value.add_argument("--target", required=True)
    value.add_argument("--user-id", required=True)
    value.add_argument("--agent-id", required=True)
    value.add_argument("--include-user-id", action="append", default=[])
    value.add_argument("--batch-size", type=int, default=128)
    value.add_argument("--apply", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.batch_size < 1 or args.batch_size > 256:
        print("mem0-migration-error:batch-size-out-of-range", file=sys.stderr)
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
