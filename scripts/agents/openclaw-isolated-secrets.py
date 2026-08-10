#!/usr/bin/env python3
"""Create the isolated OpenClaw secret payload without exposing secret values."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import grp
import secrets
import stat
import tempfile
from pathlib import Path

MIN_GATEWAY_TOKEN_BYTES = 32


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


def _existing_gateway_token(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise SecretBootstrapError("existing secret payload is not a regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        token = payload["gateway"]["token"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SecretBootstrapError("existing secret payload is invalid") from exc
    if (
        not isinstance(token, str)
        or len(token.encode("utf-8")) < MIN_GATEWAY_TOKEN_BYTES
    ):
        raise SecretBootstrapError("existing Gateway token is invalid")
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


def write_secret_payload(
    output: Path,
    output_uid: int,
    output_gid: int,
    parent_owner_uid: int | None = None,
) -> bool:
    _validate_output_parent(
        output.parent,
        output_uid if parent_owner_uid is None else parent_owner_uid,
    )
    gateway_token = _existing_gateway_token(output) or secrets.token_urlsafe(48)
    payload = {"gateway": {"token": gateway_token}}
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    if output.exists():
        try:
            if output.read_bytes() == encoded:
                os.chown(output, output_uid, output_gid, follow_symlinks=False)
                os.chmod(output, 0o400, follow_symlinks=False)
                return False
        except OSError as exc:
            raise SecretBootstrapError(
                "existing secret payload could not be checked"
            ) from exc

    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o400)
        os.fchown(descriptor, output_uid, output_gid)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        directory_descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise SecretBootstrapError(
            "secret payload could not be replaced atomically"
        ) from exc
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-parent-owner", default="root")
    parser.add_argument("--output-owner", default="openclaw")
    parser.add_argument("--output-group", default="openclaw")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        output_parent_uid = _identity_id(arguments.output_parent_owner, "user")
        output_uid = _identity_id(arguments.output_owner, "user")
        output_gid = _identity_id(arguments.output_group, "group")
        changed = write_secret_payload(
            arguments.output,
            output_uid,
            output_gid,
            output_parent_uid,
        )
    except SecretBootstrapError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(json.dumps({"status": "ok", "changed": changed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
