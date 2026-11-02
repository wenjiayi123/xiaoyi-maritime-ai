"""Run all normally admitted native scenes from origin to their own completion predicate."""

from pathlib import Path
import hashlib
import json
import os
import subprocess
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("XIAOYI_SAILING_SIMULATOR_ROOT", str(Path.home() / "Desktop/航行模拟器"))
os.environ.setdefault(
    "XIAOYI_GODOT_BINARY",
    str(Path(__file__).resolve().parents[1] / ".runtime/tools/godot-4.7.1/Godot.app/Contents/MacOS/Godot"),
)
from app.harness.contracts import encoded, digest
from app.sailing_simulator_launcher import _GODOT_BINARY, _SAILING_ROOT

root = Path(".codex_artifacts/joint-harness-phase2-20261029/native-voyages").resolve()
root.mkdir(parents=True, exist_ok=True)
scenes = [
    "harbor",
    "auto_berthing",
    "auto_unberthing",
    "narrow_channel_head_on",
    "crossing_starboard",
    "narrow_channel_overtaking",
]
# open_water is rerun through the actual Harness UI; the independent earlier full receipt is retained too.
results = []
for scene in scenes:
    folder = root / scene
    folder.mkdir(exist_ok=True)
    req = {
        "requestId": "scene-accept-" + scene,
        "voyage_scenario": scene,
        "overtaking_agreement_confirmed": scene == "narrow_channel_overtaking",
        "production_authority": False,
    }
    request = folder / "request.json"
    result = folder / "result.json"
    request.write_text(encoded(req))
    env = os.environ.copy()
    env.update(
        XIAOYI_JOINT_REQUEST=str(request), XIAOYI_JOINT_RESULT=str(result), XIAOYI_SIM_BRIDGE_DIR=str(folder / "bridge")
    )
    started = time.time()
    with (folder / "godot.log").open("w") as log:
        try:
            child = subprocess.run(
                [
                    str(_GODOT_BINARY),
                    "--headless",
                    "--fixed-fps",
                    "60",
                    "--path",
                    str(_SAILING_ROOT),
                    "--script",
                    "res://tools/harness_full_voyage.gd",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=2000,
            )
            raw = json.loads(result.read_text()) if result.exists() else {}
            passed = (
                child.returncode == 0
                and raw.get("validation", {}).get("safePass") is True
                and raw.get("source_request_sha256") == digest(req)
            )
            entry = {
                "scene": scene,
                "exit_code": child.returncode,
                "passed": passed,
                "wall_seconds": time.time() - started,
                "receipt": raw,
            }
        except Exception as exc:
            entry = {"scene": scene, "passed": False, "error": str(exc), "wall_seconds": time.time() - started}
    results.append(entry)
    (root / "matrix.json").write_text(
        json.dumps({"complete": len(results) == len(scenes), "results": results}, ensure_ascii=False, indent=2)
    )
    print(scene, entry["passed"], round(entry["wall_seconds"], 1), flush=True)
