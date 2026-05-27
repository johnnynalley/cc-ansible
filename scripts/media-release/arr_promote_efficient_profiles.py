#!/usr/bin/env python3
"""Promote accepted Profilarr test profiles into the live efficient profiles.

Run this on docker-vm. The script reads local Arr and Seerr config files for
API access, snapshots the affected state, creates frozen balanced clones from
the current production profiles, promotes the Profilarr test profile payloads
onto the existing production profile IDs, reassigns any test/balanced media to
the efficient profiles, updates Seerr defaults, and removes the test profiles.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CF_LIMIT = 100
DEFAULT_SNAPSHOT_ROOT = "/opt/media-stack/release-policy-snapshots"
DEFAULT_SEERR_SETTINGS = "/opt/seerr/config/settings.json"
DEFAULT_SEERR_URL = "http://127.0.0.1:5055/api/v1"


@dataclass(frozen=True)
class ProfileMigration:
    kind: str
    current_name: str
    test_name: str
    efficient_name: str
    balanced_name: str


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    assignment_path: str
    assignment_item: str
    migrations: tuple[ProfileMigration, ...]


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        assignment_path="/api/v3/series",
        assignment_item="series",
        migrations=(
            ProfileMigration(
                kind="regular",
                current_name="shows-regular",
                test_name="shows-regular-profilarr-test",
                efficient_name="shows-regular-efficient",
                balanced_name="shows-regular-balanced",
            ),
            ProfileMigration(
                kind="anime",
                current_name="shows-anime",
                test_name="shows-anime-profilarr-test",
                efficient_name="shows-anime-efficient",
                balanced_name="shows-anime-balanced",
            ),
        ),
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        assignment_path="/api/v3/movie",
        assignment_item="movie",
        migrations=(
            ProfileMigration(
                kind="regular",
                current_name="movies-regular",
                test_name="movies-regular-profilarr-test",
                efficient_name="movies-regular-efficient",
                balanced_name="movies-regular-balanced",
            ),
            ProfileMigration(
                kind="anime",
                current_name="movies-anime",
                test_name="movies-anime-profilarr-test",
                efficient_name="movies-anime-efficient",
                balanced_name="movies-anime-balanced",
            ),
        ),
    ),
)


def read_arr_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def read_seerr_api_key(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        settings = json.load(handle)
    key = ((settings.get("main") or {}).get("apiKey") or "").strip()
    if not key:
        raise RuntimeError(f"{path}: main.apiKey was not found")
    return key


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
    api_key_header: str = "X-Api-Key",
) -> Any:
    data = None
    headers = {api_key_header: api_key}
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
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status == 204:
                return None
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc


def find_profile(
    profiles: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    matches = [profile for profile in profiles if profile.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"multiple quality profiles named {name!r}")
    return matches[0] if matches else None


def profile_id(profile: dict[str, Any] | None) -> int | None:
    if profile is None:
        return None
    value = profile.get("id")
    return int(value) if isinstance(value, int) else None


def clone_profile_payload(
    source: dict[str, Any], target_name: str, target_id: int | None
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["name"] = target_name
    if target_id is None:
        payload.pop("id", None)
    else:
        payload["id"] = target_id
    return payload


def assignment_endpoint(instance: ArrInstance, item_id: int) -> str:
    return f"{instance.assignment_path}/{item_id}"


def assignment_counts(
    profiles: list[dict[str, Any]], assignments: list[dict[str, Any]]
) -> dict[str, int]:
    names_by_id = {
        int(profile["id"]): str(profile.get("name") or profile["id"])
        for profile in profiles
        if isinstance(profile.get("id"), int)
    }
    counts: dict[str, int] = {}
    for item in assignments:
        profile_value = item.get("qualityProfileId")
        name = names_by_id.get(profile_value, str(profile_value))
        counts[name] = counts.get(name, 0) + 1
    return counts


def write_snapshot(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def redact_for_report(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in {"apikey", "api_key", "token", "sessionsecret"}:
                redacted[key] = "REDACTED"
            else:
                redacted[key] = redact_for_report(item)
        return redacted
    if isinstance(value, list):
        return [redact_for_report(item) for item in value]
    return value


def snapshot_arr_instance(
    instance: ArrInstance, api_key: str, snapshot_dir: Path
) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(instance.base_url, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(instance.base_url, api_key, "GET", "/api/v3/qualityprofile"),
        "assignments": request_json(instance.base_url, api_key, "GET", instance.assignment_path),
        "queue_status": request_json(instance.base_url, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance.base_url, api_key, "GET", "/api/v3/command"),
    }
    for key, value in data.items():
        write_snapshot(snapshot_dir / f"{instance.name}-{key.replace('_', '-')}.json", value)
    return data


def snapshot_seerr(
    seerr_url: str, seerr_api_key: str, settings_path: str, snapshot_dir: Path
) -> dict[str, Any]:
    with open(settings_path, "r", encoding="utf-8") as handle:
        settings = json.load(handle)
    write_snapshot(snapshot_dir / "seerr-settings.json", settings)
    data = {
        "sonarr": request_json(
            seerr_url, seerr_api_key, "GET", "/settings/sonarr", api_key_header="X-API-Key"
        ),
        "radarr": request_json(
            seerr_url, seerr_api_key, "GET", "/settings/radarr", api_key_header="X-API-Key"
        ),
    }
    write_snapshot(snapshot_dir / "seerr-sonarr-api.json", data["sonarr"])
    write_snapshot(snapshot_dir / "seerr-radarr-api.json", data["radarr"])
    return data


def prepare_migration(
    profiles: list[dict[str, Any]], migration: ProfileMigration
) -> dict[str, Any]:
    current = find_profile(profiles, migration.current_name)
    efficient = find_profile(profiles, migration.efficient_name)
    if current and efficient:
        raise RuntimeError(
            f"both {migration.current_name!r} and {migration.efficient_name!r} exist"
        )
    target = current or efficient
    if target is None:
        raise RuntimeError(
            f"missing target profile {migration.current_name!r} or {migration.efficient_name!r}"
        )
    test = find_profile(profiles, migration.test_name)
    balanced = find_profile(profiles, migration.balanced_name)
    return {
        "target": target,
        "target_id": profile_id(target),
        "target_name_before": target.get("name"),
        "test": test,
        "test_id": profile_id(test),
        "balanced": balanced,
        "balanced_id": profile_id(balanced),
    }


def create_balanced_profile(
    instance: ArrInstance,
    api_key: str,
    migration: ProfileMigration,
    target: dict[str, Any],
    dry_run: bool,
) -> tuple[str, int | None]:
    target_name = str(target.get("name") or "")
    if target_name == migration.efficient_name:
        raise RuntimeError(
            f"{instance.name}: cannot create {migration.balanced_name!r}; "
            f"{migration.efficient_name!r} has already replaced the legacy payload"
        )
    payload = clone_profile_payload(target, migration.balanced_name, None)
    if dry_run:
        return "would-create", None
    created = request_json(instance.base_url, api_key, "POST", "/api/v3/qualityprofile", payload)
    return "created", int(created["id"])


def promote_profile(
    instance: ArrInstance,
    api_key: str,
    migration: ProfileMigration,
    target_id: int,
    test: dict[str, Any] | None,
    dry_run: bool,
) -> str:
    if test is None:
        return "already-promoted"
    payload = clone_profile_payload(test, migration.efficient_name, target_id)
    if dry_run:
        return "would-promote"
    request_json(
        instance.base_url,
        api_key,
        "PUT",
        f"/api/v3/qualityprofile/{target_id}",
        payload,
    )
    return "promoted"


def reassign_media(
    instance: ArrInstance,
    api_key: str,
    assignments: list[dict[str, Any]],
    target_id: int,
    from_ids: set[int],
    dry_run: bool,
) -> dict[str, Any]:
    candidates = [
        item
        for item in assignments
        if isinstance(item.get("id"), int) and item.get("qualityProfileId") in from_ids
    ]
    changed = 0
    if not dry_run:
        for item in candidates:
            payload = copy.deepcopy(item)
            payload["qualityProfileId"] = target_id
            request_json(
                instance.base_url,
                api_key,
                "PUT",
                assignment_endpoint(instance, int(item["id"])),
                payload,
            )
            changed += 1
    return {
        "planned": len(candidates),
        "changed": changed,
        "from_ids": sorted(from_ids),
        "target_id": target_id,
    }


def delete_test_profile(
    instance: ArrInstance,
    api_key: str,
    migration: ProfileMigration,
    test_id: int | None,
    remaining_assignments: int,
    dry_run: bool,
) -> str:
    if test_id is None:
        return "absent"
    if dry_run:
        return "would-delete"
    if remaining_assignments:
        raise RuntimeError(
            f"{instance.name}: refusing to delete {migration.test_name!r}; "
            f"{remaining_assignments} assignments remain"
        )
    request_json(instance.base_url, api_key, "DELETE", f"/api/v3/qualityprofile/{test_id}")
    return "deleted"


def process_arr_instance(
    instance: ArrInstance,
    snapshot_dir: Path,
    cf_limit: int,
    dry_run: bool,
) -> dict[str, Any]:
    api_key = read_arr_api_key(instance.config_path)
    before = snapshot_arr_instance(instance, api_key, snapshot_dir)
    profiles = before["quality_profiles"]
    assignments = before["assignments"]
    if len(before["custom_formats"]) > cf_limit:
        raise RuntimeError(
            f"{instance.name}: custom format count {len(before['custom_formats'])} "
            f"exceeds configured limit {cf_limit}"
        )

    prepared = {
        migration.kind: prepare_migration(profiles, migration)
        for migration in instance.migrations
    }
    results: list[dict[str, Any]] = []

    for migration in instance.migrations:
        state = prepared[migration.kind]
        target_id = state["target_id"]
        if target_id is None:
            raise RuntimeError(f"{instance.name}: {migration.current_name} has no profile id")

        balanced_action = "exists"
        balanced_id = state["balanced_id"]
        if state["balanced"] is None:
            balanced_action, balanced_id = create_balanced_profile(
                instance, api_key, migration, state["target"], dry_run
            )

        promote_action = promote_profile(
            instance, api_key, migration, target_id, state["test"], dry_run
        )

        from_ids = {value for value in (state["test_id"], balanced_id) if isinstance(value, int)}
        from_ids.discard(target_id)
        reassignment = reassign_media(instance, api_key, assignments, target_id, from_ids, dry_run)

        results.append(
            {
                "kind": migration.kind,
                "target_id": target_id,
                "target_name_before": state["target_name_before"],
                "efficient_name": migration.efficient_name,
                "balanced_name": migration.balanced_name,
                "balanced_action": balanced_action,
                "balanced_id": balanced_id,
                "test_name": migration.test_name,
                "test_id": state["test_id"],
                "promote_action": promote_action,
                "reassignment": reassignment,
            }
        )

    refreshed_profiles = request_json(instance.base_url, api_key, "GET", "/api/v3/qualityprofile")
    refreshed_assignments = request_json(instance.base_url, api_key, "GET", instance.assignment_path)

    deletion_results: dict[str, str] = {}
    for migration in instance.migrations:
        state = prepared[migration.kind]
        test_id = state["test_id"]
        remaining = 0
        if isinstance(test_id, int):
            remaining = sum(1 for item in refreshed_assignments if item.get("qualityProfileId") == test_id)
        deletion_results[migration.test_name] = delete_test_profile(
            instance, api_key, migration, test_id, remaining, dry_run
        )

    final_profiles = request_json(instance.base_url, api_key, "GET", "/api/v3/qualityprofile")
    final_assignments = request_json(instance.base_url, api_key, "GET", instance.assignment_path)
    efficient_ids = {
        profile_id(find_profile(final_profiles, migration.efficient_name))
        for migration in instance.migrations
    }
    balanced_ids = {
        profile_id(find_profile(final_profiles, migration.balanced_name))
        for migration in instance.migrations
    }
    test_names_present = [
        migration.test_name
        for migration in instance.migrations
        if find_profile(final_profiles, migration.test_name)
    ]
    old_names_present = [
        migration.current_name
        for migration in instance.migrations
        if find_profile(final_profiles, migration.current_name)
    ]
    efficient_assignment_total = sum(
        1 for item in final_assignments if item.get("qualityProfileId") in efficient_ids
    )
    balanced_assignment_total = sum(
        1 for item in final_assignments if item.get("qualityProfileId") in balanced_ids
    )
    non_efficient_assignments = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "qualityProfileId": item.get("qualityProfileId"),
        }
        for item in final_assignments
        if item.get("qualityProfileId") not in efficient_ids
    ]

    if not dry_run:
        errors = []
        if test_names_present:
            errors.append(f"test profiles still present: {test_names_present}")
        if old_names_present:
            errors.append(f"old profile names still present: {old_names_present}")
        if balanced_assignment_total:
            errors.append(f"balanced assignments remain: {balanced_assignment_total}")
        if non_efficient_assignments:
            errors.append(f"{len(non_efficient_assignments)} non-efficient assignments remain")
        if errors:
            raise RuntimeError(f"{instance.name}: post-migration validation failed: {'; '.join(errors)}")

    return {
        "instance": instance.name,
        "custom_format_count": len(before["custom_formats"]),
        "custom_format_limit": cf_limit,
        "queue_status": before["queue_status"],
        "before_assignment_counts": assignment_counts(profiles, assignments),
        "profile_results": results,
        "test_profile_deletions": deletion_results,
        "after_assignment_counts": assignment_counts(final_profiles, final_assignments),
        "efficient_assignment_total": efficient_assignment_total,
        "balanced_assignment_total": balanced_assignment_total,
        "non_efficient_assignments": non_efficient_assignments[:25],
    }


def update_sonarr_seerr_item(item: dict[str, Any], id_map: dict[int, tuple[int, str]]) -> bool:
    changed = False
    for id_key, name_key in (
        ("activeProfileId", "activeProfileName"),
        ("activeAnimeProfileId", "activeAnimeProfileName"),
    ):
        value = item.get(id_key)
        if isinstance(value, int) and value in id_map:
            new_id, new_name = id_map[value]
            if item.get(id_key) != new_id or item.get(name_key) != new_name:
                item[id_key] = new_id
                item[name_key] = new_name
                changed = True
    return changed


def update_radarr_seerr_item(item: dict[str, Any], id_map: dict[int, tuple[int, str]]) -> bool:
    value = item.get("activeProfileId")
    if isinstance(value, int) and value in id_map:
        new_id, new_name = id_map[value]
        if item.get("activeProfileId") != new_id or item.get("activeProfileName") != new_name:
            item["activeProfileId"] = new_id
            item["activeProfileName"] = new_name
            return True
    return False


def build_seerr_id_maps(arr_results: list[dict[str, Any]]) -> dict[str, dict[int, tuple[int, str]]]:
    maps: dict[str, dict[int, tuple[int, str]]] = {"sonarr": {}, "radarr": {}}
    for instance_result in arr_results:
        instance_map = maps[instance_result["instance"]]
        for result in instance_result["profile_results"]:
            target_id = result["target_id"]
            efficient_name = result["efficient_name"]
            ids = {target_id, result.get("test_id"), result.get("balanced_id")}
            for value in ids:
                if isinstance(value, int):
                    instance_map[value] = (target_id, efficient_name)
    return maps


def process_seerr(
    seerr_url: str,
    seerr_settings: str,
    snapshot_dir: Path,
    arr_results: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    api_key = read_seerr_api_key(seerr_settings)
    before = snapshot_seerr(seerr_url, api_key, seerr_settings, snapshot_dir)
    id_maps = build_seerr_id_maps(arr_results)
    changes: list[dict[str, Any]] = []

    for section in ("sonarr", "radarr"):
        for item in before[section]:
            updated = copy.deepcopy(item)
            if section == "sonarr":
                changed = update_sonarr_seerr_item(updated, id_maps[section])
            else:
                changed = update_radarr_seerr_item(updated, id_maps[section])
            if not changed:
                continue
            changes.append(
                {
                    "section": section,
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "before": {
                        key: item.get(key)
                        for key in (
                            "activeProfileId",
                            "activeProfileName",
                            "activeAnimeProfileId",
                            "activeAnimeProfileName",
                        )
                        if key in item
                    },
                    "after": {
                        key: updated.get(key)
                        for key in (
                            "activeProfileId",
                            "activeProfileName",
                            "activeAnimeProfileId",
                            "activeAnimeProfileName",
                        )
                        if key in updated
                    },
                }
            )
            if not dry_run:
                payload = copy.deepcopy(updated)
                payload.pop("id", None)
                request_json(
                    seerr_url,
                    api_key,
                    "PUT",
                    f"/settings/{section}/{item['id']}",
                    payload,
                    api_key_header="X-API-Key",
                )

    after = {
        "sonarr": request_json(
            seerr_url, api_key, "GET", "/settings/sonarr", api_key_header="X-API-Key"
        ),
        "radarr": request_json(
            seerr_url, api_key, "GET", "/settings/radarr", api_key_header="X-API-Key"
        ),
    }

    if not dry_run:
        bad_names: list[str] = []
        for section in ("sonarr", "radarr"):
            for item in after[section]:
                for key in ("activeProfileName", "activeAnimeProfileName"):
                    value = item.get(key)
                    if isinstance(value, str) and (
                        value.endswith("-profilarr-test")
                        or value.endswith("-balanced")
                        or value in {"shows-regular", "shows-anime", "movies-regular", "movies-anime"}
                    ):
                        bad_names.append(f"{section}:{item.get('id')}:{key}={value}")
        if bad_names:
            raise RuntimeError(f"Seerr validation failed: {bad_names}")

    return {"changes": changes, "after": redact_for_report(after)}


def print_text(report: dict[str, Any]) -> None:
    mode = "APPLY" if report["apply"] else "DRY-RUN"
    print(f"{mode}: snapshot {report['snapshot_dir']}")
    for instance in report["arr"]:
        print(
            "{instance}: CFs {custom_format_count}/{custom_format_limit}; "
            "queue={queue_status}".format(**instance)
        )
        print(f"  before: {instance['before_assignment_counts']}")
        for result in instance["profile_results"]:
            reassignment = result["reassignment"]
            print(
                "  {kind}: {target_name_before} -> {efficient_name} id={target_id}; "
                "balanced {balanced_action} id={balanced_id}; "
                "test {test_name} id={test_id}; {promote_action}; "
                "reassign {planned}".format(planned=reassignment["planned"], **result)
            )
        print(f"  deletions: {instance['test_profile_deletions']}")
        print(f"  after: {instance['after_assignment_counts']}")
    print(f"Seerr changes: {len(report['seerr']['changes'])}")
    for change in report["seerr"]["changes"]:
        print(
            "  {section} id={id} {name}: {before} -> {after}".format(**change)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the migration")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--snapshot-root",
        default=DEFAULT_SNAPSHOT_ROOT,
        help="directory where timestamped backups/snapshots are written",
    )
    parser.add_argument("--cf-limit", type=int, default=DEFAULT_CF_LIMIT)
    parser.add_argument("--seerr-url", default=DEFAULT_SEERR_URL)
    parser.add_argument("--seerr-settings", default=DEFAULT_SEERR_SETTINGS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "efficient-profile-promotion" if args.apply else "efficient-profile-promotion-dry-run"
    snapshot_dir = Path(args.snapshot_root) / f"{timestamp}-{suffix}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    arr_results = [
        process_arr_instance(instance, snapshot_dir, args.cf_limit, dry_run=not args.apply)
        for instance in INSTANCES
    ]
    seerr_result = process_seerr(
        args.seerr_url,
        args.seerr_settings,
        snapshot_dir,
        arr_results,
        dry_run=not args.apply,
    )
    report = {
        "apply": args.apply,
        "snapshot_dir": str(snapshot_dir),
        "arr": arr_results,
        "seerr": seerr_result,
    }
    write_snapshot(snapshot_dir / "promotion-report.json", report)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
