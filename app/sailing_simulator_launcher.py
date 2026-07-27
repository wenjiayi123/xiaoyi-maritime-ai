from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/sailing-simulator", tags=["航行模拟器启动器"])

SailingSimulatorState = Literal["offline", "starting", "online", "error", "unavailable"]

_XIAOYI_ROOT = Path(__file__).resolve().parents[1]
_SAILING_ROOT = Path(
    os.getenv("XIAOYI_SAILING_SIMULATOR_ROOT", str(_XIAOYI_ROOT / ".integrations/sailing-simulator"))
).expanduser()
_GODOT_BINARY = Path(
    os.getenv("XIAOYI_GODOT_BINARY", shutil.which("godot") or str(_XIAOYI_ROOT / ".integrations/bin/godot"))
).expanduser()
_PROJECT_CONFIG = _SAILING_ROOT / "project.godot"
_LOG_PATH = _XIAOYI_ROOT / ".runtime" / "sailing-simulator.log"
_BRIDGE_DIR = Path(
    os.getenv(
        "XIAOYI_SAILING_BRIDGE_DIR",
        str(_XIAOYI_ROOT / ".runtime" / "sailing-bridge"),
    )
).expanduser()
_launch_lock = RLock()
_sailing_process: Optional[subprocess.Popen[bytes]] = None
_launched_at: Optional[float] = None


class SailingSimulatorLaunchRequest(BaseModel):
    target: Literal["sailing-simulator"] = "sailing-simulator"


class SailingSimulatorRuntime(BaseModel):
    target: Literal["sailing-simulator"] = "sailing-simulator"
    name: str = "航行模拟器"
    state: SailingSimulatorState
    running: bool
    launchable: bool
    managed_by_xiaoyi: bool
    already_running: bool = False
    pid: Optional[int] = None
    project_root: str
    project_config: str
    engine_path: str
    main_scene_configured: bool
    message: str


def _project_has_main_scene() -> bool:
    try:
        content = _PROJECT_CONFIG.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(
        line.strip().startswith("run/main_scene=") and line.partition("=")[2].strip().strip('"')
        for line in content.splitlines()
    )


def _managed_process() -> tuple[bool, Optional[int], Optional[int]]:
    process = _sailing_process
    if process is None:
        return False, None, None
    return process.poll() is None, process.pid, process.poll()


def _external_process_pid() -> Optional[int]:
    """Find an already-running Godot process bound to the registered project."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    root = str(_SAILING_ROOT)
    engine = str(_GODOT_BINARY)
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text, _, command = line.partition(" ")
        if not pid_text.isdigit():
            continue
        if engine in command and root in command and "--path" in command:
            return int(pid_text)
    return None


def _activation_available() -> bool:
    return Path("/usr/bin/osascript").is_file()


def _activate_godot() -> None:
    if not _activation_available():
        return
    try:
        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                'tell application "Godot" to activate',
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        # Launch success does not depend on macOS focus automation.
        return


def _runtime(*, already_running: bool = False) -> SailingSimulatorRuntime:
    project_exists = _SAILING_ROOT.is_dir() and _PROJECT_CONFIG.is_file()
    engine_ready = _GODOT_BINARY.is_file() and os.access(_GODOT_BINARY, os.X_OK)
    main_scene = _project_has_main_scene() if project_exists else False
    launchable = project_exists and engine_ready and main_scene
    managed, managed_pid, return_code = _managed_process()
    external_pid = None if managed else _external_process_pid()

    if managed:
        elapsed = monotonic() - (_launched_at or 0.0)
        state: SailingSimulatorState = "starting" if elapsed < 0.8 else "online"
        message = (
            "航行模拟器进程已拉起，正在加载主场景。"
            if state == "starting"
            else "航行模拟器主进程正在运行。"
        )
        pid = managed_pid
    elif external_pid is not None:
        state = "online"
        message = "检测到航行模拟器已在运行，将直接复用现有 Godot 窗口。"
        pid = external_pid
    elif return_code is not None:
        state = "error"
        message = f"航行模拟器进程提前退出（code={return_code}），请查看启动日志。"
        pid = None
    elif not project_exists:
        state = "unavailable"
        message = "未找到登记的桌面航行模拟器项目或 project.godot。"
        pid = None
    elif not engine_ready:
        state = "unavailable"
        message = "Godot 运行程序不可用，无法启动桌面航行模拟器。"
        pid = None
    elif not main_scene:
        state = "unavailable"
        message = "航行模拟器未配置主场景，已阻止空项目启动。"
        pid = None
    else:
        state = "offline"
        message = "航行模拟器项目与 Godot 运行环境已就绪，等待启动。"
        pid = None

    return SailingSimulatorRuntime(
        state=state,
        running=state == "online",
        launchable=launchable,
        managed_by_xiaoyi=managed,
        already_running=already_running,
        pid=pid,
        project_root=str(_SAILING_ROOT),
        project_config=str(_PROJECT_CONFIG),
        engine_path=str(_GODOT_BINARY),
        main_scene_configured=main_scene,
        message=message,
    )


@router.get("/status", response_model=SailingSimulatorRuntime)
def sailing_simulator_status() -> SailingSimulatorRuntime:
    return _runtime()


@router.post("/launch", response_model=SailingSimulatorRuntime, status_code=202)
def launch_sailing_simulator(
    payload: SailingSimulatorLaunchRequest,
) -> SailingSimulatorRuntime:
    del payload  # The request model intentionally fixes the only allowed target.
    global _sailing_process, _launched_at

    with _launch_lock:
        current = _runtime()
        if current.state == "online":
            current.already_running = True
            _activate_godot()
            return current
        if current.state == "starting":
            current.already_running = True
            return current
        if not current.launchable:
            raise HTTPException(status_code=503, detail=current.message)

        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with _LOG_PATH.open("ab", buffering=0) as log_file:
                env = os.environ.copy()
                env["XIAOYI_SIM_BRIDGE_DIR"] = str(_BRIDGE_DIR)
                _sailing_process = subprocess.Popen(
                    [str(_GODOT_BINARY), "--path", str(_SAILING_ROOT)],
                    cwd=str(_SAILING_ROOT),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
                _launched_at = monotonic()
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"航行模拟器启动失败：{exc}") from exc

        return _runtime()


@router.post("/focus", response_model=SailingSimulatorRuntime)
def focus_sailing_simulator(
    payload: SailingSimulatorLaunchRequest,
) -> SailingSimulatorRuntime:
    del payload
    runtime = _runtime()
    if runtime.state not in {"starting", "online"}:
        raise HTTPException(status_code=409, detail="航行模拟器尚未运行，无法切换窗口。")
    _activate_godot()
    runtime.message = "已请求将航行模拟器窗口切换到前台。"
    return runtime
