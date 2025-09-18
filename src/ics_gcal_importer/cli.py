import pathlib

import rich
import typer
from icalendar import Calendar

from ics_gcal_importer import gcal_client, parse_ics

app = typer.Typer(help="Upload .ics events to Google Calendar")


@app.command()
def import_ics(
    ics_directory: pathlib.Path = typer.Argument(
        ..., help="Path to the directory containing .ics files"
    ),
) -> None:
    """Upload events from all found .ics files to the primary Google Calendar."""

    client = gcal_client.GCalClient()

    for ics_path in ics_directory.iterdir():
        if not ics_path.is_file() or ics_path.suffix.lower() != ".ics":
            continue
        rich.print(f"Processing {ics_path}")

        # parse
        cal = Calendar.from_ical(ics_path.read_text())

        # create in gcal
        num_created = 0
        num_updated = 0
        for gcal_payload, uid in parse_ics.extract_gcal_payloads(cal):
            if existing := client.find_event_by_ics_uid(uid):
                client.update_event(existing["id"], gcal_payload)
                num_updated += 1
            else:
                client.create_event(gcal_payload)
                num_created += 1

        rich.print(f"Done. created={num_created} updated={num_updated}")
