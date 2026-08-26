#!/usr/bin/env python3
"""Collect the media-facing Daily Summary section.

This script is deliberately deterministic. The cron agent should run this file,
not hand-roll media summaries in the model context.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(os.environ.get('HERMES_AUTOMATION_WORKSPACE', '/var/lib/hermes-automation/workspace'))
OUT = WORKSPACE / 'memory/daily-summary-sections/media.md'
LOCAL_TZ = ZoneInfo('America/Chicago')
MEDIA_VM = '100.66.6.113'
DOCKER_VM = '100.108.254.100'
SSH_USER = 'hermes-astra'


def parse_now() -> dt.datetime:
    override = os.environ.get('DAILY_SUMMARY_MEDIA_NOW')
    if override:
        parsed = dt.datetime.fromisoformat(override.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


NOW = parse_now()
START = NOW - dt.timedelta(hours=24)


def local(d: dt.datetime) -> dt.datetime:
    return d.astimezone(LOCAL_TZ)


def fmt_local(d: dt.datetime) -> str:
    return local(d).strftime('%Y-%m-%d %I:%M %p %Z')


def fmt_time(d: dt.datetime) -> str:
    return local(d).strftime('%I:%M %p').lstrip('0')


def parse_utc(value: object) -> dt.datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return dt.datetime.fromtimestamp(int(s), tz=dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def fmt_bytes(n: object) -> str:
    try:
        value = float(n or 0)
    except (TypeError, ValueError):
        return 'unknown'
    sign = '-' if value < 0 else ''
    value = abs(value)
    units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{sign}{int(value)} B'
            return f'{sign}{value:.2f} {unit}'
        value /= 1024
    return f'{sign}{value:.2f} TiB'


def duration_seconds(value: object) -> int:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return 0
    # Tautulli can return either seconds or milliseconds depending on field.
    if n > 100000:
        n /= 1000
    return int(n)


def fmt_duration(value: object) -> str:
    seconds = duration_seconds(value)
    minutes = round(seconds / 60)
    if minutes < 60:
        return f'{minutes} min'
    hours, rem = divmod(minutes, 60)
    return f'{hours}h {rem}m' if rem else f'{hours}h'


def short_error(exc: BaseException | str) -> str:
    text = str(exc).replace('\n', ' ')
    text = re.sub(r'(apikey=)[^&\s]+', r'\1<redacted>', text, flags=re.I)
    text = re.sub(r'(X-Api-Key[:=]\s*)\S+', r'\1<redacted>', text, flags=re.I)
    return text[:240]


def run_ssh(host: str, script: str, *, timeout: int = 30, input_text: str | None = None) -> str:
    proc = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', f'{SSH_USER}@{host}', script],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip()
        raise RuntimeError(f'ssh {host} rc={proc.returncode}: {detail}')
    return proc.stdout.strip()


def get_json(url: str, params: dict[str, object] | None = None, headers: dict[str, str] | None = None, *, timeout: int = 20) -> object:
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def env_or_file_secret(name: str, paths: list[Path]) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    for path in paths:
        try:
            if path.exists():
                value = path.read_text().strip()
                if value:
                    return value
        except OSError:
            continue
    return None


def load_keys() -> tuple[dict[str, str], list[str]]:
    warnings: list[str] = []
    keys: dict[str, str] = {}

    env_candidates = {
        'TAUTULLI': ['TAUTULLI_API_KEY', 'TAUTULLI_KEY'],
        'SONARR': ['SONARR_API_KEY', 'SONARR_KEY'],
        'RADARR': ['RADARR_API_KEY', 'RADARR_KEY'],
        'SEERR': ['SEERR_API_KEY', 'SEERR_KEY'],
    }
    for target, names in env_candidates.items():
        for name in names:
            value = os.environ.get(name)
            if value:
                keys[target] = value.strip()
                break

    # Credentials are injected by the root-owned Hermes collector environment.
    file_candidates = {
        'TAUTULLI': [],
        'SONARR': [],
        'RADARR': [],
        'SEERR': [],
    }
    for target, paths in file_candidates.items():
        if target not in keys:
            value = env_or_file_secret(target, paths)
            if value:
                keys[target] = value

    if 'TAUTULLI' not in keys:
        try:
            raw = run_ssh(MEDIA_VM, r'''python3 - <<'PY'
import configparser
cp = configparser.ConfigParser()
cp.read('/opt/media-stack/tautulli/config.ini')
print(cp.get('General', 'api_key', fallback=''))
PY''')
            if raw.strip():
                keys['TAUTULLI'] = raw.strip().splitlines()[-1]
            else:
                warnings.append('Tautulli API key was empty on media-vm.')
        except Exception as exc:
            warnings.append(f'Tautulli key unavailable: {short_error(exc)}.')

    missing_remote = [name for name in ('SONARR', 'RADARR', 'SEERR') if name not in keys]
    if missing_remote:
        try:
            raw = run_ssh(DOCKER_VM, r'''python3 - <<'PY'
import json
import xml.etree.ElementTree as ET
for name, path in [('SONARR','/opt/media-stack/sonarr/config.xml'), ('RADARR','/opt/media-stack/radarr/config.xml')]:
    root = ET.parse(path).getroot()
    print(name + '=' + (root.findtext('ApiKey') or ''))
try:
    data = json.load(open('/opt/seerr/config/settings.json'))
    print('SEERR=' + (data.get('main', {}).get('apiKey') or data.get('apiKey') or ''))
except Exception:
    print('SEERR=')
PY''')
            for line in raw.splitlines():
                if '=' not in line:
                    continue
                name, value = line.split('=', 1)
                if name not in missing_remote:
                    continue
                if value:
                    keys[name] = value
                else:
                    warnings.append(f'{name.title()} API key was empty on docker-vm.')
        except Exception as exc:
            warnings.append(f'Sonarr/Radarr/Seerr keys unavailable: {short_error(exc)}.')

    return keys, warnings


def collect_plex(key: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    rows: list[dict] = []
    start_idx = 0
    while True:
        data = get_json(
            f'http://{MEDIA_VM}:8181/api/v2',
            {
                'apikey': key,
                'cmd': 'get_history',
                'start': start_idx,
                'length': 100,
                'order_column': 'date',
                'order_dir': 'desc',
            },
            timeout=25,
        )
        payload = (data or {}).get('response', {}).get('data', {}) if isinstance(data, dict) else {}
        batch = payload.get('data') or []
        if not batch:
            break
        stop = False
        for rec in batch:
            when = parse_utc(rec.get('date'))
            if not when:
                continue
            if when > NOW:
                continue
            if when >= START:
                rows.append({**rec, '_when': when})
            else:
                stop = True
        if stop or len(batch) < 100:
            break
        start_idx += 100
        if start_idx > 900:
            warnings.append('Tautulli history pagination stopped after 1000 rows.')
            break
    rows.sort(key=lambda r: r['_when'])
    return rows, warnings


def arr_history(label: str, port: int, key: str) -> list[dict]:
    records: list[dict] = []
    page = 1
    while True:
        params = {
            'page': page,
            'pageSize': 250,
            'sortKey': 'date',
            'sortDirection': 'descending',
        }
        if label == 'Sonarr':
            params.update({'includeSeries': 'true', 'includeEpisode': 'true'})
        elif label == 'Radarr':
            params.update({'includeMovie': 'true'})
        data = get_json(
            f'http://{DOCKER_VM}:{port}/api/v3/history',
            params,
            {'X-Api-Key': key},
            timeout=30,
        )
        batch = data.get('records', []) if isinstance(data, dict) else []
        if not batch:
            break
        stop = False
        for rec in batch:
            when = parse_utc(rec.get('date'))
            if not when:
                continue
            if when > NOW:
                continue
            if when >= START:
                records.append({'_arr': label, '_when': when, **rec})
            else:
                stop = True
        total = int(data.get('totalRecords') or 0) if isinstance(data, dict) else 0
        page_size = int(data.get('pageSize') or 250) if isinstance(data, dict) else 250
        if stop or len(batch) < page_size or (total and page * page_size >= total):
            break
        page += 1
        if page > 20:
            raise RuntimeError(f'{label} history pagination exceeded 20 pages')
    return records


def map_media_path(path: object) -> str | None:
    if not path:
        return None
    p = str(path)
    mappings = [
        ('/data/Movies/', '/srv/media/plex/Movies/'),
        ('/data/Anime/', '/srv/media/plex/Anime/'),
        ('/data/TV/', '/srv/media/plex/Shows/'),
        ('/data/Shows/', '/srv/media/plex/Shows/'),
        ('/srv/media/plex/', '/srv/media/plex/'),
    ]
    for src, dst in mappings:
        if p.startswith(src):
            return dst + p[len(src):]
    return None


def verify_paths(paths: list[str]) -> dict[str, bool]:
    unique = sorted({p for p in paths if p})
    if not unique:
        return {}
    script = r'''python3 - <<'PY'
import os, sys
for line in sys.stdin:
    p = line.rstrip('\n')
    if not p:
        continue
    print(('OK|' if os.path.exists(p) else 'MISS|') + p)
PY'''
    raw = run_ssh(DOCKER_VM, script, timeout=60, input_text='\n'.join(unique) + '\n')
    result: dict[str, bool] = {}
    for line in raw.splitlines():
        status, _, path = line.partition('|')
        if path:
            result[path] = status == 'OK'
    return result


def title_of(rec: dict) -> str:
    movie = rec.get('movie') if isinstance(rec.get('movie'), dict) else None
    if movie:
        title = movie.get('title') or rec.get('sourceTitle') or 'Unknown movie'
        year = movie.get('year')
        return f'{title} ({year})' if year else title
    series = rec.get('series') if isinstance(rec.get('series'), dict) else None
    title = (series or {}).get('title') or 'Unknown series'
    episode = rec.get('episode') if isinstance(rec.get('episode'), dict) else None
    episodes = rec.get('episodes') if isinstance(rec.get('episodes'), list) else []
    if not episode and episodes:
        episode = episodes[0]
    if episode:
        season = episode.get('seasonNumber')
        number = episode.get('episodeNumber')
        if season is not None and number is not None:
            return f'{title} S{int(season):02d}E{int(number):02d}'
    return title


def title_group(rec: dict) -> str:
    title = title_of(rec)
    if rec.get('_arr') == 'Sonarr':
        return re.sub(r' S\d{2}E\d{2}$', '', title)
    return title


def media_record_key(rec: dict) -> tuple[str, str, object]:
    """Return a stable key for pairing an import with its replaced file."""
    arr = str(rec.get('_arr') or 'Arr')
    if rec.get('movieId') is not None:
        return arr, 'movie', rec.get('movieId')
    if rec.get('episodeId') is not None:
        return arr, 'episode', rec.get('episodeId')
    return arr, 'title', title_of(rec)


def quality_name(rec: dict) -> str:
    quality = (rec.get('quality') or {}).get('quality') or {}
    return str(quality.get('name') or 'unknown quality')


def language_names(rec: dict) -> tuple[str, ...]:
    return tuple(str(row.get('name') or 'unknown') for row in (rec.get('languages') or []))


def custom_format_names(rec: dict) -> set[str]:
    return {str(row.get('name') or 'unknown') for row in (rec.get('customFormats') or [])}


def custom_format_score(rec: dict) -> int:
    value = rec.get('customFormatScore')
    if value is None:
        value = (rec.get('data') or {}).get('customFormatScore')
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def codec_name(rec: dict) -> str | None:
    text = ' '.join(custom_format_names(rec))
    text += ' ' + str((rec.get('data') or {}).get('importedPath') or '')
    if re.search(r'(?i)(?:x265|h[ ._-]?265|hevc)', text):
        return 'x265/HEVC'
    if re.search(r'(?i)(?:x264|h[ ._-]?264|avc)', text):
        return 'x264/H.264'
    return None


def fmt_languages(names: tuple[str, ...]) -> str:
    return '+'.join(names) if names else 'unknown audio'


def upgrade_reason(old: dict, new: dict) -> str:
    """Explain the observable old-to-new differences behind an Arr upgrade."""
    reasons: list[str] = []

    old_quality = quality_name(old)
    new_quality = quality_name(new)
    if old_quality != new_quality:
        reasons.append(f'{old_quality} → {new_quality}')

    old_codec = codec_name(old)
    new_codec = codec_name(new)
    if old_codec and new_codec and old_codec != new_codec:
        reasons.append(f'{old_codec} → {new_codec}')
    elif not old_codec and new_codec == 'x265/HEVC':
        reasons.append('now x265/HEVC')

    old_languages = language_names(old)
    new_languages = language_names(new)
    if set(old_languages) != set(new_languages):
        reasons.append(f'audio {fmt_languages(old_languages)} → {fmt_languages(new_languages)}')

    revision = (new.get('quality') or {}).get('revision') or {}
    if revision.get('isRepack'):
        reasons.append('repack/proper')

    old_score = custom_format_score(old)
    new_score = custom_format_score(new)
    if old_score != new_score:
        reasons.append(f'custom-format score {old_score:,} → {new_score:,}')

    if not reasons:
        old_group = str((old.get('data') or {}).get('releaseGroup') or '').strip()
        new_group = str((new.get('data') or {}).get('releaseGroup') or '').strip()
        if old_group != new_group and (old_group or new_group):
            reasons.append(f'release group {old_group or "unknown"} → {new_group or "unknown"}')

    if not reasons:
        reasons.append('Arr marked this as an upgrade, but exposed no meaningful metadata difference')
    return '; '.join(reasons)


def import_description(rec: dict) -> str:
    details = [quality_name(rec)]
    codec = codec_name(rec)
    if codec:
        details.append(codec)
    languages = language_names(rec)
    if languages:
        details.append(fmt_languages(languages))
    revision = (rec.get('quality') or {}).get('revision') or {}
    if revision.get('isRepack'):
        details.append('repack/proper')
    score = custom_format_score(rec)
    if score:
        details.append(f'custom-format score {score:,}')
    return '; '.join(details)


def pair_imports_with_upgrades(imports: list[dict], deletes: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pair imports with API delete events whose reason is explicitly Upgrade."""
    candidates: dict[tuple[str, str, object], deque[dict]] = defaultdict(deque)
    for rec in deletes:
        if (rec.get('data') or {}).get('reason') == 'Upgrade':
            candidates[media_record_key(rec)].append(rec)

    paired: list[tuple[dict, dict | None]] = []
    for rec in imports:
        queue = candidates.get(media_record_key(rec))
        paired.append((rec, queue.popleft() if queue else None))
    return paired


