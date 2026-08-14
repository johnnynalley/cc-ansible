#!/usr/bin/env python3
"""Emit deduplicated STW and first-time shop alerts at fixed UTC slots."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hermes_cron_delivery import (
    DeliveryStateError,
    load_job_status,
    reconcile,
    stage,
)


SLOTS = {(0, 10), (0, 35), (1, 0)}
MAX_OUTPUT = 64_000
JOB_NAME = "astra-stw-vbucks-shop-watch"
JOB_SCRIPT = "hermes-stw-watch.py"


def run_collector(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > MAX_OUTPUT:
        raise RuntimeError(f"collector-failed:{path.name}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or value.get("error"):
        raise RuntimeError(f"collector-invalid:{path.name}")
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_state(path: Path, now: datetime) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    posted = value.get("posted") if isinstance(value, dict) else None
    if not isinstance(posted, dict):
        posted = {}
    cutoff = (now - timedelta(days=14)).date().isoformat()
    return {
        "posted": {key: item for key, item in posted.items() if key >= cutoff},
        "pending": value.get("pending") if isinstance(value, dict) else None,
    }


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_vbucks(value: dict[str, Any]) -> list[dict[str, Any]]:
    missions = value.get("missions")
    if not isinstance(missions, list) or value.get("count") != len(missions):
        raise RuntimeError("vbucks-count-mismatch")
    if value.get("total") != sum(item.get("amount", 0) for item in missions if isinstance(item, dict)):
        raise RuntimeError("vbucks-total-mismatch")
    for item in missions:
        if not isinstance(item, dict) or not all(
            (
                isinstance(item.get("amount"), int) and item["amount"] > 0,
                isinstance(item.get("power_level"), int) and item["power_level"] > 0,
                isinstance(item.get("zone"), str) and bool(item["zone"].strip()),
            )
        ):
            raise RuntimeError("vbucks-invalid-row")
    return missions


def validate_shop(value: dict[str, Any]) -> list[dict[str, Any]]:
    items = value.get("new_items")
    if not isinstance(items, list) or value.get("count") != len(items):
        raise RuntimeError("shop-count-mismatch")
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("firstTimeInShop") is not True:
            raise RuntimeError("shop-invalid-row")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or name.casefold() in names:
            raise RuntimeError("shop-duplicate-row")
        names.add(name.casefold())
    return items


def main() -> int:
    now = datetime.now(timezone.utc)
    home = Path(os.environ.get("HERMES_HOME", Path.home())).resolve()
    state_path = home / "state" / "stw-watch.json"
    state = load_state(state_path, now)
    try:
        status = load_job_status(home, JOB_NAME, JOB_SCRIPT)
        disposition, pending = reconcile(state["pending"], status)
    except DeliveryStateError as exc:
        print(f"STW delivery state invalid: {exc}", file=sys.stderr)
        return 1
    if disposition == "delivered" and pending is not None:
        delivered_at = now.isoformat()
        for key in pending["keys"]:
            state["posted"][key] = {"status": "delivered", "at": delivered_at}
        state["pending"] = None
        atomic_write(state_path, state)
    elif disposition == "retry" and pending is not None:
        state["pending"] = pending
        atomic_write(state_path, state)
        print(pending["payload"])
        return 0
    elif disposition == "waiting":
        return 0
    if (now.hour, now.minute) not in SLOTS:
        return 0
    slot = f"{now.date().isoformat()}T{now.hour:02d}:{now.minute:02d}Z"
    if slot in state["posted"]:
        return 0
    scripts = home / "scripts"
    try:
        missions = validate_vbucks(run_collector(scripts / "hermes-vbucks-check.py"))
        shop_items = validate_shop(run_collector(scripts / "hermes-shop-check.py"))
    except (RuntimeError, json.JSONDecodeError) as exc:
        state["posted"][slot] = {"status": "error", "reason": str(exc)}
        atomic_write(state_path, state)
        print(f"STW scheduled check failed validation: {exc}", file=sys.stderr)
        return 1
    lines: list[str] = []
    alert_keys: list[str] = []
    if missions:
        key = f"{now.date().isoformat()}:vbucks:{digest(missions)}"
        if key not in state["posted"]:
            lines.append("<@740687933803331726> **STW V-Bucks**")
            for item in missions:
                mission_type = f" {item['type']}" if item.get("type") else ""
                lines.append(
                    f"- {item['amount']} V-Bucks, PL {item['power_level']}, "
                    f"{item['zone']}{mission_type}"
                )
            alert_keys.append(key)
    if shop_items:
        key = f"{now.date().isoformat()}:shop:{digest(shop_items)}"
        if key not in state["posted"]:
            if lines:
                lines.append("")
            lines.append("<@740687933803331726> **Item Shop first-time items**")
            for item in shop_items:
                detail = item.get("type") or item.get("rarity") or "item"
                price = f" - {item['price']} V-Bucks" if item.get("price") else ""
                lines.append(f"- {item['name']} ({detail}){price}")
            alert_keys.append(key)
    state["posted"][slot] = {"status": "checked"}
    if lines:
        payload = "\n".join(lines)
        try:
            state["pending"] = stage(alert_keys, payload, status, now)
        except DeliveryStateError as exc:
            print(f"STW alert refused: {exc}", file=sys.stderr)
            return 1
    atomic_write(state_path, state)
    if lines:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
