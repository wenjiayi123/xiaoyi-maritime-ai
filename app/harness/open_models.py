"""Fixed candidate registry and optional local planner process, isolated from the original model."""
from __future__ import annotations
import os

from pathlib import Path
import hashlib
import json
import subprocess
import threading
from urllib.request import urlopen

from app.config import BASE_DIR

_lock = threading.RLock()
_process = None
_verified = {}


def registry():
    return json.loads((BASE_DIR / "config/open_model_candidates.json").read_text())["candidates"]


def planner_status():
    try:
        with urlopen("http://127.0.0.1:11437/v1/models", timeout=1) as response:
            data = json.load(response)
        matches = any(m.get("id") == "xiaoyi-agentcpm-explore" for m in data.get("data", []))
        return {"state": "ready" if matches else "port_conflict", "model_identity_verified": matches}
    except Exception:
        running = _process is not None and _process.poll() is None
        return {"state": "starting" if running else "offline", "model_identity_verified": False}


def activate():
    global _process
    with _lock:
        state = planner_status()
        if state["state"] in {"ready", "starting"}:
            return state
        if state["state"] == "port_conflict":
            raise ValueError("候选端口被其他模型占用，未启动或替换进程")
        record = registry()[0]
        path = BASE_DIR / record["local_path"]
        if not path.is_file() or path.stat().st_size != record["bytes"]:
            raise ValueError("缺少已登记候选文件，请运行固定版本下载脚本")
        signature = (path.stat().st_size, path.stat().st_mtime_ns)
        if _verified.get(str(path)) != signature:
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != record["sha256"]:
                    raise ValueError("候选模型哈希不匹配")
            _verified[str(path)] = signature
        binary = Path(os.environ.get("XIAOYI_LLAMA_SERVER_BIN", BASE_DIR / ".runtime/llama.cpp/llama-server"))
        if not binary.is_file():
            raise ValueError("登记的llama.cpp运行时不存在")
        log_path = BASE_DIR / ".runtime/open-models/agentcpm-server.log"
        with log_path.open("ab") as log:
            _process = subprocess.Popen([str(binary), "-m", str(path), "--host", "127.0.0.1", "--port", "11437",
                "--alias", record["alias"], "--ctx-size", "8192", "--parallel", "1", "--threads", "2",
                "--threads-batch", "2", "--n-gpu-layers", "0", "--reasoning", "off"], stdout=log, stderr=subprocess.STDOUT)
        return {"state": "starting", "pid": _process.pid, "original_model_changed": False}
