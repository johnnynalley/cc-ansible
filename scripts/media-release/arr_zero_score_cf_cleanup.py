#!/usr/bin/env python3
"""Remove explicitly named Arr custom formats only when inert and non-rename."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


APPS = {
    "sonarr": ("http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml"),
    "radarr": ("http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml"),
}
LIVE_ROLLBACK_ROOT = Path("/srv/live-rollbacks")


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
) -> Any:
    data = None
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc


def format_id(item: dict[str, Any]) -> int | None:
    value = item.get("format")
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        value = item.get("customFormatId")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def cleanup_plan(
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    names: list[str],
) -> list[dict[str, Any]]:
    by_name = {str(item.get("name") or ""): item for item in custom_formats}
    plan: list[dict[str, Any]] = []
    for name in names:
        custom_format = by_name.get(name)
        if custom_format is None:
            raise RuntimeError(f"custom format not found: {name}")
        cf_id = custom_format.get("id")
        if not isinstance(cf_id, int):
            raise RuntimeError(f"custom format has no numeric id: {name}")
        if custom_format.get("includeCustomFormatWhenRenaming"):
            raise RuntimeError(f"refusing rename custom format: {name}")
        profile_scores = []
        for profile in profiles:
            for item in profile.get("formatItems") or []:
                if format_id(item) != cf_id:
                    continue
                score = int(item.get("score") or 0)
                profile_scores.append(
                    {"id": profile.get("id"), "name": profile.get("name"), "score": score}
                )
                if score != 0:
                    raise RuntimeError(
                        f"refusing scored custom format {name}: "
                        f"{profile.get('name')}={score}"
                    )
        plan.append(
            {
                "id": cf_id,
                "name": name,
                "profile_scores": profile_scores,
            }
        )
    return plan


def verify_removed(
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    target_ids: set[int],
    target_names: set[str],
) -> None:
    remaining_formats = [
        custom_format
        for custom_format in custom_formats
        if custom_format.get("id") in target_ids
        or str(custom_format.get("name") or "") in target_names
    ]
    if remaining_formats:
        raise RuntimeError(
            "custom format deletion did not converge: "
            + ", ".join(str(item.get("name") or item.get("id")) for item in remaining_formats)
        )

    lingering_profiles = []
    for profile in profiles:
        if any(format_id(item) in target_ids for item in profile.get("formatItems") or []):
            lingering_profiles.append(str(profile.get("name") or profile.get("id")))
    if lingering_profiles:
        raise RuntimeError(
            "deleted custom format remains in profiles: " + ", ".join(lingering_profiles)
        )


def ensure_offhost_backup_root(
    backup_root: Path,
    *,
    mounts_path: Path = Path("/proc/mounts"),
) -> None:
    if not backup_root.is_absolute() or ".." in backup_root.parts:
        raise RuntimeError("backup root must be an absolute path without traversal")
    try:
        backup_root.relative_to(LIVE_ROLLBACK_ROOT)
    except ValueError as exc:
        raise RuntimeError(
            f"backup root must remain beneath {LIVE_ROLLBACK_ROOT}"
        ) from exc

    entries = [line.split() for line in mounts_path.read_text(encoding="utf-8").splitlines()]
    matches = [
        fields
        for fields in entries
        if len(fields) >= 3 and fields[1] == str(LIVE_ROLLBACK_ROOT)
    ]
    if len(matches) != 1 or matches[0][2] not in {"nfs", "nfs4"}:
        raise RuntimeError(
            f"{LIVE_ROLLBACK_ROOT} is not an NFS mount; refusing an apply without off-host rollback"
        )


def write_backup(
    backup_dir: Path,
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> None:
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup_dir, 0o700)
    for name, value in (
        ("custom-formats.json", custom_formats),
        ("quality-profiles.json", profiles),
    ):
        path = backup_dir / name
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=sorted(APPS))
    parser.add_argument("--name", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path("/srv/live-rollbacks/docker-vm/arr-policy"),
    )
    args = parser.parse_args()

    base_url, config_path = APPS[args.app]
    api_key = read_api_key(config_path)
    custom_formats = request_json(base_url, api_key, "GET", "/api/v3/customformat")
    profiles = request_json(base_url, api_key, "GET", "/api/v3/qualityprofile")
    plan = cleanup_plan(custom_formats, profiles, args.name)

    backup_dir: Path | None = None
    changed_profiles: list[str] = []
    deleted: list[str] = []
    if args.apply:
        ensure_offhost_backup_root(args.backup_root)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = (
            args.backup_root / f"{timestamp}-{args.app}-zero-score-cf-cleanup"
        )
        write_backup(backup_dir, custom_formats, profiles)
        target_ids = {int(item["id"]) for item in plan}
        target_names = {str(item["name"]) for item in plan}
        changed_profiles = sorted(
            {
                str(profile["name"])
                for item in plan
                for profile in item["profile_scores"]
            }
        )
        for item in plan:
            # Arr's native delete lifecycle removes the format from every
            # profile before deleting the definition. A profile PUT that omits
            # a still-defined format is rejected by the native validator.
            request_json(
                base_url,
                api_key,
                "DELETE",
                f"/api/v3/customformat/{item['id']}",
            )
            deleted.append(str(item["name"]))
        verify_removed(
            request_json(base_url, api_key, "GET", "/api/v3/customformat"),
            request_json(base_url, api_key, "GET", "/api/v3/qualityprofile"),
            target_ids,
            target_names,
        )

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "app": args.app,
                "backup_dir": str(backup_dir) if backup_dir is not None else None,
                "plan": plan,
                "changed_profiles": changed_profiles,
                "deleted": deleted,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
