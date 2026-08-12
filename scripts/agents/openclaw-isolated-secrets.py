#!/usr/bin/env python3
"""Create isolated Gateway and Codex transport secrets without exposing values."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import secrets
import stat
import tempfile
from pathlib import Path

MIN_TOKEN_BYTES = 32


class SecretBootstrapError(RuntimeError):
    """Raised for a safe, operator-facing bootstrap failure."""


def _identity_id(value: str, database: str) -> int:
    if value.isdigit():
        return int(value)
    try:
        if database == "user":
            return pwd.getpwnam(value).pw_uid
        return grp.getgrnam(value).gr_gid
    except KeyError as exc:
        raise SecretBootstrapError(f"unknown {database}: {value}") from exc


def _valid_token(value: object) -> str | None:
    if isinstance(value, str) and len(value.encode("utf-8")) >= MIN_TOKEN_BYTES:
        return value
    return None


def _regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SecretBootstrapError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise SecretBootstrapError(f"{label} is not a regular file")


def _existing_gateway_tokens(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    _regular_file(path, "existing Gateway secret payload")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        gateway_token = _valid_token(payload["gateway"]["token"])
        codex_token = _valid_token(payload.get("codex", {}).get("appServerToken"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SecretBootstrapError(
            "existing Gateway secret payload is invalid"
        ) from exc
    if gateway_token is None:
        raise SecretBootstrapError("existing Gateway token is invalid")
    if "codex" in payload and codex_token is None:
        raise SecretBootstrapError("existing Codex app-server token is invalid")
    return gateway_token, codex_token


def _existing_codex_token(path: Path) -> str | None:
    if not path.exists():
        return None
    _regular_file(path, "existing Codex token file")
    try:
        token = _valid_token(path.read_text(encoding="utf-8").strip())
    except OSError as exc:
        raise SecretBootstrapError("existing Codex token file is invalid") from exc
    if token is None:
        raise SecretBootstrapError("existing Codex token file is invalid")
    return token


def _validate_output_parent(parent: Path, owner_uid: int) -> None:
    try:
        metadata = parent.lstat()
    except OSError as exc:
        raise SecretBootstrapError("output directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or parent.is_symlink():
        raise SecretBootstrapError("output directory must be a non-symlink directory")
    if metadata.st_uid != owner_uid:
        raise SecretBootstrapError("output directory has an unexpected owner")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise SecretBootstrapError(
            "output directory must not be group or world writable"
        )


def _write_atomic(path: Path, content: bytes, uid: int, gid: int) -> bool:
    if path.exists():
        _regular_file(path, "existing secret output")
        try:
            if path.read_bytes() == content:
                os.chown(path, uid, gid, follow_symlinks=False)
                os.chmod(path, 0o400, follow_symlinks=False)
                return False
        except OSError as exc:
            raise SecretBootstrapError(
                "existing secret output could not be checked"
            ) from exc

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o400)
        os.fchown(descriptor, uid, gid)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)
        raise SecretBootstrapError(
            "secret output could not be replaced atomically"
        ) from exc
    return True


def bootstrap_secrets(
    gateway_output: Path,
    gateway_uid: int,
    gateway_gid: int,
    codex_token_output: Path,
    codex_uid: int,
    codex_gid: int,
    parent_owner_uid: int | None = None,
) -> dict[str, bool]:
    parent_uid = gateway_uid if parent_owner_uid is None else parent_owner_uid
    _validate_output_parent(gateway_output.parent, parent_uid)
    _validate_output_parent(codex_token_output.parent, parent_uid)

    gateway_token, gateway_codex_token = _existing_gateway_tokens(gateway_output)
    file_codex_token = _existing_codex_token(codex_token_output)
    if (
        gateway_codex_token is not None
        and file_codex_token is not None
        and gateway_codex_token != file_codex_token
    ):
        raise SecretBootstrapError("Codex app-server token copies disagree")

    gateway_token = gateway_token or secrets.token_urlsafe(48)
    codex_token = gateway_codex_token or file_codex_token or secrets.token_urlsafe(48)
    gateway_payload = {
        "codex": {"appServerToken": codex_token},
        "gateway": {"token": gateway_token},
    }
    gateway_encoded = (
        json.dumps(gateway_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    codex_encoded = f"{codex_token}\n".encode("utf-8")

    # Gateway first makes an interrupted first bootstrap self-healing: a later
    # run can reconstruct the executor-only token file from the JSON SecretRef.
    gateway_changed = _write_atomic(
        gateway_output, gateway_encoded, gateway_uid, gateway_gid
    )
    codex_changed = _write_atomic(
        codex_token_output, codex_encoded, codex_uid, codex_gid
    )
    return {"gateway": gateway_changed, "codex": codex_changed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-parent-owner", default="root")
    parser.add_argument("--output-owner", default="openclaw")
    parser.add_argument("--output-group", default="openclaw")
    parser.add_argument("--codex-token-output", type=Path, required=True)
    parser.add_argument("--codex-token-owner", default="openclaw-codex")
    parser.add_argument("--codex-token-group", default="openclaw-codex")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        output_parent_uid = _identity_id(arguments.output_parent_owner, "user")
        output_uid = _identity_id(arguments.output_owner, "user")
        output_gid = _identity_id(arguments.output_group, "group")
        codex_uid = _identity_id(arguments.codex_token_owner, "user")
        codex_gid = _identity_id(arguments.codex_token_group, "group")
        changes = bootstrap_secrets(
            arguments.output,
            output_uid,
            output_gid,
            arguments.codex_token_output,
            codex_uid,
            codex_gid,
            output_parent_uid,
        )
    except SecretBootstrapError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "changed": any(changes.values()),
                "changedOutputs": changes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
