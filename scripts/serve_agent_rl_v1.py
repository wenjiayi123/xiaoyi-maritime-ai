"""Local-only inference worker for the explicitly selected 1.7B experiment."""

from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.policy import LanguagePolicy  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18781)
    args = parser.parse_args()
    summary = json.loads((args.experiment / "summary.json").read_text())
    if not summary.get("rl_parameters_changed"):
        raise SystemExit("no verified RL parameter update in selected experiment")
    if summary.get("environment") == "xiaoyi-agent-env.v3-dense-progress":
        from app.agent_training.policy_v2 import CachedLanguagePolicy

        policy = CachedLanguagePolicy(cache_dir=args.experiment.parent / "frozen-prefix-cache", seed=summary["seed"])
    else:
        policy = LanguagePolicy(seed=summary["seed"])
    from safetensors.torch import load_file
    from peft import set_peft_model_state_dict

    states = {"B_base": policy.state()}
    hashes = {"B_base": policy.fingerprint()}
    groups = [("C_sft", "sft"), ("D_rl", "rl")]
    if "more_sft" in summary["weights"]:
        groups.append(("E_more_sft", "more_sft"))
    for name, folder in groups:
        set_peft_model_state_dict(
            policy.model, load_file(str(args.experiment / "checkpoints" / folder / "adapter_model.safetensors"))
        )
        states[name] = policy.state()
        hashes[name] = policy.fingerprint()
        if hashes[name] != summary["weights"][folder]:
            raise SystemExit("adapter fingerprint mismatch")
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != "/health":
                return self.reply(404, {"error": "not found"})
            return self.reply(
                200,
                {
                    "service": "xiaoyi-language-agent-rl",
                    "model": "1.7B",
                    "groups": list(states),
                    "experiment": args.experiment.name,
                    "weights": hashes,
                },
            )

        def do_POST(self):
            if self.path != "/decide":
                return self.reply(404, {"error": "not found"})
            if self.headers.get("Origin"):
                return self.reply(403, {"error": "worker accepts backend calls only"})
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 20000:
                return self.reply(413, {"error": "request size"})
            try:
                payload = json.loads(self.rfile.read(size))
                group = payload.get("group", "D_rl")
                prompt = payload["prompt"]
                if group not in states or not isinstance(prompt, str) or len(prompt) > 6000:
                    raise ValueError("invalid request")
                with lock:
                    policy.load_state(states[group])
                    choice, meta = policy.choose(prompt)
                self.reply(
                    200,
                    {
                        "choice": choice,
                        **meta,
                        "group": group,
                        "model": "Qwen3-1.7B",
                        "adapter_sha256": hashes[group],
                        "decision_mode": "causal_lm_constrained_next_token",
                    },
                )
            except Exception as exc:
                self.reply(422, {"error": str(exc)[:400]})

        def log_message(self, *args):
            pass

    print(json.dumps({"ready": True, "port": args.port, "weights": hashes}), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
