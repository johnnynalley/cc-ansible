#!/usr/bin/env python3
"""Bounded native maintenance and recall probes for Hermes LCM."""

from __future__ import annotations

import argparse
from contextlib import closing
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any


MUTATION_CONFIRMATION = "maintain-native-hermes-lcm-astra"


def load_lcm_package(plugin_root: Path) -> None:
    init_path = plugin_root / "__init__.py"
    if not init_path.is_file():
        raise RuntimeError(f"LCM plugin entry point is missing: {init_path}")
    spec = importlib.util.spec_from_file_location(
        "hermes_lcm",
        init_path,
        submodule_search_locations=[str(plugin_root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load LCM plugin from {plugin_root}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hermes_lcm"] = module
    spec.loader.exec_module(module)


def require_mutation_approval(args: argparse.Namespace) -> None:
    if not args.approved or args.confirmation != MUTATION_CONFIRMATION:
        raise RuntimeError(
            "mutation refused: pass --approved and "
            f"--confirmation={MUTATION_CONFIRMATION}"
        )


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"database is missing: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def scalar(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    return int(row[0] or 0) if row is not None else 0


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        ).fetchall()
    }


def vector_counts_by_task(
    connection: sqlite3.Connection,
    tables: set[str],
    vector_table: str,
) -> dict[str, int]:
    profile_table = "lcm_embedding_profile"
    if vector_table not in tables or profile_table not in tables:
        return {}
    vector_columns = table_columns(connection, vector_table)
    profile_columns = table_columns(connection, profile_table)
    if "identity_hash" not in vector_columns or not {
        "identity_hash",
        "task",
    }.issubset(profile_columns):
        return {}
    conditions: list[str] = []
    if "active" in profile_columns:
        conditions.append("p.active = 1")
    if "archived_at" in profile_columns:
        conditions.append("p.archived_at IS NULL")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = connection.execute(
        "SELECT p.task, COUNT(*) AS vector_count "
        f"FROM {quote_identifier(vector_table)} AS v "
        f"JOIN {quote_identifier(profile_table)} AS p "
        "ON p.identity_hash = v.identity_hash"
        f"{where} GROUP BY p.task ORDER BY p.task"
    ).fetchall()
    return {str(row["task"]): int(row["vector_count"]) for row in rows}


def database_inventory(database: Path, state_database: Path) -> dict[str, Any]:
    with closing(connect_read_only(database)) as connection:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        selected_tables = sorted(
            table
            for table in tables
            if table in {
                "messages",
                "nodes",
                "session_lifecycle",
                "lcm_embedding_profile",
                "lcm_embeddings",
                "lcm_chunk_embeddings",
                "lcm_temporal_rollups",
                "lcm_lifecycle_state",
            }
            or table.startswith("lcm_embedding")
            or table.startswith("lcm_chunk")
            or table.startswith("lcm_rollup")
        )
        counts = {
            table: scalar(
                connection,
                f"SELECT COUNT(*) FROM {quote_identifier(table)}",
            )
            for table in selected_tables
        }
        session_coverage: dict[str, int] = {}
        for table in ("messages", "nodes", "session_lifecycle"):
            if table in tables and "session_id" in table_columns(connection, table):
                session_coverage[table] = scalar(
                    connection,
                    f"SELECT COUNT(DISTINCT session_id) FROM {quote_identifier(table)} "
                    "WHERE session_id IS NOT NULL AND session_id != ''",
                )
        profiles: list[dict[str, Any]] = []
        if "lcm_embedding_profile" in tables:
            profile_columns = table_columns(connection, "lcm_embedding_profile")
            wanted = [
                name
                for name in (
                    "provider",
                    "model_name",
                    "dim",
                    "dtype",
                    "task",
                    "active",
                    "archived_at",
                )
                if name in profile_columns
            ]
            if wanted:
                rows = connection.execute(
                    "SELECT " + ", ".join(wanted) + " FROM lcm_embedding_profile "
                    "ORDER BY task, registered_at"
                ).fetchall()
                profiles = [{name: row[name] for name in wanted} for row in rows]

        embedding_vectors_by_task = vector_counts_by_task(
            connection,
            tables,
            "lcm_embedding_vectors",
        )
        chunk_vectors_by_task = vector_counts_by_task(
            connection,
            tables,
            "lcm_chunk_vectors",
        )

        backfill_inflight: list[dict[str, Any]] = []
        backfill_inflight_summary_tokens: dict[str, int] = {}
        if "lcm_embedding_backfill_inflight" in tables:
            inflight_columns = table_columns(
                connection, "lcm_embedding_backfill_inflight"
            )
            if {"state", "last_error"}.issubset(inflight_columns):
                rows = connection.execute(
                    "SELECT state, COALESCE(last_error, '') AS last_error, "
                    "COUNT(*) AS row_count "
                    "FROM lcm_embedding_backfill_inflight "
                    "GROUP BY state, COALESCE(last_error, '') "
                    "ORDER BY state, last_error"
                ).fetchall()
                backfill_inflight = [
                    {
                        "state": str(row["state"]),
                        "rows": int(row["row_count"]),
                        "last_error": (
                            str(row["last_error"])[:500]
                            if row["last_error"]
                            else None
                        ),
                    }
                    for row in rows
                ]
            if "summary_nodes" in tables:
                node_columns = table_columns(connection, "summary_nodes")
                if {"node_id", "token_count"}.issubset(node_columns):
                    row = connection.execute(
                        "SELECT COUNT(*) AS row_count, "
                        "COALESCE(MIN(n.token_count), 0) AS min_tokens, "
                        "COALESCE(MAX(n.token_count), 0) AS max_tokens, "
                        "COALESCE(SUM(CASE WHEN n.token_count > 4096 "
                        "THEN 1 ELSE 0 END), 0) AS over_4096 "
                        "FROM lcm_embedding_backfill_inflight AS i "
                        "JOIN summary_nodes AS n "
                        "ON CAST(n.node_id AS TEXT) = i.embedded_id "
                        "WHERE i.state = 'uncertain'"
                    ).fetchone()
                    backfill_inflight_summary_tokens = {
                        "rows": int(row["row_count"]),
                        "min_tokens": int(row["min_tokens"]),
                        "max_tokens": int(row["max_tokens"]),
                        "over_4096": int(row["over_4096"]),
                    }

    state_inventory: dict[str, Any] = {"present": state_database.is_file()}
    if state_database.is_file():
        with closing(connect_read_only(state_database)) as connection:
            state_inventory["quick_check"] = str(
                connection.execute("PRAGMA quick_check").fetchone()[0]
            )
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            state_inventory["tables"] = {
                table: {
                    "rows": scalar(
                        connection,
                        f"SELECT COUNT(*) FROM {quote_identifier(table)}",
                    ),
                    "distinct_session_ids": (
                        scalar(
                            connection,
                            f"SELECT COUNT(DISTINCT session_id) FROM {quote_identifier(table)} "
                            "WHERE session_id IS NOT NULL AND session_id != ''",
                        )
                        if "session_id" in table_columns(connection, table)
                        else None
                    ),
                }
                for table in sorted(tables)
                if not table.startswith("sqlite_")
            }

    return {
        "database": str(database),
        "database_bytes": database.stat().st_size,
        "quick_check": quick_check,
        "tables": counts,
        "distinct_sessions": session_coverage,
        "embedding_profiles": profiles,
        "embedding_vectors_by_task": embedding_vectors_by_task,
        "chunk_vectors_by_task": chunk_vectors_by_task,
        "backfill_inflight": backfill_inflight,
        "backfill_inflight_summary_tokens": backfill_inflight_summary_tokens,
        "state_database": state_inventory,
    }


def chunk_metadata_mismatches(
    connection: sqlite3.Connection,
    identity_hash: str,
    chunker: Any,
    policy: str,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """Return content-private chunk rows whose persisted spans are stale."""
    rows = connection.execute(
        "SELECT chunk_id, store_id, chunk_index, char_start, char_end, "
        "token_estimate FROM lcm_chunk_meta "
        "WHERE identity_hash = ? AND archived = 0 "
        "ORDER BY store_id, chunk_index",
        (identity_hash,),
    ).fetchall()
    by_store: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_store.setdefault(int(row["store_id"]), []).append(row)

    mismatches: list[dict[str, Any]] = []
    missing = 0
    max_chars = 0
    max_tokens = 0
    for store_id, metadata in by_store.items():
        message = connection.execute(
            "SELECT role, content FROM messages WHERE store_id = ?", (store_id,)
        ).fetchone()
        if message is None:
            missing += len(metadata)
            continue
        expected = {
            int(chunk.chunk_index): chunk
            for chunk in chunker(
                store_id,
                message["role"],
                message["content"],
                policy=policy,
            )
        }
        for row in metadata:
            chunk = expected.get(int(row["chunk_index"]))
            if chunk is None:
                missing += 1
                continue
            max_chars = max(max_chars, len(chunk.text))
            max_tokens = max(max_tokens, int(chunk.token_estimate))
            if (
                int(row["char_start"]) == int(chunk.char_start)
                and int(row["char_end"]) == int(chunk.char_end)
                and int(row["token_estimate"]) == int(chunk.token_estimate)
            ):
                continue
            mismatches.append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "text": str(chunk.text),
                    "store_id": store_id,
                    "chunk_index": int(chunk.chunk_index),
                    "char_start": int(chunk.char_start),
                    "char_end": int(chunk.char_end),
                    "token_estimate": int(chunk.token_estimate),
                }
            )
    return mismatches, missing, {
        "metadata_rows": len(rows),
        "source_messages": len(by_store),
        "max_reconstructed_chars": max_chars,
        "max_reconstructed_tokens": max_tokens,
    }


