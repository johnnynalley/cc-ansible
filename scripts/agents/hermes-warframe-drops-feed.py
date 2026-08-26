#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import urllib.request

RSS_URL = "https://forums.warframe.com/forum/113-livestreams.xml"
ET_TZ = ZoneInfo("America/New_York")
CT_TZ = ZoneInfo("America/Chicago")
NOW = datetime.now(CT_TZ)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

STREAM_DURATIONS = {
    "Prime Time": timedelta(hours=2),
    "Emisión Tenno": timedelta(hours=1),
    "Devstream": timedelta(hours=2),
}


@dataclass
class Event:
    event_id: str
    title: str
    kind: str
    starts_at_ct: str
    ends_at_ct: str
    channel_url: str
    drop_summary: str
    source_title: str
    source_link: str
    notes: str



def clean_html(text: str) -> str:
    text = text or ""
    text = re.sub(r"<(?:br|/p|/li|/ul|/ol|/h\d)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\r", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()



def fetch_rss() -> str:
    req = urllib.request.Request(
        RSS_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")



def parse_month_day_year(text: str, fallback_year: int | None = None) -> tuple[int, int, int] | None:
    m = re.search(
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,)?\s*(?P<year>\d{4})?",
        text,
        re.I,
    )
    if not m:
        return None
    month = MONTHS[m.group("month").lower()]
    day = int(m.group("day"))
    year = int(m.group("year") or fallback_year or NOW.year)
    return year, month, day



def parse_time_component(time_text: str) -> tuple[int, int]:
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.m\.|p\.m\.|am|pm)", time_text, re.I)
    if not m:
        raise ValueError(f"Could not parse time from: {time_text!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridian = m.group(3).lower().replace(".", "")
    if meridian == "pm" and hour != 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    return hour, minute



def build_dt_ct(date_text: str, time_text: str, fallback_year: int | None = None) -> datetime:
    parsed = parse_month_day_year(date_text, fallback_year=fallback_year)
    if not parsed:
        raise ValueError(f"Could not parse date from: {date_text!r}")
    year, month, day = parsed
    hour, minute = parse_time_component(time_text)
    dt_et = datetime(year, month, day, hour, minute, tzinfo=ET_TZ)
    return dt_et.astimezone(CT_TZ)



def dedupe(events: list[Event]) -> list[Event]:
    seen = set()
    out = []
    for event in sorted(events, key=lambda e: e.starts_at_ct):
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        out.append(event)
    return out



def ascii_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def make_event_id(kind: str, title: str, start_dt: datetime) -> str:
    return (
        f"{start_dt.strftime('%Y%m%dT%H%M')}-"
        f"{ascii_slug(kind)}-{ascii_slug(title)}"
    )


def extract_shared_drop_summary(text: str) -> str | None:
    match = re.search(
        r"Twitch Drops?:\s*(?P<drops>.*?)(?:Claim Time:|Raid Drops:|Weekend Drops!|$)",
        text,
        re.I | re.S,
    )
    if not match:
        return None
    drops = []
    for line in match.group("drops").splitlines():
        value = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if value:
            drops.append(value)
    return "; ".join(drops) or None



def extract_prime_time(text: str, source_title: str, source_link: str, year: int) -> list[Event]:
    events: list[Event] = []
    m = re.search(
        r"Tune into\s+(?P<channel>twitch\.tv/warframe)\s+on\s+(?P<date>Thursday,\s+[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\s+for\s+(?P<title>Prime Time\s+#\d+).*?The action begins at\s+(?P<time>\d{1,2}(?::\d{2})?\s*p\.m\.\s*ET)",
        text,
        re.I,
    )
    if m:
        start = build_dt_ct(m.group("date") + f", {year}", m.group("time"), fallback_year=year)
        end = start + STREAM_DURATIONS["Prime Time"]
        drop_summary = "Weekly Prime Time Twitch Drop"
        shared_drop_summary = extract_shared_drop_summary(text)
        if shared_drop_summary:
            drop_summary = shared_drop_summary
        title = m.group("title").replace(" !", "!")
        events.append(
            Event(
                event_id=make_event_id("Prime Time", title, start),
                title=f"Warframe {title} (Drops)",
                kind="Prime Time",
                starts_at_ct=start.isoformat(),
                ends_at_ct=end.isoformat(),
                channel_url="https://twitch.tv/warframe",
                drop_summary=drop_summary,
                source_title=source_title,
                source_link=source_link,
                notes="Official weekly Prime Time stream with Twitch Drops.",
            )
        )
    return events



def extract_emision_tenno(text: str, source_title: str, source_link: str, year: int) -> list[Event]:
    events: list[Event] = []
    m = re.search(
        r"watch\s+Emisi[oó]n Tenno\s+on\s+(?P<date>[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\s+at\s+(?P<time>\d{1,2}(?::\d{2})?\s*p\.m\.\s*ET)\s+over at\s+(?P<channel>twitch\.tv/warframeinternational)",
        text,
        re.I,
    )
    if m:
        start = build_dt_ct(m.group("date") + f", {year}", m.group("time"), fallback_year=year)
        end = start + STREAM_DURATIONS["Emisión Tenno"]
        drop_summary = "Shared weekly Warframe Twitch Drop campaign"
        shared_drop_summary = extract_shared_drop_summary(text)
        if shared_drop_summary:
            drop_summary = shared_drop_summary
        events.append(
            Event(
                event_id=make_event_id("Emision Tenno", "Emision Tenno", start),
                title="Warframe Emisión Tenno (Drops)",
                kind="Emisión Tenno",
                starts_at_ct=start.isoformat(),
                ends_at_ct=end.isoformat(),
                channel_url="https://twitch.tv/warframeinternational",
                drop_summary=drop_summary,
                source_title=source_title,
                source_link=source_link,
                notes="Official Spanish-language Warframe stream sharing the weekly Twitch Drop campaign.",
            )
        )
    return events



def extract_raid_events(text: str, source_title: str, source_link: str, year: int) -> list[Event]:
    events: list[Event] = []

    emision_date = None
    emision_date_match = re.search(
        r"watch\s+Emisi[oó]n Tenno\s+on\s+(?P<date>[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)",
        text,
        re.I,
    )
    if emision_date_match:
        emision_date = emision_date_match.group("date")

    prime_date = None
    prime_date_match = re.search(
        r"on\s+Thursday,\s+(?P<date>[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\s+for\s+Prime Time",
        text,
        re.I,
    )
    if prime_date_match:
        prime_date = prime_date_match.group("date")

    patterns = [
        (
            "Emisión Tenno Raid",
            emision_date,
            r"Watch\s+(?P<creator>[A-Za-z0-9_]+)\s+for 30 minutes on Wednesday from\s+(?P<start>\d{1,2}(?::\d{2})?pm)\s+to\s+(?P<end>\d{1,2}(?::\d{2})?pm)\s+ET\s+to earn\s+(?P<drop>.*?)(?:\.|Prime Time Raid|Weekend Drops!|$)",
        ),
        (
            "Prime Time Raid",
            prime_date,
            r"Watch\s+(?P<creator>[A-Za-z0-9_]+)\s+for 30 minutes on Thursday from\s+(?P<start>\d{1,2}(?::\d{2})?pm)\s+to\s+(?P<end>\d{1,2}(?::\d{2})?pm)\s+ET\s+to earn\s+(?P<drop>.*?)(?:\.|Weekend Drops!|$)",
        ),
    ]
    for kind, date_text, pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m or not date_text:
            continue
        start = build_dt_ct(date_text + f", {year}", m.group("start"), fallback_year=year)
        end = build_dt_ct(date_text + f", {year}", m.group("end"), fallback_year=year)
        creator = m.group("creator")
        drop = m.group("drop").strip().rstrip(".")
        title = f"Warframe {kind} - {creator}"
        events.append(
            Event(
                event_id=make_event_id(kind, creator, start),
                title=title,
                kind=kind,
                starts_at_ct=start.isoformat(),
                ends_at_ct=end.isoformat(),
                channel_url=f"https://twitch.tv/{creator}",
                drop_summary=drop,
                source_title=source_title,
                source_link=source_link,
                notes="Official Warframe community raid drop.",
            )
        )
    return events



def extract_weekend_drops(text: str, source_title: str, source_link: str, year: int) -> list[Event]:
    events: list[Event] = []
    if "Weekend Drops!" not in text:
        return events
    after = text.split("Weekend Drops!", 1)[1]
    pattern = re.compile(
        r"(?P<creator>[A-Za-z0-9_]+(?:\s*\([^\n]+\))?)\s+"
        r"(?P<date>[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\s+from\s+"
        r"(?P<start>\d{1,2}(?::\d{2})?(?:a|p)m)\s+to\s+(?P<end>\d{1,2}(?::\d{2})?(?:a|p)m)\s+ET\s+"
        r"Channel:\s*twitch\.tv/(?P<channel>[A-Za-z0-9_]+)\s+"
        r"Drop:\s*(?P<drop>.*?)(?=\s+(?:[A-Za-z0-9_]+\s*\([^\n]+\)\s+[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?\s+from|Each week’s schedule|$))",
        re.I | re.S,
    )
    for m in pattern.finditer(after):
        creator_label = m.group("creator").strip()
        creator_slug = re.sub(r"\s*\(.*?\)", "", creator_label).strip()
        start = build_dt_ct(m.group("date") + f", {year}", m.group("start"), fallback_year=year)
        end = build_dt_ct(m.group("date") + f", {year}", m.group("end"), fallback_year=year)
        drop = m.group("drop").strip().rstrip(".")
        events.append(
            Event(
                event_id=make_event_id("Weekend Drop", creator_slug, start),
                title=f"Warframe Weekend Drop - {creator_label}",
                kind="Weekend Drop",
                starts_at_ct=start.isoformat(),
                ends_at_ct=end.isoformat(),
                channel_url=f"https://twitch.tv/{m.group('channel')}",
                drop_summary=drop,
                source_title=source_title,
                source_link=source_link,
                notes="Official Warframe weekend creator drop campaign.",
            )
        )
    return events



def extract_devstream(text: str, source_title: str, source_link: str, year: int) -> list[Event]:
    events: list[Event] = []
    if re.search(r"No Twitch Drop", text, re.I):
        return events
    if "Devstream" not in source_title and "Devstream" not in text:
        return events
    date_match = re.search(r"on\s+(?P<date>(?:[A-Za-z]+,\s+)?[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)(?:,)?\s+at\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:AM|PM|a\.m\.|p\.m\.))\s*ET", text, re.I)
    if not date_match:
        return events
    start = build_dt_ct(date_match.group("date") + ("" if str(year) in date_match.group("date") else f", {year}"), date_match.group("time"), fallback_year=year)
    end = start + STREAM_DURATIONS["Devstream"]
    drop_summary = "Twitch Drop available"
    dm = re.search(
        r"following\s+Twitch\s+Drops?:\s*(?P<drop>.*?)\s+per\s+30\s+minute\s+claim\s+time",
        text,
        re.I | re.S,
    )
    if dm:
        drop_summary = " ".join(dm.group("drop").split())
    title = source_title.replace("Coming Soon: ", "").strip()
    events.append(
        Event(
            event_id=make_event_id("Devstream", title, start),
            title=f"Warframe {title} (Drops)",
            kind="Devstream",
            starts_at_ct=start.isoformat(),
            ends_at_ct=end.isoformat(),
            channel_url="https://twitch.tv/warframe",
            drop_summary=drop_summary,
            source_title=source_title,
            source_link=source_link,
            notes="Official Warframe Devstream with Twitch Drops.",
        )
    )
    return events



def parse_events(xml_text: str) -> list[Event]:
    root = ET.fromstring(xml_text)
    all_events: list[Event] = []
    for item in root.find("channel").findall("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        text = clean_html(item.findtext("description") or "")
        year_match = re.search(r"(20\d{2})", title)
        year = int(year_match.group(1)) if year_match else NOW.year

        if "Community Stream Schedule" in title:
            all_events.extend(extract_prime_time(text, title, link, year))
            all_events.extend(extract_emision_tenno(text, title, link, year))
            all_events.extend(extract_raid_events(text, title, link, year))
            all_events.extend(extract_weekend_drops(text, title, link, year))
        if "Devstream" in title or "Devstream" in text:
            all_events.extend(extract_devstream(text, title, link, year))

    events = dedupe(all_events)
    future = []
    horizon = NOW + timedelta(days=30)
    for event in events:
        start = datetime.fromisoformat(event.starts_at_ct)
        if NOW - timedelta(hours=1) <= start <= horizon:
            future.append(event)
    return future



def main() -> int:
    try:
        xml_text = fetch_rss()
        events = parse_events(xml_text)
        print(json.dumps([asdict(e) for e in events], indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
