import zoneinfo
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from icalendar import Calendar, Event, vRecur


def extract_gcal_payloads(cal: Calendar) -> Iterable[tuple[dict[str, Any], str]]:
    # Extract timezone information from VTIMEZONE components
    ics_timezone = _extract_timezone(cal)

    for ev in cal.events:
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
        payload.update(_event_time_payload(ev, ics_timezone))

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


def _extract_timezone(cal: Calendar) -> zoneinfo.ZoneInfo | None:
    """Extract timezone information from VTIMEZONE components."""
    timezones = set()
    for component in cal.timezones:
        tzid = str(component.get("tzid", ""))
        if tzid:
            timezones.add(zoneinfo.ZoneInfo(tzid))
    if not timezones:
        return None
    if len(timezones) > 1:
        raise NotImplementedError("Multiple VTIMEZONE components aren't supported yet")
    return next(iter(timezones))


def _ensure_timezone(dt: datetime, ics_timezone: zoneinfo.ZoneInfo | None) -> datetime:
    if dt.tzinfo:
        return dt
    elif ics_timezone:
        return dt.replace(tzinfo=ics_timezone)
    else:
        # Fallback to local timezone if no VTIMEZONE info available
        local_tz = datetime.now().astimezone().tzinfo
        return dt.replace(tzinfo=local_tz)


def _is_all_day(ev: Event) -> bool:
    start = ev.get("dtstart")
    if not start:
        return False
    val = start.dt
    return isinstance(val, date) and not isinstance(val, datetime)


def _event_time_payload(
    ev: Event, ics_timezone: zoneinfo.ZoneInfo | None
) -> dict[str, Any]:
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
            "start": {"dateTime": _ensure_timezone(start_dt, ics_timezone).isoformat()},
            "end": {"dateTime": _ensure_timezone(end_dt, ics_timezone).isoformat()},
        }
