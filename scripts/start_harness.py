"""Canonical local Harness entry; reuse matching code, never silently reuse stale code."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness.runtime import fingerprint, RELEASE  # noqa: E402

MANIFEST = ROOT / ".runtime/harness-runtime.json"


def get(url):
    with urlopen(url, timeout=4) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    saved = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    port = args.port or saved.get("port", 18018)
    database = (args.database or Path(saved.get("database", str(ROOT / "data/xiaoyi_runtime.db")))).resolve()
    base = f"http://127.0.0.1:{port}"
    if saved.get("pid") and (saved.get("port") != port or not saved.get("url")):
        state = subprocess.run(["ps", "-p", str(saved["pid"]), "-o", "stat=,command="], capture_output=True, text=True).stdout.strip()
        if state and not state.startswith("Z") and "uvicorn app.main:app" in state and Path(saved["database"]).resolve() == database:
            raise SystemExit("同一数据库的统一服务仍在另一端口运行；先正常停止，未启动重复执行器。")
    try:
        current = get(base + "/api/harness/capabilities")
    except OSError:
        current = None
    if current is None and saved.get("port") == port and saved.get("pid"):
        state = subprocess.run(["ps", "-p", str(saved["pid"]), "-o", "stat=,command="], capture_output=True, text=True).stdout.strip()
        if state and not state.startswith("Z") and "uvicorn app.main:app" in state:
            raise SystemExit("登记进程尚在启动或退出，未启动重复执行器；请等待它结束。")
    if args.status:
        print(json.dumps({"url": base, "online": current is not None, "runtime": (current or {}).get("runtime"),
            "model": (current or {}).get("drivers"), "expected_sha256": fingerprint()}, ensure_ascii=False, indent=2))
        return 0 if current and current.get("runtime", {}).get("loaded_sha256") == fingerprint() else 1
    if current:
        if current.get("runtime", {}).get("loaded_sha256") == fingerprint() and not args.restart:
            if args.database and current.get("runtime", {}).get("database") != str(database):
                raise SystemExit("运行库与指定数据库不同，未静默复用。请核查后使用 --restart。")
            if args.open:
                subprocess.run(["open", base], check=False)
            print("复用统一版本：" + base)
            return 0
        if not args.restart:
            raise SystemExit("服务版本与当前代码不一致。确认无执行任务后运行 --restart；未启动第二套后台。")
        tasks = get(base + "/api/harness/tasks?limit=100").get("items", [])
        missions = get(base + "/api/harness/joint/missions").get("items", [])
        if any(t["status"] in {"running", "queued"} for t in [*tasks, *missions]):
            raise SystemExit("仍有执行中任务；请先暂停到安全边界，未停止服务。")
        listeners = subprocess.check_output(["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"], text=True).split()
        if len(listeners) != 1:
            raise SystemExit("无法唯一识别端口所有者，未停止任何进程。")
        pid = int(listeners[0])
        command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
        if "uvicorn app.main:app" not in command:
            raise SystemExit("端口进程不是登记的舷鸥Uvicorn，未停止。")
        if database.exists():
            backup = ROOT / ".runtime/harness-backups" / (str(time.time_ns()) + ".sqlite")
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
                source.backup(destination)
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(.1)
        else:
            # Older launches did not set Uvicorn's graceful timeout. After the
            # active-work gate above, end lingering SSE reads via its own signal
            # handler; never SIGKILL a process or replay its work.
            os.kill(pid, signal.SIGINT)
            for _ in range(50):
                state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
                if not state or state.startswith("Z"):
                    break
                time.sleep(.1)
            else:
                raise SystemExit("旧进程尚未退出，未强制终止或重复启动。")
    sibling = ROOT.parent
    env = {**os.environ, "XIAOYI_RUNTIME_DB": str(database), "XIAOYI_CANONICAL_URL": base,
        "XIAOYI_MODEL_PROVIDER": "openai_compatible", "XIAOYI_MODEL_BASE_URL": "http://127.0.0.1:11435/v1",
        "XIAOYI_MODEL_NAME": "xiaoyi-local-4b", "XIAOYI_MODEL_TIMEOUT_SECONDS": "120",
        "XIAOYI_HARNESS_MODEL_BASE_URL": "http://127.0.0.1:11435/v1", "XIAOYI_HARNESS_MODEL_NAME": "xiaoyi-local-4b",
        "XIAOYI_SIMULATOR_URL": "http://127.0.0.1:18800/", "XIAOYI_PORT_DT_HEALTH_URL": "http://127.0.0.1:18800/health/live",
        "XIAOYI_SIMULATOR_ROOT": str(sibling / "模拟器/port-dt-multi"),
        "XIAOYI_ENERGY_API_URL": "http://127.0.0.1:18808", "XIAOYI_ENERGY_UI_URL": "http://127.0.0.1:18474",
        "XIAOYI_ENERGY_HEALTH_URL": "http://127.0.0.1:18808/api/health", "XIAOYI_ENERGY_ROOT": str(sibling / "能碳驾驶舱"),
        "XIAOYI_MALACCA_UI_URL": "http://127.0.0.1:18473", "XIAOYI_MALACCA_HEALTH_URL": "http://127.0.0.1:18473/api/rl/health",
        "XIAOYI_MALACCA_ROOT": str(sibling / "马六甲沙盘港口推演"),
        "SHANGHAI_LAB_MALACCA_URL": "http://127.0.0.1:18473", "SHANGHAI_LAB_ENERGY_URL": "http://127.0.0.1:18808",
        "SHANGHAI_LAB_PORT_URL": "http://127.0.0.1:18800", "XIAOYI_RETURN_URL": base + "/?xiaoyi_resume=system-linkage"}
    logpath = ROOT / ".runtime/logs/harness-v13.log"
    logpath.parent.mkdir(parents=True, exist_ok=True)
    with logpath.open("ab") as log:
        child = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--timeout-graceful-shutdown", "5"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(100):
        try:
            value = get(base + "/api/harness/capabilities")
            if value.get("runtime", {}).get("loaded_sha256") == fingerprint():
                MANIFEST.write_text(json.dumps({"port": port, "url": base, "database": str(database), "pid": child.pid, "release": RELEASE}, ensure_ascii=False, indent=2))
                if args.open:
                    subprocess.run(["open", base], check=False)
                print("统一Harness已就绪：" + base)
                return 0
        except OSError:
            pass
        if child.poll() is not None:
            break
        time.sleep(.2)
    raise SystemExit("启动未通过版本核验，查看 " + str(logpath))


if __name__ == "__main__":
    sys.exit(main())
