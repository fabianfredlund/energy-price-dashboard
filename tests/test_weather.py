"""Smoke test for src/weather.py's pure parsing helper."""

from datetime import datetime, timezone

from src.weather import _parse_payload


def test_parse_payload_converts_epoch_ms_and_casts_float():
    payload = {
        "value": [
            {"date": 1691000000000, "value": "14.0", "quality": "G"},
            {"date": 1691003600000, "value": "13.5", "quality": "G"},
        ]
    }

    df = _parse_payload(payload)

    assert len(df) == 2
    assert df["temperature_c"].dtype.kind == "f"
    assert df["temperature_c"].iloc[0] == 14.0
    assert str(df.index.tzinfo) == "Europe/Stockholm"
    assert df.index[0].tz_convert("UTC") == datetime.fromtimestamp(
        1691000000000 / 1000, tz=timezone.utc
    )


def test_parse_payload_handles_empty_value_list():
    df = _parse_payload({"value": []})
    assert len(df) == 0
    assert list(df.columns) == ["temperature_c", "quality"]
