#!/usr/bin/env python3
"""Capture Fortnite progress snapshots from Fortnite-API, OliTracker, and api-fortnite.com.

Fortnite-API: primary BR modes (overall/solo/duo/squad/ltm) with deaths/K/D.
OliTracker: reload/ranked aggregates + ranked progression (no deaths).
api-fortnite.com: per-playlist stats with placement distribution (no deaths).

The merged snapshot is the single source of truth for the normalize pipeline.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.request
import datetime as dt
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

from hermes_fortnite_rank import ranked_progression_issue

ROOT = Path(os.environ.get('HERMES_AUTOMATION_WORKSPACE', '/var/lib/hermes-automation/workspace'))
PROGRESS = ROOT / 'fortnite-progress'
SNAPDIR = PROGRESS / 'snapshots'
LATEST = PROGRESS / 'latest.json'
CONFIG = PROGRESS / 'config.json'
OLITRACKER_DIR = PROGRESS / 'olitracker'
OLITRACKER_SNAPS = OLITRACKER_DIR / 'snapshots'
OLITRACKER_LATEST = OLITRACKER_DIR / 'latest.json'
APIFN_DIR = PROGRESS / 'apifn'
APIFN_SNAPS = APIFN_DIR / 'snapshots'
APIFN_LATEST = APIFN_DIR / 'latest.json'
ENV = Path(os.environ['HERMES_COLLECTOR_ENV_FILE']) if os.environ.get('HERMES_COLLECTOR_ENV_FILE') else None

# Base modes from Fortnite-API
FN_MODES = ('overall', 'solo', 'duo', 'squad', 'ltm')
COUNTERS = ('matches', 'wins', 'kills', 'deaths', 'minutesPlayed', 'playersOutlived')

# api-fortnite.com playlist → our mode taxonomy
# Format: (mode_name, is_ranked, is_reload)
PLAYLIST_MAP: dict[str, tuple[str, bool, bool]] = {
    # Ranked Reload
    'habanero_matchmist_duos': ('ranked_reload_duos', True, True),
    'habanero_matchmist_solo': ('ranked_reload_solo', True, True),
    'habanero_matchmist_squads': ('ranked_reload_squads', True, True),
    # Unranked Reload
    'matchmistduo': ('unranked_reload_duos', False, True),
    'matchmistsolo': ('unranked_reload_solo', False, True),
    # Ranked BR
    'habaneroduo': ('ranked_br_duos', True, False),
    'habanerosolo': ('ranked_br_solo', True, False),
    'habanerosquad': ('ranked_br_squads', True, False),
    'habanerotrio': ('ranked_br_trios', True, False),
    # Ranked BR (seasonal variants)
    'habanero_dashberry_duos': ('ranked_br_duos', True, False),
    'habanero_dashberry_solo': ('ranked_br_solo', True, False),
    'habanero_dashberry_squads': ('ranked_br_squads', True, False),
    'habanero_punchberry_squads': ('ranked_br_squads', True, False),
    'habanero_punchberry_solo': ('ranked_br_solo', True, False),
    'habanero_sunflower_duos': ('ranked_br_duos', True, False),
    'habanero_sunflower_solo': ('ranked_br_solo', True, False),
    'habanero_figment_solo': ('ranked_br_solo', True, False),
    'habanero_piperboot_solo': ('ranked_br_solo', True, False),
    # Unranked BR
    'defaultduo': ('unranked_br_duos', False, False),
    'defaultsolo': ('unranked_br_solo', False, False),
    'defaultsquad': ('unranked_br_squads', False, False),
    'trios': ('unranked_br_trios', False, False),
}

# Input type priority: keyboardmouse first, then gamepad, then touch
INPUT_PRIORITY = ('keyboardmouse', 'gamepad', 'touch')


def load_env() -> None:
    if ENV is not None and ENV.exists():
        for line in ENV.read_text().splitlines():
            if not line or line.strip().startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmp, path)


def load_source_module(name: str, path: Path) -> Any:
    """Load a managed Python helper even when its deployed path has no suffix."""
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise RuntimeError(f'could not load {path}')
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# ── Fortnite-API ────────────────────────────────────────────────────────────

def get_stats(name: str, account_type: str, window: str, key: str) -> dict[str, Any]:
    qs = f'name={urllib.request.quote(name)}&accountType={urllib.request.quote(account_type)}&timeWindow={window}'
    url = 'https://fortnite-api.com/v2/stats/br/v2?' + qs
    req = urllib.request.Request(url, headers={'Authorization': key, 'User-Agent': 'OpenClaw-Fortnite-Progress'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pick_metrics(data: dict[str, Any]) -> dict[str, Any]:
    d = data.get('data') or {}
    stats = ((d.get('stats') or {}).get('all') or {})
    out: dict[str, Any] = {}
    for mode in FN_MODES:
        s = stats.get(mode) or {}
        out[mode] = {k: s.get(k) for k in ['matches', 'wins', 'winRate', 'kills', 'deaths', 'kd', 'killsPerMatch', 'killsPerMin', 'minutesPlayed', 'playersOutlived', 'lastModified'] if k in s}
    return {
        'account': d.get('account'),
        'battlePass': d.get('battlePass'),
        'modes': out,
    }


# ── OliTracker ──────────────────────────────────────────────────────────────

# OliTracker ranked keys we track separately
OLITRACKER_RANKED_KEYS = {
    'ranked_blastberry_build': 'Ranked Reload Build',
    'ranked-br-combined': 'Ranked Battle Royale',
}
# Kept for backward compatibility
OLITRACKER_RANKED_PROGRESSION_KEY = 'ranked_blastberry_build'

def fetch_olitracker(account_id: str) -> dict[str, Any] | None:
    url = f'https://olitracker.com/api/stats/{account_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'OpenClaw-Fortnite-Progress'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f'olitracker: fetch failed ({e}), continuing without it', file=sys.stderr)
        return None


def pick_olitracker_modes(data: dict[str, Any], window: str) -> dict[str, Any]:
    stats = data.get('stats', {})
    w = stats.get(window, {})
    out: dict[str, Any] = {}
    for mode in ('reload', 'ranked'):
        m = w.get(mode, {})
        builds = m.get('builds', {})
        for submode in ('overall', 'duos', 'solo', 'squads'):
            b = builds.get(submode, {})
            if not b:
                continue
            entry: dict[str, Any] = {}
            if 'matches_played' in b:
                entry['matches'] = b['matches_played']
            if 'wins' in b:
                entry['wins'] = b['wins']
            if 'kills' in b:
                entry['kills'] = b['kills']
            if 'time_played' in b:
                entry['minutesPlayed'] = b['time_played']
            if 'outlived' in b:
                entry['playersOutlived'] = b['outlived']
            if 'last_modified' in b:
                entry['lastModified'] = dt.datetime.fromtimestamp(
                    b['last_modified'], tz=dt.timezone.utc
                ).isoformat().replace('+00:00', 'Z')
            if entry.get('kills') is not None and entry.get('matches'):
                entry['killsPerMatch'] = round(entry['kills'] / entry['matches'], 3)
            if entry.get('minutesPlayed') and entry.get('kills'):
                entry['killsPerMin'] = round(entry['kills'] / entry['minutesPlayed'], 3)
            if entry.get('wins') is not None and entry.get('matches'):
                entry['winRate'] = round((entry['wins'] / entry['matches']) * 100, 3)
            flat_name = mode if submode == 'overall' else f'{mode}_{submode}'
            out[flat_name] = entry
    return out


def ranked_progression_entry(key: str, val: dict[str, Any]) -> dict[str, Any]:
    return {
        'key': key,
        'division': val.get('division'),
        'promotionProgress': val.get('promotion_progression'),
        'unrealPlacement': val.get('unreal_placement'),
    }


def pick_olitracker_ranked(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract ranked progression for all tracked ranked keys.

    Returns (entries, warnings). entries is a list of valid ranked progression
    dicts (one per key with valid data). warnings is a list of issues found.
    """
    rs = data.get('ranked_stats', {})
    if not rs:
        return [], []
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for key in OLITRACKER_RANKED_KEYS:
        val = rs.get(key)
        if not isinstance(val, dict):
            continue
        entry = ranked_progression_entry(key, val)
        issue = ranked_progression_issue(entry)
        if issue:
            warning = dict(entry)
            warning['reason'] = issue
            warnings.append(warning)
        else:
            entries.append(entry)
    return entries, warnings


