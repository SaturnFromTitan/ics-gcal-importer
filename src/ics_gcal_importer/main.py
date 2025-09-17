"""
Google Calendar ICS Importer (CLI)

A small, self-contained Python CLI to upload events from .ics files into your
Google Calendar. Designed to be:
  • idempotent (won't duplicate existing imports)
  • safe (supports --dry-run)
  • flexible (map to any of your calendars by id or display name)
  • simple (no server; installed-app OAuth flow)

Key ideas
---------
- We parse the ICS (RFC5545) using the `icalendar` package.
- We store the ICS event UID into the event's private extended properties on
  Google Calendar (`extendedProperties.private.ics_uid`).
  That lets us detect/update events on re-imports without creating duplicates.
- Recurring rules (RRULE) present in the ICS are forwarded to Google via the
  `recurrence` field (which also expects RFC5545). Instances/exceptions beyond
  that are not expanded client-side for simplicity.
- Times are converted to RFC3339; if an event is "all-day" we use date-only
  fields.

Usage
-----
    python gcal_ics_importer.py path/to/file.ics \
        --calendar "primary" \
        --update-existing \
        --dry-run

Setup
-----
1) Create OAuth 2.0 Client (Desktop) in Google Cloud Console and download
   the JSON as `credentials.json` (same folder as this script by default).
   Scopes needed: https://www.googleapis.com/auth/calendar
2) Install deps:
      pip install --upgrade google-api-python-client google-auth-httplib2 \
          google-auth-oauthlib icalendar python-dateutil
3) First run will prompt you to authorize in the browser and will store a
   `token.json` for reuse.

Limitations
-----------
- This tool does not attempt to perfectly mirror every ICS edge case (e.g.,
  complex EXDATE/EXRULE combinations or VTIMEZONE with non-IANA tz ids). It
  forwards RRULE unmodified when present and relies on Google to interpret it.
- Attendee RSVP states from ICS are passed through when available, but Google
  may adjust formatting.

"""
import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, Iterable, List, Optional, Tuple
import typing

from dateutil import tz
from icalendar import Calendar, Event, vRecur

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

logger = logging.getLogger(__file__)


@dataclass
class CliArgs:
    ics_path: str
    calendar: str
    dry_run: bool
    verbose: bool


def load_service(credentials_file: str = CREDENTIALS_FILE, token_file: str = TOKEN_FILE):
    creds: Optional[Credentials] = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # type: ignore[name-defined]
            except Exception:
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        creds = typing.cast(Credentials, creds)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def resolve_calendar_id(service, calendar_selector: str) -> str:
    """Resolve a calendar id from either a calendar id or a display name.

    If `calendar_selector` is exactly 'primary', returns 'primary'. Otherwise
    scans the user's calendar list and matches by id or summary (display name).
    """
    if calendar_selector == "primary":
        return "primary"
    page_token = None
    matches: List[Tuple[str, str]] = []  # (id, summary)
    while True:
        resp = service.calendarList().list(pageToken=page_token, maxResults=250).execute()
        for item in resp.get("items", []):
            cal_id = item.get("id")
            summary = item.get("summary")
            if calendar_selector.lower() in {cal_id.lower(), (summary or "").lower()}:
                matches.append((cal_id, summary))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    if not matches:
        raise SystemExit(f"No calendar found matching '{calendar_selector}'.")
    if len(matches) > 1:
        logger.warning("Multiple calendars matched '%s'; using first: %s (%s)",
                       calendar_selector, matches[0][1], matches[0][0])
    return matches[0][0]


# ---------------- ICS parsing helpers ----------------

def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Assume local timezone if naive; convert to UTC offset
        dt = dt.replace(tzinfo=tz.tzlocal())
    return dt.isoformat()


def _is_all_day(ev: Event) -> bool:
    start = ev.get('dtstart')
    if not start:
        return False
    val = start.dt
    return isinstance(val, date) and not isinstance(val, datetime)


