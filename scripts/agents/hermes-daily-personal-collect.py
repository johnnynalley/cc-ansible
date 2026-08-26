#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(os.environ.get('HERMES_AUTOMATION_WORKSPACE', '/var/lib/hermes-automation/workspace'))
OUT = WORKSPACE / 'memory' / 'daily-summary-sections' / 'personal.md'
LOCAL_TZ = ZoneInfo('America/Chicago')
CALENDAR_ROOT = Path(os.environ.get('HERMES_CALENDAR_ROOT', '/var/lib/hermes/astra/.local/share/vdirsyncer/calendars'))
OPS_REPOSITORY = Path(os.environ.get('HERMES_OPS_REPOSITORY', '/var/lib/hermes/astra/workspaces/cc-ansible'))
NATIVE_MEMORY = Path(os.environ.get('HERMES_NATIVE_MEMORY_FILE', '/var/lib/hermes/astra/.hermes/profiles/astra/MEMORY.md'))

TASK_DIRS = [
    CALENDAR_ROOT / 'C28F5637-E236-4AA2-AB0B-71846E946D6F',
    CALENDAR_ROOT / 'BFA4B44C-4DE3-4157-A327-CA3148CB7277',
]


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.strip() if isinstance(exc.stdout, str) else ''
        err = exc.stderr.strip() if isinstance(exc.stderr, str) else 'timeout'
        return 124, out, err
    except Exception as exc:
        return 1, '', str(exc)


def section(title: str, lines: list[str]) -> list[str]:
    body = lines or ['- Nothing notable.']
    return [f'## {title}', '', *body, '']


def unfold_ics(text: str) -> str:
    return re.sub(r'\r?\n[ \t]', '', text.replace('\r\n', '\n'))


def ics_field(block: str, name: str) -> str:
    match = re.search(rf'^{re.escape(name)}(?:;[^:]*)?:(.*)$', block, re.M)
    return match.group(1).strip().replace('\\,', ',').replace('\\n', ' ') if match else ''


def collect_tasks() -> list[str]:
    tasks: list[str] = []
    for task_dir in TASK_DIRS:
        if not task_dir.exists():
            continue
        for path in sorted(task_dir.glob('*.ics')):
            try:
                text = unfold_ics(path.read_text(errors='replace'))
            except Exception:
                continue
            for block in re.findall(r'BEGIN:VTODO(.*?)END:VTODO', text, re.S):
                status = ics_field(block, 'STATUS').upper()
                if status == 'COMPLETED':
                    continue
                summary = ics_field(block, 'SUMMARY') or path.stem
                due = ics_field(block, 'DUE')
                suffix = f' (due {due[:8]})' if due else ''
                tasks.append(f'- {summary}{suffix}')
    return tasks[:20]


def calendar_section() -> list[str]:
    lines: list[str] = []
    sync_rc, _, sync_err = run(['vdirsyncer', 'sync', 'personal'], timeout=120)
    if sync_rc != 0:
        lines.append(f'- Calendar sync warning: vdirsyncer rc={sync_rc}: {(sync_err or "no stderr")[:180]}')
    rc, out, err = run(['khal', 'list', 'today', '2d'], timeout=40)
    if rc == 0 and out:
        lines.extend(f'- {line}' for line in out.splitlines()[:30] if line.strip())
    else:
        lines.append(f'- Calendar list unavailable: khal rc={rc}: {(err or "no stderr")[:180]}')
    tasks = collect_tasks()
    if tasks:
        lines.append('')
        lines.append('### Tasks')
        lines.extend(tasks)
    return lines


def inbox_section() -> list[str]:
    cmd = [
        '/usr/local/bin/himalaya',
        'envelope',
        'list',
        '--account',
        'icloud',
        '--folder',
        'INBOX',
        '--page-size',
        '25',
    ]
    rc, out, err = run(cmd, timeout=45)
    if rc != 0:
        return [f'- Inbox unavailable: himalaya rc={rc}: {(err or "no stderr")[:180]}']
    lines = [line for line in out.splitlines() if line.strip() and 'WARN' not in line]
    return [f'- {line}' for line in lines[:15]] or ['- No recent inbox rows returned.']


def changes_section() -> list[str]:
    cmd = ['git', '-C', str(OPS_REPOSITORY), 'log', '--since=24 hours ago', '--oneline', '--max-count=12']
    rc, out, err = run(cmd, timeout=20)
    if rc != 0:
        return [f'- cc-ansible git log unavailable: {(err or "no stderr")[:180]}']
    return [f'- {line}' for line in out.splitlines()] or ['- No cc-ansible commits in the last 24 hours.']


def games_section() -> list[str]:
    lines: list[str] = []
    warframe_state = WORKSPACE / 'memory' / 'warframe-drops-state.json'
    if warframe_state.exists():
        try:
            data = json.loads(warframe_state.read_text())
            events = data.get('events') or []
            if isinstance(events, dict):
                events = list(events.values())
            current = [e for e in events if isinstance(e, dict) and not e.get('past')]
            if current:
                lines.append('- Warframe drops:')
                for event in current[:5]:
                    name = event.get('title') or event.get('streamer') or 'drop'
                    starts = event.get('starts_at_local') or event.get('starts_at_ct') or event.get('starts_at') or 'time unknown'
                    lines.append(f'  - {name}: {starts}')
        except Exception as exc:
            lines.append(f'- Warframe state unreadable: {exc}')

    rc, out, _ = run(['rg', '-n', '-i', 'warframe|fortnite|v-bucks|vbuck|games', str(NATIVE_MEMORY)], timeout=15)
    if rc == 0 and out:
        lines.append('- Memory game notes:')
        for line in out.splitlines()[:8]:
            lines.append(f'  - {line}')
    return lines


def main() -> int:
    now = datetime.now(timezone.utc)
    local = now.astimezone(LOCAL_TZ)
    lines: list[str] = []
    lines += section('Date / generated at', [
        f'- Local: {local.strftime("%A, %B %d, %Y - %-I:%M %p %Z")}',
        f'- UTC: {now.strftime("%Y-%m-%d %H:%M UTC")}',
    ])
    lines += section('Calendar + Tasks', calendar_section())
    lines += section('Inbox', inbox_section())
    lines += section('Changes & Improvements', changes_section())
    lines += section('Weather', ['- Filled by daily-summary-assemble.py.'])
    lines += section('Health', ['- Filled by daily-summary-assemble.py.'])
    lines += section('Games', games_section())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Wrote {OUT} ({OUT.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
