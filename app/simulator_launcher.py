from __future__ import annotations

import os
import subprocess
from http.client import RemoteDisconnected
from pathlib import Path
from threading import RLock
from typing import Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/simulator", tags=["港口模拟器启动器"])

SimulatorState = Literal["offline", "starting", "online", "error", "port_conflict"]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SIMULATOR_ROOT = Path(
    os.getenv("XIAOYI_SIMULATOR_ROOT", str(_PROJECT_ROOT / ".integrations/port-dt-multi"))
).expanduser()
_SIMULATOR_PYTHON = Path(
    os.getenv("XIAOYI_SIMULATOR_PYTHON", str(_SIMULATOR_ROOT / ".venv312/bin/python"))
).expanduser()
_CONFIGURED_URL = os.getenv("XIAOYI_SIMULATOR_URL", "").strip()
_SIMULATOR_HOST = os.getenv("XIAOYI_SIMULATOR_HOST", "127.0.0.1").strip() or "127.0.0.1"
_SIMULATOR_MARKERS = ("港口 AI 运营平台", "TwinLab + RL")
_LOG_PATH = _PROJECT_ROOT / ".runtime" / "port-dt-multi.log"
_launch_lock = RLock()
_simulator_process: Optional[subprocess.Popen[bytes]] = None
_active_port: Optional[int] = None
_conflicted_ports: list[int] = []


def _candidate_ports() -> tuple[int, ...]:
    if _CONFIGURED_URL:
        parsed = urlparse(_CONFIGURED_URL)
        return (int(parsed.port or 80),)
    raw = os.getenv("XIAOYI_SIMULATOR_PORTS", "8000")
    ports: list[int] = []
    for item in raw.split(","):
        try:
            port = int(item.strip())
        except ValueError:
            continue
        if 1024 <= port <= 65535 and port not in ports:
            ports.append(port)
    return tuple(ports or [8000])


_SIMULATOR_PORTS = _candidate_ports()


class SimulatorLaunchRequest(BaseModel):
    target: Literal["port-dt-multi"] = "port-dt-multi"


class SimulatorRuntime(BaseModel):
    target: Literal["port-dt-multi"] = "port-dt-multi"
    name: str = "港口数字孪生与 RL 模拟器"
    state: SimulatorState
    running: bool
    managed_by_xiaoyi: bool
    already_running: bool = False
    pid: Optional[int] = None
    port: int
    preferred_port: int = 8000
    fallback_used: bool = False
    conflicted_ports: list[int] = []
    url: str
    message: str


def _url_for_port(port: int) -> str:
    if _CONFIGURED_URL:
        return _CONFIGURED_URL.rstrip("/") + "/"
    return f"http://{_SIMULATOR_HOST}:{port}/"


def _probe_port(port: int) -> tuple[SimulatorState, str]:
    url = _url_for_port(port)
    request = Request(url, method="GET", headers={"Accept": "text/html"})
    try:
        with urlopen(request, timeout=1.0) as response:
            body = response.read(32_768).decode("utf-8", "replace")
            if getattr(response, "status", 200) != 200:
                return "offline", f"{port} 端口尚未返回就绪页面。"
            if not any(marker in body for marker in _SIMULATOR_MARKERS):
                return "port_conflict", f"{port} 端口已被其他服务占用。"
            return "online", f"模拟器首页与 {port} 端口均已就绪。"
    except HTTPError as exc:
        if exc.code in {401, 403, 404, 405}:
            return "port_conflict", f"{port} 端口已被其他服务占用（HTTP {exc.code}）。"
        return "offline", f"{port} 端口返回 HTTP {exc.code}，尚未就绪。"
    except RemoteDisconnected:
        return "port_conflict", f"{port} 端口已有非模拟器服务监听。"
    except (URLError, TimeoutError, OSError):
        return "offline", f"{port} 端口可用，模拟器尚未启动。"


def _managed_process() -> tuple[bool, Optional[int], Optional[int]]:
    process = _simulator_process
    if process is None:
        return False, None, None
    return process.poll() is None, process.pid, process.poll()


