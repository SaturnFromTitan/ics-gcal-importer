import pathlib

from icalendar import Calendar

from ics_gcal_importer import parse_ics

TEST_DATA_DIRECTORY = pathlib.Path(__file__).parent / "_data"
APPLE_ICS = TEST_DATA_DIRECTORY / "test_case_2" / "apple_support_appt.ics"


def test_repair_adds_missing_freq_key():
    line = "RRULE:YEARLY;BYMONTH=03;BYDAY=4SU"
    assert parse_ics._repair_ics_line(line) == "RRULE:FREQ=YEARLY;BYMONTH=03;BYDAY=4SU"


def test_repair_leaves_wellformed_rrule_untouched():
    line = "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=4SU"
    assert parse_ics._repair_ics_line(line) == line


def test_repair_adds_missing_offset_sign():
    assert parse_ics._repair_ics_line("TZOFFSETFROM:0100") == "TZOFFSETFROM:+0100"
    assert parse_ics._repair_ics_line("TZOFFSETTO:0200") == "TZOFFSETTO:+0200"


def test_repair_leaves_signed_offset_untouched():
    assert parse_ics._repair_ics_line("TZOFFSETFROM:+005328") == "TZOFFSETFROM:+005328"
    assert parse_ics._repair_ics_line("TZOFFSETTO:-0500") == "TZOFFSETTO:-0500"


def test_load_calendar_parses_malformed_apple_export():
    # Raw file would raise from Calendar.from_ical without repairs.
    cal = parse_ics.load_calendar(APPLE_ICS.read_text())
    assert isinstance(cal, Calendar)
    assert len(cal.events) == 1


def test_extract_timezone_tolerates_invalid_tzid():
    # "US/CET" is not a valid IANA zone; extraction must not raise.
    cal = parse_ics.load_calendar(APPLE_ICS.read_text())
    assert parse_ics._extract_timezone(cal) is None


def test_apple_event_payload():
    cal = parse_ics.load_calendar(APPLE_ICS.read_text())
    payloads = list(parse_ics.extract_gcal_payloads(cal))
    assert len(payloads) == 1
    payload, uid = payloads[0]
    assert uid == "EC9439B1-FF65-11D6-9973-003065F99D04"
    assert payload["summary"] == "Appointment with Apple Support"
    assert payload["location"] == "Telephone (4916097064381)"
    assert payload["description"] == "Agreements & Coverage Agreement Purchase"
    assert payload["start"] == {"dateTime": "2026-08-03T10:00:00+02:00"}
    assert payload["end"] == {"dateTime": "2026-08-03T10:15:00+02:00"}
