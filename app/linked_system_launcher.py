from __future__ import annotations

import json
import os
import shutil
import subprocess
from http.client import RemoteDisconnected
from pathlib import Path
from threading import RLock
from typing import Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import simulator_launcher


router = APIRouter(prefix="/api/linked-systems", tags=["小懿本机联动启动器"])

LinkedTarget = Literal["port-dt-multi", "energy-cockpit", "malacca-sandbox"]
LinkedState = Literal["offline", "starting", "online", "error", "port_conflict"]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENERGY_ROOT = Path(
    os.getenv("XIAOYI_ENERGY_ROOT", str(_PROJECT_ROOT / ".integrations/energy-cockpit"))
).expanduser()
_MALACCA_ROOT = Path(
    os.getenv("XIAOYI_MALACCA_ROOT", str(_PROJECT_ROOT / ".integrations/malacca-sandbox"))
).expanduser()

_TARGETS: dict[LinkedTarget, dict[str, object]] = {
    "port-dt-multi": {
        "name": "港口数字孪生",
        "url": os.getenv("XIAOYI_SIMULATOR_URL", "http://127.0.0.1:8000/").strip(),
        "health_url": os.getenv(
            "XIAOYI_PORT_DT_HEALTH_URL",
            "http://127.0.0.1:8000/health/live",
        ).strip(),
        "root": Path(
            os.getenv("XIAOYI_SIMULATOR_ROOT", str(_PROJECT_ROOT / ".integrations/port-dt-multi"))
        ).expanduser(),
        "command": (),
    },
    "energy-cockpit": {
        "name": "能碳驾驶舱",
        "url": os.getenv("XIAOYI_ENERGY_UI_URL", "http://127.0.0.1:5173/").strip(),
        "health_url": os.getenv(
            "XIAOYI_ENERGY_HEALTH_URL",
            "http://127.0.0.1:8808/api/health",
        ).strip(),
        "root": _ENERGY_ROOT,
        "command": ("/bin/bash", str(_ENERGY_ROOT / "scripts/start_demo.sh")),
    },
    "malacca-sandbox": {
        "name": "马六甲推演",
        "url": os.getenv("XIAOYI_MALACCA_UI_URL", "http://127.0.0.1:5174/").strip(),
        "health_url": os.getenv(
            "XIAOYI_MALACCA_HEALTH_URL",
            "http://127.0.0.1:5174/api/rl/health",
        ).strip(),
        "root": _MALACCA_ROOT,
        "command": ("/bin/bash", str(_MALACCA_ROOT / "scripts/demo/start_web_demo.sh")),
    },
}

_launch_lock = RLock()
_processes: dict[LinkedTarget, subprocess.Popen[bytes]] = {}


class LinkedSystemsLaunchRequest(BaseModel):
    targets: list[LinkedTarget] = Field(..., min_length=1, max_length=3)


class LinkedSystemRuntime(BaseModel):
    target: LinkedTarget
    name: str
    state: LinkedState
    running: bool
    managed_by_xiaoyi: bool
    already_running: bool = False
    pid: Optional[int] = None
    url: str
    message: str


class LinkedSystemsRuntime(BaseModel):
    systems: dict[str, LinkedSystemRuntime]
    all_ready: bool
    production_write_enabled: bool = False
    safety_boundary: str = "只启动登记的本机仿真服务；不开启生产写入，不下发真实设备或船舶指令。"


def _runtime_bin_dirs() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("XIAOYI_NODE_BIN_DIR", "XIAOYI_PNPM_BIN_DIR"):
        value = os.getenv(variable, "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    for executable in ("node", "pnpm", "corepack", "npx"):
        resolved = shutil.which(executable)
        if resolved:
            candidates.append(Path(resolved).resolve().parent)

    bundled_dependencies = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
    )
    candidates.extend(
        (
            bundled_dependencies / "node" / "bin",
            bundled_dependencies / "bin" / "override",
            bundled_dependencies / "bin" / "fallback",
        )
    )
    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in unique:
            unique.append(candidate)
    return unique


