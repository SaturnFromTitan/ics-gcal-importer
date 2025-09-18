import logging
import pathlib

import typer
from icalendar import Calendar

from ics_gcal_importer import gcal_client, parse_ics

logger = logging.getLogger(__name__)

app = typer.Typer(help="Upload .ics events to Google Calendar")


@app.command()
def import_ics(
    ics_directory: pathlib.Path = typer.Argument(
        ..., help="Path to the directory containing .ics files"
    ),
    dry_run: bool = typer.Option(
        default=False, help="Print actions without calling the API"
    ),
) -> None:
    """Upload events from all found .ics files to the primary Google Calendar."""

    client = gcal_client.GCalClient()

    total_created = 0
    total_updated = 0

    for ics_path in ics_directory.iterdir():
        if not ics_path.is_file() or ics_path.suffix.lower() != ".ics":
            continue
        logger.info("Processing %s", ics_path)

        # parse
        cal = Calendar.from_ical(ics_path.read_text())
        for gcal_payload, uid in parse_ics.extract_gcal_payloads(cal):
            if existing := client.find_event_by_ics_uid(uid):
                client.update_event(existing["id"], gcal_payload, dry_run)
                total_updated += 1
            else:
                client.create_event(gcal_payload, dry_run)
                total_created += 1

    logger.info("Done. created=%d updated=%d", total_created, total_updated)
