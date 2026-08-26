#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from icalendar import Calendar, Event


WORKSPACE = Path(os.environ.get("HERMES_AUTOMATION_WORKSPACE", "/var/lib/hermes-automation/workspace"))
STATE_PATH = WORKSPACE / "fortnite-progress/tournaments/calendar-sync-state.json"
ELIGIBILITY_PATH = WORKSPACE / "fortnite-progress/tournaments/eligibility.json"
CANDIDATE_PLAN_PATH = WORKSPACE / "state/fortnite-tournament-candidate-plan.json"
LOCAL_CALENDAR_DIR = Path.home() / ".local/share/vdirsyncer/calendars/fortnite-tournaments"
PASSWORD_CMD = "/usr/local/libexec/hermes-get-caldav-password"
CALDAV_BASE_URL = "https://nextcloud.jnalley.me/remote.php/dav/calendars/johnny/"
CALENDAR_SLUG = "fortnite-tournaments"
CALENDAR_DISPLAY_NAME = "Fortnite Tournaments"
SOURCE_URL = "https://www.fortnite.com/competitive/schedule?region=NAC"
GECKODRIVER_PATH = Path("/snap/bin/geckodriver")
SCHEDULE_ROUTE_ID = "routes/competitive.schedule"
PRODID = "-//Hermes//Fortnite Tournament Calendar Sync//EN"
REGION = "NAC"