def collect_arr(keys: dict[str, str]) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    records: list[dict] = []
    for label, port, key_name in [('Sonarr', 8989, 'SONARR'), ('Radarr', 7878, 'RADARR')]:
        key = keys.get(key_name)
        if not key:
            warnings.append(f'{label} skipped because API key was unavailable.')
            continue
        try:
            records.extend(arr_history(label, port, key))
        except Exception as exc:
            warnings.append(f'{label} history unavailable on docker-vm:{port}: {short_error(exc)}.')
    records.sort(key=lambda r: r['_when'])
    return records, warnings


def collect_seerr(key: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    rows: list[dict] = []
    skip = 0
    while True:
        data = get_json(
            f'http://{DOCKER_VM}:5055/api/v1/request',
            {'take': 50, 'skip': skip, 'sort': 'added'},
            {'X-Api-Key': key},
            timeout=25,
        )
        batch = data.get('results', []) if isinstance(data, dict) else []
        if not batch:
            break
        stop = False
        for rec in batch:
            when = parse_utc(rec.get('createdAt') or rec.get('updatedAt'))
            if not when:
                continue
            if when > NOW:
                continue
            if when >= START:
                rows.append({'_when': when, **rec})
            else:
                stop = True
        if stop or len(batch) < 50:
            break
        skip += 50
        if skip >= 500:
            warnings.append('Seerr pagination stopped after 500 requests.')
            break
    rows.sort(key=lambda r: r['_when'])
    return rows, warnings


def raw_seerr_title(media: dict) -> str | None:
    title = (
        media.get('title')
        or media.get('name')
        or media.get('originalTitle')
        or media.get('originalName')
    )
    return str(title) if title else None


def seerr_lookup_id(media: dict) -> str | None:
    for key in ('tmdbId', 'externalServiceSlug'):
        value = media.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.isdigit():
            return text
    return None


def resolve_seerr_title(key: str | None, media: dict, media_type: str, cache: dict[tuple[str, str], str]) -> str:
    title = raw_seerr_title(media)
    if title:
        return title

    lookup_id = seerr_lookup_id(media)
    if not lookup_id:
        slug = media.get('externalServiceSlug')
        return str(slug) if slug else 'Unknown title'

    if not key:
        return f'TMDb {lookup_id}'

    endpoint = 'tv' if str(media_type).lower() in {'tv', 'show', 'series'} else 'movie'
    cache_key = (endpoint, lookup_id)
    if cache_key not in cache:
        try:
            detail = get_json(
                f'http://{DOCKER_VM}:5055/api/v1/{endpoint}/{urllib.parse.quote(lookup_id)}',
                headers={'X-Api-Key': key},
                timeout=15,
            )
            cache[cache_key] = raw_seerr_title(detail) if isinstance(detail, dict) else None
        except Exception:
            cache[cache_key] = None
        if not cache[cache_key]:
            cache[cache_key] = f'TMDb {lookup_id}'
    return cache[cache_key]


def render_plex(rows: list[dict], warnings: list[str]) -> list[str]:
    lines = ['## Plex Activity', '']
    if warnings:
        lines.extend(f'- ⚠️ {w}' for w in warnings)
    if not rows:
        lines.append('- No Plex plays recorded in the last 24 hours.')
        return lines
    total_seconds = sum(duration_seconds(r.get('play_duration') or r.get('duration')) for r in rows)
    users = Counter(r.get('friendly_name') or r.get('user') or 'unknown' for r in rows)
    playback = Counter((r.get('transcode_decision') or r.get('video_decision') or 'unknown').replace('copy', 'direct stream') for r in rows)
    user_text = ', '.join(f'{user} {count}' for user, count in users.most_common(6))
    play_text = ', '.join(f'{mode} {count}' for mode, count in playback.most_common())
    lines.append(f'- {len(rows)} plays, about {fmt_duration(total_seconds)} total. Users: {user_text}. Playback: {play_text}.')
    lines.append('- Recent plays:')
    for rec in rows[-12:]:
        title = rec.get('full_title') or rec.get('title') or 'Unknown title'
        user = rec.get('friendly_name') or rec.get('user') or 'unknown'
        dur = fmt_duration(rec.get('play_duration') or rec.get('duration'))
        mode = (rec.get('transcode_decision') or rec.get('video_decision') or 'unknown').replace('copy', 'direct stream')
        platform = rec.get('platform') or 'unknown platform'
        lines.append(f'  - {fmt_time(rec["_when"])}: {title} ({dur}; {user}; {mode}; {platform})')
    if len(rows) > 12:
        lines.append(f'  - {len(rows) - 12} older play(s) omitted for concision.')
    return lines


def render_arr(records: list[dict], warnings: list[str]) -> list[str]:
    lines = ['## Media Changes', '']
    if warnings:
        lines.extend(f'- ⚠️ {w}' for w in warnings)
    if not records:
        lines.append('- No Sonarr/Radarr history records in the last 24 hours.')
        return lines

    imports = [r for r in records if r.get('eventType') in {'downloadFolderImported', 'episodeFileImported', 'movieFileImported'} or 'Imported' in str(r.get('eventType'))]
    grabs = [r for r in records if r.get('eventType') in {'grabbed', 'downloadGrabbed'}]
    deletes = [r for r in records if 'Deleted' in str(r.get('eventType'))]
    failed = [r for r in records if r.get('eventType') == 'downloadFailed']

    # Disk-verify import paths as a confidence check (optional).
    import_paths: dict[int, str] = {}
    verify_needed: list[str] = []
    for rec in imports:
        mapped = map_media_path((rec.get('data') or {}).get('importedPath'))
        if mapped:
            import_paths[id(rec)] = mapped
            verify_needed.append(mapped)
    try:
        verified = verify_paths(verify_needed)
    except Exception as exc:
        verified = {}
        lines.append(f'- ⚠️ Disk verification unavailable on docker-vm /srv/media: {short_error(exc)}.')

    # Arr delete records report size directly but do NOT include file paths,
    # so disk verification is not possible for deletes. Trust the API size.
    imported_size = sum(int((r.get('data') or {}).get('size') or 0) for r in imports)
    freed_size = sum(int((r.get('data') or {}).get('size') or 0) for r in deletes)
    net = imported_size - freed_size

    grab_counts = Counter(r.get('_arr') for r in grabs)
    import_counts = Counter(r.get('_arr') for r in imports)
    delete_counts = Counter(r.get('_arr') for r in deletes)
    failed_counts = Counter(r.get('_arr') for r in failed)
    lines.append(
        '- Totals: '
        f"grabs {len(grabs)} ({', '.join(f'{k} {v}' for k, v in grab_counts.items()) or 'none'}); "
        f"imports/upgrades {len(imports)} ({', '.join(f'{k} {v}' for k, v in import_counts.items()) or 'none'}); "
        f"replacement deletes {len(deletes)} ({', '.join(f'{k} {v}' for k, v in delete_counts.items()) or 'none'}); "
        f"failed downloads {len(failed)} ({', '.join(f'{k} {v}' for k, v in failed_counts.items()) or 'none'})."
    )
    sign = '+' if net >= 0 else ''
    lines.append(f'- Storage delta: +{fmt_bytes(imported_size)} new content, {fmt_bytes(freed_size)} replaced/freed by upgrades, net {sign}{fmt_bytes(net)}.')
    # Report upgrade reason breakdown
    upgrade_deletes = [r for r in deletes if (r.get('data') or {}).get('reason') == 'Upgrade']
    non_upgrade_deletes = [r for r in deletes if (r.get('data') or {}).get('reason') != 'Upgrade']
    upgrade_freed = sum(int((r.get('data') or {}).get('size') or 0) for r in upgrade_deletes)
    non_upgrade_freed = sum(int((r.get('data') or {}).get('size') or 0) for r in non_upgrade_deletes)
    if upgrade_deletes:
        lines.append(f'  - Upgrades freed {fmt_bytes(upgrade_freed)} across {len(upgrade_deletes)} replacement(s).')
    if non_upgrade_deletes:
        lines.append(f'  - Other deletes freed {fmt_bytes(non_upgrade_freed)} across {len(non_upgrade_deletes)} removal(s).')
    # Disk verification confidence for imports
    if verified:
        verified_ok = sum(1 for rec in imports if import_paths.get(id(rec)) and verified.get(import_paths[id(rec)]) is True)
        verified_miss = sum(1 for rec in imports if import_paths.get(id(rec)) and verified.get(import_paths[id(rec)]) is False)
        if verified_ok or verified_miss:
            lines.append(f'  - Import disk verification: {verified_ok} confirmed, {verified_miss} not found on disk.')

    if grabs:
        grouped = Counter(title_group(r) for r in grabs)
        lines.append('- Grabs by title:')
        for title, count in grouped.most_common():
            lines.append(f'  - {title}: {count} grab(s)')
    if imports:
        grouped_pairs: dict[str, list[tuple[dict, dict | None]]] = defaultdict(list)
        for rec, old in pair_imports_with_upgrades(imports, deletes):
            grouped_pairs[title_group(rec)].append((rec, old))
        lines.append('- Imports/upgrades by title:')
        ordered_titles = sorted(grouped_pairs, key=lambda title: (-len(grouped_pairs[title]), title.lower()))
        for title in ordered_titles:
            pairs = grouped_pairs[title]
            added = [rec for rec, old in pairs if old is None]
            upgraded = [(rec, old) for rec, old in pairs if old is not None]
            imported_bytes = sum(int((rec.get('data') or {}).get('size') or 0) for rec, _ in pairs)
            freed_bytes = sum(int((old.get('data') or {}).get('size') or 0) for _, old in upgraded)
            kinds: list[str] = []
            if upgraded:
                kinds.append(f'{len(upgraded)} upgraded')
            if added:
                kinds.append(f'{len(added)} added')
            label = 'Upgraded' if upgraded and not added else 'Added' if added and not upgraded else 'Mixed'
            size_text = f'+{fmt_bytes(imported_bytes)}'
            if freed_bytes:
                size_text += f', {fmt_bytes(freed_bytes)} old files replaced'
            lines.append(f'  - {label} — {title}: {len(pairs)} import(s) ({", ".join(kinds)}), {size_text}')

            if upgraded:
                reasons = Counter(upgrade_reason(old, rec) for rec, old in upgraded)
                for reason, count in reasons.most_common():
                    lines.append(f'    - {count}× {reason}')
            if added:
                descriptions = Counter(import_description(rec) for rec in added)
                for description, count in descriptions.most_common():
                    lines.append(f'    - {count}× new file: {description}')
    if failed:
        lines.append('- Failed downloads:')
        for rec in failed:
            message = short_error((rec.get('data') or {}).get('message') or 'download failed')
            lines.append(f'  - {rec.get("_arr") or "Arr"}: {title_of(rec)} — {message}')
    return lines


def render_seerr(rows: list[dict], warnings: list[str], key: str | None = None) -> list[str]:
    lines = ['## Seerr Requests', '']
    if warnings:
        lines.extend(f'- ⚠️ {w}' for w in warnings)
    if not rows:
        lines.append('- No Seerr requests created or updated in the last 24 hours.')
        return lines
    status_names = {1: 'pending', 2: 'approved', 3: 'declined', 4: 'available', 5: 'available'}
    title_cache: dict[tuple[str, str], str] = {}
    lines.append(f'- {len(rows)} request(s) created or updated in the last 24 hours.')
    for rec in rows[-20:]:
        media = rec.get('media') or {}
        media_type = rec.get('type') or media.get('mediaType') or 'media'
        title = resolve_seerr_title(key, media, media_type, title_cache)
        year = (media.get('releaseDate') or media.get('firstAirDate') or '')[:4]
        if year and year not in str(title):
            title = f'{title} ({year})'
        status = status_names.get(rec.get('status'), str(rec.get('status')))
        media_status = media.get('status')
        if media_status and str(media_status) != str(rec.get('status')):
            status += f'/media {media_status}'
        who = (rec.get('requestedBy') or {}).get('displayName') or (rec.get('requestedBy') or {}).get('username') or 'unknown user'
        lines.append(f'- {fmt_time(rec["_when"])}: {title} ({media_type}; {status}; {who})')
    if len(rows) > 20:
        lines.append(f'- {len(rows) - 20} older request(s) omitted for concision.')
    return lines


def main() -> int:
    keys, key_warnings = load_keys()

    plex_rows: list[dict] = []
    plex_warnings = [w for w in key_warnings if 'Tautulli' in w]
    if keys.get('TAUTULLI'):
        try:
            plex_rows, more = collect_plex(keys['TAUTULLI'])
            plex_warnings.extend(more)
        except Exception as exc:
            plex_warnings.append(f'Tautulli/Plex activity unavailable: {short_error(exc)}.')

    arr_records: list[dict] = []
    arr_warnings = [w for w in key_warnings if any(name in w for name in ('Sonarr', 'Radarr'))]
    try:
        arr_records, more = collect_arr(keys)
        arr_warnings.extend(more)
    except Exception as exc:
        arr_warnings.append(f'Sonarr/Radarr media changes unavailable: {short_error(exc)}.')

    seerr_rows: list[dict] = []
    seerr_warnings = [w for w in key_warnings if 'Seerr' in w]
    if keys.get('SEERR'):
        try:
            seerr_rows, more = collect_seerr(keys['SEERR'])
            seerr_warnings.extend(more)
        except Exception as exc:
            seerr_warnings.append(f'Seerr requests unavailable: {short_error(exc)}.')

    lines: list[str] = []
    lines.append('## Date / generated at')
    lines.append('')
    lines.append(f'- Generated: {fmt_local(NOW)}')
    lines.append(f'- Window: {fmt_local(START)} to {fmt_local(NOW)}')
    lines.append('')
    lines.extend(render_plex(plex_rows, plex_warnings))
    lines.append('')
    lines.extend(render_arr(arr_records, arr_warnings))
    lines.append('')
    lines.extend(render_seerr(seerr_rows, seerr_warnings, keys.get('SEERR')))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('\n'.join(lines).rstrip() + '\n')
    print(json.dumps({
        'ok': True,
        'path': str(OUT),
        'bytes': OUT.stat().st_size,
        'plex_rows': len(plex_rows),
        'arr_records': len(arr_records),
        'seerr_rows': len(seerr_rows),
        'warnings': plex_warnings + arr_warnings + seerr_warnings,
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
