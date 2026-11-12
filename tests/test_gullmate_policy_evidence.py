import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import policy_release as release
from app.ais_evidence import observed_minute
from app.visual_evidence import search_figures


class Response(io.BytesIO):
    def geturl(self):
        return release.SOURCE


def test_wrong_release_is_rejected_before_inspecting_fields(monkeypatch):
    monkeypatch.setattr(release, "urlopen", lambda *a, **kw: Response(b'{"production_authority":false}'))
    with pytest.raises(release.ReleaseUnavailable, match="哈希"):
        release.compare(release.PolicySelection())


def test_specialists_disagree_on_one_window_without_sharing_private_observations(monkeypatch):
    # Reuse the published native fixture. It is local to this six-system distribution.
    source = Path(__file__).resolve().parents[2]/"carbon/frontend/public/gullmate-policy-release.json"
    raw = source.read_bytes()
    monkeypatch.setattr(release, "urlopen", lambda *a, **kw: Response(raw))
    pick = release.PolicySelection(window=0)
    roles = {k:release.review_role(k,pick) for k in release.ROLE_CHECKS}
    assert roles["energy"]["decision"] == roles["operations"]["decision"] == "pass"
    assert roles["safety"]["decision"] == "veto"
    assert "peak_kw" not in roles["energy"]["policy_metrics"]
    assert roles["safety"]["checks"]["peak"] is False
    assert release.compare(pick)["decision"] == "retain_baseline"


def test_missing_ais_observation_never_returns_nearest_minute():
    at=datetime(2024,12,25,0,1,tzinfo=timezone.utc)
    assert observed_minute(at)["fields"]["vessel_count"]=="104"
    with pytest.raises(LookupError):
        observed_minute(at.replace(day=26))
    with pytest.raises(ValueError):
        observed_minute(at.replace(tzinfo=None))


def test_review_command_is_explicit_and_never_silently_drops_bad_parameters():
    assert release.from_command("解释一下训练 PPO 的原理") == (False, None)
    assert release.from_command("/策略复验 window=99") == (True, None)
    assert release.from_command("/policy-review seed=17 seed=37") == (True, None)
    matched, pick=release.from_command("小鸥，/策略复验 scenario=stress window=4")
    assert matched and pick.scenario=="stress" and pick.window==4


def test_registered_image_links_pixel_location_and_measurement_to_source():
    hit=search_figures("higher demand delay")["hits"][0]
    assert hit["id"]=="stress"
    assert any(word["box"][2]>0 for line in hit["matched_ocr_lines"] for word in line["words"])
    assert len(hit["edges"])==3 and hit["values_from_source"]["joint-17-8192"]>hit["values_from_source"]["fixed"]
    assert not search_figures("柠檬蛋糕")["hits"]
