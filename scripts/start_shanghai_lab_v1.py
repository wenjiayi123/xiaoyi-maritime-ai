"""Start the isolated Shanghai lab on dedicated ports; never starts sailing.

Existing listeners must answer the expected health endpoint. Only child processes
started by this invocation are terminated on Ctrl-C. Original demo ports are free.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--build-mobile", action="store_true")
    args = parser.parse_args()
    sibling = ROOT.parent
    energy = Path(os.getenv("SHANGHAI_ENERGY_ROOT", str(sibling / "能碳驾驶舱")))
    malacca = Path(os.getenv("SHANGHAI_MALACCA_ROOT", str(sibling / "马六甲沙盘港口推演")))
    port = Path(os.getenv("SHANGHAI_PORT_ROOT", str(sibling / "模拟器/port-dt-multi")))
    mobile = Path(os.getenv("SHANGHAI_MOBILE_ROOT", str(sibling / "模拟器/dt_mobile_app")))
    node = os.getenv("SHANGHAI_NODE") or shutil.which("node")
    if not node:
        fallback = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        node = str(fallback) if fallback.exists() else None
    if not node:
        raise SystemExit("Node >= 24 is required; set SHANGHAI_NODE.")
    runtime = ROOT / ".runtime/shanghai-lab-v1/launch"
    runtime.mkdir(parents=True, exist_ok=True)
    common = {"PATH": str(Path(node).parent) + os.pathsep + os.environ.get("PATH", "")}

    def uvicorn(folder, interpreter, module, port_number):
        return [str(folder / interpreter), "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port_number)]

    services = [
        (
            "malacca",
            malacca,
            [node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "18473", "--strictPort"],
            18473,
            "/api/shanghai-lab/v1/health",
            {},
        ),
        (
            "energy",
            energy / "backend",
            uvicorn(energy / "backend", ".venv/bin/python", "app.main:app", 18808),
            18808,
            "/api/shanghai-lab/v1/health",
            {},
        ),
        (
            "port",
            port,
            uvicorn(port, ".venv312/bin/python", "app.server:app", 18800),
            18800,
            "/api/shanghai-lab/v1/health",
            {},
        ),
        (
            "xiaoyi",
            ROOT,
            uvicorn(ROOT, ".venv/bin/python", "app.main:app", 18018),
            18018,
            "/api/harness/shanghai/catalog",
            {
                "XIAOYI_RUNTIME_DB": str(runtime / "runtime.sqlite"),
                "SHANGHAI_LAB_MALACCA_URL": "http://127.0.0.1:18473",
                "SHANGHAI_LAB_ENERGY_URL": "http://127.0.0.1:18808",
                "SHANGHAI_LAB_PORT_URL": "http://127.0.0.1:18800",
            },
        ),
        (
            "energy-web",
            energy / "frontend",
            [node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "18474", "--strictPort"],
            18474,
            "/",
            {"VITE_API_TARGET": "http://127.0.0.1:18808"},
        ),
        (
            "portai",
            mobile,
            [
                str(ROOT / ".venv/bin/python"),
                "-m",
                "http.server",
                "7357",
                "--bind",
                "127.0.0.1",
                "--directory",
                "build/web",
            ],
            7357,
            "/flutter_bootstrap.js",
            {},
        ),
    ]

    def healthy(number, endpoint):
        try:
            with urlopen(f"http://127.0.0.1:{number}{endpoint}", timeout=3) as response:
                return response.status == 200
        except OSError:
            return False

    if args.status:
        rows = {name: healthy(number, endpoint) for name, _, _, number, endpoint, _ in services}
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if all(rows.values()) else 1
    if args.build_mobile or not (mobile / "build/web/main.dart.js").exists():
        flutter = shutil.which("flutter")
        if not flutter:
            raise SystemExit("Flutter is required to build PortAI.")
        subprocess.run(
            [
                flutter,
                "build",
                "web",
                "--release",
                "--dart-define=XIAOYI_API_BASE_URL=http://127.0.0.1:18018",
                "--dart-define=API_BASE_URL=http://127.0.0.1:18800",
            ],
            cwd=mobile,
            check=True,
        )
    children = []
    try:
        for name, cwd, command, number, endpoint, env in services:
            if name == "xiaoyi" and (ROOT / ".runtime/harness-runtime.json").exists():
                manifest = json.loads((ROOT / ".runtime/harness-runtime.json").read_text())
                if manifest["port"] != number:
                    raise RuntimeError("统一Harness端口与上海联动契约不同，请完成统一启动配置。")
                subprocess.run([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/start_harness.py")], check=True)
                continue
            if healthy(number, endpoint):
                print(name + ": reuse responding local service", flush=True)
                continue
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", number)) == 0:
                    raise RuntimeError(f"Port {number} is occupied by an unexpected listener; no process was killed.")
            with (runtime / (name + ".log")).open("a") as log:
                process = subprocess.Popen(
                    command, cwd=cwd, env={**os.environ, **common, **env}, stdout=log, stderr=subprocess.STDOUT
                )
            children.append(process)
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError(name + " failed; see " + str(runtime / (name + ".log")))
                if healthy(number, endpoint):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError(name + " readiness timeout")
        print(
            "上海统一试验：http://127.0.0.1:18018/web/shanghai-lab.html\n原有策略与演示端口未替换。Ctrl-C only stops processes created by this invocation.",
            flush=True,
        )
        while children:
            if any(p.poll() is not None for p in children):
                raise RuntimeError("A lab service stopped; inspect launch logs.")
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
