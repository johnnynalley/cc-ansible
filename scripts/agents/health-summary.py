#!/usr/bin/env python3
"""Deterministic Apple Health daily summary with duplicate-row collapse.

Health Auto Export sends rolling windows, so the receiver can see the same
minute sample many times. This script intentionally does not trust raw SUM().
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_DB_PATH = Path("/var/lib/openclaw-health/health.db")
TZ = ZoneInfo("America/Chicago")


@dataclass
class MetricSummary:
    metric: str
    total: float | None
    rawTotal: float | None
    rows: int
    rawRows: int
    rowDuplicateFactor: float | None
    valueDuplicateFactor: float | None
    unit: str | None = None


def default_date() -> str:
    return (datetime.now(TZ).date() - timedelta(days=1)).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    connection.execute("PRAGMA query_only = ON")
    return connection


def metric_total(cur: sqlite3.Cursor, metric: str, date: str) -> MetricSummary:
    raw_total, raw_rows, unit = cur.execute(
        """
        SELECT SUM(value), COUNT(*), MAX(unit)
        FROM health_metrics
        WHERE metric_name = ? AND substr(date_start, 1, 10) = ?
        """,
        (metric, date),
    ).fetchone()
    total, rows = cur.execute(
        """
        SELECT SUM(value), COUNT(*)
        FROM (
            SELECT MAX(value) AS value
            FROM health_metrics
            WHERE metric_name = ? AND substr(date_start, 1, 10) = ?
            GROUP BY metric_name, date_start, date_end, source, unit
        )
        """,
        (metric, date),
    ).fetchone()
    raw_rows = int(raw_rows or 0)
    rows = int(rows or 0)
    return MetricSummary(
        metric=metric,
        total=float(total) if total is not None else None,
        rawTotal=float(raw_total) if raw_total is not None else None,
        rows=rows,
        rawRows=raw_rows,
        rowDuplicateFactor=(raw_rows / rows) if rows else None,
        valueDuplicateFactor=(
            (float(raw_total) / float(total)) if raw_total and total else None
        ),
        unit=unit,
    )


def metric_avg(cur: sqlite3.Cursor, metric: str, date: str) -> MetricSummary:
    raw_total, raw_rows, unit = cur.execute(
        """
        SELECT AVG(value), COUNT(*), MAX(unit)
        FROM health_metrics
        WHERE metric_name = ? AND substr(date_start, 1, 10) = ?
        """,
        (metric, date),
    ).fetchone()
    avg, rows = cur.execute(
        """
        SELECT AVG(value), COUNT(*)
        FROM (
            SELECT MAX(value) AS value
            FROM health_metrics
            WHERE metric_name = ? AND substr(date_start, 1, 10) = ?
            GROUP BY metric_name, date_start, date_end, source, unit
        )
        """,
        (metric, date),
    ).fetchone()
    raw_rows = int(raw_rows or 0)
    rows = int(rows or 0)
    return MetricSummary(
        metric=metric,
        total=float(avg) if avg is not None else None,
        rawTotal=float(raw_total) if raw_total is not None else None,
        rows=rows,
        rawRows=raw_rows,
        rowDuplicateFactor=(raw_rows / rows) if rows else None,
        valueDuplicateFactor=None,
        unit=unit,
    )


def normalize_percentage(summary: MetricSummary) -> MetricSummary:
    """Normalize HealthKit fractions while preserving already-percent values."""
    if summary.total is not None and 0 <= summary.total <= 1:
        summary.total *= 100
    if summary.rawTotal is not None and 0 <= summary.rawTotal <= 1:
        summary.rawTotal *= 100
    return summary


def sleep_summary(cur: sqlite3.Cursor, date: str) -> dict:
    rows = cur.execute(
        """
        SELECT sleep_state, date_start, date_end, source, MAX(duration_minutes) AS duration_minutes
        FROM sleep
        WHERE substr(date_start, 1, 10) = ?
        GROUP BY sleep_state, date_start, date_end, source
        """,
        (date,),
    ).fetchall()
    return {
        "rows": len(rows),
        "minutes": sum(float(r[4] or 0) for r in rows),
        "states": sorted({r[0] for r in rows if r[0]}),
    }


def workout_summary(cur: sqlite3.Cursor, date: str) -> dict:
    rows = cur.execute(
        """
        SELECT workout_type, date_start, date_end, source, MAX(duration_minutes), MAX(calories), MAX(distance), MAX(distance_unit)
        FROM workouts
        WHERE substr(date_start, 1, 10) = ?
        GROUP BY workout_type, date_start, date_end, source
        """,
        (date,),
    ).fetchall()
    return {
        "rows": len(rows),
        "minutes": sum(float(r[4] or 0) for r in rows),
        "calories": sum(float(r[5] or 0) for r in rows),
        "distance": sum(float(r[6] or 0) for r in rows),
        "types": sorted({r[0] for r in rows if r[0]}),
    }


def fmt_int(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value):,}"


def fmt_1(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def fmt_mi(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def build(date: str, db_path: Path = DEFAULT_DB_PATH) -> dict:
    if not db_path.exists():
        return {
            "schemaVersion": 1,
            "ok": False,
            "date": date,
            "error": "health database is unavailable",
        }

    with closing(connect(db_path)) as con:
        cur = con.cursor()
        totals = {
            name: metric_total(cur, name, date)
            for name in [
                "step_count",
                "walking_running_distance",
                "active_energy",
                "apple_exercise_time",
                "flights_climbed",
                "apple_stand_hour",
            ]
        }
        avgs = {
            name: metric_avg(cur, name, date)
            for name in [
                "resting_heart_rate",
                "heart_rate_variability",
                "blood_oxygen_saturation",
                "respiratory_rate",
            ]
        }
        avgs["blood_oxygen_saturation"] = normalize_percentage(
            avgs["blood_oxygen_saturation"]
        )
        sleep = sleep_summary(cur, date)
        workouts = workout_summary(cur, date)

    warnings: list[str] = []
    steps = totals["step_count"].total or 0
    distance = totals["walking_running_distance"].total or 0
    active = totals["active_energy"].total or 0
    duplicate_factors = [
        m.valueDuplicateFactor for m in totals.values() if m.valueDuplicateFactor
    ]
    worst_duplicate = max(duplicate_factors) if duplicate_factors else 1.0

    if steps > 35000:
        warnings.append("steps exceed typical daily maximum - verify if accurate")
    if distance > 20:
        warnings.append(
            "walking/running distance exceeds typical daily maximum - verify if accurate"
        )
    if active > 2500:
        warnings.append(
            "active energy exceeds typical daily maximum - verify if accurate"
        )
    if worst_duplicate > 1.2:
        warnings.append(
            f"duplicate receiver rows collapsed before reporting; worst raw/dedup factor {worst_duplicate:.1f}x"
        )

    return {
        "schemaVersion": 1,
        "ok": True,
        "date": date,
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "totals": {k: asdict(v) for k, v in totals.items()},
        "averages": {k: asdict(v) for k, v in avgs.items()},
        "sleep": sleep,
        "workouts": workouts,
        "warnings": warnings,
    }


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8") as output:
            output.write(content)
            if not content.endswith("\n"):
                output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temp_path.chmod(0o640)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def markdown(summary: dict, include_heading: bool = True) -> str:
    if not summary.get("ok"):
        body = (
            f"- ⚠️ Health data unavailable - {summary.get('error', 'unknown error')}."
        )
        return "## Health\n\n" + body if include_heading else body

    date = datetime.fromisoformat(summary["date"]).strftime("%B %-d")
    t = summary["totals"]
    a = summary["averages"]
    sleep = summary["sleep"]
    workouts = summary["workouts"]

    lines: list[str] = []
    if include_heading:
        lines.extend(["## Health", ""])

    lines.append(
        f"- Yesterday, {date}: {fmt_int(t['step_count']['total'])} steps, "
        f"{fmt_mi(t['walking_running_distance']['total'])} mi walking/running distance, "
        f"{fmt_int(t['active_energy']['total'])} active kcal, "
        f"{fmt_int(t['apple_exercise_time']['total'])} exercise minutes, "
        f"{fmt_1(t['flights_climbed']['total'])} flights climbed, "
        f"and {fmt_int(t['apple_stand_hour']['total'])} stand hours."
    )

    vitals: list[str] = []
    if a["resting_heart_rate"]["total"] is not None:
        vitals.append(f"Resting HR avg {fmt_int(a['resting_heart_rate']['total'])} bpm")
    if a["heart_rate_variability"]["total"] is not None:
        vitals.append(f"HRV avg {fmt_1(a['heart_rate_variability']['total'])} ms")
    if a["blood_oxygen_saturation"]["total"] is not None:
        vitals.append(f"SpO2 avg {fmt_1(a['blood_oxygen_saturation']['total'])}%")
    if a["respiratory_rate"]["total"] is not None:
        vitals.append(
            f"respiratory rate avg {fmt_1(a['respiratory_rate']['total'])}/min"
        )
    if vitals:
        lines.append("- " + "; ".join(vitals) + ".")

    if sleep["rows"] or workouts["rows"]:
        bits = []
        if sleep["rows"]:
            bits.append(
                f"sleep rows {sleep['rows']} ({sleep['minutes'] / 60:.1f}h recorded)"
            )
        else:
            bits.append("no sleep rows")
        if workouts["rows"]:
            bits.append(
                f"workouts {workouts['rows']} ({workouts['minutes']:.0f} min recorded)"
            )
        else:
            bits.append("no workouts")
        lines.append("- Receiver recorded " + "; ".join(bits) + ".")
    else:
        lines.append(
            "- No sleep rows or workouts were recorded in the receiver for yesterday."
        )

    raw_steps = t["step_count"]["rawTotal"]
    dedup_steps = t["step_count"]["total"]
    if summary["warnings"]:
        warning = "; ".join(summary["warnings"])
        if raw_steps and dedup_steps and raw_steps > dedup_steps * 1.2:
            warning += f" (steps raw {fmt_int(raw_steps)} -> {fmt_int(dedup_steps)})"
        lines.append("- ⚠️ Health sanity: " + warning + ".")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=default_date(),
        help="Local date YYYY-MM-DD, default yesterday America/Chicago",
    )
    parser.add_argument(
        "--db-path", type=Path, default=DEFAULT_DB_PATH, help=argparse.SUPPRESS
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--no-heading", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        parsed_date = datetime.strptime(args.date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        parser.error("--date must be YYYY-MM-DD")

    summary = build(parsed_date, args.db_path)
    if args.format == "json":
        rendered = json.dumps(summary, indent=2, sort_keys=True)
    else:
        rendered = markdown(summary, include_heading=not args.no_heading)
    if args.output:
        write_atomic(args.output, rendered)
    else:
        print(rendered)
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
