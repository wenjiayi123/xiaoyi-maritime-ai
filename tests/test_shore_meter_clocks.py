from app.shore_meter_clocks import verify_clock_claims


def test_meter_clock_is_bound_to_departure_ship_and_source_timezone():
    r = {"schema":"gullmate.shore-call-review.v1","call":"SC_00283",
         "eta":"2025-03-01T14:00:00+00:00","etd":"2025-03-01T23:55:00+00:00"}
    for text in ("SC_00283 登记离泊到23:55", "到泊14:00、离泊北京时间07:55:00"):
        remaining, issues = verify_clock_claims(text,[r])
        assert not issues and ":" not in remaining
    for text in ("离泊14:00", "离泊23:54", "到港23:55", "离泊23:55:01", "离泊北京时间23:55"):
        assert verify_clock_claims(text,[r])[1]
    assert verify_clock_claims("设备功率23:55", [r]) == ("设备功率23:55", [])
    assert verify_clock_claims("SC_00001 离泊23:55", [r])[0].endswith("23:55")
