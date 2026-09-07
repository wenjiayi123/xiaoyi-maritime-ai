"""Exercise registered local linked-agent adapters and restore owned changes."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password:
        parser.error("only local HTTP services are allowed")
    if not args.tag.replace("_", "").replace("-", "").isalnum():
        parser.error("tag must be alphanumeric")
    root = Path(__file__).resolve().parents[1]
    output = root / "reports" / f"linked_agent_acceptance_{args.tag}.json"
    if output.exists():
        parser.error("choose a new tag; previous evidence is preserved")

    def request(path, data=None):
        req = Request(args.base_url.rstrip("/") + path, data=json.dumps(data).encode() if data is not None else None, headers={"Content-Type":"application/json"})
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    def finish(run):
        deadline = time.monotonic() + 150
        while run["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.4)
            run = request("/api/linked-agent/runs/" + run["id"])
        return run

    rows = []
    cases = [("port.observe", {}), ("port.evaluate", {"scenario":"high_density_berthing","horizon_min":60,"step_min":15}),
             ("energy.observe", {}), ("energy.compare", {"green_preference":.8,"carbon_price_cny_per_ton":100}),
             ("malacca.observe", {}), ("malacca.scenario", {"scenario":"peak-arrivals"}),
             ("malacca.clock", {"action":"stop"}), ("sailing.observe", {})]
    for action, params in cases:
        try:
            plan = request("/api/linked-agent/plans", {"action_id":action,"parameters":params,"samples":3,"interval_seconds":2,"restore_after_observation":True})
            payload = {"plan_sha256":plan["plan_sha256"],"request_id":uuid4().hex}
            path = f"/api/linked-agent/plans/{plan['id']}/execute"
            started = request(path,payload)
            duplicate = request(path,payload)
            run = finish(started)
            checks = {"completed":run["status"]=="completed", "idempotent":started["id"]==duplicate["id"], "observed":len(run["observations"])==3,
                      "restored":not plan["mutates"] or run.get("restored") is True, "production_disabled":run["production_authority"] is False}
            rows.append({"action":action,"checks":checks,"passed":all(checks.values()),"run":run})
            print(action,checks,flush=True)
            if plan["mutates"] and not checks["restored"]:
                break
        except Exception as exc:
            rows.append({"action":action,"passed":False,"error":str(exc)})
            print(action,type(exc).__name__,flush=True)
    report = {"generated_at":datetime.now(timezone.utc).isoformat(),"scope":"Eight local adapter actions, idempotency, observation and configuration restoration; no production control or field KPI claim.","passed":len(rows)==8 and all(r['passed'] for r in rows),"rows":rows,
              "source_sha256":{file:hashlib.sha256((root/file).read_bytes()).hexdigest() for file in ["app/linked_agent.py","app/linked_agent_catalog.py","app/automation.py","app/access_control.py","web/linked_agent.js","web/app.js","web/index.html","web/styles.css"]}}
    with output.open("x") as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
        handle.write("\n")
    print(output.relative_to(root))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
