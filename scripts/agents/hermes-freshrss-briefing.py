#!/usr/bin/env python3
"""Collect FreshRSS candidates for Astra's single Daily Summary delivery path."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_CREDENTIAL = Path("/etc/hermes/astra/freshrss.json")
MAX_RESPONSE = 4 * 1024 * 1024
MAX_TOTAL = 10
MAX_PER_CATEGORY = 2
CATEGORIES = {
    "OpenClaw / AI": (
        "openclaw", "hermes agent", "anthropic", "claude", "openrouter",
        "gpt-5", "gpt 5", "llm", "ai agent", "agentic",
    ),
    "Linux / Kernel": (
        "linux", "kernel", "systemd", "wayland", "pipewire", "mesa",
        "btrfs", "nvidia", "kde", "gnome",
    ),
    "Homelab / Self-hosting": (
        "self-host", "self host", "homelab", "proxmox", "zfs",
        "nextcloud", "docker", "caddy", "vaultwarden", "immich",
        "jellyfin", "plex", "servarr", "sonarr", "radarr", "prowlarr",
        "sabnzbd", "qbittorrent",
    ),
    "Apple / Asahi": (
        "apple", "macos", "ios", "iphone", "ipad", "macbook", "asahi",
        "apple silicon",
    ),
    "Security / Infra": (
        "security", "cve", "vulnerability", "exploit", "openssl", "ssh",
        "wireguard", "tailscale", "cloudflare",
    ),
}


class BriefingError(RuntimeError):
    """Raised for a bounded FreshRSS collection failure."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BriefingError(f"invalid-json:{path.name}") from exc
    return value


def _request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Hermes-Astra-FreshRSS/1.0",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise BriefingError("response-too-large")
    return body


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _category(item: dict[str, Any]) -> str | None:
    haystack = " ".join(
        (item.get("title", ""), item.get("origin", ""), item.get("summary", ""))
    ).casefold()
    for name, keywords in CATEGORIES.items():
        if any(keyword in haystack for keyword in keywords):
            return name
    return None


def _normalize(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise BriefingError("items-invalid")
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    result: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        published = raw.get("published")
        published_at = (
            datetime.fromtimestamp(published, tz=timezone.utc)
            if isinstance(published, (int, float)) and not isinstance(published, bool)
            else None
        )
        if published_at is not None and published_at < cutoff:
            continue
        alternate = raw.get("alternate")
        url = alternate[0].get("href") if isinstance(alternate, list) and alternate else None
        origin = raw.get("origin") if isinstance(raw.get("origin"), dict) else {}
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        item = {
            "id": str(raw.get("id") or "")[:500],
            "title": str(raw.get("title") or "").strip()[:300],
            "origin": str(origin.get("title") or "")[:200],
            "url": str(url or "")[:2000],
            "published": published_at.isoformat() if published_at else None,
            "summary": _strip_html(summary.get("content"))[:320],
        }
        category = _category(item)
        if category:
            item["category"] = category
            result.append(item)
    return result


def _select(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for category in CATEGORIES:
        result.extend([item for item in items if item["category"] == category][:MAX_PER_CATEGORY])
        if len(result) >= MAX_TOTAL:
            break
    return result[:MAX_TOTAL]


def _briefing(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["📰 **RSS Briefing**"]
    current = None
    for item in items:
        if item["category"] != current:
            current = item["category"]
            lines.extend(("", f"**{current}:**"))
        title = item["title"] or "(untitled)"
        origin = item["origin"] or "Unknown source"
        lines.append(f"- {title} — {origin} <{item['url']}>")
    return "\n".join(lines)


def _daily_summary_section(payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    lines = [
        "## RSS Candidates",
        "",
        f"- Generated: {payload.get('generatedAt', 'unknown')}",
        f"- Candidate count: {len(items)}",
        "- These are collector candidates, not approved briefing items. "
        "The Daily Summary compose agent must review relevance and accuracy.",
    ]
    if not items:
        lines.append("- No current matching unread items.")
        return "\n".join(lines)

    current_category = None
    for item in items:
        category = item.get("category") or "Uncategorized"
        if category != current_category:
            lines.extend(("", f"- {category}:"))
            current_category = category
        title = item.get("title") or "(untitled)"
        origin = item.get("origin") or "Unknown source"
        published = item.get("published") or "publish time unavailable"
        url = item.get("url") or ""
        lines.append(f"  - {title} | {origin} | {published} | <{url}>")
        if item.get("summary"):
            lines.append(f"    - Source summary: {item['summary']}")
    return "\n".join(lines)


def collect(credential_path: Path, root: Path, section_path: Path) -> dict[str, Any]:
    credential = _read_json(credential_path)
    if not isinstance(credential, dict) or set(credential) < {
        "endpoint", "username", "password",
    }:
        raise BriefingError("credential-schema")
    endpoint = str(credential["endpoint"]).rstrip("/")
    auth_body = urllib.parse.urlencode(
        {"Email": credential["username"], "Passwd": credential["password"]}
    ).encode("utf-8")
    auth = _request(f"{endpoint}/accounts/ClientLogin", data=auth_body).decode("utf-8")
    token = next((line[5:] for line in auth.splitlines() if line.startswith("Auth=")), "")
    if not token:
        raise BriefingError("auth-token-missing")
    url = (
        f"{endpoint}/reader/api/0/stream/contents/user/-/state/"
        "com.google/reading-list?output=json&n=100&xt=user/-/state/com.google/read"
    )
    raw = json.loads(
        _request(url, headers={"Authorization": f"GoogleLogin auth={token}"}).decode(
            "utf-8"
        )
    )
    if not isinstance(raw, dict):
        raise BriefingError("feed-invalid")
    normalized = _normalize(raw.get("items", []))
    selected = _select(normalized)
    generated_at = _now_iso()
    payload = {
        "generatedAt": generated_at,
        "count": len(selected),
        "items": selected,
    }
    _atomic_write(root / "latest-briefing.json", json.dumps(payload, indent=2, sort_keys=True))
    _atomic_write(root / "latest-briefing.md", _briefing(selected))
    _atomic_write(section_path, _daily_summary_section(payload), mode=0o640)
    _atomic_write(
        root / "state.json",
        json.dumps(
            {
                "lastRun": generated_at,
                "matched": len(normalized),
                "candidateCount": len(selected),
            },
            indent=2,
            sort_keys=True,
        ),
    )
    return {
        "status": "ok",
        "matched": len(normalized),
        "candidateCount": len(selected),
        "section": str(section_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential", type=Path, default=DEFAULT_CREDENTIAL)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--section", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.credential, args.root, args.section), sort_keys=True))
        return 0
    except (
        BriefingError,
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"FreshRSS Daily Summary collection failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