def _probe_json_health(health_url: str) -> tuple[LinkedState, str]:
    request = Request(health_url, method="GET", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=1.2) as response:
            body = response.read(256_000).decode("utf-8", "replace")
            if getattr(response, "status", 200) != 200:
                return "offline", "健康接口尚未就绪。"
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return "port_conflict", "目标端口返回了非预期内容，已阻止启动。"
            return "online", "业务健康接口已就绪。"
    except HTTPError as exc:
        if exc.code in {401, 403, 404, 405}:
            return "port_conflict", f"目标端口已被其他服务占用（HTTP {exc.code}）。"
        return "offline", f"健康接口返回 HTTP {exc.code}，尚未就绪。"
    except json.JSONDecodeError:
        return "port_conflict", "目标端口返回了非 JSON 内容，已阻止启动。"
    except RemoteDisconnected:
        return "port_conflict", "目标端口已有其他服务监听，但未返回登记的业务健康响应。"
    except (URLError, TimeoutError, OSError):
        return "offline", "服务尚未启动。"


def _probe_ui(ui_url: str) -> tuple[LinkedState, str]:
    request = Request(ui_url, method="GET", headers={"Accept": "text/html"})
    try:
        with urlopen(request, timeout=1.2) as response:
            body = response.read(64_000).decode("utf-8", "replace").lower()
            if getattr(response, "status", 200) != 200:
                return "offline", "前端页面尚未就绪。"
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "text/html" not in content_type and "<html" not in body and "<!doctype" not in body:
                return "port_conflict", "前端端口返回了非 HTML 内容，已阻止复用。"
            return "online", "前端页面已就绪。"
    except HTTPError as exc:
        if exc.code in {401, 403, 404, 405}:
            return "port_conflict", f"前端端口已被其他服务占用（HTTP {exc.code}）。"
        return "offline", f"前端页面返回 HTTP {exc.code}，尚未就绪。"
    except RemoteDisconnected:
        return "port_conflict", "前端端口已有其他服务监听，但未返回登记的页面。"
    except (URLError, TimeoutError, OSError):
        return "offline", "前端页面尚未启动。"


def _probe_target(target: LinkedTarget) -> tuple[LinkedState, str]:
    spec = _TARGETS[target]
    ui_url = str(spec["url"])
    if target == "port-dt-multi":
        simulator = simulator_launcher.simulator_status()
        if simulator.state == "port_conflict":
            return "port_conflict", simulator.message
        if simulator.state != "online":
            return "offline", simulator.message
        configured_path = urlparse(str(spec["health_url"])).path or "/health/live"
        health_url = f"{simulator.url.rstrip('/')}{configured_path}"
        ui_url = f"{simulator.url.rstrip('/')}/"
    else:
        health_url = str(spec["health_url"])

    health_state, health_message = _probe_json_health(health_url)
    if health_state != "online":
        return health_state, health_message
    ui_state, ui_message = _probe_ui(ui_url)
    if ui_state == "offline":
        return "offline", f"业务后端已在线，但{ui_message}"
    if ui_state != "online":
        return ui_state, ui_message
    return "online", "业务健康接口与前端页面均已就绪。"


def _managed_process(target: LinkedTarget) -> tuple[bool, Optional[int], Optional[int]]:
    if target == "port-dt-multi":
        return simulator_launcher._managed_process()
    process = _processes.get(target)
    if process is None:
        return False, None, None
    return process.poll() is None, process.pid, process.poll()


def _runtime(target: LinkedTarget, *, already_running: bool = False) -> LinkedSystemRuntime:
    state, message = _probe_target(target)
    managed, pid, return_code = _managed_process(target)
    if state == "offline" and managed:
        state = "starting"
        message = "小懿已拉起进程，正在等待业务健康接口。"
    elif state == "offline" and return_code is not None:
        state = "error"
        message = f"服务进程提前退出（code={return_code}），请查看启动日志。"
    spec = _TARGETS[target]
    runtime_url = f"{simulator_launcher.simulator_base_url()}/" if target == "port-dt-multi" else str(spec["url"])
    return LinkedSystemRuntime(
        target=target,
        name=str(spec["name"]),
        state=state,
        running=state == "online",
        managed_by_xiaoyi=managed,
        already_running=already_running,
        pid=pid if managed else None,
        url=runtime_url,
        message=message,
    )


