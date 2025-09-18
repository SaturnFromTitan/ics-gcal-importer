import json
import logging
import textwrap
import typing
from typing import Any, ClassVar

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

KEYRING_SERVICE_NAME = "gcal-ics-importer"
KEYRING_USER_NAME = "oauth-token"


class GCalClient:
    """Thin wrapper around Google Calendar API client tailored to the usecase of this CLI."""

    _SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/calendar"]
    _CALENDAR_ID: ClassVar[str] = "primary"

    def __init__(self) -> None:
        self.service = self._load_service()

    def _load_service(self) -> Any:
        creds = None

        # 1) get credentials from keyring
        token_json = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_USER_NAME)
        if token_json:
            try:
                token_dict = json.loads(token_json)
                creds = Credentials.from_authorized_user_info(token_dict, self._SCOPES)  # type: ignore[no-untyped-call]
            except json.JSONDecodeError:
                creds = None

        # 2) Run OAuth flow
        if not creds or not creds.valid:
            # 2.1) credentials can be refreshed via refresh_token
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())  # type: ignore[no-untyped-call]
                except Exception:
                    creds = None

            # 2.2) credentials have to be acquired via the initial credentials
            if not creds:
                client_config_json = ""
                while not client_config_json:
                    client_config_json = input(
                        textwrap.dedent(
                            """
                            Please paste the content of the Google client config, i.e. the credentials file downloaded from the Google Cloud Console after creating your OAuth 2.0-Client-ID
                            (It's typically called `client_secret_<some_id>.apps.googleusercontent.com.json`)
                            """.strip("\n")
                        )
                    )
                client_config = json.loads(client_config_json)
                flow = InstalledAppFlow.from_client_config(client_config, self._SCOPES)
                creds = flow.run_local_server(port=0)

            # update credentials in keychain
            creds = typing.cast(Credentials, creds)
            keyring.set_password(
                KEYRING_SERVICE_NAME,
                KEYRING_USER_NAME,
                creds.to_json(),  # type: ignore[no-untyped-call]
            )

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

    def create_event(self, body: dict[str, Any]) -> str:
        created = (
            self.service.events()
            .insert(calendarId=self._CALENDAR_ID, body=body)
            .execute()
        )
        return created.get("id")

    def update_event(self, event_id: str, body: dict[str, Any]) -> str:
        updated = (
            self.service.events()
            .patch(calendarId=self._CALENDAR_ID, eventId=event_id, body=body)
            .execute()
        )
        return updated.get("id")
