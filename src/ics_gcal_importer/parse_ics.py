import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from icalendar import Calendar, Event, vRecur

logger = logging.getLogger(__name__)


def extract_gcal_payloads(cal: Calendar) -> Iterable[tuple[dict[str, Any], str]]:
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

        yield payload, uid


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Assume local timezone if naive; convert to UTC offset
        local_tz = datetime.now().astimezone().tzinfo
        dt = dt.replace(tzinfo=local_tz)
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
