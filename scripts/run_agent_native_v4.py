"""Execute a registered user goal through V4 native tools, saving every choice.

--mode rules is explicitly a harness contract probe and never model evidence.
Model mode loads the chosen LoRA and uses greedy action logits without fallback.
"""

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment_v3 import DynamicTask, teacher_action  # noqa: E402
from app.agent_training.environment_v4 import ReadableEnvironment  # noqa: E402
from app.agent_training.live import ACCEPTANCE_GOAL, parse_goal, save  # noqa: E402
from app.agent_training.live_v4 import ReceiptBackend, native_step  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["rules", "model"], required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--goal", default=ACCEPTANCE_GOAL)
    parser.add_argument("--inject-read-timeout", action="store_true")
    parser.add_argument("--inject-lost-response", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    values = asdict(parse_goal(args.goal))
    if values["family"] == "clock_restore":
        raise ValueError("V4 native clock-control acceptance is not enabled yet")
    values.update(
        max_steps=20,
        shocks=tuple(
            name
            for name, flag in [("read_timeout", args.inject_read_timeout), ("lost_receipt", args.inject_lost_response)]
            if flag
        ),
    )
    task = DynamicTask(**values)
    env, backend, model = ReadableEnvironment(task), ReceiptBackend(output), None
    backend.decision_producer = args.mode
    manifest = {
        "mode": args.mode,
        "goal": args.goal,
        "task": asdict(task),
        "production_authority": False,
        "evidence_scope": "native API contract probe, no language model"
        if args.mode == "rules"
        else "single greedy model execution of a registered goal, not a comparative RL result",
        "action_space": "13 displayed tool/parameter candidates; user parameter parsing is deterministic",
        "sources": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "app/agent_training/live_v4.py",
                ROOT / "app/agent_training/live.py",
                ROOT / "app/agent_training/environment_v3.py",
                ROOT / "app/agent_training/environment_v4.py",
            ]
        },
    }
    if args.mode == "model":
        if not args.adapter:
            raise ValueError("model mode requires an explicitly selected adapter")
        from app.agent_training.policy_v2 import CachedLanguagePolicy
        from scripts.run_agent_rl_v3 import load_adapter

        model = CachedLanguagePolicy(cache_dir=ROOT / ".codex_artifacts/agent-rl-v3-20261102/prefix-cache", threads=4)
        load_adapter(model, args.adapter.resolve())
        manifest.update(
            adapter=str(args.adapter.resolve()),
            adapter_sha256=hashlib.sha256(args.adapter.read_bytes()).hexdigest(),
            parameter_fingerprint=model.fingerprint(),
        )
    save(output / "manifest.json", manifest)
    records, started = [], time.monotonic()
    while not env.done:
        prompt = env.prompt()
        if model:
            label, policy = model.choose(prompt, sample=False, temperature=1)
        else:
            label, policy = (
                teacher_action(env),
                {"producer": "visible-state rule contract probe", "model_action": False},
            )
        transition = native_step(env, backend, label)
        transition["model_action"] = args.mode == "model"
        row = {"prompt": prompt, "choice": label, "policy": policy, "transition": transition}
        records.append(row)
        save(
            output / "trajectory.json",
            {"manifest": manifest, "steps": records, "done": env.done, "success": env.success},
        )
        print(label, transition["feedback"], flush=True)
    result = {
        "success": env.success,
        "mode": args.mode,
        "model_used": bool(model),
        "steps": len(records),
        "seconds": time.monotonic() - started,
        "pending_requests": list(backend.pending),
        "report": str(output / "report.html") if env.success else None,
        "rl_advantage_established": False,
    }
    save(output / "result.json", result)
    print(result, flush=True)
    raise SystemExit(0 if env.success else 1)


if __name__ == "__main__":
    main()
