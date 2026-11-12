import pytest
from app.cooperative_review import DeviceReview,inspect_day
from app.harness.required_energy import required_energy_issues
from app.harness.verification import numbers


@pytest.mark.parametrize("unit",["kWh","MWh","kW","MW","TEU"])
def test_numeric_evidence_supports_units_without_spaces(unit):
    assert numbers("实交3065.40"+unit+"。")==numbers("3065.40 "+unit)=={"3065.4"}
    assert numbers("实交3065.41"+unit)!=numbers("3065.40 "+unit)


def test_requested_readings_require_both_values_only_when_asked():
    d=inspect_day(DeviceReview(day="2024-03-20",baseline="fixed",demand="normal"))
    t={"goal":"请给出最低交付和事后物理上界"}
    assert len(required_energy_issues(t,"两项服务实际达标。",d))==2
    assert len(required_energy_issues(t,"最低交付4312.00kWh。",d))==1
    assert not required_energy_issues(t,"最低交付4312kWh，事后上界4296.575kWh。",d)
    assert not required_energy_issues({"goal":"能否同时保持充电与冷链？"},"两项达标。",d)
