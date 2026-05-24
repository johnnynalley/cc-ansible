#!/usr/bin/env python3
"""Link a Profilarr database through the local authenticated web app.

Run this on media-vm with privileges that can read the Profilarr admin password
file. The password is used only for the local login form and is never printed.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_URL = "http://127.0.0.1:6868"
DEFAULT_DB = "/opt/profilarr/config/data/profilarr.db"
DEFAULT_PASSWORD_FILE = "/root/profilarr-admin.initial-password"


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
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    password = Path(args.password_file).read_text().strip()

    if database_exists(db_path, args.name, args.repository_url):
        report = {"changed": False, "reason": "database already linked", "name": args.name}
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"{args.name}: already linked")
        return 0

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
    report = {"changed": True, "linked": linked, "name": args.name, "latest_link_job": job}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{args.name}: link queued; linked={linked}; latest_link_job={job}")
    return 0 if linked else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
