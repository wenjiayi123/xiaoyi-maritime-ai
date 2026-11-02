"""Start an isolated web entry and the selected 1.7B worker; preserve other services."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def probe(port, path):
    try:
        with urlopen(f"http://127.0.0.1:{port}" + path, timeout=2) as response:
            return json.load(response)
    except Exception:
        return None


def occupied(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--web-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    active = ROOT / ".runtime/agent-rl-v1/active-experiment.json"
    selected = args.experiment or (
        Path(json.loads(active.read_text())["experiment"])
        if active.exists()
        else ROOT / ".codex_artifacts/agent-rl-v1-20261101/experiment-003"
    )
    selected = selected.resolve()
    if not selected.is_relative_to(ROOT / ".codex_artifacts"):
        raise SystemExit("experiment must be inside this project artifact directory")
    web = probe(18783, "/api/harness/agent-rl/status")
    model = probe(18781, "/health")
    if args.status:
        print(json.dumps({"web": web is not None, "model": model, "selected": str(selected)}, ensure_ascii=False))
        return
    folder = ROOT / ".runtime/agent-rl-v1/launch"
    folder.mkdir(parents=True, exist_ok=True)
    children = []
    env = {
        **os.environ,
        "XIAOYI_AGENT_RL_EXPERIMENT": str(selected),
        "XIAOYI_RUNTIME_DB": str(folder / "platform.sqlite"),
    }

    def launch(name, command, port, health_path):
        if occupied(port):
            raise SystemExit(f"{name} port {port} occupied by an unverified service; nothing terminated")
        stream = (folder / (name + ".log")).open("ab")
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        stream.close()
        children.append(child)
        print(json.dumps({"starting": name, "pid": child.pid, "port": port}), flush=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f"{name} exited; inspect {folder / (name + '.log')}")
            result = probe(port, health_path)
            if result:
                return result
            time.sleep(1)
        raise RuntimeError(f"{name} startup timed out")

    try:
        if web:
            if web.get("experiment") != selected.name:
                raise SystemExit("existing web service uses a different experiment")
        else:
            web = launch(
                "web",
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18783",
                ],
                18783,
                "/api/harness/agent-rl/status",
            )
        if not args.web_only:
            if not (selected / "summary.json").is_file():
                raise SystemExit("training not complete; --web-only can show progress")
            if model:
                if model.get("service") != "xiaoyi-language-agent-rl" or model.get("experiment") != selected.name:
                    raise SystemExit("existing model worker identity or experiment does not match")
            else:
                model = launch(
                    "model",
                    [
                        str(ROOT / ".venv-lora/bin/python"),
                        "-u",
                        str(ROOT / "scripts/serve_agent_rl_v1.py"),
                        "--experiment",
                        str(selected),
                    ],
                    18781,
                    "/health",
                )
        (folder / "processes.json").write_text(
            json.dumps(
                {
                    "owned_pids": [c.pid for c in children],
                    "experiment": str(selected),
                    "url": "http://127.0.0.1:18783/web/agent-rl.html",
                },
                indent=2,
            )
        )
        print("READY http://127.0.0.1:18783/web/agent-rl.html", flush=True)
        while children and all(c.poll() is None for c in children):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