# ── api-fortnite.com ────────────────────────────────────────────────────────

def fetch_apifn(account_id: str, key: str) -> dict[str, Any] | None:
    url = f'https://prod.api-fortnite.com/api/v2/stats/{account_id}'
    req = urllib.request.Request(url, headers={'x-api-key': key, 'User-Agent': 'OpenClaw-Fortnite-Progress'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f'apifn: fetch failed ({e}), continuing without it', file=sys.stderr)
        return None


def pick_apifn_modes(data: dict[str, Any]) -> dict[str, Any]:
    """Extract per-playlist stats from api-fortnite.com and merge into our mode taxonomy.

    For playlists that map to the same mode (e.g. multiple ranked BR duo seasons),
    we sum the stats. For input types, we prefer keyboardmouse.
    """
    stats = data.get('stats', {})
    # Group by (mode_name, input_type)
    raw: dict[tuple[str, str], dict[str, Any]] = {}

    for key, value in stats.items():
        m = re.match(r'br_(.+)_(keyboardmouse|gamepad|touch)_m0_playlist_(.+)$', key)
        if not m:
            continue
        metric, input_type, playlist = m.group(1), m.group(2), m.group(3)

        if playlist not in PLAYLIST_MAP:
            continue
        mode_name, _, _ = PLAYLIST_MAP[playlist]

        entry = raw.setdefault((mode_name, input_type), {})
        if metric == 'kills':
            entry['kills'] = (entry.get('kills') or 0) + value
        elif metric == 'matchesplayed':
            entry['matches'] = (entry.get('matches') or 0) + value
        elif metric == 'minutesplayed':
            entry['minutesPlayed'] = (entry.get('minutesPlayed') or 0) + value
        elif metric == 'playersoutlived':
            entry['playersOutlived'] = (entry.get('playersOutlived') or 0) + value
        elif metric == 'score':
            entry['score'] = (entry.get('score') or 0) + value
        elif metric == 'placetop1':
            entry['wins'] = (entry.get('wins') or 0) + value
        elif metric == 'placetop3':
            entry['top3'] = (entry.get('top3') or 0) + value
        elif metric == 'placetop5':
            entry['top5'] = (entry.get('top5') or 0) + value
        elif metric == 'placetop6':
            entry['top6'] = (entry.get('top6') or 0) + value
        elif metric == 'placetop10':
            entry['top10'] = (entry.get('top10') or 0) + value
        elif metric == 'placetop12':
            entry['top12'] = (entry.get('top12') or 0) + value
        elif metric == 'placetop25':
            entry['top25'] = (entry.get('top25') or 0) + value
        elif metric == 'lastmodified':
            ts = dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat().replace('+00:00', 'Z')
            existing = entry.get('lastModified', '')
            if ts > existing:
                entry['lastModified'] = ts

    # Pick best input type for each mode
    out: dict[str, Any] = {}
    for (mode_name, input_type), entry in raw.items():
        if mode_name not in out:
            out[mode_name] = entry
        else:
            # Prefer keyboardmouse, then gamepad
            existing_prio = INPUT_PRIORITY.index(out.get(f'_{mode_name}_input', 'touch'))
            new_prio = INPUT_PRIORITY.index(input_type)
            if new_prio < existing_prio:
                out[mode_name] = entry

    # Compute derived stats
    for mode_name, entry in out.items():
        if entry.get('kills') is not None and entry.get('matches'):
            entry['killsPerMatch'] = round(entry['kills'] / entry['matches'], 3)
        if entry.get('minutesPlayed') and entry.get('kills'):
            entry['killsPerMin'] = round(entry['kills'] / entry['minutesPlayed'], 3)
        if entry.get('wins') is not None and entry.get('matches'):
            entry['winRate'] = round((entry['wins'] / entry['matches']) * 100, 3)

    return out


# ── Delta / duplicate detection ─────────────────────────────────────────────

def delta(cur: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not prev:
        return None
    d: dict[str, Any] = {}
    for window in ('season', 'lifetime'):
        d[window] = {}
        cur_modes = (((cur.get(window) or {}).get('modes')) or {})
        prev_modes = (((prev.get(window) or {}).get('modes')) or {})
        all_modes = set(list(cur_modes.keys()) + list(prev_modes.keys()))
        for mode in sorted(all_modes):
            cs = cur_modes.get(mode) or {}
            ps = prev_modes.get(mode) or {}
            md: dict[str, int] = {}
            for k in ('matches', 'wins', 'kills', 'deaths', 'minutesPlayed', 'playersOutlived'):
                if isinstance(cs.get(k), (int, float)) and isinstance(ps.get(k), (int, float)):
                    md[k] = int(cs[k] - ps[k])
            d[window][mode] = md
    return d


def parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(dt.timezone.utc)


def is_recent_duplicate(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if not previous:
        return False
    for w in ('season', 'lifetime'):
        cm = (((current.get(w) or {}).get('modes')) or {})
        pm = (((previous.get(w) or {}).get('modes')) or {})
        all_modes = set(list(cm.keys()) + list(pm.keys()))
        for mode in all_modes:
            c = cm.get(mode) or {}
            p = pm.get(mode) or {}
            for k in ('matches', 'wins', 'kills', 'deaths', 'minutesPlayed', 'playersOutlived', 'kd', 'winRate', 'killsPerMatch', 'killsPerMin'):
                if c.get(k) != p.get(k):
                    return False
    return (parse_ts(current['capturedAt']) - parse_ts(previous['capturedAt'])).total_seconds() < 1800


# ── Merge ───────────────────────────────────────────────────────────────────

def merge_snapshot(fn_season: dict[str, Any], fn_lifetime: dict[str, Any],
                   oli_data: dict[str, Any] | None,
                   apifn_data: dict[str, Any] | None) -> dict[str, Any]:
    """Merge all sources into one unified snapshot.

    Fortnite-API owns: overall, solo, duo, squad, ltm (with deaths, K/D).
    OliTracker adds: reload/ranked aggregates + ranked progression.
    api-fortnite.com adds: per-playlist ranked/unranked reload/BR breakdowns.
    """
    merged: dict[str, Any] = {
        'season': {
            'account': fn_season.get('account'),
            'battlePass': fn_season.get('battlePass'),
            'modes': fn_season.get('modes', {}),
        },
        'lifetime': {
            'account': fn_lifetime.get('account'),
            'battlePass': fn_lifetime.get('battlePass'),
            'modes': fn_lifetime.get('modes', {}),
        },
    }

    if oli_data:
        for window in ('season', 'lifetime'):
            oli_modes = pick_olitracker_modes(oli_data, 'seasonal' if window == 'season' else window)
            for mode_name, mode_data in oli_modes.items():
                merged[window]['modes'][mode_name] = mode_data

        ranked_entries, ranked_warnings = pick_olitracker_ranked(oli_data)
        if ranked_entries:
            merged['rankedProgression'] = ranked_entries
        if ranked_warnings:
            merged['rankedProgressionWarnings'] = ranked_warnings

    if apifn_data:
        apifn_modes = pick_apifn_modes(apifn_data)
        # api-fortnite.com stats are lifetime totals, not seasonal
        for mode_name, mode_data in apifn_modes.items():
            merged['lifetime']['modes'][mode_name] = mode_data

    return merged


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description='Capture a Fortnite progress snapshot and normalize tracker artifacts.')
    ap.add_argument('--dry-run', action='store_true', help='fetch and compare stats without writing')
    args = ap.parse_args()
    load_env()
    fn_key = os.environ.get('FORTNITE_API_KEY')
    apifn_key = os.environ.get('API_FORTNITE_KEY')
    if not fn_key:
        print(json.dumps({'status': 'error', 'error': 'FORTNITE_API_KEY is not set'}))
        return 2
    cfg = json.loads(CONFIG.read_text())
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    account_id = None

    # Fetch Fortnite-API (primary)
    fn_errors: list[str] = []
    fn_season: dict[str, Any] | None = None
    fn_lifetime: dict[str, Any] | None = None
    try:
        fn_season = pick_metrics(get_stats(cfg['epicName'], cfg.get('accountType', 'epic'), 'season', fn_key))
        account_id = fn_season.get('account', {}).get('id')
    except Exception as e:
        fn_errors.append(f'season: {e}')
    try:
        fn_lifetime = pick_metrics(get_stats(cfg['epicName'], cfg.get('accountType', 'epic'), 'lifetime', fn_key))
        if not account_id:
            account_id = fn_lifetime.get('account', {}).get('id')
    except Exception as e:
        fn_errors.append(f'lifetime: {e}')

    if fn_errors and not fn_season and not fn_lifetime:
        print(json.dumps({'status': 'error', 'error': '; '.join(fn_errors), 'capturedAt': now.isoformat().replace('+00:00', 'Z')}))
        return 1

    # Fetch OliTracker (supplemental)
    oli_data: dict[str, Any] | None = None
    if account_id:
        oli_data = fetch_olitracker(account_id)
        if oli_data:
            oli_snap = OLITRACKER_SNAPS / f"{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
            atomic_write(oli_snap, oli_data)
            atomic_write(OLITRACKER_LATEST, oli_data)

    # Fetch api-fortnite.com (supplemental)
    apifn_data: dict[str, Any] | None = None
    if account_id and apifn_key:
        apifn_data = fetch_apifn(account_id, apifn_key)
        if apifn_data:
            apifn_snap = APIFN_SNAPS / f"{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
            atomic_write(apifn_snap, apifn_data)
            atomic_write(APIFN_LATEST, apifn_data)

    # Merge
    current: dict[str, Any] = {
        'schema': 3,
        'capturedAt': now.isoformat().replace('+00:00', 'Z'),
        'source': 'Fortnite-API.com + OliTracker + api-fortnite.com',
        'epicName': cfg['epicName'],
        'accountType': cfg.get('accountType', 'epic'),
    }
    current.update(merge_snapshot(fn_season or {}, fn_lifetime or {}, oli_data, apifn_data))
    if fn_errors:
        current['_fnErrors'] = fn_errors

    prev = json.loads(LATEST.read_text()) if LATEST.exists() else None
    current['deltaFromPrevious'] = delta(current, prev)
    duplicate = is_recent_duplicate(current, prev)

    if args.dry_run:
        print(json.dumps({
            'status': 'ok',
            'dryRun': True,
            'wouldCaptureAt': current['capturedAt'],
            'hasPrevious': bool(prev),
            'duplicate': duplicate,
            'hasOliTracker': oli_data is not None,
            'hasApiFn': apifn_data is not None,
        }))
        return 0

    if duplicate:
        print(json.dumps({
            'status': 'ok',
            'snapshot': str(LATEST),
            'skipped': True,
            'reason': 'identical stats within 30 minutes of previous snapshot',
            'hasPrevious': bool(prev),
            'capturedAt': current['capturedAt'],
            'normalize': {'status': 'ok', 'shouldPost': False, 'reason': 'duplicate skipped'},
        }))
        return 0

    snap = SNAPDIR / f"{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
    atomic_write(snap, current)
    atomic_write(LATEST, current)

    normalize_status = None
    try:
        normalize_path = Path(os.environ.get('HERMES_FORTNITE_NORMALIZER', '/usr/local/libexec/hermes-fortnite-progress-normalize'))
        mod = load_source_module('fortnite_progress_normalize', normalize_path)
        normalize_status = mod.run()
    except Exception as e:
        normalize_status = {'status': 'error', 'error': str(e)}

    print(json.dumps({
        'status': 'ok',
        'snapshot': str(snap),
        'hasPrevious': bool(prev),
        'capturedAt': current['capturedAt'],
        'hasOliTracker': oli_data is not None,
        'hasApiFn': apifn_data is not None,
        'normalize': normalize_status,
    }))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
