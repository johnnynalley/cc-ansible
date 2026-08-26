#!/usr/bin/env python3
"""Normalize Fortnite progress snapshots, compute trends, and format summaries.

JSON snapshots stay the source of truth. This script builds derived artifacts:
- fortnite-progress/history.sqlite
- fortnite-progress/exports/*.csv
- fortnite-progress/trends/latest-trends.json
- fortnite-progress/milestones/state.json + events.jsonl

Modes are discovered dynamically from snapshot data. Fortnite-API provides:
overall, solo, duo, squad, ltm. OliTracker adds: reload, reload_duos, etc.,
ranked, ranked_duos, etc.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hermes_fortnite_rank import ranked_progression_issue

ROOT = Path(os.environ.get('HERMES_AUTOMATION_WORKSPACE', '/var/lib/hermes-automation/workspace'))
PROGRESS = ROOT / 'fortnite-progress'
SNAPDIR = PROGRESS / 'snapshots'
DB = PROGRESS / 'history.sqlite'
EXPORTS = PROGRESS / 'exports'
TRENDS_DIR = PROGRESS / 'trends'
MILESTONES = PROGRESS / 'milestones'
TREND_LATEST = TRENDS_DIR / 'latest-trends.json'
STATE_PATH = MILESTONES / 'state.json'
EVENTS_PATH = MILESTONES / 'events.jsonl'

WINDOWS = ('season', 'lifetime')
# Base modes from Fortnite-API. OliTracker modes are discovered dynamically.
BASE_MODES = ('overall', 'solo', 'duo', 'squad', 'ltm')
COUNTERS = ('matches', 'wins', 'kills', 'deaths', 'minutesPlayed', 'playersOutlived')
RESET_COUNTERS = ('matches', 'wins', 'kills', 'deaths', 'minutesPlayed', 'playersOutlived')


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    with open(fd, 'w') as f:
        f.write(text)
    Path(tmp).replace(path)


def atomic_json(path: Path, data: Any) -> None:
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + '\n')


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not data.get('capturedAt'):
        raise ValueError(f'{path}: missing capturedAt')
    data['_path'] = str(path)
    data['_captured_dt'] = parse_ts(data['capturedAt'])
    return data


def load_snapshots() -> list[dict[str, Any]]:
    snaps = []
    for path in sorted(SNAPDIR.glob('*.json')):
        try:
            snaps.append(load_snapshot(path))
        except Exception as e:
            print(f'warning: skipping {path}: {e}', file=sys.stderr)
    snaps.sort(key=lambda s: (s['_captured_dt'], s['_path']))
    return snaps


def discover_modes(snaps: list[dict[str, Any]]) -> tuple[str, ...]:
    """Discover all mode names present across all snapshots."""
    modes: set[str] = set(BASE_MODES)
    for snap in snaps:
        for window in WINDOWS:
            snap_modes = (((snap.get(window) or {}).get('modes')) or {})
            modes.update(snap_modes.keys())
    # Sort: base modes first in canonical order, then OliTracker modes alphabetically
    ordered = list(BASE_MODES) + sorted(m for m in modes if m not in BASE_MODES)
    return tuple(ordered)


def metric_num(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
        return value
    return None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript('''
    create table if not exists snapshots (
      snapshot_id text primary key,
      captured_at text not null,
      epic_name text,
      account_type text,
      source text,
      raw_path text not null,
      battle_pass_level integer,
      battle_pass_progress integer
    );

    create table if not exists stat_buckets (
      snapshot_id text not null,
      captured_at text not null,
      time_window text not null,
      bucket text not null,
      matches integer,
      wins integer,
      kills integer,
      deaths integer,
      kd real,
      win_rate real,
      kills_per_match real,
      kills_per_min real,
      minutes_played integer,
      players_outlived integer,
      last_modified text,
      primary key (snapshot_id, time_window, bucket),
      foreign key (snapshot_id) references snapshots(snapshot_id)
    );

    create table if not exists daily_deltas (
      from_snapshot_id text not null,
      to_snapshot_id text not null,
      from_captured_at text not null,
      to_captured_at text not null,
      time_window text not null,
      bucket text not null,
      matches integer,
      wins integer,
      kills integer,
      deaths integer,
      minutes_played integer,
      players_outlived integer,
      period_kd real,
      period_win_rate real,
      period_kills_per_match real,
      period_minutes_per_match real,
      primary key (from_snapshot_id, to_snapshot_id, time_window, bucket)
    );
    ''')


def upsert_snapshot(conn: sqlite3.Connection, snap: dict[str, Any], modes: tuple[str, ...]) -> None:
    sid = snap['capturedAt']
    bp = ((snap.get('season') or {}).get('battlePass') or (snap.get('lifetime') or {}).get('battlePass') or {})
    conn.execute(
        '''insert into snapshots(snapshot_id,captured_at,epic_name,account_type,source,raw_path,battle_pass_level,battle_pass_progress)
           values(?,?,?,?,?,?,?,?)
           on conflict(snapshot_id) do update set
             captured_at=excluded.captured_at,
             epic_name=excluded.epic_name,
             account_type=excluded.account_type,
             source=excluded.source,
             raw_path=excluded.raw_path,
             battle_pass_level=excluded.battle_pass_level,
             battle_pass_progress=excluded.battle_pass_progress''',
        (sid, snap['capturedAt'], snap.get('epicName'), snap.get('accountType'), snap.get('source'), snap['_path'], bp.get('level'), bp.get('progress')),
    )
    for window in WINDOWS:
        snap_modes = (((snap.get(window) or {}).get('modes')) or {})
        for bucket in modes:
            m = snap_modes.get(bucket) or {}
            conn.execute(
                '''insert into stat_buckets(snapshot_id,captured_at,time_window,bucket,matches,wins,kills,deaths,kd,win_rate,kills_per_match,kills_per_min,minutes_played,players_outlived,last_modified)
                   values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   on conflict(snapshot_id,time_window,bucket) do update set
                     captured_at=excluded.captured_at,
                     matches=excluded.matches,
                     wins=excluded.wins,
                     kills=excluded.kills,
                     deaths=excluded.deaths,
                     kd=excluded.kd,
                     win_rate=excluded.win_rate,
                     kills_per_match=excluded.kills_per_match,
                     kills_per_min=excluded.kills_per_min,
                     minutes_played=excluded.minutes_played,
                     players_outlived=excluded.players_outlived,
                     last_modified=excluded.last_modified''',
                (
                    sid,
                    snap['capturedAt'],
                    window,
                    bucket,
                    metric_num(m.get('matches')),
                    metric_num(m.get('wins')),
                    metric_num(m.get('kills')),
                    metric_num(m.get('deaths')),
                    metric_num(m.get('kd')),
                    metric_num(m.get('winRate')),
                    metric_num(m.get('killsPerMatch')),
                    metric_num(m.get('killsPerMin')),
                    metric_num(m.get('minutesPlayed')),
                    metric_num(m.get('playersOutlived')),
                    m.get('lastModified'),
                ),
            )


def prune_removed_snapshots(conn: sqlite3.Connection, snaps: list[dict[str, Any]]) -> None:
    ids = [snap['capturedAt'] for snap in snaps]
    if not ids:
        conn.execute('delete from daily_deltas')
        conn.execute('delete from stat_buckets')
        conn.execute('delete from snapshots')
        return
    placeholders = ','.join('?' for _ in ids)
    conn.execute(f'delete from stat_buckets where snapshot_id not in ({placeholders})', ids)
    conn.execute(f'delete from snapshots where snapshot_id not in ({placeholders})', ids)


def counter_reset_detected(cur: dict[str, Any], prev: dict[str, Any]) -> bool:
    for k in RESET_COUNTERS:
        cv = metric_num(cur.get(k))
        pv = metric_num(prev.get(k))
        if isinstance(cv, (int, float)) and isinstance(pv, (int, float)) and cv < pv:
            return True
    return False


def counter_delta(cur: dict[str, Any], prev: dict[str, Any], *, reset_safe: bool = False) -> dict[str, int]:
    if reset_safe and counter_reset_detected(cur, prev):
        return {}
    out: dict[str, int] = {}
    for k in COUNTERS:
        cv = metric_num(cur.get(k))
        pv = metric_num(prev.get(k))
        if isinstance(cv, (int, float)) and isinstance(pv, (int, float)):
            out[k] = int(cv - pv)
    return out


def enrich_period(delta: dict[str, int]) -> dict[str, Any]:
    out: dict[str, Any] = dict(delta)
    matches = out.get('matches') or 0
    deaths = out.get('deaths') or 0
    kills = out.get('kills') or 0
    wins = out.get('wins') or 0
    minutes = out.get('minutesPlayed') or 0
    out['periodKd'] = round(kills / deaths, 3) if deaths else (float(kills) if kills else 0.0)
    out['periodWinRate'] = round((wins / matches) * 100, 3) if matches else 0.0
    out['periodKillsPerMatch'] = round(kills / matches, 3) if matches else 0.0
    out['periodMinutesPerMatch'] = round(minutes / matches, 3) if matches else 0.0
    return out


def recompute_deltas(conn: sqlite3.Connection, snaps: list[dict[str, Any]], modes: tuple[str, ...]) -> None:
    conn.execute('delete from daily_deltas')
    for prev, cur in zip(snaps, snaps[1:]):
        for window in WINDOWS:
            prev_modes = (((prev.get(window) or {}).get('modes')) or {})
            cur_modes = (((cur.get(window) or {}).get('modes')) or {})
            for bucket in modes:
                d = enrich_period(counter_delta(cur_modes.get(bucket) or {}, prev_modes.get(bucket) or {}, reset_safe=(window == 'season')))
                conn.execute(
                    '''insert or replace into daily_deltas(from_snapshot_id,to_snapshot_id,from_captured_at,to_captured_at,time_window,bucket,matches,wins,kills,deaths,minutes_played,players_outlived,period_kd,period_win_rate,period_kills_per_match,period_minutes_per_match)
                       values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (
                        prev['capturedAt'], cur['capturedAt'], prev['capturedAt'], cur['capturedAt'], window, bucket,
                        d.get('matches'), d.get('wins'), d.get('kills'), d.get('deaths'), d.get('minutesPlayed'), d.get('playersOutlived'),
                        d.get('periodKd'), d.get('periodWinRate'), d.get('periodKillsPerMatch'), d.get('periodMinutesPerMatch'),
                    ),
                )


def reconcile(conn: sqlite3.Connection, snapshot_count: int, modes: tuple[str, ...]) -> dict[str, Any]:
    expected_buckets = snapshot_count * len(WINDOWS) * len(modes)
    expected_deltas = max(snapshot_count - 1, 0) * len(WINDOWS) * len(modes)
    counts = {
        'snapshots': conn.execute('select count(*) from snapshots').fetchone()[0],
        'stat_buckets': conn.execute('select count(*) from stat_buckets').fetchone()[0],
        'daily_deltas': conn.execute('select count(*) from daily_deltas').fetchone()[0],
    }
    expected = {
        'snapshots': snapshot_count,
        'stat_buckets': expected_buckets,
        'daily_deltas': expected_deltas,
    }
    mismatches = [name for name, value in counts.items() if value != expected[name]]
    integrity = conn.execute('pragma integrity_check').fetchone()[0]
    ok = not mismatches and integrity == 'ok'
    return {
        'ok': ok,
        'counts': counts,
        'expected': expected,
        'mismatches': mismatches,
        'integrity': integrity,
    }


def export_csv(conn: sqlite3.Connection) -> list[str]:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    outputs = []
    daily_path = EXPORTS / 'daily-summary.csv'
    rows = conn.execute(
        '''select to_captured_at,time_window,bucket,matches,wins,kills,deaths,minutes_played,players_outlived,period_kd,period_win_rate,period_kills_per_match,period_minutes_per_match
           from daily_deltas order by to_captured_at,time_window,bucket'''
    ).fetchall()
    with daily_path.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['captured_at','time_window','bucket','matches','wins','kills','deaths','minutes_played','players_outlived','period_kd','period_win_rate','period_kills_per_match','period_minutes_per_match'])
        w.writerows(rows)
    outputs.append(str(daily_path))

    mode_path = EXPORTS / 'mode-summary.csv'
    rows = conn.execute(
        '''select captured_at,time_window,bucket,matches,wins,kills,deaths,kd,win_rate,kills_per_match,kills_per_min,minutes_played,players_outlived,last_modified
           from stat_buckets order by captured_at,time_window,bucket'''
    ).fetchall()
    with mode_path.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['captured_at','time_window','bucket','matches','wins','kills','deaths','kd','win_rate','kills_per_match','kills_per_min','minutes_played','players_outlived','last_modified'])
        w.writerows(rows)
    outputs.append(str(mode_path))
    return outputs


def get_modes(snap: dict[str, Any], window: str = 'season') -> dict[str, dict[str, Any]]:
    return (((snap.get(window) or {}).get('modes')) or {})


def ranked_progression_label(entry: dict[str, Any]) -> str:
    labels = {
        'ranked_blastberry_build': 'Ranked Reload Build',
        'ranked_blastberry_nobuild': 'Ranked Reload Zero Build',
        'ranked-br-combined': 'Ranked Battle Royale',
        'ranked-zb': 'Ranked Zero Build',
    }
    return labels.get(entry.get('key'), 'Ranked')


def diff_snap(cur: dict[str, Any], base: dict[str, Any] | None, window: str = 'season',
              modes: tuple[str, ...] = BASE_MODES) -> dict[str, dict[str, Any]]:
    if not base:
        return {}
    out: dict[str, dict[str, Any]] = {}
    cmodes = get_modes(cur, window)
    bmodes = get_modes(base, window)
    for mode in modes:
        out[mode] = enrich_period(counter_delta(cmodes.get(mode) or {}, bmodes.get(mode) or {}, reset_safe=(window == 'season')))
    return out


def season_reset_between(cur: dict[str, Any], base: dict[str, Any] | None) -> bool:
    if not base:
        return False
    cur_overall = get_modes(cur, 'season').get('overall') or {}
    base_overall = get_modes(base, 'season').get('overall') or {}
    return counter_reset_detected(cur_overall, base_overall)


def find_rolling_base(snaps: list[dict[str, Any]], latest: dict[str, Any], days: int) -> dict[str, Any] | None:
    cutoff = latest['_captured_dt'] - timedelta(days=days)
    candidates = [s for s in snaps if s['_captured_dt'] >= cutoff and s['_captured_dt'] < latest['_captured_dt']]
    if candidates:
        return candidates[0]
    return snaps[0] if snaps and snaps[0] is not latest else None


def compute_trends(snaps: list[dict[str, Any]], milestone_events: list[dict[str, Any]],
                   modes: tuple[str, ...]) -> dict[str, Any]:
    if not snaps:
        return {'status': 'empty', 'snapshots': 0}
    latest = snaps[-1]
    previous = snaps[-2] if len(snaps) >= 2 else None
    base7 = find_rolling_base(snaps, latest, 7)
    first = snaps[0] if len(snaps) > 1 else None
    baseline = first or latest
    tracked_days = round((latest['_captured_dt'] - baseline['_captured_dt']).total_seconds() / 86400, 3) if baseline else 0
    bp = ((latest.get('season') or {}).get('battlePass') or {})
    since_first_season = diff_snap(latest, first, 'season', modes)
    since_first_lifetime = diff_snap(latest, first, 'lifetime', modes)
    # rankedProgression is now a list of entries (one per ranked mode)
    raw_ranked = latest.get('rankedProgression')
    raw_ranked_warnings = list(latest.get('rankedProgressionWarnings') or [])
    ranked_warnings: list[dict[str, Any]] = []
    # Handle both old single-dict format and new list format
    if isinstance(raw_ranked, dict):
        raw_ranked = [raw_ranked]
    ranked_prog: list[dict[str, Any]] = []
    if isinstance(raw_ranked, list):
        for entry in raw_ranked:
            issue = ranked_progression_issue(entry)
            if issue:
                warning = dict(entry)
                warning['reason'] = issue
                warning['source'] = 'normalize'
                ranked_warnings.append(warning)
            else:
                ranked_prog.append(entry)
    ranked_keys = {entry.get('key') for entry in ranked_prog}
    for warning in raw_ranked_warnings:
        if not isinstance(warning, dict):
            continue
        issue = ranked_progression_issue(warning)
        key = warning.get('key')
        if issue is None and key not in ranked_keys:
            ranked_prog.append({
                field: warning.get(field)
                for field in ('key', 'division', 'promotionProgress', 'unrealPlacement')
            })
            ranked_keys.add(key)
            continue
        retained = dict(warning)
        if issue is not None:
            retained['reason'] = issue
            retained['source'] = 'normalize'
        ranked_warnings.append(retained)
    trends = {
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),
        'status': 'ok',
        'snapshots': len(snaps),
        'latestSnapshot': latest['capturedAt'],
        'previousSnapshot': previous['capturedAt'] if previous else None,
        'seasonResetFromPrevious': season_reset_between(latest, previous),
        'rolling7BaseSnapshot': base7['capturedAt'] if base7 else None,
        'firstSnapshot': baseline['capturedAt'],
        'epicName': latest.get('epicName'),
        'battlePass': {'level': bp.get('level'), 'progress': bp.get('progress')},
        'latestSeason': {'modes': get_modes(latest, 'season')},
        'latestLifetime': {'modes': get_modes(latest, 'lifetime')},
        'rankedProgression': ranked_prog if ranked_prog else None,
        'rankedProgressionWarnings': ranked_warnings,
        'trackedRange': {
            'baselineSnapshot': baseline['capturedAt'],
            'latestSnapshot': latest['capturedAt'],
            'daysTracked': tracked_days,
            'note': 'Tracked all-time means progress since the first stored tracker snapshot. Earlier play is only available as aggregate season/lifetime totals from the first baseline unless a source provides older history.',
        },
        'trackedAllTime': {
            'season': since_first_season,
            'lifetime': since_first_lifetime,
        },
        'deltas': {
            'previous': diff_snap(latest, previous, 'season', modes),
            'rolling7': diff_snap(latest, base7, 'season', modes),
            'sinceFirst': since_first_season,
            'lifetimeSinceFirst': since_first_lifetime,
        },
        'milestones': {'new': milestone_events},
        'limitations': [
            'Fortnite-API BR stats are aggregate season/lifetime stats; they do not track Creative/Realistics or full match history.',
            'OliTracker reload/ranked modes do not track deaths, so K/D is unavailable for those modes.',
            'Pre-baseline progression is not reconstructable; it is captured only as aggregate totals at baseline.',
        ],
    }
    return trends


def load_state() -> dict[str, Any] | None:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return None


def append_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    MILESTONES.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open('a') as f:
        for event in events:
            f.write(json.dumps(event, sort_keys=True) + '\n')


def threshold_events(state: dict[str, Any], latest: dict[str, Any], snaps: list[dict[str, Any]],
                     initializing: bool) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
    seen = state.setdefault('seen', {})
    bests = state.setdefault('bests', {})
    events: list[dict[str, Any]] = []
    bp = ((latest.get('season') or {}).get('battlePass') or {})
    season = get_modes(latest, 'season')
    overall = season.get('overall') or {}
    solo = season.get('solo') or {}

    checks: list[tuple[str, str, int, int | None]] = []
    if isinstance(bp.get('level'), int):
        checks.append(('battle_pass_level', 'Battle Pass level', 25, bp['level']))
    for metric, label, step in [
        ('kills', 'season kills', 100),
        ('wins', 'season wins', 5),
        ('matches', 'season matches', 50),
    ]:
        val = overall.get(metric)
        if isinstance(val, int):
            checks.append((f'season_overall_{metric}', label, step, val))

    for key, label, step, val in checks:
        if val is None or val < step:
            continue
        threshold = (val // step) * step
        mark = f'{key}_{threshold}'
        if not seen.get(mark):
            seen[mark] = {'threshold': threshold, 'snapshot': latest['capturedAt'], 'value': val}
            if not initializing:
                events.append({'type': 'threshold', 'key': mark, 'label': label, 'threshold': threshold, 'value': val, 'snapshot': latest['capturedAt'], 'createdAt': now})

    kd = overall.get('kd')
    if isinstance(kd, (int, float)):
        for threshold in [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
            if kd >= threshold:
                mark = f'season_overall_kd_{threshold:.1f}'
                if not seen.get(mark):
                    seen[mark] = {'threshold': threshold, 'snapshot': latest['capturedAt'], 'value': kd}
                    if not initializing:
                        events.append({'type': 'threshold', 'key': mark, 'label': 'season K/D', 'threshold': threshold, 'value': kd, 'snapshot': latest['capturedAt'], 'createdAt': now})

    if len(snaps) >= 2:
        prev = snaps[-2]
        solo_delta = counter_delta(get_modes(latest, 'season').get('solo') or {}, get_modes(prev, 'season').get('solo') or {}, reset_safe=True)
        solo_win_delta = solo_delta.get('wins') or 0
        mark = 'tracked_solo_first_win_alerted'
        if solo_win_delta > 0 and not seen.get(mark):
            seen[mark] = {
                'snapshot': latest['capturedAt'],
                'previousSnapshot': prev['capturedAt'],
                'value': solo.get('wins'),
                'delta': solo_win_delta,
            }
            if not initializing:
                events.append({
                    'type': 'first',
                    'key': mark,
                    'label': 'first solo win since tracking began',
                    'value': solo.get('wins'),
                    'delta': solo_win_delta,
                    'previousSnapshot': prev['capturedAt'],
                    'snapshot': latest['capturedAt'],
                    'createdAt': now,
                })

    for prev, cur in zip(snaps, snaps[1:]):
        d = enrich_period(counter_delta(get_modes(cur, 'season').get('overall') or {}, get_modes(prev, 'season').get('overall') or {}, reset_safe=True))
        for metric, label in [('kills', 'best tracked period kills'), ('wins', 'best tracked period wins'), ('matches', 'best tracked period matches')]:
            val = d.get(metric)
            if not isinstance(val, int):
                continue
            bkey = f'season_overall_period_best_{metric}'
            old = (bests.get(bkey) or {}).get('value')
            if old is None or val > old:
                bests[bkey] = {'value': val, 'from': prev['capturedAt'], 'to': cur['capturedAt']}
                if not initializing and cur is latest and val > 0:
                    events.append({'type': 'best', 'key': bkey, 'label': label, 'value': val, 'from': prev['capturedAt'], 'to': cur['capturedAt'], 'createdAt': now})
    return events


def update_milestones(snaps: list[dict[str, Any]], seed: bool = False) -> list[dict[str, Any]]:
    if not snaps:
        return []
    state = load_state()
    initializing = state is None or seed
    if state is None:
        state = {'initializedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'), 'seen': {}, 'bests': {}}
    latest = snaps[-1]
    events = threshold_events(state, latest, snaps, initializing=initializing)
    state['updatedAt'] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
    state['lastSnapshot'] = latest['capturedAt']
    atomic_json(STATE_PATH, state)
    append_events(events)
    return events


def format_minutes(minutes: int | float | None) -> str:
    if not minutes:
        return '0 min'
    minutes = int(minutes)
    h, m = divmod(minutes, 60)
    if h and m:
        return f'{h}h {m}m'
    if h:
        return f'{h}h'
    return f'{m}m'


def top_delta_mode(delta_modes: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    candidates = []
    for mode, d in delta_modes.items():
        if (d.get('matches') or 0) > 0:
            candidates.append((mode, d))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1].get('kills') or 0, item[1].get('matches') or 0))


def mode_display_name(mode: str) -> str:
    """Human-readable mode name for Discord summaries."""
    names = {
        'ltm': 'LTM/Reload (API)',
        'reload': 'Reload',
        'reload_duos': 'Reload Duos',
        'reload_solo': 'Reload Solo',
        'reload_squads': 'Reload Squads',
        'ranked': 'Ranked',
        'ranked_duos': 'Ranked Duos',
        'ranked_solo': 'Ranked Solo',
        'ranked_squads': 'Ranked Squads',
    }
    return names.get(mode, mode)


def build_discord_summary(trends: dict[str, Any]) -> dict[str, Any]:
    if trends.get('status') != 'ok':
        return {'shouldPost': False, 'message': '', 'reasons': []}
    prev = ((trends.get('deltas') or {}).get('previous') or {})
    rolling = ((trends.get('deltas') or {}).get('rolling7') or {})
    overall = prev.get('overall') or {}
    seven = rolling.get('overall') or {}
    milestones = (trends.get('milestones') or {}).get('new') or []
    bp = trends.get('battlePass') or {}
    reset = bool(trends.get('seasonResetFromPrevious'))
    latest_overall = (((trends.get('latestSeason') or {}).get('modes') or {}).get('overall') or {})
    ranked_prog = trends.get('rankedProgression')

    matches = overall.get('matches') or 0
    wins = overall.get('wins') or 0
    kills = overall.get('kills') or 0
    deaths = overall.get('deaths') or 0
    minutes = overall.get('minutesPlayed') or 0
    kpm = overall.get('periodKillsPerMatch') or 0
    kd = overall.get('periodKd') or 0
    winrate = overall.get('periodWinRate') or 0

    reasons = []
    if wins > 0:
        reasons.append('wins')
    if matches >= 5:
        reasons.append('matches')
    if kills >= 20:
        reasons.append('kills')
    if milestones:
        reasons.append('milestones')
    if bp.get('level') and any(e.get('key','').startswith('battle_pass_level') for e in milestones):
        reasons.append('battle-pass')

    should_post = bool(reasons)
    if not should_post:
        return {'shouldPost': False, 'message': '', 'reasons': []}

    if reset and not any((matches, wins, kills, deaths, minutes)):
        parts = [f'🎮 **Fortnite progress:** new season baseline captured: {latest_overall.get("matches", 0)} matches, {latest_overall.get("kills", 0)} kills, {latest_overall.get("wins", 0)} wins.']
    else:
        parts = [f'🎮 **Fortnite progress:** +{matches} matches, +{kills} kills, +{deaths} deaths, +{wins} wins over {format_minutes(minutes)}.']
    if matches:
        parts.append(f'Period: {kpm:.2f} K/M, {kd:.2f} K/D, {winrate:.1f}% win rate.')

    # Per-mode deltas — only modes that had activity this period
    mode_deltas: list[str] = []
    for mode_key, label in [
        ('duo', 'Duos'), ('solo', 'Solos'), ('squad', 'Squads'), ('ltm', 'Reload/LTM'),
    ]:
        d = prev.get(mode_key) or {}
        if (d.get('matches') or 0) > 0:
            kd_str = f', {d.get("periodKd",0):.2f} K/D' if d.get('deaths') else ''
            mode_deltas.append(f'{label}: +{d.get("kills",0)}k/{d.get("matches",0)}m{kd_str}')
    if mode_deltas:
        parts.append(' | '.join(mode_deltas))

    # Ranked progression — show all available ranked modes
    div_names = {
        0: 'Bronze 1', 1: 'Bronze 2', 2: 'Bronze 3',
        3: 'Silver 1', 4: 'Silver 2', 5: 'Silver 3',
        6: 'Gold 1', 7: 'Gold 2', 8: 'Gold 3',
        9: 'Platinum 1', 10: 'Platinum 2', 11: 'Platinum 3',
        12: 'Diamond 1', 13: 'Diamond 2', 14: 'Diamond 3',
        15: 'Elite 1', 16: 'Elite 2', 17: 'Elite 3',
        18: 'Champion 1', 19: 'Champion 2', 20: 'Champion 3',
        21: 'Unreal',
    }
    # ranked_prog is now a list; handle both old single-dict and new list formats
    ranked_list = ranked_prog if isinstance(ranked_prog, list) else ([ranked_prog] if isinstance(ranked_prog, dict) else [])
    for rp in ranked_list:
        if ranked_progression_issue(rp) is not None:
            continue
        if rp.get('division') is None:
            continue
        div_name = div_names.get(rp['division'], f'Division {rp["division"]}')
        if rp.get('unrealPlacement') is not None:
            rank_text = f'{div_name} #{rp["unrealPlacement"]}'
        elif rp.get('promotionProgress') is not None:
            rank_text = f'{div_name} ({rp["promotionProgress"]}% promotion)'
        else:
            rank_text = div_name
        parts.append(f'{ranked_progression_label(rp)}: {rank_text}.')

    if seven.get('matches'):
        parts.append(f'7-day: +{seven.get("matches",0)} matches, +{seven.get("kills",0)} kills, +{seven.get("wins",0)} wins, {seven.get("periodKillsPerMatch",0):.2f} K/M.')

    # Blunt read
    blunt_parts: list[str] = []
    if matches >= 3:
        if wins > 0:
            if winrate >= 30:
                blunt_parts.append(f'win rate is cooking at {winrate:.0f}%')
            elif winrate >= 15:
                blunt_parts.append(f'decent {winrate:.0f}% win rate')
            else:
                blunt_parts.append(f'{wins} win{"s" if wins != 1 else ""} in {matches} matches')
        else:
            blunt_parts.append(f'{matches} matches, no wins')
        if kd >= 5:
            blunt_parts.append(f'{kd:.1f} K/D is nasty')
        elif kd >= 3:
            blunt_parts.append(f'solid {kd:.1f} K/D')
        elif kd < 1.5 and deaths > 0:
            blunt_parts.append(f'{kd:.1f} K/D needs work')
        if kpm >= 5:
            blunt_parts.append(f'{kpm:.1f} K/M is aggressive')
        elif kpm < 2 and matches >= 3:
            blunt_parts.append(f'{kpm:.1f} K/M is slow')
        seven_kd = seven.get('periodKd') or 0
        seven_wr = seven.get('periodWinRate') or 0
        if seven_kd and kd and kd > seven_kd * 1.3:
            blunt_parts.append(f'K/D well above your {seven_kd:.1f} weekly avg')
        elif seven_kd and kd and kd < seven_kd * 0.6:
            blunt_parts.append(f'K/D below your {seven_kd:.1f} weekly avg')
        if seven_wr and winrate and winrate > seven_wr * 1.5:
            blunt_parts.append(f'win rate up from {seven_wr:.0f}% weekly')
        elif seven_wr and winrate and winrate < seven_wr * 0.4:
            blunt_parts.append(f'win rate down from {seven_wr:.0f}% weekly')
        if blunt_parts:
            parts.append('Blunt read: ' + '; '.join(blunt_parts) + '.')
        elif wins > 0:
            parts.append('Blunt read: wins landed, nothing else stood out.')
        else:
            parts.append('Blunt read: quiet session.')
    elif wins > 0:
        parts.append(f'Blunt read: {wins} win{"s" if wins != 1 else ""} in a short session.')
    else:
        parts.append('Blunt read: light session, not much to read.')

    if bp.get('level') is not None:
        progress = bp.get('progress')
        bp_text = f'BP level {bp.get("level")}' + (f' ({progress}% to next)' if progress is not None else '')
        parts.append(bp_text + '.')

    if milestones:
        labels = []
        for event in milestones[:4]:
            if event.get('type') == 'threshold':
                labels.append(f'{event.get("label")} {event.get("threshold")}')
            elif event.get('type') == 'best':
                labels.append(f'{event.get("label")}: {event.get("value")}')
            else:
                labels.append(str(event.get('label') or event.get('key')))
        parts.append('Milestones: ' + '; '.join(labels) + '.')

    parts.append('_BR API stats do not include Creative/Realistics or full match history. Reload/ranked via OliTracker (no death tracking)._')
    return {'shouldPost': True, 'message': '\n'.join(parts), 'reasons': reasons}


def run(seed_milestones: bool = False) -> dict[str, Any]:
    snaps = load_snapshots()
    modes = discover_modes(snaps)
    PROGRESS.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        prune_removed_snapshots(conn, snaps)
        for snap in snaps:
            upsert_snapshot(conn, snap, modes)
        recompute_deltas(conn, snaps, modes)
        csvs = export_csv(conn)
        reconciliation = reconcile(conn, len(snaps), modes)
        conn.commit()
    events = update_milestones(snaps, seed=seed_milestones)
    trends = compute_trends(snaps, events, modes)
    summary = build_discord_summary(trends)
    trends['discord'] = summary
    trends['reconciliation'] = reconciliation
    atomic_json(TREND_LATEST, trends)
    status = 'ok' if snaps else 'empty'
    if snaps and not reconciliation.get('ok'):
        status = 'error'
    return {
        'status': status,
        'snapshots': len(snaps),
        'modes': list(modes),
        'db': str(DB),
        'trends': str(TREND_LATEST),
        'exports': csvs,
        'milestoneEvents': events,
        'shouldPost': summary.get('shouldPost', False),
        'discordMessage': summary.get('message', ''),
        'postReasons': summary.get('reasons', []),
        'reconciliation': reconciliation,
        'latestSnapshot': snaps[-1]['capturedAt'] if snaps else None,
    }


def clone_snapshot(snap: dict[str, Any], captured_at: str) -> dict[str, Any]:
    cloned = json.loads(json.dumps({k: v for k, v in snap.items() if not k.startswith('_')}))
    cloned['capturedAt'] = captured_at
    cloned['_path'] = f'<synthetic:{captured_at}>'
    cloned['_captured_dt'] = parse_ts(captured_at)
    return cloned


def bump_metric(snap: dict[str, Any], window: str, mode: str, metric: str, amount: int) -> None:
    modes = ((snap.get(window) or {}).get('modes') or {})
    bucket = modes.setdefault(mode, {})
    bucket[metric] = int(bucket.get(metric) or 0) + amount


def run_self_tests() -> dict[str, Any]:
    snaps = load_snapshots()
    if len(snaps) < 2:
        raise RuntimeError('self-test requires at least two snapshots')
    modes = discover_modes(snaps)
    latest = snaps[-1]
    tests: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: Any = None) -> None:
        tests.append({'name': name, 'passed': bool(passed), 'detail': detail})

    zero = clone_snapshot(latest, '2099-01-01T00:00:00Z')
    zero_trends = compute_trends(snaps + [zero], [], modes)
    zero_summary = build_discord_summary(zero_trends)
    record('zero_delta_no_post', zero_summary.get('shouldPost') is False, zero_summary)

    valid_unreal = clone_snapshot(latest, '2099-01-01T00:15:00Z')
    valid_unreal_entry = {
        'key': 'ranked_blastberry_build',
        'division': 21,
        'promotionProgress': 57,
        'unrealPlacement': 986496,
    }
    valid_unreal['rankedProgression'] = []
    valid_unreal['rankedProgressionWarnings'] = [{
        **valid_unreal_entry,
        'reason': 'OliTracker reported Unreal with promotion progress instead of placement',
    }]
    valid_unreal_trends = compute_trends(snaps + [valid_unreal], [], modes)
    record(
        'valid_unreal_warning_is_readjudicated',
        valid_unreal_entry in (valid_unreal_trends.get('rankedProgression') or [])
        and not valid_unreal_trends.get('rankedProgressionWarnings'),
        {
            'rankedProgression': valid_unreal_trends.get('rankedProgression'),
            'warnings': valid_unreal_trends.get('rankedProgressionWarnings'),
        },
    )

    bad_rank = clone_snapshot(latest, '2099-01-01T00:30:00Z')
    bad_rank['rankedProgression'] = [{
        'key': 'ranked_blastberry_build',
        'division': 21,
        'promotionProgress': 40,
        'unrealPlacement': None,
    }]
    bad_rank['rankedProgressionWarnings'] = []
    bad_rank_trends = compute_trends(snaps + [bad_rank], [], modes)
    record(
        'untrusted_unreal_rank_suppressed',
        bad_rank_trends.get('rankedProgression') is None
        and any(
            warning.get('reason') == 'OliTracker reported Unreal without a valid Unreal placement'
            for warning in bad_rank_trends.get('rankedProgressionWarnings') or []
        ),
        bad_rank_trends.get('rankedProgressionWarnings'),
    )

    reset = clone_snapshot(latest, '2099-01-01T01:00:00Z')
    reset.setdefault('season', {}).setdefault('modes', {}).setdefault('overall', {})
    for metric in RESET_COUNTERS:
        reset['season']['modes']['overall'][metric] = 0
    reset_trends = compute_trends(snaps + [reset], [], modes)
    reset_delta = ((reset_trends.get('deltas') or {}).get('previous') or {}).get('overall') or {}
    record(
        'season_reset_no_negative_delta',
        reset_trends.get('seasonResetFromPrevious') is True and all((reset_delta.get(k) or 0) >= 0 for k in RESET_COUNTERS),
        {'reset': reset_trends.get('seasonResetFromPrevious'), 'delta': reset_delta},
    )

    solo = clone_snapshot(latest, '2099-01-02T00:00:00Z')
    for window in WINDOWS:
        for mode in ('overall', 'solo'):
            bump_metric(solo, window, mode, 'matches', 1)
            bump_metric(solo, window, mode, 'wins', 1)
            bump_metric(solo, window, mode, 'kills', 3)
            bump_metric(solo, window, mode, 'deaths', 0)
            bump_metric(solo, window, mode, 'minutesPlayed', 8)
    state = {'seen': {}, 'bests': {}}
    solo_events = threshold_events(state, solo, snaps + [solo], initializing=False)
    solo_keys = [e.get('key') for e in solo_events]
    record('tracked_solo_first_win_fires_once', solo_keys.count('tracked_solo_first_win_alerted') == 1, solo_events)
    repeat_events = threshold_events(state, solo, snaps + [solo], initializing=False)
    record('tracked_solo_first_win_no_duplicate', not any(e.get('key') == 'tracked_solo_first_win_alerted' for e in repeat_events), repeat_events)

    bp = clone_snapshot(latest, '2099-01-03T00:00:00Z')
    bp.setdefault('season', {}).setdefault('battlePass', {})['level'] = 475
    bp_state = {'seen': {}, 'bests': {}}
    bp_events = threshold_events(bp_state, bp, snaps + [bp], initializing=False)
    record('battle_pass_threshold_once', any(e.get('key') == 'battle_pass_level_475' for e in bp_events), bp_events)
    bp_repeat = threshold_events(bp_state, bp, snaps + [bp], initializing=False)
    record('battle_pass_threshold_no_duplicate', not any(e.get('key') == 'battle_pass_level_475' for e in bp_repeat), bp_repeat)

    kills = clone_snapshot(latest, '2099-01-04T00:00:00Z')
    current_kills = ((kills.get('season') or {}).get('modes') or {}).get('overall', {}).get('kills') or 0
    target = ((int(current_kills) // 100) + 1) * 100
    bump_metric(kills, 'season', 'overall', 'kills', target - int(current_kills))
    kill_state = {'seen': {}, 'bests': {}}
    kill_events = threshold_events(kill_state, kills, snaps + [kills], initializing=False)
    record('kill_threshold_once', any(e.get('key') == f'season_overall_kills_{target}' for e in kill_events), kill_events)
    kill_repeat = threshold_events(kill_state, kills, snaps + [kills], initializing=False)
    record('kill_threshold_no_duplicate', not any(e.get('key') == f'season_overall_kills_{target}' for e in kill_repeat), kill_repeat)

    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        reconciliation = reconcile(conn, len(snaps), modes)
    record('db_snapshot_reconciliation', reconciliation.get('ok') is True, reconciliation)

    passed = sum(1 for t in tests if t['passed'])
    return {'status': 'ok' if passed == len(tests) else 'fail', 'passed': passed, 'total': len(tests), 'tests': tests}


def main() -> int:
    ap = argparse.ArgumentParser(description='Normalize Fortnite progress snapshots and compute trends.')
    ap.add_argument('--summary-json', action='store_true', help='emit compact machine-readable JSON for cron use')
    ap.add_argument('--seed-milestones', action='store_true', help='initialize milestone state without producing first-run alerts')
    ap.add_argument('--self-test', action='store_true', help='run synthetic regression tests without writing tracker state')
    args = ap.parse_args()
    try:
        result = run_self_tests() if args.self_test else run(seed_milestones=args.seed_milestones)
        print(json.dumps(result, indent=None if args.summary_json else 2, sort_keys=True))
        return 0 if result.get('status') in ('ok', 'empty') else 1
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
