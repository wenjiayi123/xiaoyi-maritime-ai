"""Run predeclared V12 tasks against the actual application and save receipts."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:18018")
    p.add_argument("--protocol", default=".codex_artifacts/harness-v12-20261031/protocol-r3.json")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    out = Path(args.output)
    if out.exists():
        p.error("Choose a new output directory.")
    out.mkdir(parents=True)
    spec = json.loads(Path(args.protocol).read_text())

    def api(path, body=None):
        req = Request(args.base_url.rstrip("/") + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type":"application/json"})
        with urlopen(req, timeout=20) as response:
            return json.load(response)

    rows = []
    for case in spec["live_tasks"]:
        payload = {k:v for k,v in case.items() if k != "id"}
        payload["request_id"] = "v12-live-" + uuid4().hex
        start = time.monotonic()
        before = api("/api/port-simulator/status")
        task = api("/api/harness/tasks", payload)
        print(json.dumps({"case":case['id'], "task_id":task['id']}), flush=True)
        while task["status"] in {"queued", "running"} and time.monotonic() - start < payload["budget"]["max_active_seconds"] + 140:
            time.sleep(1)
            task = api("/api/harness/tasks/" + task["id"])
        receipt = api("/api/harness/tasks/" + task["id"] + "/export")
        after = api("/api/port-simulator/status")
        final = task.get("final") or {}
        text = final.get("text", "")
        outputs = {r['tool']:json.loads(next(a['content'] for a in receipt['artifacts'] if a['name']==r['artifact'])) for r in task['results'] if r['ok']}
        snapshot = outputs.get("runtime.snapshot", {}).get("snapshot", {})
        gate = final.get("verification", {}).get("delivery_readiness") or {}
        checks = {"completed":task['status']=='completed', "real_model":task['driver']=='model', "event_chain":receipt['integrity']['event_chain_valid'], "artifacts":receipt['integrity']['artifact_hashes_valid'], "fresh_at_delivery":gate.get('analysis_usable') is True and -5 <= gate.get('age_seconds',9999) <= 120, "production_disabled":task['production_authority'] is False and gate.get('operational_release') is False, "scenario_unchanged":before['scenario_id']==after['scenario_id'] and before['run_id']==after['run_id']}
        if case['id']=='live-free-summary':
            alerts = [a for a in snapshot.get('alerts',[]) if a.get('status') not in {'closed','resolved'} and a.get('severity') in {'critical','high'}]
            checks.update(
                model_authored=final.get('synthesis',{}).get('model_authored') is True,
                both_tools={'runtime.snapshot','knowledge.search'}.issubset(outputs),
                identity=all(snapshot.get('port',{}).get(k,'NO_SOURCE') in text for k in ['name','code']),
                critical_assets=all(a.get('asset_id') in text for a in alerts if a.get('asset_id')),
                simulation_boundary='模拟' in text or '仿真' in text,
                no_false_gap=not bool(re.search(r'(?:缺少|缺失|未提供)(?:具体)?(?:港区名称|港区编号|观测时间)',text)),
            )
        else:
            expected = {'runtime.snapshot','maritime.query','maritime.risk','twin.compare','maritime.handover'}
            business = [v for k,v in outputs.items() if k in expected - {'runtime.snapshot'}]
            checks.update(
                five_tools=expected.issubset(outputs),
                same_snapshot=len(business)==4 and len({v['snapshot_sha256'] for v in business})==1,
                origin_disclosed=final.get('synthesis',{}).get('model_authored') is False,
                unsigned=outputs.get('maritime.handover',{}).get('handover_state')=='draft_requires_human_acceptance',
                required_metrics={'grid_demand','shore_power','low_soc_agv','gate_queue'}.issubset({r.get('metric_id') for r in outputs.get('maritime.query',{}).get('rows',[])}),
                scenarios={'normal','energy_peak','storm'}.issubset({r.get('scenario') for r in outputs.get('twin.compare',{}).get('branches',[])}),
            )
        row = {'case':case['id'], 'task_id':task['id'], 'checks':checks, 'passed':all(checks.values()), 'elapsed_seconds':round(time.monotonic()-start,3), 'snapshot_age_seconds':gate.get('age_seconds'), 'usage':task['usage'], 'receipt':receipt}
        rows.append(row)
        (out/(case['id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2))
        (out/'report.json').write_text(json.dumps({'passed':all(r['passed'] for r in rows),'rows':rows},ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k!='receipt'},ensure_ascii=False),flush=True)
    raise SystemExit(0 if all(r['passed'] for r in rows) else 1)


if __name__=='__main__':
    main()
