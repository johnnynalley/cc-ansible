#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(os.environ.get('HERMES_AUTOMATION_WORKSPACE', '/var/lib/hermes-automation/workspace'))
SECTIONS = WORKSPACE / 'memory' / 'daily-summary-sections'
OUTPUT = Path(os.environ.get('DAILY_SUMMARY_SCRATCH_OUT', WORKSPACE / 'memory' / 'daily-summary-scratch.md'))
FRESH_SECONDS = int(os.environ.get('DAILY_SUMMARY_FRESH_SECONDS', '5400'))  # 90 minutes
LOCAL_TZ = ZoneInfo('America/Chicago')
FORTNITE_TOURNAMENT_STATE = WORKSPACE / 'fortnite-progress' / 'tournaments' / 'calendar-sync-state.json'
HEALTH_REPORT_JSON = Path(
    os.environ.get(
        'HERMES_HEALTH_REPORT_JSON',
        '/var/lib/hermes/health/reports/yesterday.json',
    )
)
HEALTH_REPORT_MARKDOWN = Path(
    os.environ.get(
        'HERMES_HEALTH_REPORT_MARKDOWN',
        '/var/lib/hermes/health/reports/yesterday.md',
    )
)


def parse_now() -> datetime:
    override = os.environ.get('DAILY_SUMMARY_ASSEMBLE_NOW')
    if override:
        parsed = datetime.fromisoformat(override.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def clean(text: str) -> str:
    return re.sub(r'\n{3,}', '\n\n', text).strip()



def replace_section(text: str, heading: str, replacement: str) -> str:
    next_heading = r'(?=^##\s+[^\n]+\n|\Z)'
    pattern = rf'(?ms)^##\s+{re.escape(heading)}\s*\n.*?{next_heading}'
    replacement = clean(replacement) + '\n\n'
    if re.search(pattern, text):
        return re.sub(pattern, replacement, text, count=1)
    return clean(text) + '\n\n' + replacement


def deterministic_health_section(now: datetime) -> str:
    local_yesterday = (now.astimezone(LOCAL_TZ).date() - timedelta(days=1)).isoformat()
    try:
        if HEALTH_REPORT_JSON.stat().st_size > 1_048_576:
            raise ValueError('aggregate JSON exceeds size limit')
        if HEALTH_REPORT_MARKDOWN.stat().st_size > 65_536:
            raise ValueError('aggregate Markdown exceeds size limit')
        report = json.loads(HEALTH_REPORT_JSON.read_text(encoding='utf-8'))
        markdown = HEALTH_REPORT_MARKDOWN.read_text(encoding='utf-8').strip()
    except Exception as exc:
        return (
            '## Health\n\n'
            f'- ⚠️ Health data unavailable - aggregate report failed validation: '
            f'{type(exc).__name__}.'
        )

    if report.get('ok') is not True or report.get('date') != local_yesterday:
        return (
            '## Health\n\n'
            '- ⚠️ Health data unavailable - aggregate report is stale or invalid.'
        )
    if not markdown:
        return '## Health\n\n- ⚠️ Health data unavailable - aggregate report is empty.'

    return f'## Health\n\n{markdown}'


def deterministic_weather_section(now: datetime) -> str:
    """Fetch live wttr.in data and return deterministic ## Weather markdown."""
    import urllib.request  # local import avoids startup cost
    url = 'https://wttr.in/75040?format=j1'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'}), timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        return f'## Weather\n\n- ⚠️ Live weather unavailable: {exc}.'

    try:
        cur = data['current_condition'][0]
        today = data['weather'][0]
        hourly = today.get('hourly', [])
        cur_desc = cur['weatherDesc'][0]['value']
        cur_temp = cur.get('temp_F', '?')
        feels = cur.get('FeelsLikeF', '?')
        humid = cur.get('humidity', '?')
        wind_dir = cur.get('winddir16Point', '?')
        wind_mph = cur.get('windspeedMiles', '?')
        precip = cur.get('precipInches', '?')
        hi = today.get('maxtempF', '?')
        lo = today.get('mintempF', '?')
        # pick noon-ish hourly for a short summary if available
        mid = hourly[len(hourly)//2] if hourly else {}
        mid_desc = mid.get('weatherDesc', [{}])[0].get('value', '') if mid else ''
        summary = f'high {hi}°F, low {lo}°F' + (f', midday {mid_desc}' if mid_desc else '')
    except Exception as exc:
        return f'## Weather\n\n- ⚠️ Live weather parse failed: {exc}.'

    return (
        f'## Weather\n\n'
        f'- Current: {cur_desc} {cur_temp}°F, feels {feels}°F, humidity {humid}%, wind {wind_dir} {wind_mph}mph, precip {precip}in\n'
        f'- Today: {summary}\n'
    )


def short_time(dt: datetime) -> str:
    return dt.strftime('%I:%M %p').lstrip('0')


def compress_fortnite_titles(titles: list[str]) -> str:
    divisions: list[int] = []
    others: list[str] = []
    for title in titles:
        match = re.fullmatch(r'FNCS Division (\d+)', title)
        if match:
            divisions.append(int(match.group(1)))
        else:
            others.append(title)

    parts: list[str] = []
    if divisions:
        ordered = sorted(set(divisions))
        if ordered == list(range(ordered[0], ordered[-1] + 1)) and len(ordered) > 1:
            parts.append(f'FNCS Divisions {ordered[0]}-{ordered[-1]}')
        else:
            parts.extend(f'FNCS Division {division}' for division in ordered)
    parts.extend(others)
    return '; '.join(parts)


def deterministic_fortnite_section(now: datetime) -> str:
    local_now = now.astimezone(LOCAL_TZ)
    start_date = local_now.date()
    end_date = start_date + timedelta(days=7)

    if not FORTNITE_TOURNAMENT_STATE.exists():
        return (
            '## Fortnite\n\n'
            '- ⚠️ Tournament calendar state is missing; no week-ahead event list available.'
        )

    try:
        data = json.loads(FORTNITE_TOURNAMENT_STATE.read_text(encoding='utf-8'))
    except Exception as exc:
        return f'## Fortnite\n\n- ⚠️ Tournament calendar state could not be read: {exc}.'

    updated_raw = data.get('updatedAt')
    try:
        updated = datetime.fromisoformat(updated_raw.replace('Z', '+00:00')).astimezone(timezone.utc) if updated_raw else None
    except Exception:
        updated = None

    stale_note = ''
    updated_note = 'source sync time unknown'
    if updated:
        age_hours = max(0, int((now - updated).total_seconds() // 3600))
        updated_note = f'source synced {updated.astimezone(LOCAL_TZ).strftime("%a %-I:%M %p %Z")}'
        if age_hours >= 12:
            stale_note = f'; stale {age_hours}h'

    grouped: dict[tuple[datetime.date, str], list[str]] = {}
    for item in data.get('events', []):
        try:
            start_utc = datetime.fromisoformat(item['startUtc'].replace('Z', '+00:00'))
            end_utc = datetime.fromisoformat(item['endUtc'].replace('Z', '+00:00'))
        except Exception:
            continue
        start_local = start_utc.astimezone(LOCAL_TZ)
        end_local = end_utc.astimezone(LOCAL_TZ)
        if not (start_date <= start_local.date() <= end_date):
            continue
        timerange = f'{short_time(start_local)}-{short_time(end_local)}'
        grouped.setdefault((start_local.date(), timerange), []).append(str(item.get('title', 'Untitled event')))

    lines = [
        '## Fortnite',
        '',
        f'- NAC tournament outlook: next 7 calendar days, {start_date.strftime("%b %-d")} through {end_date.strftime("%b %-d")} ({updated_note}{stale_note}).',
    ]
    if not grouped:
        lines.append('- No official NAC events found in the synced calendar state for this window.')
        return '\n'.join(lines)

    current_day = None
    for (day, timerange), titles in sorted(grouped.items(), key=lambda entry: (entry[0][0], entry[0][1])):
        if day != current_day:
            lines.append(f'- {day.strftime("%a %b %-d")}:')
            current_day = day
        lines.append(f'  - {timerange}: {compress_fortnite_titles(sorted(titles))}')
    return '\n'.join(lines)


def main() -> int:
    now = parse_now()
    inputs = [
        ('personal.md', SECTIONS / 'personal.md'),
        ('updates.md', SECTIONS / 'updates.md'),
        ('media.md', SECTIONS / 'media.md'),
        ('rss.md', SECTIONS / 'rss.md'),
    ]

    coverage: list[str] = [
        'Coverage',
        f'- generated: {now.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")} / {now.strftime("%Y-%m-%d %H:%M:%S UTC")}',
        f'- freshness window: {FRESH_SECONDS // 60} minutes',
        '- fortnite-events.md: deterministic from synced tournament calendar state',
    ]
    sections: list[str] = []
    fresh_input_count = 0
    health_section_added = False

    for label, path in inputs:
        if not path.exists():
            coverage.append(f'- {label}: missing')
            continue

        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        raw_age = (now - mtime).total_seconds()
        age = max(0, raw_age)
        fresh = age <= FRESH_SECONDS
        future_note = '' if raw_age >= 0 else f', clock-skew/future by {int(abs(raw_age))}s treated as age 0'
        status = 'fresh' if fresh else 'stale'
        coverage.append(
            f'- {label}: {status} '
            f'(mtime {mtime.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")} / '
            f'{mtime.strftime("%Y-%m-%d %H:%M:%S UTC")}, age {int(age // 60)}m{future_note})'
        )

        if fresh:
            text = clean(path.read_text())
            if text:
                fresh_input_count += 1
                if label == 'personal.md':
                    text = replace_section(text, 'Health', deterministic_health_section(now))
                    text = replace_section(text, 'Weather', deterministic_weather_section(now))
                    health_section_added = True
                sections.append(text)

    if not health_section_added:
        sections.append(deterministic_health_section(now))
    sections.append(deterministic_fortnite_section(now))

    content = '\n'.join(coverage) + '\n\n'
    content += ('\n\n'.join(sections) + '\n') if sections else 'No fresh sections available.\n'
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content)
    print(
        f'Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes), '
        f'fresh_sections={fresh_input_count}/{len(inputs)}, deterministic_sections=2'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
