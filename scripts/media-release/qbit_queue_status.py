#!/usr/bin/env python3
"""Read-only qBittorrent torrent-state summary for Arr queue incidents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from http.cookiejar import CookieJar
from typing import Any


PROBLEM_STATES = {
    "error",
    "missingFiles",
    "stalledDL",
    "queuedDL",
    "metaDL",
    "checkingDL",
    "checkingResumeData",
}


def parse_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value.startswith(("'", '"'))
            ):
                value = value[1:-1]
            values[key.strip()] = value
    return values


def qbit_client(env_path: str) -> tuple[str, urllib.request.OpenerDirector]:
    env = parse_env(env_path)
    missing = [key for key in ("QBIT_API", "QBIT_USER", "QBIT_PASS") if not env.get(key)]
    if missing:
        raise RuntimeError(f"{env_path}: missing required values: {', '.join(missing)}")

    base_url = env["QBIT_API"].rstrip("/")
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode(
        {"username": env["QBIT_USER"], "password": env["QBIT_PASS"]}
    ).encode()
    request = urllib.request.Request(f"{base_url}/auth/login", data=body, method="POST")
    with opener.open(request, timeout=15) as response:
        status = response.status
        text = response.read().decode("utf-8", errors="replace")
    if text.strip() != "Ok." and status != 204:
        raise RuntimeError("qBittorrent API login failed")
    return base_url, opener


def api_get(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)
    with opener.open(f"{base_url}{path}{query}", timeout=30) as response:
        return json.load(response)


def api_post(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    path: str,
    params: dict[str, Any],
) -> str:
    body = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(f"{base_url}{path}", data=body, method="POST")
    with opener.open(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def progress_percent(torrent: dict[str, Any]) -> str:
    try:
        return f"{float(torrent.get('progress') or 0) * 100:.1f}%"
    except (TypeError, ValueError):
        return "unknown"


def compact_torrent(torrent: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": torrent.get("name"),
        "hash": str(torrent.get("hash") or "")[:12],
        "category": torrent.get("category"),
        "state": torrent.get("state"),
        "progress": progress_percent(torrent),
        "amount_left": torrent.get("amount_left"),
        "eta": torrent.get("eta"),
        "dlspeed": torrent.get("dlspeed"),
        "num_seeds": torrent.get("num_seeds"),
        "num_leechs": torrent.get("num_leechs"),
        "tracker": torrent.get("tracker"),
        "save_path": torrent.get("save_path"),
        "content_path": torrent.get("content_path"),
    }


def is_finished(torrent: dict[str, Any]) -> bool:
    try:
        return float(torrent.get("progress") or 0) >= 1.0
    except (TypeError, ValueError):
        return False


def torrent_size_left(torrent: dict[str, Any]) -> int:
    value = torrent.get("amount_left")
    return int(value) if isinstance(value, int) else 0


def write_manifest(path: str, result: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return str(target)


def delete_torrents(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    torrents: list[dict[str, Any]],
) -> None:
    hashes = [str(torrent.get("hash")) for torrent in torrents if torrent.get("hash")]
    if not hashes:
        return
    api_post(
        base_url,
        opener,
        "/torrents/delete",
        {
            "hashes": "|".join(hashes),
            "deleteFiles": "true",
        },
    )


def tracker_summary(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    torrent_hash: str,
) -> list[dict[str, Any]]:
    trackers = api_get(base_url, opener, "/torrents/trackers", {"hash": torrent_hash})
    summary: list[dict[str, Any]] = []
    for tracker in trackers:
        url = str(tracker.get("url") or "")
        if not url or url.startswith("**"):
            continue
        summary.append(
            {
                "status": tracker.get("status"),
                "tier": tracker.get("tier"),
                "url": url,
                "msg": tracker.get("msg"),
                "num_seeds": tracker.get("num_seeds"),
                "num_leeches": tracker.get("num_leeches"),
            }
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize qBittorrent states without printing credentials."
    )
    parser.add_argument("--env", default="/etc/qbit-port-sync.env")
    parser.add_argument(
        "--filter",
        default="all",
        help="qBittorrent torrent filter, for example all, downloading, stalled, errored.",
    )
    parser.add_argument("--title-regex")
    parser.add_argument("--problem-only", action="store_true")
    parser.add_argument(
        "--delete-states",
        help=(
            "comma-separated qBittorrent states to delete with files; requires "
            "--apply-delete and --manifest"
        ),
    )
    parser.add_argument("--category")
    parser.add_argument("--keep-finished", action="store_true", default=True)
    parser.add_argument("--include-finished", action="store_false", dest="keep_finished")
    parser.add_argument("--apply-delete", action="store_true")
    parser.add_argument("--manifest")
    parser.add_argument("--include-trackers", action="store_true")
    parser.add_argument("--sample-limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base_url, opener = qbit_client(args.env)
    torrents = api_get(base_url, opener, "/torrents/info", {"filter": args.filter})
    if args.title_regex:
        import re

        pattern = re.compile(args.title_regex, re.IGNORECASE)
        torrents = [torrent for torrent in torrents if pattern.search(torrent.get("name") or "")]
    if args.problem_only:
        torrents = [
            torrent for torrent in torrents if str(torrent.get("state") or "") in PROBLEM_STATES
        ]
    if args.category:
        torrents = [
            torrent for torrent in torrents if str(torrent.get("category") or "") == args.category
        ]

    delete_states = {
        state.strip() for state in (args.delete_states or "").split(",") if state.strip()
    }
    delete_candidates = [
        torrent
        for torrent in torrents
        if delete_states
        and str(torrent.get("state") or "") in delete_states
        and (not args.keep_finished or not is_finished(torrent))
    ]
    delete_bytes_left = sum(torrent_size_left(torrent) for torrent in delete_candidates)

    state_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    save_path_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for torrent in torrents:
        state = str(torrent.get("state") or "unknown")
        state_counts[state] += 1
        category_counts[str(torrent.get("category") or "none")] += 1
        save_path_counts[str(torrent.get("save_path") or "unknown")] += 1
        if len(samples[state]) < args.sample_limit:
            item = compact_torrent(torrent)
            if args.include_trackers and torrent.get("hash"):
                item["trackers"] = tracker_summary(base_url, opener, str(torrent["hash"]))
            samples[state].append(item)

    result = {
        "apply_delete": args.apply_delete,
        "delete_states": sorted(delete_states),
        "delete_candidate_count": len(delete_candidates),
        "delete_candidate_amount_left": delete_bytes_left,
        "delete_candidates": [compact_torrent(torrent) for torrent in delete_candidates],
        "filter": args.filter,
        "problem_only": args.problem_only,
        "total": len(torrents),
        "state_counts": dict(state_counts.most_common()),
        "category_counts": dict(category_counts.most_common()),
        "save_path_counts": dict(save_path_counts.most_common()),
        "samples": samples,
    }

    if args.apply_delete:
        if not delete_states:
            raise RuntimeError("--apply-delete requires --delete-states")
        if not args.manifest:
            raise RuntimeError("--apply-delete requires --manifest")
        result["manifest"] = write_manifest(args.manifest, result)
        delete_torrents(base_url, opener, delete_candidates)
        result["deleted_count"] = len(delete_candidates)
    elif args.manifest:
        result["manifest"] = write_manifest(args.manifest, result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print(f"qBittorrent torrents: {len(torrents)} filter={args.filter}")
    print("state counts:")
    for state, count in state_counts.most_common():
        print(f"- {state}: {count}")
    print("category counts:")
    for category, count in category_counts.most_common():
        print(f"- {category}: {count}")
    print("save paths:")
    for save_path, count in save_path_counts.most_common():
        print(f"- {save_path}: {count}")
    print("samples:")
    for state, items in samples.items():
        print(f"- {state}:")
        for item in items:
            print(
                "  "
                f"{item['name']} | hash={item['hash']} | category={item['category']} "
                f"| progress={item['progress']} | left={item['amount_left']} "
                f"| seeds={item['num_seeds']} | eta={item['eta']} | path={item['save_path']}"
            )
            if args.include_trackers:
                for tracker in item.get("trackers") or []:
                    print(
                        "    tracker "
                        f"status={tracker['status']} seeds={tracker['num_seeds']} "
                        f"url={tracker['url']} msg={tracker['msg'] or ''}"
                    )
    if delete_states:
        print(
            "delete candidates: "
            f"{len(delete_candidates)} amount_left={delete_bytes_left} "
            f"states={','.join(sorted(delete_states))}"
        )
        if result.get("manifest"):
            print(f"manifest: {result['manifest']}")
        if args.apply_delete:
            print(f"deleted torrents: {result['deleted_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
