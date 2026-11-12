"""Register an accepted30-case UI and old/new adapter identities without retraining."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_capability_scale as scale  # noqa: E402


def prepare(round_dir, out):
    c = scale.core
    p = c.verify(round_dir)
    result = c.read(round_dir / "RESULTS.json")
    if not result["suite_passed"] or any(x["successes"] != 60 or x["attempted"] != 60 for x in result["counts"].values()):
        raise ValueError("30-case, twice-per-model acceptance is incomplete")
    for row in result["results"]:
        folder = Path(row["folder"])
        c.audit_job(c.read(folder / "job.json"), folder, p)
    out.mkdir(parents=True, exist_ok=False)
    ui = copy.deepcopy(p)
    ui["groups"] = ["E_more_sft", "D_scale_rl"]
    ui["models"]["D_scale_rl"] = ui["models"].pop("D_rl")
    ui.update(time=c.now(), source_acceptance_round=str(round_dir),
              serving_aliases={"D_scale_rl": "Same exact fixed64 adapter audited as D_rl in round003; name isolates it from accepted-v1 D_rl"})
    for case in ui["cases"]:
        case["title"] = case["id"] + " · " + case["category"]
        case["fault"] = case["inject_read_fault"]
    original = c.read(c.OLD / "summary.json")
    groups = {"B_base": {"parameter_fingerprint": original["weights"]["initial"]}}
    for group, key in [("C_sft", "sft"), ("D_rl", "rl"), ("E_more_sft", "more_sft")]:
        f = c.OLD / "checkpoints" / key / "adapter_model.safetensors"
        groups[group] = {"adapter": str(f), "file_sha256": c.sha(f), "parameter_fingerprint": original["weights"][key]}
    groups["D_scale_rl"] = ui["models"]["D_scale_rl"]
    registry = {"time": c.now(), "seed": original["seed"], "cache_dir": str(c.OLD.parent / "frozen-prefix-cache"),
                "base_model_instances": 1, "groups": groups, "original_accepted_groups_unchanged": True}
    sources = dict(c.read(round_dir / "SOURCES.json"))
    for rel in ["scripts/serve_agent_capability_registry.py", "scripts/serve_agent_capability_scale.py",
                "scripts/serve_agent_capability_demo.py", "scripts/prepare_agent_capability_scale_live.py"]:
        sources[rel] = c.sha(ROOT / rel)
    for rel in sources:
        dst = out / "source" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    c.live.save(out / "PROTOCOL.json", ui)
    c.live.save(out / "REGISTRY.json", registry)
    c.live.save(out / "SOURCES.json", sources)
    c.live.save(out / "LOCK.json", {n: c.sha(out / n) for n in ["PROTOCOL.json", "REGISTRY.json", "SOURCES.json"]})
    c.live.save(out / "ACCEPTANCE_LINK.json", {"time": c.now(), "round": str(round_dir),
                                               "results_sha256": c.sha(round_dir / "RESULTS.json"),
                                               "full_native_replays": 120, "new_model_calls": 0})
    print("Registered30-case UI;120 native replays verified; no model loaded", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.round.resolve(), args.output.resolve())
