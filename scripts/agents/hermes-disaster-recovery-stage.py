#!/usr/bin/env python3
"""Stage and verify application-consistent Hermes recovery artifacts."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
PRUNED_DIRECTORY_NAMES = {
    ".cache",
    ".npm",
    "backups",
    "cache",
    "legacy-openclaw",
    "node_modules",
    "state-snapshots",
    "staging",
    "workspaces",
}


class BackupError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise BackupError(f"unsafe-symlink:{path}")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise BackupError(f"not-directory:{path}")
    os.chmod(path, 0o700)


def request_json(
    base_url: str,
    path: str,
    method: str = "GET",
    *,
    body: dict | None = None,
    require_status: bool = True,
) -> dict:
    data = None
    if method != "GET":
        data = json.dumps(body).encode() if body is not None else b""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise BackupError(
            f"qdrant-{method.lower()}-failed:{path}:{type(exc).__name__}"
        ) from exc
    if require_status and payload.get("status") != "ok":
        raise BackupError(f"qdrant-status-not-ok:{path}")
    return payload


def qdrant_point_counts(base_url: str, collections: list[str]) -> dict[str, int]:
    counts = {}
    for name in collections:
        payload = request_json(
            base_url,
            f"/collections/{urllib.parse.quote(name, safe='')}/points/count",
            method="POST",
            body={"exact": True},
        ).get("result", {})
        count = payload.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise BackupError(f"qdrant-invalid-point-count:{name}")
        counts[name] = count
    return counts


def qdrant_versions_compatible(source: str, restored: str) -> bool:
    pattern = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
    source_match = pattern.fullmatch(source)
    restored_match = pattern.fullmatch(restored)
    if source_match is None or restored_match is None:
        return False
    source_major, source_minor, _ = map(int, source_match.groups())
    restored_major, restored_minor, _ = map(int, restored_match.groups())
    return restored_major == source_major and restored_minor in {
        source_minor,
        source_minor + 1,
    }


def download_file(url: str, target: Path) -> None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=300) as response, target.open(
            "wb"
        ) as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, urllib.error.URLError) as exc:
        raise BackupError(f"download-failed:{type(exc).__name__}") from exc


def discover_profiles(hermes_root: Path) -> list[tuple[str, Path]]:
    profiles: list[tuple[str, Path]] = []
    if not hermes_root.is_dir() or hermes_root.is_symlink():
        raise BackupError(f"invalid-hermes-root:{hermes_root}")
    for account_home in sorted(hermes_root.iterdir()):
        name = account_home.name
        if not PROFILE_NAME.fullmatch(name) or account_home.is_symlink():
            continue
        profile_home = account_home / ".hermes" / "profiles" / name
        if profile_home.is_dir() and not profile_home.is_symlink():
            profiles.append((name, profile_home))
    if not profiles:
        raise BackupError("no-hermes-profiles")
    return profiles


def refresh_native_backup(name: str) -> None:
    result = subprocess.run(
        [
            "/usr/bin/systemctl",
            "start",
            "--wait",
            f"hermes-profile-backup@{name}.service",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=1800,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError(f"native-backup-failed:{name}:rc={result.returncode}")


def stage_native_backups(
    profiles: list[tuple[str, Path]], stage: Path, refresh: bool
) -> list[dict]:
    destination_root = stage / "native-profile-backups"
    destination_root.mkdir(mode=0o700)
    rows = []
    for name, profile_home in profiles:
        if refresh:
            refresh_native_backup(name)
        source = profile_home / "backups" / "nightly.zip"
        if source.is_symlink() or not source.is_file():
            raise BackupError(f"native-backup-missing:{name}")
        target = destination_root / f"{name}.zip"
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        with zipfile.ZipFile(target) as archive:
            corrupt = archive.testzip()
            entry_count = len(archive.infolist())
        if corrupt is not None:
            raise BackupError(f"native-backup-corrupt:{name}")
        rows.append(
            {
                "profile": name,
                "artifact": str(target.relative_to(stage)),
                "bytes": target.stat().st_size,
                "entries": entry_count,
                "sha256": sha256_file(target),
            }
        )
    return rows


def should_prune(path: Path) -> bool:
    if path.name in PRUNED_DIRECTORY_NAMES:
        return True
    return path.parts[-3:] == (".local", "share", "containers")


def discover_sqlite_databases(roots: list[Path]) -> list[tuple[Path, Path]]:
    databases: dict[Path, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise BackupError(f"invalid-sqlite-root:{root}")
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            kept = []
            for dirname in dirnames:
                candidate = directory_path / dirname
                if candidate.is_symlink() or should_prune(candidate):
                    continue
                kept.append(dirname)
            dirnames[:] = kept
            for filename in filenames:
                if not filename.endswith(".db"):
                    continue
                source = directory_path / filename
                if source.is_symlink() or not source.is_file():
                    raise BackupError(f"unsafe-sqlite-source:{source}")
                databases[source.resolve()] = source
    return sorted(
        (source, source.relative_to("/")) for source in databases.values()
    )


def backup_sqlite(source: Path, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{urllib.parse.quote(str(source))}?mode=ro"
    try:
        source_db = sqlite3.connect(source_uri, uri=True, timeout=60)
        target_db = sqlite3.connect(target)
        with source_db, target_db:
            source_db.backup(target_db, pages=4096, sleep=0.01)
        source_db.close()
        check = target_db.execute("PRAGMA quick_check").fetchone()
        target_db.close()
    except sqlite3.Error as exc:
        with contextlib.suppress(OSError):
            target.unlink()
        raise BackupError(
            f"sqlite-backup-failed:{source}:{type(exc).__name__}"
        ) from exc
    if not check or check[0] != "ok":
        raise BackupError(f"sqlite-quick-check-failed:{source}")
    os.chmod(target, 0o600)
    return {
        "source": str(source),
        "artifact": str(target),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "quickCheck": "ok",
    }


def stage_sqlite(databases: list[tuple[Path, Path]], stage: Path) -> list[dict]:
    rows = []
    for source, relative in databases:
        target = stage / "sqlite" / relative
        row = backup_sqlite(source, target)
        row["artifact"] = str(target.relative_to(stage))
        rows.append(row)
    return rows


def stage_qdrant(base_url: str, stage: Path) -> dict:
    root = request_json(base_url, "/", require_status=False)
    cluster = request_json(base_url, "/cluster").get("result", {})
    if cluster.get("status") != "disabled":
        raise BackupError("qdrant-full-snapshot-requires-single-node")
    collections_payload = request_json(base_url, "/collections").get("result", {})
    collections = sorted(
        row["name"]
        for row in collections_payload.get("collections", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    )
    counts_before = qdrant_point_counts(base_url, collections)
    snapshot = request_json(
        base_url, "/snapshots?wait=true", method="POST"
    ).get("result", {})
    name = snapshot.get("name")
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or not name.endswith(".snapshot")
    ):
        raise BackupError("qdrant-invalid-snapshot-name")
    counts_after = qdrant_point_counts(base_url, collections)
    if counts_after != counts_before:
        with contextlib.suppress(BackupError):
            request_json(
                base_url,
                f"/snapshots/{urllib.parse.quote(name)}",
                method="DELETE",
            )
        raise BackupError("qdrant-point-count-changed-during-snapshot")
    target = stage / "qdrant" / name
    target.parent.mkdir(mode=0o700)
    download_file(
        f"{base_url.rstrip('/')}/snapshots/{urllib.parse.quote(name)}", target
    )
    os.chmod(target, 0o600)
    digest = sha256_file(target)
    expected = snapshot.get("checksum")
    if expected and expected != digest:
        raise BackupError("qdrant-snapshot-checksum-mismatch")
    cleanup_warning = None
    try:
        request_json(
            base_url, f"/snapshots/{urllib.parse.quote(name)}", method="DELETE"
        )
    except BackupError as exc:
        cleanup_warning = str(exc)
    return {
        "version": root.get("version"),
        "commit": root.get("commit"),
        "clusterStatus": cluster.get("status"),
        "collections": collections,
        "pointCounts": counts_after,
        "artifact": str(target.relative_to(stage)),
        "bytes": target.stat().st_size,
        "sha256": digest,
        "reportedChecksum": expected,
        "sourceSnapshotCleanupWarning": cleanup_warning,
    }


def verify_qdrant_restore(stage: Path, base_url: str) -> dict:
    verified = verify_stage(stage)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    expected = manifest.get("qdrant", {})
    expected_collections = expected.get("collections")
    expected_counts = expected.get("pointCounts")
    if not isinstance(expected_collections, list) or not isinstance(
        expected_counts, dict
    ):
        raise BackupError("qdrant-restore-contract-missing")
    root = request_json(base_url, "/", require_status=False)
    source_version = expected.get("version")
    restored_version = root.get("version")
    if not isinstance(source_version, str) or not isinstance(
        restored_version, str
    ):
        raise BackupError("qdrant-restore-version-missing")
    if not qdrant_versions_compatible(source_version, restored_version):
        raise BackupError("qdrant-restore-version-incompatible")
    payload = request_json(base_url, "/collections").get("result", {})
    restored_collections = sorted(
        row["name"]
        for row in payload.get("collections", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    )
    if restored_collections != expected_collections:
        raise BackupError("qdrant-restore-collection-mismatch")
    restored_counts = qdrant_point_counts(base_url, restored_collections)
    if restored_counts != expected_counts:
        raise BackupError("qdrant-restore-point-count-mismatch")
    return {
        **verified,
        "qdrantRestore": "ok",
        "qdrantVersion": restored_version,
        "qdrantPoints": sum(restored_counts.values()),
    }


def verify_stage(stage: Path) -> dict:
    manifest_path = stage / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupError("manifest-missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        raise BackupError("manifest-schema")
    checked = 0
    for section in ("nativeProfileBackups", "sqliteBackups"):
        for row in manifest.get(section, []):
            artifact = stage / row["artifact"]
            if artifact.is_symlink() or not artifact.is_file():
                raise BackupError(f"artifact-missing:{row['artifact']}")
            if sha256_file(artifact) != row["sha256"]:
                raise BackupError(f"artifact-hash:{row['artifact']}")
            checked += 1
            if section == "nativeProfileBackups":
                with zipfile.ZipFile(artifact) as archive:
                    if archive.testzip() is not None:
                        raise BackupError(
                            f"native-backup-corrupt:{row['profile']}"
                        )
            else:
                database = sqlite3.connect(
                    f"file:{urllib.parse.quote(str(artifact))}?mode=ro", uri=True
                )
                result = database.execute("PRAGMA quick_check").fetchone()
                database.close()
                if not result or result[0] != "ok":
                    raise BackupError(f"sqlite-quick-check:{row['artifact']}")
    qdrant = manifest.get("qdrant", {})
    qdrant_artifact = stage / qdrant.get("artifact", "")
    if qdrant_artifact.is_symlink() or not qdrant_artifact.is_file():
        raise BackupError("qdrant-artifact-missing")
    if sha256_file(qdrant_artifact) != qdrant.get("sha256"):
        raise BackupError("qdrant-artifact-hash")
    checked += 1
    return {
        "status": "ok",
        "artifacts": checked,
        "profiles": len(manifest.get("nativeProfileBackups", [])),
        "sqlite": len(manifest.get("sqliteBackups", [])),
        "qdrantCollections": len(qdrant.get("collections", [])),
        "createdAt": manifest.get("createdAt"),
    }


def write_status(
    path: Path,
    result: str,
    phase: str,
    exit_code: int = 0,
    detail: str | None = None,
) -> None:
    payload = {
        "schemaVersion": 1,
        "updatedAt": utc_now(),
        "result": result,
        "phase": phase,
        "exitCode": exit_code,
    }
    if detail:
        payload["detail"] = detail[:240]
    write_json_atomic(path, payload, mode=0o644)


def stage_backup(args: argparse.Namespace) -> dict:
    ensure_private_directory(args.stage_root)
    profiles = discover_profiles(args.hermes_root)
    lock_path = args.stage_root / ".lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        partial = Path(
            tempfile.mkdtemp(prefix=".partial-", dir=args.stage_root)
        )
        os.chmod(partial, 0o700)
        try:
            native = stage_native_backups(
                profiles, partial, not args.no_refresh_native
            )
            sqlite_roots = [
                profile.parent.parent.parent for _, profile in profiles
            ]
            sqlite_roots.append(args.automation_root)
            databases = discover_sqlite_databases(sqlite_roots)
            sqlite_rows = stage_sqlite(databases, partial)
            qdrant = stage_qdrant(args.qdrant_url, partial)
            manifest = {
                "schemaVersion": 1,
                "createdAt": utc_now(),
                "host": os.uname().nodename,
                "nativeProfileBackups": native,
                "sqliteBackups": sqlite_rows,
                "qdrant": qdrant,
                "resticDirectRoots": [
                    str(args.hermes_root),
                    str(args.automation_root),
                    "/etc/hermes",
                ],
            }
            write_json_atomic(partial / "manifest.json", manifest)
            verified = verify_stage(partial)
            current = args.stage_root / "current"
            previous = args.stage_root / "previous"
            if previous.exists():
                if previous.is_symlink() or not previous.is_dir():
                    raise BackupError("unsafe-previous-stage")
                shutil.rmtree(previous)
            if current.exists():
                if current.is_symlink() or not current.is_dir():
                    raise BackupError("unsafe-current-stage")
                os.replace(current, previous)
            os.replace(partial, current)
            write_status(args.status_file, "staged", "stage")
            return verified
        except Exception:
            shutil.rmtree(partial, ignore_errors=True)
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("stage", "verify", "verify-qdrant", "status")
    )
    parser.add_argument(
        "--hermes-root", type=Path, default=Path("/var/lib/hermes")
    )
    parser.add_argument(
        "--automation-root",
        type=Path,
        default=Path("/var/lib/hermes-automation"),
    )
    parser.add_argument(
        "--stage-root",
        type=Path,
        default=Path("/var/backups/hermes-disaster-recovery"),
    )
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument(
        "--status-file",
        type=Path,
        default=Path(
            "/var/lib/hermes/astra/.hermes/profiles/astra/state/"
            "disaster-recovery-backup.json"
        ),
    )
    parser.add_argument("--no-refresh-native", action="store_true")
    parser.add_argument("--result", choices=("ok", "failed", "staged"))
    parser.add_argument("--phase", default="restic")
    parser.add_argument("--exit-code", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "stage":
            result = stage_backup(args)
        elif args.command == "verify":
            result = verify_stage(args.stage_root / "current")
        elif args.command == "verify-qdrant":
            result = verify_qdrant_restore(
                args.stage_root / "current", args.qdrant_url
            )
        else:
            if args.result is None:
                raise BackupError("status-result-required")
            write_status(
                args.status_file,
                args.result,
                args.phase,
                args.exit_code,
            )
            result = {"status": args.result, "phase": args.phase}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        BackupError,
        json.JSONDecodeError,
        OSError,
        sqlite3.Error,
        zipfile.BadZipFile,
    ) as exc:
        detail = f"{type(exc).__name__}:{exc}"
        with contextlib.suppress(Exception):
            write_status(args.status_file, "failed", args.command, 1, detail)
        print(f"hermes-disaster-recovery-error:{detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
