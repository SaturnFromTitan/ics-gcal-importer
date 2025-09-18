import logging
import pathlib
import typing
from typing import Any, ClassVar

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GCalClient:
    """Thin wrapper around Google Calendar API client tailored to the usecase of this CLI."""

    _SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/calendar"]
    _CALENDAR_ID: ClassVar[str] = "primary"
    # FIXME: credentials and tokens shouldn't be saved as clear text on disk. use keychain instead
    _TOKEN_FILE: ClassVar[pathlib.Path] = pathlib.Path("token.json")
    _CREDENTIALS_FILE: ClassVar[pathlib.Path] = pathlib.Path("credentials.json")

    def __init__(self) -> None:
        self.service = self._load_service()

    def _load_service(self) -> Any:
        creds: Credentials | None = None
        if self._TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                self._TOKEN_FILE, self._SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())  # type: ignore[no-untyped-call]
                except Exception:
                    creds = None
            if not creds:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._CREDENTIALS_FILE, self._SCOPES
                )
                creds = flow.run_local_server(port=0)
            creds = typing.cast(Credentials, creds)
            self._TOKEN_FILE.write_text(creds.to_json())  # type: ignore[no-untyped-call]
        return build("calendar", "v3", credentials=creds)

    # ---------------- Calendar helpers ----------------
    def find_event_by_ics_uid(self, uid: str) -> dict[str, Any] | None:
        if not uid:
            return None
        try:
            resp = (
                self.service.events()
                .list(
                    calendarId=self._CALENDAR_ID,
                    privateExtendedProperty=f"ics_uid={uid}",
                    maxResults=1,
                    singleEvents=False,
                    showDeleted=False,
                )
                .execute()
            )
            items = resp.get("items", [])
            return items[0] if items else None
        except HttpError:
            logger.exception("Error searching for existing event with UID %s", uid)
            return None

    def create_event(self, body: dict[str, Any], dry_run: bool) -> str:
        if dry_run:
            logger.info("[DRY-RUN] Would create event: %s", body.get("summary"))
            return "(dry-run-new-id)"
        created = (
            self.service.events()
            .insert(calendarId=self._CALENDAR_ID, body=body)
            .execute()
        )
        return created.get("id")

    def update_event(self, event_id: str, body: dict[str, Any], dry_run: bool) -> str:
        if dry_run:
            logger.info(
                "[DRY-RUN] Would update event %s: %s", event_id, body.get("summary")
            )
            return event_id
        updated = (
            self.service.events()
            .patch(calendarId=self._CALENDAR_ID, eventId=event_id, body=body)
            .execute()
        )
        return updated.get("id")
