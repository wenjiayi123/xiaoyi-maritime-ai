"""Isolated native sample; no interactive controls or model weights are changed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from app.config import BASE_DIR
from app.harness.contracts import encoded


def validate_sample(run_id, cancelled=lambda: False):
    from app import sailing_simulator_launcher as launcher

    if not launcher._runtime().launchable:
        raise ValueError("航行项目或Godot未就绪；请检查登记路径")
    folder = BASE_DIR / ".runtime/harness-sailing" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    request = {"requestId": run_id, "scope": "isolated_native_4_second_sample", "production_authority": False}
    source, result = folder / "request.json", folder / "result.json"
    # The caller supplies a unique, durable linked-run id. Never reuse an old receipt.
    if source.exists() or result.exists():
        raise ValueError("该原生航行尝试已存在，禁止重复执行；请读取原回执")
    source.write_text(encoded(request))
    script = launcher._SAILING_ROOT / "tools/harness_joint_validation.gd"
    if not script.is_file():
        raise ValueError("登记原生验证脚本缺失")
    env = {**os.environ, "XIAOYI_JOINT_REQUEST": str(source), "XIAOYI_JOINT_RESULT": str(result),
           "XIAOYI_SIM_BRIDGE_DIR": str(folder / "bridge")}
    started = time.monotonic()
    with (folder / "godot.log").open("a") as log:
        process = subprocess.Popen([str(launcher._GODOT_BINARY), "--headless", "--fixed-fps", "60",
            "--path", str(launcher._SAILING_ROOT), "--script", "res://tools/harness_joint_validation.gd"],
            env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                if cancelled():
                    raise ValueError("用户停止原生样本任务；未声明验证成功")
                if time.monotonic() - started > 90:
                    raise TimeoutError("原生样本超时")
                time.sleep(.15)
            if process.returncode or not result.is_file():
                raise ValueError("原生样本未返回成功回执；查看当前尝试的godot.log")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=4)
    raw = json.loads(result.read_text())
    checks = {
        "request_bound": raw.get("requestId") == run_id and raw.get("source_request_sha256") == hashlib.sha256(source.read_bytes()).hexdigest(),
        "scene_loaded": raw.get("scene_loaded") is True,
        "actor_loaded": raw.get("actor_loaded") is True and raw.get("inference_count", 0) > 0,
        "sample_passed": raw.get("validation", {}).get("safePass") is True,
        "production_disabled": raw.get("production_authority") is False,
    }
    if not all(checks.values()):
        raise ValueError("原生样本回执绑定、策略加载或验证未通过：" + encoded(checks))
    return {"raw": raw, "checks": checks, "receipt_sha256": hashlib.sha256(result.read_bytes()).hexdigest(),
            "scope": "独立Godot原生4秒样本；非完整航次、非原生窗口点击、非实船控制", "production_authority": False}
