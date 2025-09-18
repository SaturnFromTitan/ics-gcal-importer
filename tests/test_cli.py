import pathlib

from typer.testing import CliRunner

from ics_gcal_importer.cli import app

runner = CliRunner()

TEST_DATA_DIRECTORY = pathlib.Path(__file__).parent / "_data"

PAYLOAD1 = {
    "summary": "Berlin Hbf ➞ Halle(Saale)Hbf",
    "description": "dummy",
    "location": "Berlin Hbf",
    "extendedProperties": {
        "private": {"ics_uid": "00000000-0000-0000-0000-000000000000@bahn.de"}
    },
    "start": {"dateTime": "2025-09-13T09:00:00+02:00"},
    "end": {"dateTime": "2025-09-13T10:13:00+02:00"},
}
PAYLOAD2 = {
    "summary": "Halle(Saale)Hbf ➞ Berlin Hbf",
    "description": "dummy",
    "location": "Halle(Saale)Hbf",
    "extendedProperties": {
        "private": {"ics_uid": "00000000-0000-0000-0000-000000000001@bahn.de"}
    },
    "start": {"dateTime": "2025-09-14T15:06:00+02:00"},
    "end": {"dateTime": "2025-09-14T16:22:00+02:00"},
}


def test_bahn_2_events__created(mocker):
    mocked_gcal_client = mocker.MagicMock()
    mocked_gcal_client.find_event_by_ics_uid.return_value = None
    mocker.patch(
        "ics_gcal_importer.cli.gcal_client.GCalClient", return_value=mocked_gcal_client
    )

    path = TEST_DATA_DIRECTORY / "test_case_1"
    res = runner.invoke(app, [str(path)])
    assert res.exit_code == 0, f"command failed with output: {res.output}"

    assert mocked_gcal_client.create_event.call_args_list == [
        mocker.call(PAYLOAD1),
        mocker.call(PAYLOAD2),
    ]
    mocked_gcal_client.update_event.assert_not_called()


def test_bahn_2_events__updated(mocker):
    mocked_gcal_client = mocker.MagicMock()
    event_id1 = 123
    event_id2 = 321
    mocked_gcal_client.find_event_by_ics_uid.side_effect = [
        {"id": event_id1},
        {"id": event_id2},
    ]
    mocker.patch(
        "ics_gcal_importer.cli.gcal_client.GCalClient", return_value=mocked_gcal_client
    )

    path = TEST_DATA_DIRECTORY / "test_case_1"
    res = runner.invoke(app, [str(path)])
    assert res.exit_code == 0, f"command failed with output: {res.output}"

    mocked_gcal_client.create_event.assert_not_called()
    assert mocked_gcal_client.update_event.call_args_list == [
        mocker.call(event_id1, PAYLOAD1),
        mocker.call(event_id2, PAYLOAD2),
    ]