def _probe_simulator() -> tuple[SimulatorState, str]:
    global _active_port, _conflicted_ports

    managed, _, _ = _managed_process()
    ordered = list(_SIMULATOR_PORTS)
    if _active_port in ordered:
        ordered.remove(_active_port)
        ordered.insert(0, _active_port)

    available: list[tuple[int, str]] = []
    # Keep conflicts discovered by an earlier full scan when an already-running
    # simulator is checked first. Otherwise reusing the fallback instance would
    # incorrectly hide the reason why the preferred port was skipped.
    conflicts: list[int] = list(_conflicted_ports)
    for port in ordered:
        state, message = _probe_port(port)
        if state == "online":
            _active_port = port
            _conflicted_ports = conflicts
            return state, message
        if state == "port_conflict":
            if port not in conflicts:
                conflicts.append(port)
            continue
        available.append((port, message))
        if managed and port == _active_port:
            _conflicted_ports = conflicts
            return "offline", message

    _conflicted_ports = conflicts
    if available:
        _active_port = available[0][0]
        if conflicts:
            skipped = "、".join(str(port) for port in conflicts)
            return "offline", f"已跳过冲突端口 {skipped}，将使用 {_active_port} 端口启动模拟器。"
        return "offline", available[0][1]

    _active_port = None
    ports = "、".join(str(port) for port in _SIMULATOR_PORTS)
    return "port_conflict", f"候选端口 {ports} 均被其他服务占用，未启动模拟器。"


def simulator_base_url() -> str:
    if _active_port is None:
        _probe_simulator()
    return _url_for_port(_active_port or _SIMULATOR_PORTS[0]).rstrip("/")


def _runtime(*, already_running: bool = False) -> SimulatorRuntime:
    state, message = _probe_simulator()
    managed, pid, return_code = _managed_process()
    port = _active_port or _SIMULATOR_PORTS[0]
    if state == "offline" and managed:
        state = "starting"
        message = f"模拟器进程已拉起，正在 {port} 端口加载数字孪生与 RL 工作台。"
    elif state == "offline" and return_code is not None:
        state = "error"
        message = f"模拟器进程提前退出（code={return_code}），请查看启动日志。"
    return SimulatorRuntime(
        state=state,
        running=state == "online",
        managed_by_xiaoyi=managed,
        already_running=already_running,
        pid=pid if managed else None,
        port=port,
        preferred_port=_SIMULATOR_PORTS[0],
        fallback_used=port != _SIMULATOR_PORTS[0],
        conflicted_ports=list(_conflicted_ports),
        url=_url_for_port(port),
        message=message,
    )


@router.get("/status", response_model=SimulatorRuntime)
def simulator_status() -> SimulatorRuntime:
    return _runtime()


@router.post("/launch", response_model=SimulatorRuntime, status_code=202)
def launch_simulator(payload: SimulatorLaunchRequest) -> SimulatorRuntime:
    del payload  # target is intentionally constrained by the request model.
    global _simulator_process

    with _launch_lock:
        current = _runtime()
        if current.state == "online":
            current.already_running = True
            current.message = f"模拟器已在 {current.port} 端口在线，将直接复用。"
            return current
        if current.state == "port_conflict":
            raise HTTPException(status_code=409, detail=current.message)
        if current.state == "starting":
            current.already_running = True
            return current
        if not (_SIMULATOR_ROOT / "app/server.py").is_file():
            raise HTTPException(status_code=503, detail="未找到登记的港口模拟器项目，请检查 XIAOYI_SIMULATOR_ROOT。")
        if not _SIMULATOR_PYTHON.is_file() or not os.access(_SIMULATOR_PYTHON, os.X_OK):
            raise HTTPException(status_code=503, detail="模拟器 Python 运行环境不可用，请先恢复 .venv312。")

        port = current.port
        env = os.environ.copy()
        env["PORT_DT_SERVER_PORT"] = str(port)
        env["PORT_DT_ENABLE_DESKTOP_INTEGRATIONS"] = "1"
        env["XIAOYI_AI_BASE_URL"] = os.getenv(
            "XIAOYI_AI_BASE_URL",
            "http://127.0.0.1:8010",
        )
        env["XIAOYI_AI_PROJECT"] = str(_PROJECT_ROOT)
        env["XIAOYI_AI_START_COMMAND"] = os.getenv(
            "XIAOYI_AI_START_COMMAND",
            f"/bin/bash {str(_PROJECT_ROOT / 'run.sh')}",
        )
        sailing_root = os.getenv("XIAOYI_SAILING_SIMULATOR_ROOT", "")
        godot_binary = os.getenv("XIAOYI_GODOT_BINARY", "")
        if sailing_root:
            env["SAILING_SIM_PROJECT"] = sailing_root
        if godot_binary:
            env["SAILING_SIM_GODOT"] = godot_binary
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _LOG_PATH.open("ab", buffering=0) as log_file:
                _simulator_process = subprocess.Popen(
                    [str(_SIMULATOR_PYTHON), "-m", "app.server"],
                    cwd=str(_SIMULATOR_ROOT),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"模拟器启动失败：{exc}") from exc

        return _runtime()
