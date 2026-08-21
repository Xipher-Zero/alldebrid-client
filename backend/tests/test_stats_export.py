from datetime import date
import json

from fastapi.encoders import jsonable_encoder


def test_stats_export_payload_accepts_date_values():
    payload = {"daily_trend": [{"date": date(2026, 5, 12), "cnt": 1}]}
    encoded = jsonable_encoder(payload)
    json.dumps(encoded)
    assert encoded["daily_trend"][0]["date"] == "2026-05-12"
