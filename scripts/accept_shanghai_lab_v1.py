"""Real local HTTP acceptance; preserves every response in a new evidence directory."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.shanghai_lab_v1.data import digest
from integrations.shanghai_lab_v1.protocol import packed


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    try:
        with urlopen(Request(url, data=data, headers={"Content-Type": "application/json"}), timeout=55) as r:
            return r.status, json.load(r)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def run(base, out):
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for index, scenario in enumerate(
        ["normal", "arrival_surge", "berth_outage", "grid_derating", "weather_closure", "communications_loss"]
    ):
        body = {"request_id": "accept-" + uuid4().hex, "day": "2025-10-15", "scenario": scenario, "seed": 17}
        status, result = request(base + "/api/harness/shanghai/trials", body)
        (out / (scenario + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        expected = "blocked" if scenario == "communications_loss" else "completed_simulation_pending_mobile"
        ok = status == 200 and result.get("status") == expected
        if ok and scenario != "communications_loss":
            status2, readback = request(base + "/api/harness/shanghai/trials/" + result["id"])
            status3, duplicate = request(base + "/api/harness/shanghai/trials", body)
            ok = status2 == status3 == 200 and result == readback == duplicate
            changed = {**body, "seed": 18}
            conflict, _ = request(base + "/api/harness/shanghai/trials", changed)
            ok = ok and conflict == 409 and result["execution"]["restore_verified"]
            for step in result["steps"]:
                ok = ok and step["status"] == "passed"
            if scenario == "normal":
                packet = packed(result["snapshot"], "snapshot") | packed(result["plan"], "plan")
                packet["snapshot_transport_sha256"] = "0" * 64
                denied, response = request("http://127.0.0.1:18808/api/shanghai-lab/v1/evaluate", packet)
                (out / "tamper-rejection.json").write_text(
                    json.dumps({"http_status": denied, "response": response}, ensure_ascii=False, indent=2)
                )
                ok = ok and denied == 422
        results.append(
            {
                "scenario": scenario,
                "passed": ok,
                "http_status": status,
                "status": result.get("status"),
                "error": result.get("error"),
                "elapsed_seconds": result.get("elapsed_seconds"),
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    summary = {
        "schema": "shanghai-stage02-acceptance.v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(r["passed"] for r in results),
        "cases": results,
        "native_services": ["xiaoyi", "malacca-sandbox", "energy-cockpit", "port-dt-multi"],
        "mobile": "pending stage06 real client acknowledgement",
        "sailing": "excluded",
        "production_authority": False,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18018")
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    run(a.base, a.output)