def _start_registered_process(target: LinkedTarget) -> None:
    spec = _TARGETS[target]
    root = Path(spec["root"])
    command = tuple(str(part) for part in spec["command"])
    energy_frontend_only = False
    if target == "energy-cockpit":
        backend_state, _ = _probe_json_health(str(spec["health_url"]))
        energy_frontend_only = backend_state == "online"
        if energy_frontend_only:
            command = ("/bin/bash", str(root / "scripts/run_frontend.sh"))
    if not root.is_dir() or not command or not Path(command[-1]).is_file():
        raise HTTPException(status_code=503, detail=f"未找到登记的{spec['name']}项目或启动脚本。")
    if (
        target == "energy-cockpit"
        and not energy_frontend_only
        and not (root / "backend/.venv/bin/python").is_file()
    ):
        raise HTTPException(status_code=503, detail="能碳驾驶舱后端 Python 环境不可用。")
    if target == "malacca-sandbox" and not (root / "node_modules/.bin/vite").is_file():
        raise HTTPException(status_code=503, detail="马六甲推演依赖不完整，请先恢复 node_modules。")

    log_path = _PROJECT_ROOT / ".runtime" / f"{target}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OPEN_BROWSER"] = "0"
    if target == "energy-cockpit" and energy_frontend_only:
        env["FRONTEND_HOST"] = "127.0.0.1"
        env["FRONTEND_PORT"] = str(urlparse(str(spec["url"])).port or 5173)
        health_parts = urlparse(str(spec["health_url"]))
        env["VITE_API_TARGET"] = f"{health_parts.scheme}://{health_parts.netloc}"
    elif target == "malacca-sandbox":
        env["PORT"] = str(urlparse(str(spec["url"])).port or 5174)
        path_parts = [str(path) for path in _runtime_bin_dirs()]
        if path_parts:
            env["PATH"] = os.pathsep.join([*path_parts, env.get("PATH", "")])
    try:
        with log_path.open("ab", buffering=0) as log_file:
            _processes[target] = subprocess.Popen(
                list(command),
                cwd=str(root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"{spec['name']}启动失败：{exc}") from exc


def _launch_target(target: LinkedTarget) -> LinkedSystemRuntime:
    current = _runtime(target)
    if current.state == "online":
        current.already_running = True
        current.message = "服务已在线，小懿将直接复用并继续流程。"
        return current
    if current.state == "starting":
        if target == "energy-cockpit":
            backend_state, _ = _probe_json_health(str(_TARGETS[target]["health_url"]))
            if backend_state != "online":
                _start_registered_process(target)
                return _runtime(target)
        current.already_running = True
        return current
    if current.state == "port_conflict":
        raise HTTPException(status_code=409, detail=current.message)

    if target == "port-dt-multi":
        simulator_launcher.launch_simulator(
            simulator_launcher.SimulatorLaunchRequest(target="port-dt-multi")
        )
    else:
        _start_registered_process(target)
    return _runtime(target)


def _selected_targets(raw_targets: Optional[str]) -> list[LinkedTarget]:
    if not raw_targets:
        return list(_TARGETS)
    requested = list(dict.fromkeys(item.strip() for item in raw_targets.split(",") if item.strip()))
    invalid = [item for item in requested if item not in _TARGETS]
    if invalid:
        raise HTTPException(status_code=422, detail=f"未登记的联动目标：{'、'.join(invalid)}")
    return requested  # type: ignore[return-value]


@router.get("/status", response_model=LinkedSystemsRuntime)
def linked_systems_status(
    targets: Optional[str] = Query(default=None, max_length=120),
) -> LinkedSystemsRuntime:
    selected = _selected_targets(targets)
    systems = {target: _runtime(target) for target in selected}
    return LinkedSystemsRuntime(
        systems=systems,
        all_ready=bool(systems) and all(item.running for item in systems.values()),
    )


@router.post("/launch", response_model=LinkedSystemsRuntime, status_code=202)
def launch_linked_systems(payload: LinkedSystemsLaunchRequest) -> LinkedSystemsRuntime:
    selected = list(dict.fromkeys(payload.targets))
    systems: dict[str, LinkedSystemRuntime] = {}
    with _launch_lock:
        for target in selected:
            try:
                systems[target] = _launch_target(target)
            except HTTPException as exc:
                runtime = _runtime(target)
                runtime.state = "port_conflict" if exc.status_code == 409 else "error"
                runtime.running = False
                runtime.message = str(exc.detail)
                systems[target] = runtime
    return LinkedSystemsRuntime(
        systems=systems,
        all_ready=all(item.running for item in systems.values()),
    )