def reconcile_chunk_metadata(
    engine: Any,
    database: Path,
    *,
    policy: str,
    apply: bool,
    limit: int,
) -> dict[str, Any]:
    """Re-embed only active chunk rows made stale by chunk-boundary changes."""
    from hermes_lcm.chunking import chunk_message, normalize_content_policy
    from hermes_lcm.embedding_provider import resolve_provider
    from hermes_lcm.vector_store import EmbeddingIdentity, VectorStore

    normalized_policy = normalize_content_policy(policy)
    with closing(connect_read_only(database)) as connection:
        profile = connection.execute(
            "SELECT identity_hash, provider, model_name, revision, dim, dtype, "
            "byteorder FROM lcm_embedding_profile "
            "WHERE active = 1 AND archived_at IS NULL AND task = 'chunk' "
            "ORDER BY registered_at DESC, identity_hash DESC LIMIT 1"
        ).fetchone()
        if profile is None:
            raise RuntimeError("active chunk embedding profile is missing")
        mismatches, missing, metrics = chunk_metadata_mismatches(
            connection,
            str(profile["identity_hash"]),
            chunk_message,
            normalized_policy,
        )

    report: dict[str, Any] = {
        "status": "ready" if mismatches else "current",
        "mode": "apply" if apply else "dry-run",
        "policy": normalized_policy,
        "mismatched_rows": len(mismatches),
        "missing_reconstruction_rows": missing,
        "repaired_rows": 0,
        **metrics,
    }
    if not apply or not mismatches:
        return report
    if missing:
        raise RuntimeError(
            "chunk metadata reconciliation refused: source reconstruction is missing"
        )
    if len(mismatches) > limit:
        raise RuntimeError(
            "chunk metadata reconciliation refused: "
            f"mismatches={len(mismatches)} exceeds limit={limit}"
        )

    provider_name = str(profile["provider"] or "").strip().lower()
    if provider_name not in {"fastembed", "ollama"}:
        raise RuntimeError(
            "chunk metadata reconciliation requires a local embedding provider"
        )
    model = str(profile["model_name"] or "").strip()
    provider_config = dataclasses.replace(engine._config, embedding_model=model)
    provider = resolve_provider(provider_config, for_backfill=True)
    if provider is None or str(provider.provider_id).lower() != provider_name:
        raise RuntimeError("active chunk embedding provider could not be resolved")
    vectors = provider.embed_documents([row["text"] for row in mismatches])
    if len(vectors) != len(mismatches):
        raise RuntimeError("embedding provider returned an incomplete repair batch")

    identity = EmbeddingIdentity.canonical(
        provider_name,
        model,
        str(profile["revision"] or ""),
        int(profile["dim"]),
        str(profile["dtype"] or "float32"),
        str(profile["byteorder"] or "little"),
        "chunk",
    )
    if identity.identity_hash != str(profile["identity_hash"]):
        raise RuntimeError("active chunk embedding identity changed before repair")
    store = VectorStore(database, config=engine._config)
    try:
        for row, vector in zip(mismatches, vectors):
            store.record_chunk_embedding(
                row["chunk_id"],
                model,
                vector,
                store_id=row["store_id"],
                chunk_index=row["chunk_index"],
                char_start=row["char_start"],
                char_end=row["char_end"],
                token_estimate=row["token_estimate"],
                identity=identity,
            )
            report["repaired_rows"] += 1
    finally:
        store.close()
    report["status"] = "complete"
    return report


