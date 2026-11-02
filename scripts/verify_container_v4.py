"""Build the current image in the owned Linux guest and verify hardened local startup."""

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/remediation-v4-20261030"
LIMA = ROOT / ".runtime/tools/lima-2.2.1/bin/limactl"
ENV = {**os.environ, "LIMA_HOME": str(ROOT / ".runtime/container-vm")}
NAME = "xiaoyi-v4-accepted-20261030"
IMAGE = "xiaoyi-ai:accepted-v4-20261030"


def guest(*args, input_text=None, log=None, timeout=120):
    command = [str(LIMA), "shell", "--workdir=/mnt/xiaoyi", "xiaoyi-build", *args]
    if log:
        with (OUT / log).open("x") as handle:
            result = subprocess.run(command, env=ENV, input=input_text, text=True, stdout=handle,
                                    stderr=subprocess.STDOUT, timeout=timeout)
    else:
        result = subprocess.run(command, env=ENV, input=input_text, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("guest command failed: " + " ".join(args[:4]) + "; " + (log or result.stderr[-1000:]))
    return result.stdout


def health():
    last = None
    for _ in range(30):
        try:
            with urlopen("http://127.0.0.1:18010/health/ready", timeout=3) as response:
                data = json.load(response)
            if data["status"] == "ready":
                return data
        except Exception as error:
            last = type(error).__name__
        time.sleep(1)
    raise RuntimeError("container did not become ready: " + str(last))


def main():
    receipt = OUT / "container-acceptance.json"
    if receipt.exists():
        raise ValueError("never overwrite container acceptance")
    quality = json.loads((OUT / "repository-quality.json").read_text())
    sources = quality["source_sha256"]
    guest("sudo", "docker", "compose", "-f", "/mnt/xiaoyi/compose.yaml", "config", "--quiet",
          log="docker-compose-final.log")
    guest("sudo", "docker", "build", "--progress=plain", "--tag", IMAGE, ".",
          log="docker-build-final.log", timeout=900)
    # Only our previously accepted stage3 container is stopped; no shared workloads.
    guest("sudo", "docker", "stop", "xiaoyi-v3-accepted-20261030")
    guest("sudo", "docker", "run", "--detach", "--name", NAME, "--read-only",
          "--tmpfs", "/tmp:size=64m,mode=1777", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
          "-p", "127.0.0.1:18010:8010", "-e", "XIAOYI_ENV=local", "-e", "XIAOYI_SECURITY_MODE=local",
          "--mount", "type=volume,source=xiaoyi-v4-accepted-runtime,target=/app/runtime",
          "--mount", "type=volume,source=xiaoyi-v4-accepted-rl,target=/app/data/rl_runs",
          "--mount", "type=volume,source=xiaoyi-v4-accepted-kb,target=/app/data/kb_pending", IMAGE,
          log="docker-run-final.log")
    before = health()
    code = """import json,sys,hashlib,os,pathlib
expected=json.load(sys.stdin)
drift=[p for p,h in expected.items() if not pathlib.Path('/app',p).is_file() or hashlib.sha256(pathlib.Path('/app',p).read_bytes()).hexdigest()!=h]
excluded=[p for p in ['.env','.runtime/models','.runtime/open-models','artifacts/lora','data/xiaoyi_runtime.db'] if pathlib.Path('/app',p).exists()]
pathlib.Path('/app/runtime/container-acceptance-marker.json').write_text('local-owned-persistence-check')
print(json.dumps({'uid':os.getuid(),'source_count':len(expected),'source_drift':drift,'excluded_host_material_present':excluded}))
"""
    source_check = json.loads(guest("sudo", "docker", "exec", "-i", NAME, "python", "-c", code,
                                    input_text=json.dumps(sources)))
    with urlopen("http://127.0.0.1:18010/api/harness/assurance/remediation-v4", timeout=60) as response:
        research = json.load(response)
    guest("sudo", "docker", "stop", "--time", "10", NAME)
    guest("sudo", "docker", "start", NAME)
    after = health()
    marker = guest("sudo", "docker", "exec", NAME, "python", "-c",
                   "from pathlib import Path;print(Path('/app/runtime/container-acceptance-marker.json').read_text())").strip()
    inspect = json.loads(guest("sudo", "docker", "inspect", NAME))[0]
    image = json.loads(guest("sudo", "docker", "image", "inspect", IMAGE))[0]
    checks = {"build_current_image": True, "compose_config": True, "non_root": source_check["uid"] != 0,
              "read_only": inspect["HostConfig"]["ReadonlyRootfs"],
              "all_capabilities_dropped": inspect["HostConfig"]["CapDrop"] == ["ALL"],
              "no_new_privileges": "no-new-privileges:true" in inspect["HostConfig"]["SecurityOpt"],
              "sources_match_host": not source_check["source_drift"],
              "no_host_env_db_or_llm_weights": not source_check["excluded_host_material_present"],
              "restart_volume_persistence": marker == "local-owned-persistence-check",
              "health_before_and_after": before["status"] == after["status"] == "ready",
              "packaged_research_sources_current": research["current"],
              "production_authority_disabled": not after["runtime_posture"]["production_authority"] and not research["production_authority"]}
    report = {"schema": "xiaoyi-container-acceptance.v4", "checked_at": datetime.now(timezone.utc).isoformat(),
              "passed": all(checks.values()), "status": "Docker实际构建、当前源码、非root只读启动、重启持久化和健康探针已验证",
              "checks": checks, "image": {"tag": IMAGE, "id": image["Id"], "architecture": image["Architecture"],
                  "size_bytes": image["Size"], "base_digest": "sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f"},
              "engine_version": guest("sudo", "docker", "version", "--format", "{{.Server.Version}}").strip(),
              "source_sha256": sources, "source_check": source_check, "health_before": before, "health_after": after,
              "packaged_research_summary": {"current": research["current"], "weather_modes": research["physical"]["modes"],
                  "short_legacy_passed": research["legacy_summary"]["short_passed"], "scored_functions": len(research["scorecard"]["components"]),
                  "production_authority": research["production_authority"]},
              "evidence_logs_sha256": {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in
                  ["docker-compose-final.log", "docker-build-final.log", "docker-run-final.log"]},
              "notice": "Owned Linux VM, local container only. Host4B/embedding model weights and historical SQLite are excluded; this container does not prove local LLM inference or field/HIL/OT/production qualification. Its own final external receipt cannot be embedded into the image that it identifies.",
              "production_authority": False}
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": checks, "image_id": image["Id"]}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