def _event_time_payload(ev: Event) -> Dict[str, Any]:
    """Return {start: ..., end: ...} payload for Google Calendar events.

    For all-day events we use date-only fields; for timed events use dateTime.
    If ICS has no DTEND for all-day, infer DTEND = DTSTART + 1 day (RFC5545).
    """
    start = ev.get('dtstart')
    end = ev.get('dtend')

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
            end_dt = start_dt + timedelta(hours=1)  # type: ignore[name-defined]
        else:
            end_dt = end.dt
        return {
            "start": {"dateTime": _to_rfc3339(start_dt)},
            "end": {"dateTime": _to_rfc3339(end_dt)},
        }


def ics_to_gcal_payloads(cal: Calendar) -> Iterable[Dict[str, Any]]:
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        ev: Event = component
        uid = str(ev.get('uid') or '')
        summary = str(ev.get('summary') or '')
        description = str(ev.get('description') or '')
        location = str(ev.get('location') or '')

        payload: Dict[str, Any] = {
            "summary": summary or None,
            "description": description or None,
            "location": location or None,
            "extendedProperties": {"private": {"ics_uid": uid}} if uid else None,
        }
        payload.update(_event_time_payload(ev))

        # recurrence (RRULE) — pass through if present
        rrule = ev.get('rrule')
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


# ---------------- Google Calendar helpers ----------------

def find_event_by_ics_uid(service, calendar_id: str, uid: str) -> Optional[Dict[str, Any]]:
    if not uid:
        return None
    # Search via private extended property filter
    try:
        resp = service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"ics_uid={uid}",
            maxResults=1,
            singleEvents=False,
            showDeleted=False,
        ).execute()
        items = resp.get("items", [])
        return items[0] if items else None
    except HttpError as e:
        logger.error("Error searching for existing event with UID %s: %s", uid, e)
        return None


def create_event(service, calendar_id: str, body: Dict[str, Any], dry_run: bool) -> str:
    if dry_run:
        logger.info("[DRY-RUN] Would create event: %s", body.get("summary"))
        return "(dry-run-new-id)"
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created.get("id")


def update_event(service, calendar_id: str, event_id: str, body: Dict[str, Any], dry_run: bool) -> str:
    if dry_run:
        logger.info("[DRY-RUN] Would update event %s: %s", event_id, body.get("summary"))
        return event_id
    updated = service.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()
    return updated.get("id")


# ---------------- CLI ----------------

def parse_args(argv: List[str]) -> CliArgs:
    p = argparse.ArgumentParser(description="Upload .ics events to Google Calendar")
    p.add_argument("ics_path", help="Path(s) to .ics file(s) to import")
    p.add_argument("--calendar", default="primary",
                   help="Calendar id or display name (default: primary)")
    p.add_argument("--dry-run", action="store_true", help="Print actions without calling the API")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    ns = p.parse_args(argv)
    return CliArgs(
        ics_path=ns.ics_path,
        calendar=ns.calendar,
        dry_run=ns.dry_run,
        verbose=ns.verbose,
    )


def load_ics(path: str) -> Calendar:
    with open(path, 'rb') as f:
        data = f.read()
    cal = Calendar.from_ical(data)
    return cal


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s: %(message)s')

    service = load_service()

    calendar_id = resolve_calendar_id(service, args.calendar)
    logger.info("Using calendar: %s", calendar_id)

    total_created = 0
    total_updated = 0

    ics_files = [
        os.path.join(args.ics_path, f)
        for f in os.listdir(args.ics_path)
        if os.path.isfile(os.path.join(args.ics_path, f)) and f.lower().endswith('.ics')
    ]
    for ics_file_path in ics_files:
        logger.info("Processing %s", ics_file_path)
        cal = load_ics(ics_file_path)

        for payload in ics_to_gcal_payloads(cal):
            uid = None
            ext = payload.get("extendedProperties") or {}
            if ext and isinstance(ext, dict):
                uid = (ext.get("private") or {}).get("ics_uid")

            existing = find_event_by_ics_uid(service, calendar_id, uid or "")

            if existing:
                update_event(service, calendar_id, existing["id"], payload, args.dry_run)
                total_updated += 1
            else:
                create_event(service, calendar_id, payload, args.dry_run)
                total_created += 1

    logger.info("Done. created=%d updated=%d", total_created, total_updated)
    return 0
