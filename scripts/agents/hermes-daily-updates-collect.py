#!/usr/bin/env python3
"""Collect the updates and homelab section for the retained Daily Summary."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MAX_RESPONSE = 4 * 1024 * 1024
CONTAINER_ENDPOINTS = {
    "media-vm": "http://100.66.6.113:2375/containers/json",
    "docker-vm": "http://100.108.254.100:2375/containers/json",
    "nextcloud-vm": "http://100.112.46.126:2375/containers/json",
}
PRIORITY = [
    "tautulli",
    "plex",
    "prowlarr",
    "sonarr",
    "radarr",
    "bazarr",
    "sabnzbd",
    "qbittorrent",
    "vaultwarden",
    "immich-server",
    "seerr",
    "caddy",
    "gitea",
    "freshrss",
    "audiobookshelf",
]
REPOS = {
    "tautulli": "Tautulli/Tautulli",
    "prowlarr": "Prowlarr/Prowlarr",
    "sonarr": "Sonarr/Sonarr",
    "radarr": "Radarr/Radarr",
    "bazarr": "morpheus65535/bazarr",
    "sabnzbd": "sabnzbd/sabnzbd",
    "qbittorrent": "qbittorrent/qBittorrent",
    "vaultwarden": "dani-garcia/vaultwarden",
    "immich-server": "immich-app/immich",
    "seerr": "fallenbagel/jellyseerr",
    "caddy": "caddyserver/caddy",
    "gitea": "go-gitea/gitea",
    "freshrss": "FreshRSS/FreshRSS",
    "audiobookshelf": "advplyr/audiobookshelf",
}
APT_HOSTS = [
    ("local host", None),
    ("ts440", "ts440"),
    ("pve-alto", "pve-alto"),
    ("pve-herc", "pve-herc"),
    ("pve-m70q", "pve-m70q"),
    ("docker-vm", "docker-vm"),
    ("media-vm", "media-vm"),
    ("nextcloud-vm", "nextcloud-vm"),
    ("freepbx-vm", "freepbx-vm"),
    ("homebridge-lxc", "homebridge-lxc"),
    ("syncthing-lxc", "syncthing-lxc"),
    ("pbs-lxc", "pbs-lxc"),
    ("pdm-vm", "pdm-vm"),
    ("mercury", "mercury"),
]
HTTP_CHECKS = [
    ("plex", "100.66.6.113", 32400),
    ("radarr", "100.108.254.100", 7878),
    ("sonarr", "100.108.254.100", 8989),
    ("bazarr", "100.108.254.100", 6767),
    ("sabnzbd", "100.108.254.100", 8080),
    ("prowlarr", "100.108.254.100", 9696),
    ("qbittorrent", "100.108.254.100", 8085),
    ("nextcloud", "100.112.46.126", 11000),
]


class CollectError(RuntimeError):
    pass


def run(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def fetch_json(url: str, timeout: int = 10) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Hermes-DailySummary/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise CollectError("response-too-large")
        return json.loads(body.decode("utf-8"))
    except Exception as exc:
        return {"__error__": str(exc)[:240]}


def atomic_write(path: Path, content: str, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def image_tag(image: str) -> str:
    image = image.split("@", 1)[0]
    final = image.rsplit("/", 1)[-1]
    return image.rsplit(":", 1)[1] if ":" in final else "latest"


def normalise_version(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    text = re.sub(r"^version[-_ ]*", "", text, flags=re.I)
    text = re.sub(r"^[vV]", "", text)
    text = re.sub(r"-ls\d+$", "", text)
    text = re.sub(r"[_+]linuxserver.*$", "", text, flags=re.I)
    text = re.sub(
        r"[-+](hotfix|build|release|stable|alpine|ubuntu|debian).*$",
        "",
        text,
        flags=re.I,
    )
    match = re.search(r"(\d+(?:\.\d+){1,3})", text)
    return match.group(1) if match else text


def version_tuple(value: Any) -> tuple[int, ...] | None:
    numbers = re.findall(r"\d+", normalise_version(value))
    return tuple(int(number) for number in numbers[:4]) if numbers else None


def running_version(container: dict[str, Any]) -> str:
    labels = container.get("Labels") or {}
    for key in (
        "org.opencontainers.image.version",
        "org.label-schema.version",
        "build_version",
        "BUILD_VERSION",
        "version",
    ):
        if labels.get(key):
            return str(labels[key])
    return image_tag(str(container.get("Image", "")))


def service_name(container: dict[str, Any]) -> str:
    names = [value.strip("/") for value in container.get("Names", []) if value]
    name = (names[0] if names else str(container.get("Id", ""))[:12]).casefold()
    if name in {"jellyseerr", "overseerr"}:
        return "seerr"
    if name.startswith("immich_server"):
        return "immich-server"
    return name.replace("_", "-")


def collect_containers() -> tuple[dict[str, Any], list[str]]:
    snapshot: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "services": {},
    }
    errors = []
    for host, url in CONTAINER_ENDPOINTS.items():
        value = fetch_json(url, timeout=8)
        if isinstance(value, dict) and value.get("__error__"):
            errors.append(f"{host}: {value['__error__']}")
            continue
        if not isinstance(value, list):
            errors.append(f"{host}: invalid response")
            continue
        for container in value:
            if not isinstance(container, dict):
                continue
            name = service_name(container)
            image = str(container.get("Image", ""))
            snapshot["services"].setdefault(
                name,
                {
                    "host": host,
                    "image": image,
                    "tag": image_tag(image),
                    "version": running_version(container),
                    "state": container.get("State"),
                    "status": container.get("Status"),
                },
            )
    return snapshot, errors


def snapshot_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    previous = old.get("services", {}) if isinstance(old, dict) else {}
    current = new.get("services", {})
    changes = []
    for name, value in sorted(current.items()):
        prior = previous.get(name)
        if prior is None:
            changes.append(f"Added {name} on {value['host']}: {value['image']}")
        elif any(
            prior.get(key) != value.get(key)
            for key in ("image", "tag", "version")
        ):
            changes.append(
                f"{name} on {value['host']}: image {prior.get('image')} -> "
                f"{value.get('image')}; version {prior.get('version')} -> "
                f"{value.get('version')}"
            )
    for name, value in sorted(previous.items()):
        if name not in current:
            changes.append(f"Removed {name} previously on {value.get('host')}")
    return changes


def github_latest(repository: str) -> str | None:
    value = fetch_json(
        f"https://api.github.com/repos/{repository}/releases/latest", timeout=10
    )
    if isinstance(value, dict) and not value.get("__error__"):
        release = value.get("tag_name") or value.get("name")
        return str(release) if release else None
    return None


def behind_latest(snapshot: dict[str, Any]) -> tuple[list[str], list[str]]:
    behind: list[str] = []
    incomplete: list[str] = []
    services = snapshot.get("services", {})
    for service in PRIORITY:
        record = services.get(service)
        if not isinstance(record, dict):
            incomplete.append(f"{service}: not found in Docker snapshot")
            continue
        if service == "plex":
            incomplete.append(
                "plex: latest PMS version not checked confidently from public releases"
            )
            continue
        repository = REPOS.get(service)
        latest = github_latest(repository) if repository else None
        if not latest:
            incomplete.append(f"{service}: latest release lookup failed")
            continue
        current = normalise_version(record.get("version") or record.get("tag"))
        current_tuple = version_tuple(current)
        latest_tuple = version_tuple(latest)
        if current_tuple is None or latest_tuple is None:
            incomplete.append(
                f"{service}: could not compare current {record.get('version')} "
                f"to latest {latest}"
            )
        elif current_tuple < latest_tuple:
            behind.append(
                f"{service}: {current or record.get('version')} -> "
                f"{normalise_version(latest)}"
            )
    return behind, incomplete


def hermes_info() -> dict[str, Any]:
    rc, installed, error = run(["/usr/local/bin/hermes", "--version"], timeout=20)
    commits = fetch_json(
        "https://api.github.com/repos/NousResearch/hermes-agent/commits?per_page=15",
        timeout=10,
    )
    releases = fetch_json(
        "https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=3",
        timeout=10,
    )
    subjects: list[str] = []
    if isinstance(commits, list):
        for commit in commits[:15]:
            if not isinstance(commit, dict):
                continue
            subject = str(
                ((commit.get("commit") or {}).get("message") or "")
            ).splitlines()[0]
            if subject:
                subjects.append(subject)
    themes: list[str] = []
    joined = " ".join(subjects).casefold()
    for key, label in (
        ("plugin", "plugin/runtime work"),
        ("cron", "scheduler/cron work"),
        ("model", "model routing"),
        ("session", "session handling"),
        ("discord", "Discord integration"),
        ("memory", "memory/context work"),
        ("lcm", "lossless context/recall"),
        ("fix", "bug fixes"),
    ):
        if key in joined:
            themes.append(label)
    release_lines: list[str] = []
    if isinstance(releases, list):
        for release in releases[:3]:
            if isinstance(release, dict):
                release_lines.append(
                    f"{release.get('tag_name') or release.get('name')} "
                    f"({str(release.get('published_at', ''))[:10]})"
                )
    return {
        "installed": installed if rc == 0 else f"unavailable ({error[:120]})",
        "themes": themes,
        "releases": release_lines,
    }


def hermes_capabilities() -> dict[str, Any]:
    plugin_rc, plugin_output, plugin_error = run(
        ["/usr/local/bin/hermes", "plugins", "list", "--json"], timeout=45
    )
    plugins: list[dict[str, Any]] = []
    if plugin_rc == 0 and plugin_output:
        try:
            parsed = json.loads(plugin_output)
            if isinstance(parsed, list):
                plugins = [value for value in parsed if isinstance(value, dict)]
        except json.JSONDecodeError:
            plugins = []
    enabled_plugins = [
        str(plugin.get("name"))
        for plugin in plugins
        if str(plugin.get("status", "")).casefold() in {"enabled", "active"}
    ]
    user_plugins = [
        f"{plugin.get('name')} ({plugin.get('status', 'unknown')})"
        for plugin in plugins
        if plugin.get("source") == "user"
    ]
    skills_rc, skills_output, skills_error = run(
        ["/usr/local/bin/hermes", "skills", "list"], timeout=45
    )
    skills_summary = "unavailable"
    if skills_rc == 0 and skills_output:
        summary_lines = [
            line.strip()
            for line in skills_output.splitlines()
            if re.search(r"\d+ hub-installed, \d+ builtin, \d+ local", line)
        ]
        skills_summary = summary_lines[-1] if summary_lines else "list completed"
    dependency_versions = {}
    for distribution in ("mem0ai", "qdrant-client", "ollama"):
        try:
            dependency_versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            dependency_versions[distribution] = "not installed"
    return {
        "pluginCount": len(plugins),
        "enabledPlugins": enabled_plugins,
        "userPlugins": user_plugins,
        "pluginError": "" if plugin_rc == 0 else plugin_error[:160],
        "skills": skills_summary,
        "skillsError": "" if skills_rc == 0 else skills_error[:160],
        "dependencies": dependency_versions,
    }


def apt_one(item: tuple[str, str | None]) -> tuple[str, dict[str, Any]]:
    name, ssh_host = item
    command = ["/usr/bin/apt", "list", "--upgradable"]
    if ssh_host is not None:
        command = [
            "/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            ssh_host, "/usr/bin/apt", "list", "--upgradable",
        ]
    rc, output, error = run(command, timeout=25)
    if rc not in (0, 100) and not output:
        return name, {"error": (error or f"rc {rc}")[:180]}
    lines = [
        line for line in output.splitlines()
        if line.strip() and not line.startswith("Listing")
    ]
    security = [line for line in lines if re.search(r"security|debian-security", line, re.I)]
    return name, {"count": len(lines), "security": len(security)}


def apt_all() -> dict[str, dict[str, Any]]:
    result = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(apt_one, item) for item in APT_HOSTS]
        for future in as_completed(futures):
            name, value = future.result()
            result[name] = value
    return result


def service_one(item: tuple[str, str, int]) -> tuple[str, str]:
    name, address, port = item
    paths = ("/", "/identity") if name == "plex" else ("/",)
    last = "not checked"
    for path in paths:
        try:
            with urllib.request.urlopen(
                f"http://{address}:{port}{path}", timeout=5
            ) as response:
                return name, f"HTTP {response.getcode()}"
        except urllib.error.HTTPError as exc:
            return name, f"HTTP {exc.code}"
        except (OSError, urllib.error.URLError) as exc:
            last = str(exc)[:120]
    return name, f"unavailable ({last})"


def service_all() -> dict[str, str]:
    result = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(service_one, item) for item in HTTP_CHECKS]
        for future in as_completed(futures):
            name, value = future.result()
            result[name] = value
    return result


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def collect(section: Path, state: Path) -> None:
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/Chicago"))
    old = load_state(state)
    containers, container_errors = collect_containers()
    changes = snapshot_changes(old, containers)
    behind, incomplete = behind_latest(containers)
    packages = apt_all()
    services = service_all()
    hermes = hermes_info()
    capabilities = hermes_capabilities()
    storage_rc, storage, storage_error = run(
        [
            "/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "ts440", "/usr/local/bin/storage-status",
        ],
        timeout=60,
    )

    lines = [
        "Date / generated at",
        "",
        f"- Local: {local.strftime('%A, %B %d, %Y - %-I:%M %p %Z')}",
        f"- UTC: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "Updates",
        "",
        "- Container snapshot:",
    ]
    lines.extend(
        [f"  - {change}" for change in changes[:20]]
        if changes else ["  - No container image, tag, or version changes detected."]
    )
    lines.extend(f"  - Snapshot warning: {value}" for value in container_errors)
    lines.extend(["", "- Currently behind latest:"])
    lines.extend(
        [f"  - {value}" for value in behind]
        if behind else ["  - None confirmed."]
    )
    if incomplete:
        shown = "; ".join(incomplete[:10])
        extra = f"; plus {len(incomplete) - 10} more" if len(incomplete) > 10 else ""
        lines.append(f"  - Coverage incomplete: {shown}{extra}.")
    lines.extend(["", "- Hermes:"])
    lines.append(f"  - Installed: `{hermes['installed']}`")
    if hermes["themes"]:
        lines.append(
            "  - Recent upstream themes: " + ", ".join(hermes["themes"]) + "."
        )
    if hermes["releases"]:
        lines.append(
            "  - Recent releases checked: " + "; ".join(hermes["releases"]) + "."
        )
    lines.extend(["", "- Hermes plugins and skills:"])
    if capabilities["pluginError"]:
        lines.append(f"  - Plugin inventory unavailable: {capabilities['pluginError']}")
    else:
        lines.append(
            f"  - Enabled plugins: {len(capabilities['enabledPlugins'])} of "
            f"{capabilities['pluginCount']}."
        )
        for value in capabilities["userPlugins"][:12]:
            lines.append(f"    - `{value}`")
    lines.append(f"  - Skills: {capabilities['skills']}")
    if capabilities["skillsError"]:
        lines.append(f"  - Skill inventory warning: {capabilities['skillsError']}")
    dependency_text = ", ".join(
        f"{name} {version}"
        for name, version in capabilities["dependencies"].items()
    )
    lines.append(f"  - Memory dependencies: {dependency_text}.")
    lines.extend(["", "- System package updates:"])
    for name, _ in APT_HOSTS:
        value = packages.get(name, {"error": "not checked"})
        if "error" in value:
            lines.append(f"  - {name}: unavailable ({value['error']})")
        else:
            suffix = f", {value['security']} security-flagged" if value["security"] else ""
            lines.append(f"  - {name}: {value['count']} upgradable{suffix}")
    security_hosts = sorted(
        name
        for name, value in packages.items()
        if isinstance(value, dict) and value.get("security")
    )
    if security_hosts:
        lines.append(
            "  - Security updates flagged on: " + ", ".join(security_hosts) + "."
        )
    lines.extend(["", "Homelab", "", "- Service reachability:"])
    for name, _, _ in HTTP_CHECKS:
        lines.append(f"  - {name}: {services.get(name, 'not checked')}")
    lines.extend(["", "- ts440 storage-status:"])
    if storage_rc == 0 and storage:
        lines.extend(f"  {line}" for line in storage.splitlines()[:40])
    else:
        lines.append(f"  - unavailable: {(storage_error or 'no output')[:240]}")
    atomic_write(section, "\n".join(lines))
    atomic_write(state, json.dumps(containers, indent=2, sort_keys=True), mode=0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        collect(args.section, args.state)
        print(json.dumps({"status": "ok", "section": str(args.section)}))
        return 0
    except (CollectError, OSError, subprocess.SubprocessError) as exc:
        print(f"Hermes Daily Summary updates collection failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
