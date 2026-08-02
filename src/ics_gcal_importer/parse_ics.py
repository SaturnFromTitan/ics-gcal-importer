import zoneinfo
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any, cast

from icalendar import Calendar, Event, vRecur

_FREQ_KEYWORDS = frozenset(
    {"SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
)


def load_calendar(text: str) -> Calendar:
    """Parse ICS text into a Calendar, repairing common non-standard exports.

    Some calendar apps (notably older Apple iCal) emit RFC 5545 violations that
    strict parsers reject outright. We repair the known ones first so these
    files can still be imported.
    """
    return cast(Calendar, Calendar.from_ical(_repair_ics_text(text)))


def _repair_ics_text(text: str) -> str:
    return "\n".join(_repair_ics_line(line) for line in text.splitlines())


def _repair_ics_line(line: str) -> str:
    # Older Apple iCal writes VTIMEZONE RRULEs without the required FREQ= key,
    # e.g. "RRULE:YEARLY;BYMONTH=3;BYDAY=4SU", which dateutil cannot parse.
    if line.startswith("RRULE:"):
        parts = line[len("RRULE:") :].split(";")
        if parts and "=" not in parts[0] and parts[0].upper() in _FREQ_KEYWORDS:
            parts[0] = "FREQ=" + parts[0].upper()
            return "RRULE:" + ";".join(parts)
        return line
    # Older Apple iCal also drops the mandatory sign on positive UTC offsets,
    # e.g. "TZOFFSETFROM:0100" instead of "TZOFFSETFROM:+0100" (without the
    # sign, dateutil misreads "0200" as +20:00). Negative offsets keep their
    # "-", so an already-signed value is left untouched and we only ever assume
    # "+" for the unsigned (positive) case.
    for key in ("TZOFFSETFROM:", "TZOFFSETTO:"):
        if not line.startswith(key):
            continue

        value = line[len(key) :]
        if value and value[0] not in "+-":
            return f"{key}+{value}"
    return line


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
        if not tzid:
            continue
        try:
            timezones.add(zoneinfo.ZoneInfo(tzid))
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            # Non-IANA TZIDs (e.g. Apple's "US/CET") can't resolve here. Event
            # datetimes already carry the offsets parsed from the VTIMEZONE
            # component, so a global fallback zone isn't required.
            continue
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