MOBILE_PATTERN = re.compile(r"(?:\bMobile\b|_Mobile\b)", re.IGNORECASE)
ZERO_BUILD_PATTERN = re.compile(r"(?:\bZero Build\b|\bZB\b|_ZB\b|ZB_)", re.IGNORECASE)
FNCS_PATTERN = re.compile(r"(?:\bFNCS\b|Fortnite Championship Series|_FNCS)", re.IGNORECASE)
FNCS_DIVISION_PATTERNS = (
    re.compile(r"\bFNCS\s+Division\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"FNCSDivisionalCup_Division(\d+)", re.IGNORECASE),
)
PLAN_MAX_AGE = timedelta(minutes=30)


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class TournamentEvent:
    title: str
    url: str
    round_id: str
    start_utc: datetime
    end_utc: datetime
    mode: str
    format: str

    @property
    def uid(self) -> str:
        digest = hashlib.sha256(self.round_id.encode("utf-8")).hexdigest()[:24]
        return f"fortnite-nac-{digest}@openclaw.jnalley.me"


@dataclass(frozen=True)
class EventDecision:
    accepted: bool
    reason: str
    title: str
    round_id: str
    event_group_id: str
    start_utc: datetime
    end_utc: datetime
    mode: str
    format: str
    url: str

    def to_json(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "title": self.title,
            "roundId": self.round_id,
            "eventGroupId": self.event_group_id,
            "startUtc": self.start_utc.isoformat(),
            "endUtc": self.end_utc.isoformat(),
            "mode": self.mode,
            "format": self.format,
            "url": self.url,
        }


def run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise SyncError(f"command failed: {' '.join(cmd)}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def get_caldav_password() -> str:
    proc = run([PASSWORD_CMD], timeout=20)
    password = proc.stdout.strip()
    if not password:
        raise SyncError("CalDAV password command returned no password")
    return password


def ensure_remote_calendar() -> str:
    calendar_url = f"{CALDAV_BASE_URL}{CALENDAR_SLUG}/"
    auth = ("johnny", get_caldav_password())
    headers = {"Depth": "0"}
    probe = requests.request("PROPFIND", calendar_url, auth=auth, headers=headers, timeout=30)
    if probe.status_code in (200, 207):
        return calendar_url
    if probe.status_code not in (404, 405):
        raise SyncError(f"CalDAV calendar probe failed with HTTP {probe.status_code}")

    body = f"""<?xml version="1.0" encoding="utf-8" ?>
<C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:ICAL="http://apple.com/ns/ical/">
  <D:set>
    <D:prop>
      <D:displayname>{CALENDAR_DISPLAY_NAME}</D:displayname>
      <ICAL:calendar-color>#ff7a00ff</ICAL:calendar-color>
      <C:supported-calendar-component-set>
        <C:comp name="VEVENT" />
      </C:supported-calendar-component-set>
    </D:prop>
  </D:set>
</C:mkcalendar>
"""
    created = requests.request(
        "MKCALENDAR",
        calendar_url,
        auth=auth,
        headers={"Content-Type": "application/xml; charset=utf-8"},
        data=body.encode("utf-8"),
        timeout=30,
    )
    if created.status_code not in (200, 201, 204, 405):
        raise SyncError(f"CalDAV calendar create failed with HTTP {created.status_code}")
    return calendar_url


def vdirsyncer_sync() -> None:
    LOCAL_CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    run(["vdirsyncer", "discover", "personal"], timeout=120)
    run(["vdirsyncer", "sync", "personal"], timeout=240)
    if not LOCAL_CALENDAR_DIR.exists():
        raise SyncError(f"local Fortnite calendar was not discovered at {LOCAL_CALENDAR_DIR}")


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def webdriver_request(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    timeout: int = 30,
) -> object:
    response = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = response.json()
    except ValueError as exc:
        raise SyncError(f"WebDriver returned non-JSON HTTP {response.status_code} for {url}") from exc
    value = body.get("value") if isinstance(body, dict) else None
    if response.status_code >= 400:
        detail = value.get("message") if isinstance(value, dict) else value
        raise SyncError(f"WebDriver HTTP {response.status_code} for {url}: {detail}")
    if isinstance(value, dict) and value.get("error"):
        raise SyncError(f"WebDriver error for {url}: {value.get('message') or value['error']}")
    return value


def fetch_official_schedule_days(*, timeout: int = 120) -> list[dict[str, object]]:
    if not GECKODRIVER_PATH.exists():
        raise SyncError(f"geckodriver is missing at {GECKODRIVER_PATH}")

    port = reserve_local_port()
    base_url = f"http://127.0.0.1:{port}"
    session_id: str | None = None
    with tempfile.NamedTemporaryFile("w+", prefix="fortnite-calendar-geckodriver-", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(GECKODRIVER_PATH), "--port", str(port)],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "MOZ_HEADLESS": "1"},
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    status = webdriver_request("GET", f"{base_url}/status", timeout=2)
                    if isinstance(status, dict) and status.get("ready"):
                        break
                except (requests.RequestException, SyncError):
                    time.sleep(0.25)
            else:
                raise SyncError("geckodriver did not become ready within 20 seconds")

            if proc.poll() is not None:
                log.flush()
                log.seek(0)
                raise SyncError(f"geckodriver exited during startup: {log.read()[-2000:].strip()}")

            session = webdriver_request(
                "POST",
                f"{base_url}/session",
                payload={
                    "capabilities": {
                        "alwaysMatch": {
                            "browserName": "firefox",
                            "acceptInsecureCerts": True,
                            "pageLoadStrategy": "normal",
                            "moz:firefoxOptions": {"args": ["-headless"]},
                        }
                    }
                },
                timeout=30,
            )
            if not isinstance(session, dict) or not session.get("sessionId"):
                raise SyncError("WebDriver did not return a Firefox session ID")
            session_id = str(session["sessionId"])
            session_url = f"{base_url}/session/{session_id}"
            webdriver_request(
                "POST",
                f"{session_url}/url",
                payload={"url": SOURCE_URL},
                timeout=timeout,
            )

            script = f"""
const route = window.__reactRouterDataRouter?.state?.loaderData?.[{json.dumps(SCHEDULE_ROUTE_ID)}];
if (!route || !Array.isArray(route.scheduleDays)) return null;
return {{ activeRegion: route.activeRegion, scheduleDays: route.scheduleDays }};
"""
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                value = webdriver_request(
                    "POST",
                    f"{session_url}/execute/sync",
                    payload={"script": script, "args": []},
                    timeout=20,
                )
                if isinstance(value, dict) and isinstance(value.get("scheduleDays"), list):
                    if value.get("activeRegion") != REGION:
                        raise SyncError(
                            f"official schedule loaded region {value.get('activeRegion')!r}, expected {REGION}"
                        )
                    return value["scheduleDays"]
                time.sleep(1)
            raise SyncError("official Fortnite schedule loader data did not appear within 45 seconds")
        except requests.RequestException as exc:
            raise SyncError(f"WebDriver request failed: {exc}") from exc
        finally:
            if session_id:
                try:
                    webdriver_request("DELETE", f"{base_url}/session/{session_id}", timeout=15)
                except Exception:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


def load_eligibility() -> dict[str, object]:
    if not ELIGIBILITY_PATH.exists():
        return {
            "currentFncsDivision": None,
            "excludeMobile": True,
            "notes": "Missing eligibility file; FNCS divisional cups are excluded until eligibility is explicit.",
        }
    data = json.loads(ELIGIBILITY_PATH.read_text(encoding="utf-8"))
    division = data.get("currentFncsDivision")
    if division is not None:
        try:
            division = int(division)
        except (TypeError, ValueError) as exc:
            raise SyncError(f"invalid currentFncsDivision in {ELIGIBILITY_PATH}: {division!r}") from exc
        if division < 1 or division > 5:
            raise SyncError(f"currentFncsDivision must be 1-5 or null in {ELIGIBILITY_PATH}")
        data["currentFncsDivision"] = division
    data.setdefault("excludeMobile", True)
    data.setdefault("excludeZeroBuild", True)
    data.setdefault("eligibleFncsRoundIds", [])
    data.setdefault("eligibleFncsEventGroups", [])
    for field in ("eligibleFncsRoundIds", "eligibleFncsEventGroups"):
        if not isinstance(data[field], list) or not all(isinstance(item, str) for item in data[field]):
            raise SyncError(f"{field} must be a list of strings in {ELIGIBILITY_PATH}")
    return data


def event_filter_text(
    title: str,
    round_id: str,
    event_group_id: str,
    mode: str,
    event_format: str,
) -> str:
    return " ".join([title, round_id, event_group_id, mode, event_format])


def fncs_divisions(text: str) -> set[int]:
    divisions: set[int] = set()
    for pattern in FNCS_DIVISION_PATTERNS:
        divisions.update(int(match.group(1)) for match in pattern.finditer(text))
    return divisions


def classify_event(
    title: str,
    round_id: str,
    event_group_id: str,
    mode: str,
    event_format: str,
    eligibility: dict[str, object],
) -> tuple[bool, str]:
    filter_text = event_filter_text(title, round_id, event_group_id, mode, event_format)
    if eligibility.get("excludeMobile", True) and MOBILE_PATTERN.search(filter_text):
        return False, "excluded Mobile event"
    if eligibility.get("excludeZeroBuild", True) and ZERO_BUILD_PATTERN.search(filter_text):
        return False, "excluded Zero Build event"

    divisions = fncs_divisions(filter_text)
    if len(divisions) > 1:
        return False, f"conflicting FNCS division identifiers: {sorted(divisions)}"
    if divisions:
        event_division = next(iter(divisions))
        current_division = eligibility.get("currentFncsDivision")
        if event_division == current_division:
            return True, f"matches tracked FNCS Division {current_division}"
        return False, f"requires FNCS Division {event_division}; tracked division is {current_division}"

    if FNCS_PATTERN.search(filter_text):
        allowed_rounds = set(eligibility.get("eligibleFncsRoundIds") or [])
        allowed_groups = set(eligibility.get("eligibleFncsEventGroups") or [])
        if round_id in allowed_rounds:
            return True, "explicitly allowed FNCS round in eligibility tracker"
        if event_group_id in allowed_groups:
            return True, "explicitly allowed FNCS event group in eligibility tracker"
        return False, "non-divisional FNCS stage requires explicitly tracked qualification"

    return True, "not excluded by current tournament eligibility"


def is_relevant_event(
    title: str,
    round_id: str,
    event_group_id: str,
    mode: str,
    event_format: str,
    eligibility: dict[str, object],
) -> bool:
    accepted, _ = classify_event(title, round_id, event_group_id, mode, event_format, eligibility)
    return accepted


def event_labels(event: TournamentEvent) -> list[str]:
    filter_text = event_filter_text(event.title, event.round_id, "", event.mode, event.format)
    labels: list[str] = []
    if MOBILE_PATTERN.search(filter_text):
        labels.append("Mobile")
    if ZERO_BUILD_PATTERN.search(filter_text):
        labels.append("ZB")
    return labels


def display_title(event: TournamentEvent) -> str:
    labels = event_labels(event)
    label_text = f" [{' / '.join(labels)}]" if labels else ""
    return f"Fortnite: {event.title}{label_text} ({REGION})"


def parse_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SyncError(f"official schedule event is missing {field_name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyncError(f"official schedule event has invalid {field_name}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SyncError(f"official schedule event has timezone-free {field_name}: {value!r}")
    return parsed.astimezone(timezone.utc)


def infer_event_mode_and_format(title: str, round_id: str) -> tuple[str, str]:
    text = f"{title} {round_id}"
    if ZERO_BUILD_PATTERN.search(text):
        mode = "Zero Build"
    elif re.search(r"\bReload\b", text, re.IGNORECASE):
        mode = "Reload"
    else:
        mode = "Battle Royale"

    event_format = "Unspecified"
    for pattern, label in (
        (r"\bSolos?\b", "Solos"),
        (r"\bDuos?\b", "Duos"),
        (r"\bTrios?\b", "Trios"),
        (r"\bSquads?\b", "Squads"),
    ):
        if re.search(pattern, text, re.IGNORECASE):
            event_format = label
            break
    return mode, event_format


def parse_official_event_decisions(
    schedule_days: list[dict[str, object]],
    now_utc: datetime,
    eligibility: dict[str, object],
) -> list[EventDecision]:
    decisions: list[EventDecision] = []
    source_future_nac = 0
    for day in schedule_days:
        if not isinstance(day, dict) or not isinstance(day.get("events"), list):
            raise SyncError("official schedule loader returned an unexpected scheduleDays shape")
        for raw_event in day["events"]:
            if not isinstance(raw_event, dict):
                raise SyncError("official schedule loader returned a non-object event")
            event_window = raw_event.get("eventWindow")
            if not isinstance(event_window, dict):
                continue
            round_id = event_window.get("eventWindowId") or raw_event.get("eventWindowId")
            if not isinstance(round_id, str) or not round_id.endswith(f"_{REGION}"):
                continue
            if event_window.get("isTBD"):
                continue
            start_utc = parse_utc_datetime(event_window.get("beginTime"), "beginTime")
            end_utc = parse_utc_datetime(event_window.get("endTime"), "endTime")
            if end_utc <= start_utc:
                raise SyncError(f"official schedule event {round_id} ends before it begins")
            if end_utc < now_utc - timedelta(hours=2):
                continue
            source_future_nac += 1

            title = raw_event.get("tournamentName")
            event_group = raw_event.get("eventGroup")
            if not isinstance(title, str) or not title.strip():
                raise SyncError(f"official schedule event {round_id} is missing tournamentName")
            if not isinstance(event_group, dict) or not isinstance(event_group.get("id"), str):
                raise SyncError(f"official schedule event {round_id} is missing eventGroup.id")
            title = title.strip()
            event_group_id = str(event_group["id"])
            mode, event_format = infer_event_mode_and_format(title, round_id)
            event_url = (
                f"https://www.fortnite.com/competitive/events/{event_group_id}?"
                f"{urlencode({'round': round_id})}"
            )
            accepted, reason = classify_event(
                title,
                round_id,
                event_group_id,
                mode,
                event_format,
                eligibility,
            )
            decisions.append(
                EventDecision(
                    accepted=accepted,
                    reason=reason,
                    title=title,
                    url=event_url,
                    round_id=round_id,
                    event_group_id=event_group_id,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    mode=mode,
                    format=event_format,
                )
            )

    if not source_future_nac:
        raise SyncError("official schedule loader returned no current or future NAC events")
    deduped = {decision.round_id: decision for decision in decisions}
    return sorted(deduped.values(), key=lambda decision: (decision.start_utc, decision.title, decision.round_id))


def decision_to_event(decision: EventDecision) -> TournamentEvent:
    return TournamentEvent(
        title=decision.title,
        url=decision.url,
        round_id=decision.round_id,
        start_utc=decision.start_utc,
        end_utc=decision.end_utc,
        mode=decision.mode,
        format=decision.format,
    )


def parse_official_events(
    schedule_days: list[dict[str, object]],
    now_utc: datetime,
    eligibility: dict[str, object],
) -> list[TournamentEvent]:
    return [
        decision_to_event(decision)
        for decision in parse_official_event_decisions(schedule_days, now_utc, eligibility)
        if decision.accepted
    ]


def self_test() -> dict[str, object]:
    def fixture_event(title: str, round_id: str, begin: str, end: str, group_id: str) -> dict[str, object]:
        return {
            "tournamentName": title,
            "eventWindowId": round_id,
            "eventGroup": {"id": group_id, "type": "webId"},
            "eventWindow": {
                "eventWindowId": round_id,
                "beginTime": begin,
                "endTime": end,
                "isTBD": False,
            },
        }

    eligibility = {
        "currentFncsDivision": 5,
        "excludeMobile": True,
        "excludeZeroBuild": True,
    }
    # Test-only fixture: this never feeds the live calendar sync.
    test_schedule_days = [{
        "date": "2026-07-25",
        "events": [
            fixture_event(
                "Solo Victory Cup",
                "S41_SoloVictoryCup_Round1_Day4_NAC",
                "2026-07-25T19:00:00Z",
                "2026-07-25T22:00:00Z",
                "S41_SoloVictoryCup",
            ),
            fixture_event(
                "FNCS Division 5",
                "S41_FNCSDivisionalCup_Division5_Event7_NAC",
                "2026-07-26T23:00:00Z",
                "2026-07-27T02:00:00Z",
                "S41_FNCSDivisionalCup_Division5",
            ),
            fixture_event(
                "FNCS Division 4",
                "S41_FNCSDivisionalCup_Division4_Event7_NAC",
                "2026-07-26T23:00:00Z",
                "2026-07-27T02:00:00Z",
                "S41_FNCSDivisionalCup_Division4",
            ),
            fixture_event(
                "Mobile Series",
                "S41_MobileSeriesOpen_Event1_NAC",
                "2026-07-26T23:00:00Z",
                "2026-07-27T02:00:00Z",
                "S41_MobileSeriesOpen",
            ),
            fixture_event(
                "Console Solo Victory Cup (ZB)",
                "S41_ConsoleVCC_SolosZB_Event1_NAC",
                "2026-07-26T23:00:00Z",
                "2026-07-27T02:00:00Z",
                "S41_ConsoleVCC_SolosZB",
            ),
            fixture_event(
                "Fortnite Championship Series",
                "S41_FNCSMajor2_PlayInStage_Day1_NAC",
                "2026-07-27T23:00:00Z",
                "2026-07-28T02:00:00Z",
                "S41_FNCSMajor2_PlayInStage",
            ),
            fixture_event(
                "Fortnite Championship Series",
                "S41_FNCSMajor2_HeatsStage_Heat2_NAC",
                "2026-07-28T23:00:00Z",
                "2026-07-29T02:00:00Z",
                "S41_FNCSMajor2_HeatsStage",
            ),
            fixture_event(
                "Fortnite Championship Series",
                "S41_FNCSMajor2_LastChanceQualifier_NAC",
                "2026-07-29T23:00:00Z",
                "2026-07-30T02:00:00Z",
                "S41_FNCSMajor2_LCQ",
            ),
            fixture_event(
                "Fortnite Championship Series",
                "S41_FNCSMajor2_Final_Day1_NAC",
                "2026-07-30T23:00:00Z",
                "2026-07-31T02:00:00Z",
                "S41_FNCSMajor2_Final",
            ),
        ],
    }]
    decisions = parse_official_event_decisions(
        test_schedule_days,
        datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        eligibility,
    )
    events = parse_official_events(
        test_schedule_days,
        datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        eligibility,
    )
    assert [event.title for event in events] == ["Solo Victory Cup", "FNCS Division 5"]
    assert events[0].start_utc.isoformat() == "2026-07-25T19:00:00+00:00"
    assert events[0].end_utc.isoformat() == "2026-07-25T22:00:00+00:00"
    assert events[0].mode == "Battle Royale"
    assert events[0].format == "Solos"
    assert events[0].url.endswith("?round=S41_SoloVictoryCup_Round1_Day4_NAC")
    by_round = {decision.round_id: decision for decision in decisions}
    assert by_round["S41_FNCSDivisionalCup_Division5_Event7_NAC"].accepted
    assert not by_round["S41_FNCSDivisionalCup_Division4_Event7_NAC"].accepted
    for round_id in (
        "S41_FNCSMajor2_PlayInStage_Day1_NAC",
        "S41_FNCSMajor2_HeatsStage_Heat2_NAC",
        "S41_FNCSMajor2_LastChanceQualifier_NAC",
        "S41_FNCSMajor2_Final_Day1_NAC",
    ):
        assert not by_round[round_id].accepted
        assert "explicitly tracked qualification" in by_round[round_id].reason
    advanced = {**eligibility, "eligibleFncsRoundIds": ["S41_FNCSMajor2_HeatsStage_Heat2_NAC"]}
    allowed, reason = classify_event(
        "Fortnite Championship Series",
        "S41_FNCSMajor2_HeatsStage_Heat2_NAC",
        "S41_FNCSMajor2_HeatsStage",
        "Battle Royale",
        "Duos",
        advanced,
    )
    assert allowed and "explicitly allowed" in reason
    return {"status": "ok", "tests": 15, "eventCount": len(events), "decisionCount": len(decisions)}


def canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def build_candidate_plan(
    decisions: list[EventDecision],
    eligibility: dict[str, object],
    generated_at: datetime,
) -> dict[str, object]:
    decision_rows = [decision.to_json() for decision in decisions]
    body: dict[str, object] = {
        "schemaVersion": 1,
        "generatedAt": generated_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "source": SOURCE_URL,
        "region": REGION,
        "eligibilityPath": str(ELIGIBILITY_PATH),
        "eligibility": eligibility,
        "summary": {
            "candidateCount": len(decision_rows),
            "acceptedCount": sum(1 for row in decision_rows if row["accepted"]),
            "rejectedCount": sum(1 for row in decision_rows if not row["accepted"]),
        },
        "decisions": decision_rows,
    }
    return {**body, "digest": canonical_digest(body)}


def collect_candidate_plan(*, write: bool) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc)
    eligibility = load_eligibility()
    decisions = parse_official_event_decisions(
        fetch_official_schedule_days(),
        generated_at,
        eligibility,
    )
    plan = build_candidate_plan(decisions, eligibility, generated_at)
    if write:
        write_json_atomic(CANDIDATE_PLAN_PATH, plan)
    return plan


def load_reviewed_plan(expected_digest: str) -> dict[str, object]:
    if not CANDIDATE_PLAN_PATH.exists():
        raise SyncError(f"candidate plan is missing at {CANDIDATE_PLAN_PATH}; run --collect first")
    plan = json.loads(CANDIDATE_PLAN_PATH.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise SyncError("candidate plan is not a JSON object")
    actual_digest = str(plan.get("digest") or "")
    body = {key: value for key, value in plan.items() if key != "digest"}
    computed_digest = canonical_digest(body)
    if not expected_digest or expected_digest != actual_digest or actual_digest != computed_digest:
        raise SyncError("candidate plan digest does not match the reviewed digest")
    generated_raw = plan.get("generatedAt")
    if not isinstance(generated_raw, str):
        raise SyncError("candidate plan is missing generatedAt")
    generated_at = parse_utc_datetime(generated_raw, "generatedAt")
    age = datetime.now(timezone.utc) - generated_at
    if age < timedelta(seconds=-30) or age > PLAN_MAX_AGE:
        raise SyncError(f"candidate plan is stale or future-dated: age={age}")
    current_eligibility = load_eligibility()
    if plan.get("eligibility") != current_eligibility:
        raise SyncError("eligibility changed after collection; collect and review a new plan")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(row, dict) for row in decisions):
        raise SyncError("candidate plan decisions are malformed")
    return plan


def events_from_plan(plan: dict[str, object]) -> list[TournamentEvent]:
    events: list[TournamentEvent] = []
    for row in plan.get("decisions") or []:
        if not row.get("accepted"):
            continue
        events.append(
            TournamentEvent(
                title=str(row["title"]),
                url=str(row["url"]),
                round_id=str(row["roundId"]),
                start_utc=parse_utc_datetime(row["startUtc"], "startUtc"),
                end_utc=parse_utc_datetime(row["endUtc"], "endUtc"),
                mode=str(row["mode"]),
                format=str(row["format"]),
            )
        )
    return sorted(events, key=lambda event: (event.start_utc, event.title, event.round_id))


def index_existing_events() -> dict[str, Path]:
    existing: dict[str, Path] = {}
    if not LOCAL_CALENDAR_DIR.exists():
        return existing
    for path in LOCAL_CALENDAR_DIR.glob("*.ics"):
        try:
            calendar = Calendar.from_ical(path.read_bytes())
        except Exception:
            continue
        for component in calendar.walk("VEVENT"):
            uid = str(component.get("UID", "")).strip()
            if uid:
                existing[uid] = path
    return existing


def verify_local_calendar(expected_events: list[TournamentEvent]) -> dict[str, object]:
    expected_rounds = {event.round_id for event in expected_events}
    actual_rounds: list[str] = []
    parse_errors: list[str] = []
    for path in sorted(LOCAL_CALENDAR_DIR.glob("*.ics")):
        try:
            calendar = Calendar.from_ical(path.read_bytes())
        except Exception as exc:
            parse_errors.append(f"{path.name}: {exc}")
            continue
        for component in calendar.walk("VEVENT"):
            if str(component.get("X-OPENCLAW-MANAGED", "")).strip() != "fortnite-tournament-calendar-sync":
                continue
            round_id = str(component.get("X-OPENCLAW-SOURCE-ROUND", "")).strip()
            if not round_id:
                parse_errors.append(f"{path.name}: managed event missing source round")
                continue
            actual_rounds.append(round_id)

    actual_set = set(actual_rounds)
    duplicates = sorted(round_id for round_id in actual_set if actual_rounds.count(round_id) > 1)
    missing = sorted(expected_rounds - actual_set)
    unexpected = sorted(actual_set - expected_rounds)
    return {
        "ok": not parse_errors and not duplicates and not missing and not unexpected,
        "expectedCount": len(expected_rounds),
        "actualCount": len(actual_rounds),
        "missingRoundIds": missing,
        "unexpectedRoundIds": unexpected,
        "duplicateRoundIds": duplicates,
        "parseErrors": parse_errors,
    }


def preserved_alarms(path: Path | None) -> list[object]:
    if not path or not path.exists():
        return []
    try:
        calendar = Calendar.from_ical(path.read_bytes())
    except Exception:
        return []
    for component in calendar.walk("VEVENT"):
        alarms = [copy.deepcopy(child) for child in component.subcomponents if child.name == "VALARM"]
        if alarms:
            return alarms
    return []


def build_calendar(event: TournamentEvent, alarms: list[object]) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")

    vevent = Event()
    vevent.add("uid", event.uid)
    vevent.add("dtstamp", event.start_utc)
    vevent.add("dtstart", event.start_utc)
    vevent.add("dtend", event.end_utc)
    labels = event_labels(event)
    vevent.add("summary", display_title(event))
    vevent.add("location", "Fortnite - NA Central")
    vevent.add("status", "CONFIRMED")
    vevent.add("transp", "OPAQUE")
    vevent.add("categories", ["Fortnite", "Tournament", REGION, *labels])
    vevent.add("url", event.url)
    vevent.add("description", "\n".join([
        "Official Fortnite Competitive event.",
        f"Region: {REGION}",
        f"Mode: {event.mode}",
        f"Format: {event.format}",
        f"Labels: {', '.join(labels) if labels else 'None'}",
        f"Round: {event.round_id}",
        f"Source: {event.url}",
    ]))
    vevent["X-OPENCLAW-MANAGED"] = "fortnite-tournament-calendar-sync"
    vevent["X-OPENCLAW-SOURCE-ROUND"] = event.round_id
    for alarm in alarms:
        vevent.add_component(alarm)
    calendar.add_component(vevent)
    return calendar.to_ical()


def event_path(uid: str, existing: dict[str, Path]) -> Path:
    if uid in existing:
        return existing[uid]
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "-", uid)
    return LOCAL_CALENDAR_DIR / f"{safe}.ics"