def continuity_audit(database: Path, state_database: Path) -> dict[str, Any]:
    """Report lifecycle/session continuity without emitting IDs or content."""
    now = time.time()
    with closing(connect_read_only(database)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        message_sessions = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT session_id FROM messages "
                "WHERE session_id IS NOT NULL AND session_id != ''"
            ).fetchall()
        }
        node_sessions = (
            {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT session_id FROM summary_nodes "
                    "WHERE session_id IS NOT NULL AND session_id != ''"
                ).fetchall()
            }
            if "summary_nodes" in tables
            else set()
        )
        lcm_sessions = message_sessions | node_sessions
        recent_message_sessions = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT session_id FROM messages "
                "WHERE session_id IS NOT NULL AND session_id != '' AND timestamp >= ?",
                (now - 86400.0,),
            ).fetchall()
        }

        lifecycle_rows = []
        if "lcm_lifecycle_state" in tables:
            lifecycle_rows = connection.execute(
                "SELECT current_session_id, last_finalized_session_id, updated_at "
                "FROM lcm_lifecycle_state"
            ).fetchall()
        empty_rows: list[sqlite3.Row] = []
        empty_refs: set[str] = set()
        for row in lifecycle_rows:
            refs = {
                str(value)
                for value in (
                    row["current_session_id"],
                    row["last_finalized_session_id"],
                )
                if value
            }
            if not refs or refs.isdisjoint(lcm_sessions):
                empty_rows.append(row)
                empty_refs.update(refs)
        empty_ages = [
            max(0.0, (now - float(row["updated_at"])) / 3600.0)
            for row in empty_rows
            if row["updated_at"] is not None
        ]

        rollup_counts: dict[str, dict[str, int]] = {}
        if "lcm_rollups" in tables:
            rollup_columns = table_columns(connection, "lcm_rollups")
            if {"period_kind", "status"}.issubset(rollup_columns):
                rows = connection.execute(
                    "SELECT period_kind, status, COUNT(*) AS row_count "
                    "FROM lcm_rollups GROUP BY period_kind, status "
                    "ORDER BY period_kind, status"
                ).fetchall()
                for row in rows:
                    rollup_counts.setdefault(str(row["period_kind"]), {})[
                        str(row["status"])
                    ] = int(row["row_count"])

    state_sessions: set[str] = set()
    if state_database.is_file():
        with closing(connect_read_only(state_database)) as connection:
            session_columns = table_columns(connection, "sessions")
            id_column = "id" if "id" in session_columns else "session_id"
            state_sessions = {
                str(row[0])
                for row in connection.execute(
                    f"SELECT {quote_identifier(id_column)} FROM sessions "
                    f"WHERE {quote_identifier(id_column)} IS NOT NULL "
                    f"AND {quote_identifier(id_column)} != ''"
                ).fetchall()
            }

    return {
        "read_only": True,
        "lcm_message_sessions": len(message_sessions),
        "lcm_node_sessions": len(node_sessions),
        "state_sessions": len(state_sessions),
        "state_lcm_overlap": len(state_sessions & lcm_sessions),
        "state_only_sessions": len(state_sessions - lcm_sessions),
        "lcm_only_sessions": len(lcm_sessions - state_sessions),
        "recent_lcm_message_sessions_24h": len(recent_message_sessions),
        "recent_lcm_sessions_present_in_state": len(
            recent_message_sessions & state_sessions
        ),
        "recent_lcm_sessions_missing_in_state": len(
            recent_message_sessions - state_sessions
        ),
        "lifecycle_rows": len(lifecycle_rows),
        "empty_lifecycle_rows": len(empty_rows),
        "empty_lifecycle_refs": len(empty_refs),
        "empty_refs_present_in_state": len(empty_refs & state_sessions),
        "empty_rows_younger_than_24h": sum(age < 24.0 for age in empty_ages),
        "empty_row_age_hours_min": round(min(empty_ages), 2) if empty_ages else None,
        "empty_row_age_hours_max": round(max(empty_ages), 2) if empty_ages else None,
        "temporal_rollups": rollup_counts,
    }


