"""One Qwen base model with separately identified accepted and expanded LoRA adapters."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18781)
    args = parser.parse_args()
    cfg = json.loads(args.registry.read_text())
    from app.agent_training.policy_v2 import CachedLanguagePolicy
    from safetensors.torch import load_file
    from peft import set_peft_model_state_dict

    policy = CachedLanguagePolicy(cache_dir=cfg["cache_dir"], seed=cfg["seed"], threads=4)
    states, hashes = {}, {}
    for group, record in cfg["groups"].items():
        if record.get("adapter"):
            path = Path(record["adapter"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["file_sha256"]:
                raise ValueError("Registry adapter file changed: " + group)
            set_peft_model_state_dict(policy.model, load_file(str(path)))
        else:
            policy.load_state(policy.initial)
        states[group] = policy.state()
        hashes[group] = policy.fingerprint()
        if hashes[group] != record["parameter_fingerprint"]:
            raise ValueError("Registry tensor identity mismatch: " + group)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            raw = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path != "/health":
                return self.reply(404, {"error": "not found"})
            self.reply(200, {"service": "xiaoyi-language-agent-rl", "model": "1.7B", "base_model_instances": 1,
                             "experiment": "capability-scale-30-with-accepted-v1", "groups": list(states),
                             "weights": hashes, "registry_sha256": hashlib.sha256(args.registry.read_bytes()).hexdigest()})

        def do_POST(self):
            if self.path != "/decide":
                return self.reply(404, {"error": "not found"})
            if self.headers.get("Origin"):
                return self.reply(403, {"error": "worker accepts backend calls only"})
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 20000:
                    raise ValueError("request size")
                body = json.loads(self.rfile.read(size))
                group, prompt = body["group"], body["prompt"]
                if group not in states or not isinstance(prompt, str) or len(prompt) > 6000:
                    raise ValueError("invalid group or prompt")
                with lock:
                    policy.load_state(states[group])
                    choice, meta = policy.choose(prompt)
                self.reply(200, {"choice": choice, **meta, "group": group, "model": "Qwen3-1.7B",
                                 "adapter_sha256": hashes[group], "decision_mode": "causal_lm_constrained_next_token"})
            except Exception as exc:
                self.reply(422, {"error": str(exc)[:400]})

        def log_message(self, *args):
            pass

    print(json.dumps({"ready": True, "port": args.port, "base_model_instances": 1, "weights": hashes}), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
