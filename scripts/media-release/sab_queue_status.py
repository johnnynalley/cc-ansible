#!/usr/bin/env python3
"""Summarize SABnzbd queue state and stale incomplete folders."""

from __future__ import annotations

import argparse
import configparser
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.parse
import urllib.request
from typing import Any


def read_sab_config(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as handle:
        raw_config = handle.read()

    lines = raw_config.splitlines()
    section_start = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("[")),
        len(lines),
    )
    flat_values: dict[str, str] = {}
    for line in lines[:section_start]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        flat_values[key.strip()] = value.strip().strip('"').strip("'")

    parser = configparser.RawConfigParser()
    section_values: dict[str, str] = {}
    if section_start < len(lines):
        parser.read_string("\n".join(lines[section_start:]), source=path)
        if parser.has_section("misc"):
            section_values = dict(parser["misc"])

    misc = {**flat_values, **section_values}
    values = {
        "host": misc.get("host", "127.0.0.1"),
        "port": misc.get("port", "8080"),
        "api_key": misc.get("api_key", ""),
        "download_dir": misc.get("download_dir", "/incomplete"),
        "complete_dir": misc.get("complete_dir", ""),
    }
    if not values["api_key"]:
        raise RuntimeError(f"{path}: missing SABnzbd api_key")
    return values


def api_get(base_url: str, api_key: str, mode: str) -> Any:
    query = urllib.parse.urlencode(
        {
            "mode": mode,
            "output": "json",
            "apikey": api_key,
        }
    )
    with urllib.request.urlopen(f"{base_url}/api?{query}", timeout=30) as response:
        return json.load(response)


def normalize(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def dir_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_blocks * 512
            except FileNotFoundError:
                continue
        for name in dirs:
            try:
                total += (Path(root) / name).stat().st_blocks * 512
            except FileNotFoundError:
                continue
    try:
        total += path.stat().st_blocks * 512
    except FileNotFoundError:
        pass
    return total


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def compact_slot(slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": slot.get("filename") or slot.get("name"),
        "nzo_id": slot.get("nzo_id"),
        "status": slot.get("status"),
        "percentage": slot.get("percentage"),
        "mbleft": slot.get("mbleft"),
        "mb": slot.get("mb"),
        "storage": slot.get("storage"),
        "script": slot.get("script"),
    }


def queue_references(slots: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    keys = ("filename", "name", "storage", "path")
    for slot in slots:
        for key in keys:
            value = slot.get(key)
            if isinstance(value, str) and value:
                refs.add(normalize(Path(value).name))
                refs.add(normalize(value))
    return {ref for ref in refs if ref}


def is_referenced(dirname: str, refs: set[str]) -> bool:
    name = normalize(dirname)
    if not name:
        return False
    for ref in refs:
        if name == ref or name.startswith(ref) or ref.startswith(name):
            return True
    return False


def list_incomplete_dirs(path: Path, refs: set[str], min_age_hours: float) -> list[dict[str, Any]]:
    now = dt.datetime.now(dt.timezone.utc)
    cutoff_seconds = min_age_hours * 3600
    result: list[dict[str, Any]] = []
    if not path.exists():
        return result
    for item in sorted(path.iterdir(), key=lambda value: value.name.lower()):
        if not item.is_dir():
            continue
        try:
            stat = item.stat()
        except FileNotFoundError:
            continue
        mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
        age_seconds = (now - mtime).total_seconds()
        referenced = is_referenced(item.name, refs)
        result.append(
            {
                "path": str(item),
                "name": item.name,
                "mtime": mtime.isoformat(),
                "age_hours": round(age_seconds / 3600, 2),
                "referenced_by_queue": referenced,
                "delete_candidate": (not referenced and age_seconds >= cutoff_seconds),
                "size_bytes": dir_size(item),
            }
        )
    return result


def write_manifest(path: str, payload: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize SABnzbd queue state and stale incomplete folders."
    )
    parser.add_argument("--config", default="/opt/media-stack/sabnzbd/sabnzbd.ini")
    parser.add_argument("--base-url")
    parser.add_argument("--download-dir")
    parser.add_argument("--min-age-hours", type=float, default=6.0)
    parser.add_argument("--manifest")
    parser.add_argument("--apply-delete", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sample-limit", type=int, default=10)
    args = parser.parse_args()

    config = read_sab_config(args.config)
    base_url = args.base_url or f"http://127.0.0.1:{config['port']}"
    download_dir = Path(args.download_dir or config["download_dir"])

    queue = api_get(base_url, config["api_key"], "queue")
    history = api_get(base_url, config["api_key"], "history")
    slots = list((queue.get("queue") or {}).get("slots") or [])
    history_slots = list((history.get("history") or {}).get("slots") or [])
    refs = queue_references(slots)
    incomplete_dirs = list_incomplete_dirs(download_dir, refs, args.min_age_hours)
    candidates = [item for item in incomplete_dirs if item["delete_candidate"]]

    payload: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": base_url,
        "download_dir": str(download_dir),
        "complete_dir": config.get("complete_dir"),
        "queue_count": len(slots),
        "history_count": len(history_slots),
        "queue_slots": [compact_slot(slot) for slot in slots],
        "history_samples": [
            {
                "name": slot.get("name") or slot.get("filename"),
                "status": slot.get("status"),
                "fail_message": slot.get("fail_message"),
                "completed": slot.get("completed"),
                "storage": slot.get("storage"),
            }
            for slot in history_slots[: args.sample_limit]
        ],
        "incomplete_dirs": incomplete_dirs,
        "delete_candidates": candidates,
        "delete_candidate_count": len(candidates),
        "delete_candidate_size_bytes": sum(int(item["size_bytes"]) for item in candidates),
        "deleted": [],
    }

    if args.apply_delete:
        if not args.manifest:
            raise RuntimeError("--apply-delete requires --manifest")
        for item in candidates:
            path = Path(str(item["path"]))
            if path.parent != download_dir:
                raise RuntimeError(f"refusing to delete unexpected path: {path}")
            shutil.rmtree(path)
            payload["deleted"].append(str(path))

    if args.manifest:
        payload["manifest"] = write_manifest(args.manifest, payload)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"SAB queue items: {payload['queue_count']}")
    print(f"SAB history items sampled: {payload['history_count']}")
    print(f"incomplete dirs: {len(incomplete_dirs)} at {download_dir}")
    print(
        "delete candidates: "
        f"{len(candidates)} / {human_size(payload['delete_candidate_size_bytes'])}"
    )
    if args.manifest:
        print(f"manifest: {payload['manifest']}")
    if payload["deleted"]:
        print(f"deleted dirs: {len(payload['deleted'])}")

    print("queue samples:")
    for slot in payload["queue_slots"][: args.sample_limit]:
        print(
            "- "
            f"{slot.get('filename')} | status={slot.get('status')} "
            f"left={slot.get('mbleft')}MB percent={slot.get('percentage')}"
        )

    print("delete candidate samples:")
    for item in candidates[: args.sample_limit]:
        print(
            "- "
            f"{item['name']} | size={human_size(int(item['size_bytes']))} "
            f"age={item['age_hours']}h"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
