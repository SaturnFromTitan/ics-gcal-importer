# ics importer for google calendar

Often, services like bahn.de, booking, airbnb, etc. don't integrate with google calendar but only provide a download link to an `.ics` file.

This small utility here imports all `.ics` files from the local `Downloads` directory of my mac and imports them to my primary gcal calendar.

## Usage

```sh
uv run import-ics
```