def backup_database(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise RuntimeError(f"backup destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise RuntimeError(f"backup parent is missing: {destination.parent}")
    source_connection = connect_read_only(source)
    destination_connection: sqlite3.Connection | None = None
    try:
        destination_connection = sqlite3.connect(destination)
        source_connection.backup(destination_connection)
        destination_connection.commit()
        quick_check = str(
            destination_connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        if quick_check != "ok":
            raise RuntimeError(f"backup quick_check failed: {quick_check}")
    except Exception:
        if destination_connection is not None:
            destination_connection.close()
            destination_connection = None
        destination.unlink(missing_ok=True)
        raise
    finally:
        source_connection.close()
        if destination_connection is not None:
            destination_connection.close()
    digest = hashlib.sha256()
    with destination.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "source": str(source),
        "destination": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": digest.hexdigest(),
        "quick_check": quick_check,
    }


def sanitized_retrieval_result(raw: str, query: str) -> dict[str, Any]:
    payload = json.loads(raw)
    results = (
        payload.get("results")
        or payload.get("memories")
        or payload.get("hits")
        or []
    )
    if not isinstance(results, list):
        results = []
    sessions = sorted(
        {
            str(item.get("session_id"))
            for item in results
            if isinstance(item, dict) and item.get("session_id")
        }
    )
    types: dict[str, int] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        result_type = str(item.get("type") or item.get("kind") or "unknown")
        types[result_type] = types.get(result_type, 0) + 1
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    coverage = payload.get("coverage")
    if coverage is None:
        coverage = provenance.get("coverage")
    return {
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "result_count": len(results),
        "result_types": types,
        "distinct_result_sessions": len(sessions),
        "coverage": coverage,
        "degraded": bool(payload.get("degraded", False)),
        "degraded_to_fts": bool(payload.get("degraded_to_fts", False)),
        "degraded_reason": payload.get("degraded_reason"),
        "provenance": {
            key: provenance.get(key)
            for key in (
                "arms",
                "arms_run",
                "arm_weights",
                "fallback",
                "rollups",
                "scope",
            )
            if key in provenance
        },
    }


def embedded_summary_query(database: Path, max_terms: int = 12) -> str:
    with closing(connect_read_only(database)) as connection:
        row = connection.execute(
            "SELECT n.summary "
            "FROM lcm_embedding_vectors AS v "
            "JOIN lcm_embedding_profile AS p "
            "ON p.identity_hash = v.identity_hash "
            "JOIN summary_nodes AS n "
            "ON CAST(n.node_id AS TEXT) = v.embedded_id "
            "WHERE p.task = 'summary' AND p.active = 1 "
            "AND p.archived_at IS NULL "
            "AND LENGTH(TRIM(n.summary)) >= 32 "
            "ORDER BY n.token_count DESC, n.node_id "
            "LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("no active embedded summary is available for recall smoke")
    terms = [
        term
        for term in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", str(row[0]))
        if term.upper() not in {"AND", "OR", "NOT", "NEAR"}
    ]
    query = " ".join(terms[:max_terms])
    if len(terms) < 3:
        raise RuntimeError("embedded summary recall smoke lacks usable query terms")
    return query


def proactive_recall_smoke(engine: Any, database: Path) -> dict[str, Any]:
    """Exercise native proactive assembly while returning no retained content."""
    query = embedded_summary_query(database)
    message = engine._build_proactive_recall_message(
        [{"role": "user", "content": query}],
        "user",
        set(),
    )
    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    return {
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "generated": bool(content),
        "wrapped": bool(
            content.startswith("<relevant-memories>")
            and content.endswith("</relevant-memories>")
        ),
        "injected": int(engine._proactive_recall_injected_count or 0),
        "skipped": int(engine._proactive_recall_skipped_count or 0),
        "timeout": int(engine._proactive_recall_timeout_count or 0),
        "content_sha256": (
            hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None
        ),
    }


def parse_backfill_report(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {
            "status",
            "pending",
            "selected",
            "embedded",
            "skipped_overcap",
            "failed",
            "in_flight",
            "uncertain_remote_acceptance",
            "remaining",
            "tokens_consumed",
            "error",
        }:
            result[key.strip()] = value.strip()
    return result


def build_backfill_command(args: argparse.Namespace) -> str:
    if args.retry_uncertain and not args.apply:
        raise RuntimeError("--retry-uncertain requires --apply")
    command = f"embed backfill --corpus {args.corpus} --limit {args.limit}"
    if args.policy:
        command += f" --policy {args.policy}"
    if args.apply:
        command += " --apply"
    if args.retry_uncertain:
        command += " --retry-uncertain"
    return command


def backfill_progress_stalled(*, embedded: int, pending: int) -> bool:
    """A live corpus progresses when rows embed, even if new rows add debt."""
    return pending > 0 and embedded < 1


def build_engine(args: argparse.Namespace):
    os.environ["HERMES_HOME"] = str(args.hermes_home)
    os.environ["LCM_DATABASE_PATH"] = str(args.database)
    load_lcm_package(args.plugin_root)
    from hermes_lcm.config import LCMConfig
    from hermes_lcm.engine import LCMEngine

    return LCMEngine(config=LCMConfig.from_env(), hermes_home=str(args.hermes_home))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "inventory",
            "continuity-audit",
            "config",
            "doctor",
            "doctor-summary",
            "backup",
            "warmup",
            "backfill",
            "backfill-all",
            "backfill-bounded",
            "recall-smoke",
            "recall-embedded-smoke",
            "proactive-smoke",
            "grep-smoke",
            "reconcile-chunks",
        ),
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=Path("/usr/local/share/hermes-plugins/hermes-lcm"),
    )
    parser.add_argument(
        "--hermes-home",
        type=Path,
        default=Path("/var/lib/hermes/astra/.hermes/profiles/astra"),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("/var/lib/hermes/astra/.hermes/profiles/astra/lcm.db"),
    )
    parser.add_argument(
        "--state-database",
        type=Path,
        default=Path("/var/lib/hermes/astra/.hermes/profiles/astra/state.db"),
    )
    parser.add_argument("--corpus", choices=("summary", "chunks"), default="summary")
    parser.add_argument("--policy", choices=("conversational", "heads", "full"))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-passes", type=int, default=1000)
    parser.add_argument("--query")
    parser.add_argument("--backup-destination", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--retry-uncertain", action="store_true")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()

    if args.limit < 1 or args.max_passes < 1:
        parser.error("--limit and --max-passes must be positive")

    if args.operation == "inventory":
        print(json.dumps(database_inventory(args.database, args.state_database), sort_keys=True))
        return 0

    if args.operation == "continuity-audit":
        print(json.dumps(continuity_audit(args.database, args.state_database), sort_keys=True))
        return 0

    if args.operation in {"backup", "warmup"} or (
        args.operation in {"backfill", "backfill-all", "backfill-bounded"}
        and args.apply
    ) or (args.operation == "reconcile-chunks" and args.apply):
        require_mutation_approval(args)

    if args.operation == "backup":
        if args.backup_destination is None:
            parser.error("backup requires --backup-destination")
        print(
            json.dumps(
                backup_database(args.database, args.backup_destination),
                sort_keys=True,
            )
        )
        return 0

    engine = build_engine(args)
    try:
        from hermes_lcm.command import handle_lcm_command

        if args.operation == "reconcile-chunks":
            print(
                json.dumps(
                    reconcile_chunk_metadata(
                        engine,
                        args.database,
                        policy=args.policy or "conversational",
                        apply=args.apply,
                        limit=args.limit,
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if args.operation == "config":
            config = engine._config
            print(
                json.dumps(
                    {
                        "embeddings_enabled": bool(config.embeddings_enabled),
                        "embedding_provider": config.embedding_provider,
                        "embedding_model": config.embedding_model,
                        "embedding_storage_dtype": config.embedding_storage_dtype,
                        "embedding_store_dim": config.embedding_store_dim,
                        "embedding_binary_prescreen": bool(
                            config.embedding_binary_prescreen
                        ),
                        "embedding_content_policy": config.embedding_content_policy,
                        "embedding_query_timeout_s": (
                            config.embedding_query_timeout_s
                        ),
                        "recall_query_timeout_s": config.recall_query_timeout_s,
                        "embedding_backfill_timeout_s": (
                            config.embedding_backfill_timeout_s
                        ),
                        "proactive_recall_enabled": bool(
                            config.proactive_recall_enabled
                        ),
                        "temporal_rollups_enabled": bool(
                            config.temporal_rollups_enabled
                        ),
                        "ollama_base_url": config.ollama_base_url,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.operation in {"doctor", "doctor-summary"}:
            raw = engine.handle_tool_call("lcm_doctor", {})
            if args.operation == "doctor":
                print(raw)
                return 0
            payload = json.loads(raw)
            checks = payload.get("checks") or []
            statuses = {
                str(item.get("check")): str(item.get("status"))
                for item in checks
                if isinstance(item, dict)
            }
            lifecycle = next(
                (
                    item.get("detail") or {}
                    for item in checks
                    if isinstance(item, dict)
                    and item.get("check") == "lifecycle_fragmentation"
                ),
                {},
            )
            print(
                json.dumps(
                    {
                        "overall": payload.get("overall"),
                        "checks": statuses,
                        "lifecycle": {
                            key: lifecycle.get(key)
                            for key in (
                                "empty_lifecycle_rows",
                                "distinct_message_sessions",
                                "distinct_node_sessions",
                                "state_sessions_total",
                                "lcm_message_sessions_missing_in_state",
                                "state_sessions_missing_in_lcm_any",
                            )
                        },
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.operation == "proactive-smoke":
            print(
                json.dumps(
                    proactive_recall_smoke(engine, args.database),
                    sort_keys=True,
                )
            )
            return 0
        if args.operation == "warmup":
            output = handle_lcm_command("embed warmup", engine)
        elif args.operation in {"backfill", "backfill-all", "backfill-bounded"}:
            command = build_backfill_command(args)
            if args.operation == "backfill":
                output = handle_lcm_command(command, engine)
            else:
                if not args.apply:
                    parser.error(
                        f"{args.operation} requires --apply"
                    )
                previous_remaining: int | None = None
                total_embedded = 0
                output = ""
                for pass_number in range(1, args.max_passes + 1):
                    output = handle_lcm_command(command, engine)
                    report = parse_backfill_report(output)
                    status = report.get("status", "")
                    if status in {"error", "refused", "failed"}:
                        raise RuntimeError(
                            f"{args.corpus} backfill stopped with status={status}: "
                            f"{report.get('error', 'no error detail')}"
                        )
                    failed = int(report.get("failed", "0") or 0)
                    skipped = int(report.get("skipped_overcap", "0") or 0)
                    uncertain = int(
                        report.get("uncertain_remote_acceptance", "0") or 0
                    )
                    if failed or skipped or (uncertain and not args.retry_uncertain):
                        raise RuntimeError(
                            f"{args.corpus} backfill requires review: "
                            f"failed={failed} skipped={skipped} uncertain={uncertain}"
                        )
                    embedded = int(report.get("embedded", "0") or 0)
                    remaining = int(report.get("remaining", "-1") or -1)
                    total_embedded += embedded
                    if args.retry_uncertain:
                        if uncertain == 0:
                            print(
                                json.dumps(
                                    {
                                        "status": "complete",
                                        "corpus": args.corpus,
                                        "passes": pass_number,
                                        "embedded": total_embedded,
                                        "remaining_uncertain": 0,
                                    },
                                    sort_keys=True,
                                )
                            )
                            return 0
                        if backfill_progress_stalled(
                            embedded=embedded,
                            pending=uncertain,
                        ):
                            raise RuntimeError(
                                f"{args.corpus} uncertain retry made no progress: "
                                f"embedded={embedded} uncertain={uncertain}"
                            )
                        continue
                    if remaining == 0:
                        print(
                            json.dumps(
                                {
                                    "status": "complete",
                                    "corpus": args.corpus,
                                    "passes": pass_number,
                                    "embedded": total_embedded,
                                    "remaining": 0,
                                },
                                sort_keys=True,
                            )
                        )
                        return 0
                    if backfill_progress_stalled(
                        embedded=embedded,
                        pending=remaining,
                    ):
                        raise RuntimeError(
                            f"{args.corpus} backfill made no progress: "
                            f"embedded={embedded} remaining={remaining}"
                        )
                    previous_remaining = remaining
                if args.operation == "backfill-bounded":
                    print(
                        json.dumps(
                            {
                                "status": "partial",
                                "corpus": args.corpus,
                                "passes": args.max_passes,
                                "embedded": total_embedded,
                                "remaining": previous_remaining,
                            },
                            sort_keys=True,
                        )
                    )
                    return 0
                raise RuntimeError(
                    f"{args.corpus} backfill exceeded {args.max_passes} passes"
                )
        elif args.operation in {
            "recall-smoke",
            "recall-embedded-smoke",
            "grep-smoke",
        }:
            if args.operation == "recall-embedded-smoke":
                query = embedded_summary_query(args.database)
            elif not args.query:
                parser.error(f"{args.operation} requires --query")
            else:
                query = args.query
            if args.operation in {"recall-smoke", "recall-embedded-smoke"}:
                raw = engine.handle_tool_call(
                    "lcm_recall", {"query": query, "limit": min(args.limit, 25)}
                )
            else:
                raw = engine.handle_tool_call(
                    "lcm_grep",
                    {
                        "query": query,
                        "limit": min(args.limit, 200),
                        "mode": "full_text",
                        "session_scope": "all",
                    },
                )
            print(json.dumps(sanitized_retrieval_result(raw, query), sort_keys=True))
            return 0
        else:  # pragma: no cover - argparse choices keep this unreachable
            raise RuntimeError(f"unsupported operation: {args.operation}")

        print(output)
        lowered = output.lower()
        if "status: error" in lowered or "status: refused" in lowered:
            return 1
        if args.apply and "status: failed" in lowered:
            return 1
        if args.operation == "backfill" and args.apply:
            report = parse_backfill_report(output)
            if any(
                int(report.get(key, "0") or 0) > 0
                for key in (
                    "failed",
                    "skipped_overcap",
                    "uncertain_remote_acceptance",
                )
            ):
                return 1
        return 0
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"hermes-lcm-maintenance-error:{exc}", file=sys.stderr)
        raise SystemExit(1)
