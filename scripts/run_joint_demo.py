"""Start the existing GullMate launcher and the built Flutter receipt client locally."""
from __future__ import annotations

import argparse
import json
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def occupied(port):
    with socket.socket() as probe:
        probe.settimeout(.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def health():
    with urlopen("http://127.0.0.1:8010/api/harness/joint/capabilities", timeout=3) as response:
        data = json.load(response)
    if data.get("schema") != "xiaoyi-joint-capabilities.v1":
        raise ValueError("8010端口服务身份不符合联合系统契约")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只读检查，不启动服务")
    args = parser.parse_args()
    mobile = ROOT.parent / "模拟器/dt_mobile_app/build/web"
    if not (mobile / "index.html").is_file():
        raise SystemExit("移动端尚未构建，请先按部署说明运行flutter build web。")
    if args.check:
        health()
        with urlopen("http://127.0.0.1:7357/", timeout=3) as response:
            if "PortAI 港口数字孪生" not in response.read().decode():
                raise SystemExit("7357端口不是预期的移动端构建。")
        print("舷鸥联合API和Flutter回执端就绪。")
        return
    children = []
    handles = []
    log_dir = ROOT / ".runtime/joint-demo"
    log_dir.mkdir(parents=True, exist_ok=True)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        if occupied(8010):
            health()
        else:
            handle = (log_dir / "xiaoyi.log").open("ab")
            handles.append(handle)
            children.append(subprocess.Popen(["bash", str(ROOT / "run.sh")], cwd=ROOT, stdout=handle, stderr=handle))
            deadline = time.monotonic() + 180
            while True:
                try:
                    health()
                    break
                except (URLError, TimeoutError):
                    if stopping or children[-1].poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("舷鸥未在预算内启动，请查看.runtime/joint-demo/xiaoyi.log")
                    time.sleep(.5)
        if occupied(7357):
            with urlopen("http://127.0.0.1:7357/", timeout=3) as response:
                if "PortAI 港口数字孪生" not in response.read().decode():
                    raise ValueError("7357端口已被其他服务占用，未覆盖或停止它")
        else:
            handle = (log_dir / "mobile.log").open("ab")
            handles.append(handle)
            children.append(subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "http.server", "7357",
                                              "--bind", "127.0.0.1", "--directory", str(mobile)],
                                             stdout=handle, stderr=handle))
        print("联合系统 http://127.0.0.1:8010/ → 双模式港航联合系统", flush=True)
        print("Flutter回执端 http://127.0.0.1:7357/；下游服务由获批任务按需启动。", flush=True)
        print("Ctrl+C只停止本启动器创建的进程；已在运行的服务继续保留。", flush=True)
        while children and not stopping:
            if any(p.poll() is not None for p in children):
                raise RuntimeError("启动器创建的服务意外退出，请检查日志")
            time.sleep(.5)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
