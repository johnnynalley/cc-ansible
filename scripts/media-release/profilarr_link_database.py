#!/usr/bin/env python3
"""Link a Profilarr database through the local authenticated web app.

Run this on docker-vm with privileges that can read the Profilarr admin password
file. The password is used only for the local login form and is never printed.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_URL = "http://127.0.0.1:6868"
DEFAULT_DB = "/opt/profilarr/config/data/profilarr.db"
DEFAULT_PASSWORD_FILE = "/root/profilarr-admin.initial-password"
DEFAULT_BACKUP_DIR = "/opt/profilarr/config/data/backups"
DEFAULT_DATA_ROOT = "/opt/profilarr/config/data"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_form(
    opener: urllib.request.OpenerDirector,
    url: str,
    data: dict[str, str],
    origin: str,
) -> tuple[int, str]:
    encoded = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": origin,
            "Referer": url,
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def is_redirect_success(status: int, body: str, location: str | None = None) -> bool:
    if status == 303:
        return True
    if status != 200:
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    if payload.get("type") != "redirect":
        return False
    if location is not None and payload.get("location") != location:
        return False
    return True


def database_exists(db_path: Path, name: str, repository_url: str) -> bool:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            """
            SELECT 1 FROM database_instances
            WHERE lower(name) = lower(?) OR lower(repository_url) = lower(?)
            LIMIT 1
            """,
            (name, repository_url),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def latest_link_job(db_path: Path) -> dict[str, Any] | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, job_type, status, run_at, payload, source, attempts,
                   started_at, finished_at, created_at, updated_at
            FROM job_queue
            WHERE job_type = 'pcd.link'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def wait_for_database(db_path: Path, name: str, repository_url: str, timeout: int) -> tuple[bool, dict[str, Any] | None]:
    deadline = time.monotonic() + timeout
    job = None
    while time.monotonic() < deadline:
        if database_exists(db_path, name, repository_url):
            return True, latest_link_job(db_path)
        job = latest_link_job(db_path)
        if job and job.get("status") in {"failed", "cancelled"}:
            return False, job
        time.sleep(3)
    return database_exists(db_path, name, repository_url), job


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "database"


def backup_database(db_path: Path, backup_dir: Path, name: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"profilarr-pre-link-{slugify(name)}-{stamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def direct_link_database(args: argparse.Namespace, db_path: Path) -> dict[str, Any]:
    database_uuid = str(uuid4())
    repo_path = Path(args.data_root) / "databases" / database_uuid
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    clone_cmd = [
        "git",
        "clone",
        "--branch",
        args.branch,
        "--depth",
        "1",
        args.repository_url,
        str(repo_path),
    ]
    subprocess.run(clone_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    local_path = f"/config/data/databases/{database_uuid}"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO database_instances (
                uuid, name, repository_url, local_path, sync_strategy, auto_pull,
                enabled, last_synced_at, created_at, updated_at,
                personal_access_token, is_private, local_ops_enabled,
                git_user_name, git_user_email, conflict_strategy
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    NULL, 0, 0, NULL, NULL, 'override')
            """,
            (
                database_uuid,
                args.name,
                args.repository_url,
                local_path,
                int(args.sync_strategy),
                1 if args.auto_pull else 0,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        shutil.rmtree(repo_path, ignore_errors=True)
        raise
    finally:
        conn.close()
    return {"uuid": database_uuid, "local_path": local_path, "repo_path": str(repo_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--username", default="johnny")
    parser.add_argument("--password-file", default=DEFAULT_PASSWORD_FILE)
    parser.add_argument("--name", default="Dumpstarr")
    parser.add_argument("--repository-url", default="https://github.com/Dumpstarr/Database")
    parser.add_argument("--branch", default="stable")
    parser.add_argument("--sync-strategy", default="60")
    parser.add_argument("--auto-pull", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="insert the database row and clone the repo directly; restart Profilarr afterwards",
    )
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)

    if database_exists(db_path, args.name, args.repository_url):
        report = {"changed": False, "reason": "database already linked", "name": args.name}
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"{args.name}: already linked")
        return 0

    backup_path = None
    if not args.skip_backup:
        backup_path = backup_database(db_path, Path(args.backup_dir), args.name)

    if args.direct:
        direct = direct_link_database(args, db_path)
        report = {
            "changed": True,
            "linked": True,
            "name": args.name,
            "backup_path": str(backup_path) if backup_path else None,
            "method": "direct",
            "direct": direct,
        }
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            backup_text = f"; backup={backup_path}" if backup_path else ""
            print(f"{args.name}: linked directly{backup_text}; restart Profilarr to import ops")
        return 0

    password = Path(args.password_file).read_text().strip()
    cookiejar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar), NoRedirect)
    base_url = args.url.rstrip("/")
    status, body = post_form(
        opener,
        f"{base_url}/auth/login",
        {"username": args.username, "password": password},
        base_url,
    )
    if not is_redirect_success(status, body, "/"):
        raise RuntimeError(f"login failed with HTTP {status}: {body[:200]}")

    form = {
        "name": args.name,
        "repository_url": args.repository_url,
        "branch": args.branch,
        "sync_strategy": str(args.sync_strategy),
        "auto_pull": "1" if args.auto_pull else "0",
        "local_ops_enabled": "0",
        "conflict_strategy": "override",
    }
    status, body = post_form(opener, f"{base_url}/databases/new", form, base_url)
    if not is_redirect_success(status, body, "/databases"):
        raise RuntimeError(f"database link form failed with HTTP {status}: {body[:500]}")

    linked, job = wait_for_database(db_path, args.name, args.repository_url, args.wait_seconds)
    report = {
        "changed": True,
        "linked": linked,
        "name": args.name,
        "backup_path": str(backup_path) if backup_path else None,
        "method": "form",
        "latest_link_job": job,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        backup_text = f"; backup={backup_path}" if backup_path else ""
        print(f"{args.name}: link queued; linked={linked}{backup_text}; latest_link_job={job}")
    return 0 if linked else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
