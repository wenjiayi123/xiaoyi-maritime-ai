"""Summarize preserved trials without converting development cases into blind scores."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/harness-v13-20261101"


def main():
    trials, latest = [], {}
    for path in sorted(OUT.glob("r*/*/result.json"), key=lambda p:p.stat().st_mtime):
        result = json.loads(path.read_text())
        if "case" not in result:
            continue
        result["evidence"] = str(path.relative_to(ROOT))
        task = json.loads(path.with_name("task.json").read_text())
        result["status"] = task["status"]
        result["usage"] = task["usage"]
        result["loaded_sha256"] = json.loads(path.with_name("capabilities.json").read_text()).get("runtime",{}).get("loaded_sha256")
        trials.append(result)
        latest[result["case"]["id"]] = result
    with urlopen("http://127.0.0.1:18018/api/harness/capabilities",timeout=10) as response:
        capabilities = json.load(response)
    trajectories = []
    for result in latest.values():
        with urlopen("http://127.0.0.1:18018/api/harness/tasks/" + result["task_id"] + "/learning-trajectory",timeout=10) as response:
            trajectory = json.load(response)
        folder = ROOT / Path(result["evidence"]).parent
        (folder / "learning-trajectory.json").write_text(json.dumps(trajectory,ensure_ascii=False,indent=2))
        trajectories.append({"task_id":result["task_id"],"integrity":trajectory["integrity"],
            "training_performed":trajectory["training_performed"],"transitions":len(trajectory["transitions"])})
    summary = {"generated_at":datetime.now(timezone.utc).isoformat(),"scope":"development-visible targeted integration; not blind/general autonomy score",
        "runtime":capabilities["runtime"],"model":capabilities["drivers"],
        "latest_model_cases":list(latest.values()),"latest_passed":sum(r["passed"] for r in latest.values()),
        "latest_total":len(latest),"all_preserved_model_trials":trials,"trajectory_exports":trajectories,
        "protected_files":json.loads((OUT/"protected-after.json").read_text()),
        "database_lineage":json.loads((OUT/"database-lineage.json").read_text()),
        "historical_task_retention":json.loads((OUT/"original-task-retention.json").read_text()),
        "ten_adapter_acceptance":{"evidence":"reports/linked_agent_acceptance_harness_v13_20261101.json",
            "passed":json.loads((ROOT/"reports/linked_agent_acceptance_harness_v13_20261101.json").read_text())["passed"],"actions":10},
        "recovery_trials":[{"evidence":str(p.relative_to(ROOT)),**json.loads(p.read_text())} for p in sorted(OUT.glob("recovery-model*/result.json"))],
        "additional_branch":[json.loads(p.read_text()) for p in OUT.glob("paused-branch/*/result.json")],
        "actual_adapter_checks":[{"evidence":str(p.relative_to(ROOT)),**json.loads(p.read_text())} for p in OUT.glob("*-adapter/result.json")],
        "test_logs":[str(p.relative_to(ROOT)) for p in [OUT/"full-regression-complete.log",OUT/"node-final.log",OUT/"ruff-final.log",OUT/"release-check-passed.log"] if p.exists()],
        "limits":["existing CPU 4B latency and failures preserved","automatic verification is a runtime rule, not model tool selection",
            "no Harness RL training or new policy training","headless sailing sample only, no full-voyage/native-window acceptance",
            "production authority remains false","no arbitrary applications or arbitrary host commands"]}
    (OUT/"acceptance-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({"latest_passed":summary["latest_passed"],"latest_total":summary["latest_total"],"runtime":summary["runtime"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
