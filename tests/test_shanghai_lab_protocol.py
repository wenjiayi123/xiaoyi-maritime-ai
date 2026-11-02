import copy
import json
from pathlib import Path
import subprocess
import os
import shutil

import pytest

from integrations.shanghai_lab_v1.data import digest, make_case, verified_dataset
from integrations.shanghai_lab_v1.protocol import (
    energy_ledger,
    packed,
    strict_json,
    unpack,
    validate_plan,
    verify_energy,
)

NODE = Path(
    os.getenv("SHANGHAI_NODE")
    or shutil.which("node")
    or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
)
PLANNER = (
    Path(os.getenv("SHANGHAI_MALACCA_ROOT", str(Path(__file__).resolve().parents[2] / "马六甲沙盘港口推演")))
    / "scripts/operations/runShanghaiPlanV1.ts"
)


@pytest.fixture(scope="module")
def dataset():
    return verified_dataset()


def node_plan(case):
    if not PLANNER.is_file():
        pytest.skip("external Malacca planner absent; set SHANGHAI_MALACCA_ROOT for integration checks")
    if not NODE.is_file():
        pytest.skip("Node.js unavailable for external TypeScript planner integration")
    result = subprocess.run(
        [str(NODE), "--experimental-strip-types", str(PLANNER)],
        input=json.dumps(packed(case, "snapshot")),
        text=True,
        capture_output=True,
        timeout=15,
    )
    if result.returncode:
        raise ValueError(result.stderr)
    return json.loads(result.stdout)


@pytest.mark.parametrize("scenario", ["normal", "arrival_surge", "berth_outage", "grid_derating", "weather_closure"])
def test_cross_language_plan_and_energy_balance(scenario, dataset):
    case = make_case(scenario=scenario, dataset=dataset)
    plan = node_plan(case)
    v = validate_plan(case, plan)
    assert v["feasible"] and v["processed_teu"] == sum(j["teu"] for j in case["jobs"])
    ledger = energy_ledger(case, plan)
    assert verify_energy(case, plan, ledger)["totals"] == ledger["totals"]
    for row in ledger["hourly"]:
        assert row["grid_kw"] + row["pv_kw"] - row["curtailment_kw"] + row["discharge_kw"] == pytest.approx(
            row["load_kw"] + row["charge_kw"]
        )


def test_independent_checker_rejects_conflicts_and_partial_plans(dataset):
    case = make_case(dataset=dataset)
    plan = node_plan(case)
    altered = copy.deepcopy(plan)
    altered["scheduled"].pop()
    with pytest.raises(ValueError, match="partial"):
        validate_plan(case, altered)
    altered = copy.deepcopy(plan)
    a, b = altered["scheduled"][:2]
    b.update(
        start_hour=a["start_hour"],
        end_hour=a["start_hour"] + next(j["duration_hours"] for j in case["jobs"] if j["id"] == b["job_id"]),
        berth=a["berth"],
    )
    with pytest.raises(ValueError):
        validate_plan(case, altered)
    ledger = energy_ledger(case, plan)
    ledger["hourly"][0]["grid_kw"] += 1
    with pytest.raises(ValueError, match="balance"):
        verify_energy(case, plan, ledger)


def test_transport_rejects_wrong_hash_duplicate_key_and_nonfinite():
    with pytest.raises(ValueError):
        unpack({"snapshot_json": "{}", "snapshot_transport_sha256": "0" * 64}, "snapshot")
    with pytest.raises(ValueError):
        strict_json('{"a":1,"a":2}')
    with pytest.raises(ValueError):
        strict_json('{"a":NaN}')


def test_disconnected_trial_is_refused_by_native_planner(dataset):
    with pytest.raises(ValueError, match="quality"):
        node_plan(make_case(scenario="communications_loss", dataset=dataset))
