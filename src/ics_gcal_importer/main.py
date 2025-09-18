import logging
import pathlib
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

import typer
from dateutil import tz
from icalendar import Calendar, Event, vRecur

from ics_gcal_importer.gcal_client import GCalClient

logger = logging.getLogger(__name__)

app = typer.Typer(help="Upload .ics events to Google Calendar")


# ---------------- CLI ----------------
@app.command()
def main(
    ics_path: pathlib.Path = typer.Argument(..., help="Path to .ics file(s) to import"),
    dry_run: bool = typer.Option(
        default=False, help="Print actions without calling the API"
    ),
) -> None:
    """Upload .ics events to Google Calendar."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    client = GCalClient()

    total_created = 0
    total_updated = 0

    ics_files = [
        f for f in ics_path.iterdir() if f.is_file() and f.suffix.lower() == ".ics"
    ]
    for ics_file_path in ics_files:
        logger.info("Processing %s", ics_file_path)
        cal = Calendar.from_ical(ics_file_path.read_text())

        for payload in ics_to_gcal_payloads(cal):
            uid = None
            ext = payload.get("extendedProperties") or {}
            if ext and isinstance(ext, dict):
                uid = (ext.get("private") or {}).get("ics_uid")

            existing = client.find_event_by_ics_uid(uid or "")

            if existing:
                client.update_event(existing["id"], payload, dry_run)
                total_updated += 1
            else:
                client.create_event(payload, dry_run)
                total_created += 1

    logger.info("Done. created=%d updated=%d", total_created, total_updated)


# ---------------- ICS parsing helpers ----------------
def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Assume local timezone if naive; convert to UTC offset
        dt = dt.replace(tzinfo=tz.tzlocal())
    return dt.isoformat()


def _is_all_day(ev: Event) -> bool:
    start = ev.get("dtstart")
    if not start:
        return False
    val = start.dt
    return isinstance(val, date) and not isinstance(val, datetime)


def _event_time_payload(ev: Event) -> dict[str, Any]:
    """Return {start: ..., end: ...} payload for Google Calendar events.

    For all-day events we use date-only fields; for timed events use dateTime.
    If ICS has no DTEND for all-day, infer DTEND = DTSTART + 1 day (RFC5545).
    """
    start = ev.get("dtstart")
    end = ev.get("dtend")

    if _is_all_day(ev):
        start_date: date = start.dt
        if end is None:
            # all-day and no DTEND => same-day event (one day)
            end_date = date.fromordinal(start_date.toordinal() + 1)
        else:
            end_date = end.dt
        return {
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
    else:
        start_dt: datetime = start.dt
        if end is None:
            # No DTEND; assume 1 hour duration
            end_dt = start_dt + timedelta(hours=1)
        else:
            end_dt = end.dt
        return {
            "start": {"dateTime": _to_rfc3339(start_dt)},
            "end": {"dateTime": _to_rfc3339(end_dt)},
        }


def ics_to_gcal_payloads(cal: Calendar) -> Iterable[dict[str, Any]]:
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        ev: Event = component
        uid = str(ev.get("uid") or "")
        summary = str(ev.get("summary") or "")
        description = str(ev.get("description") or "")
        location = str(ev.get("location") or "")

        payload: dict[str, Any] = {
            "summary": summary or None,
            "description": description or None,
            "location": location or None,
            "extendedProperties": {"private": {"ics_uid": uid}} if uid else None,
        }
        payload.update(_event_time_payload(ev))

        # recurrence (RRULE) — pass through if present
        rrule = ev.get("rrule")
        if isinstance(rrule, vRecur):
            # Convert to iCalendar RRULE line(s)
            parts = []
            for k, v in rrule.items():
                key = k.upper()
                if isinstance(v, (list, tuple)):
                    val = ",".join(str(x) for x in v)
                else:
                    val = str(v)
                parts.append(f"{key}={val}")
            if parts:
                payload["recurrence"] = ["RRULE:" + ";".join(parts)]

        yield payload