def write_if_changed(path: Path, content: bytes) -> str:
    if path.exists() and path.read_bytes() == content:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
    return "updated" if path.exists() else "added"


def sync_events(events: list[TournamentEvent], *, dry_run: bool) -> dict[str, int]:
    existing = index_existing_events()
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    for event in events:
        path = event_path(event.uid, existing)
        had_existing = path.exists()
        content = build_calendar(event, preserved_alarms(path))
        if dry_run:
            status = "unchanged" if had_existing and path.read_bytes() == content else ("updated" if had_existing else "added")
        else:
            if had_existing and path.read_bytes() != content:
                status = "updated"
            elif not had_existing:
                status = "added"
            else:
                status = "unchanged"
            if status != "unchanged":
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                os.replace(tmp_path, path)
        counts[status] += 1

    # Remove .ics files for events no longer in the source (expired or excluded by filter).
    current_uids = {event.uid for event in events}
    counts["removed"] = 0
    if not dry_run:
        for uid, path in existing.items():
            if uid not in current_uids:
                try:
                    path.unlink()
                    counts["removed"] += 1
                except OSError:
                    pass
    return counts


def write_state(
    events: list[TournamentEvent],
    counts: dict[str, int],
    source_timezone: str,
    eligibility: dict[str, object],
    reviewed_plan_digest: str,
    verification: dict[str, object],
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "calendar": CALENDAR_DISPLAY_NAME,
        "calendarSlug": CALENDAR_SLUG,
        "source": SOURCE_URL,
        "sourceTimezone": source_timezone,
        "sourceTransport": "Epic schedule React Router loader via headless Firefox",
        "reviewedPlanDigest": reviewed_plan_digest,
        "verification": verification,
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "eventCount": len(events),
        "counts": counts,
        "filter": {
            "region": REGION,
            "eligibilityPath": str(ELIGIBILITY_PATH),
            "currentFncsDivision": eligibility.get("currentFncsDivision"),
            "excluded": [
                "Mobile cups when excludeMobile is true",
                "Zero Build/ZB cups when excludeZeroBuild is true",
                "FNCS divisions other than currentFncsDivision",
                "FNCS non-divisional events without an explicitly tracked qualifying round or event group",
            ],
            "rationale": eligibility.get("rationale"),
        },
        "events": [
            {
                "uid": event.uid,
                "title": event.title,
                "displayTitle": display_title(event),
                "labels": event_labels(event),
                "roundId": event.round_id,
                "startUtc": event.start_utc.isoformat(),
                "endUtc": event.end_utc.isoformat(),
                "source": event.url,
            }
            for event in events
        ],
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect and apply AI-reviewed official Fortnite NAC tournament calendar plans."
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--collect",
        action="store_true",
        help="Fetch all candidates, record explicit eligibility decisions, and write a hashed review plan.",
    )
    actions.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print the complete candidate plan without saving or changing the calendar.",
    )
    actions.add_argument(
        "--apply-reviewed",
        metavar="DIGEST",
        help="Apply the exact recent candidate plan matching the digest supplied by the AI reviewer.",
    )
    actions.add_argument("--self-test", action="store_true", help="Run offline parser and filtering regression tests.")
    args = parser.parse_args()

    try:
        if args.self_test:
            print(json.dumps(self_test(), sort_keys=True))
            return 0
        if args.collect or args.dry_run:
            plan = collect_candidate_plan(write=bool(args.collect))
            print(json.dumps({
                **plan,
                "planPath": str(CANDIDATE_PLAN_PATH) if args.collect else None,
                "status": "ok",
                "dryRun": bool(args.dry_run),
            }, indent=2, sort_keys=True))
            return 0

        plan = load_reviewed_plan(str(args.apply_reviewed))
        eligibility = load_eligibility()
        events = events_from_plan(plan)
        source_timezone = "UTC"
        ensure_remote_calendar()
        vdirsyncer_sync()
        counts = sync_events(events, dry_run=False)
        vdirsyncer_sync()
        verification = verify_local_calendar(events)
        if not verification["ok"]:
            raise SyncError(f"post-sync calendar verification failed: {json.dumps(verification, sort_keys=True)}")
        write_state(
            events,
            counts,
            source_timezone,
            eligibility,
            str(plan["digest"]),
            verification,
            dry_run=False,
        )
        print(json.dumps({
            "status": "ok",
            "dryRun": False,
            "reviewedPlanDigest": plan["digest"],
            "calendar": CALENDAR_DISPLAY_NAME,
            "calendarSlug": CALENDAR_SLUG,
            "source": SOURCE_URL,
            "sourceTimezone": source_timezone,
            "eventCount": len(events),
            "counts": counts,
            "verification": verification,
            "firstEvent": events[0].start_utc.isoformat() if events else None,
            "lastEvent": events[-1].start_utc.isoformat() if events else None,
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
