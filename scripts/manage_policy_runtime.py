"""Start/check/stop the pinned local guest; no host Python or model replacement."""

from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness.transport import health  # noqa: E402

LIMA = ROOT / ".runtime/tools/lima-2.2.1/bin/limactl"
ENV = {**os.environ, "LIMA_HOME": str(ROOT / ".runtime/policy-vm")}
NAME = "xiaoyi-policy-runtime"


def command(*args):
    return subprocess.run([str(LIMA), *args], env=ENV, cwd=ROOT, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["check", "start", "stop", "bootstrap", "freeze"], default="check", nargs="?")
    args = p.parse_args()
    if args.action == "stop":
        command("stop", NAME)
        return
    if args.action in ["start", "bootstrap"]:
        if not LIMA.is_file():
            raise SystemExit(
                "Missing pinned Lima 2.2.1. Follow docs/HARNESS_POLICY_RUNTIME_20261029.md; do not change the original environments."
            )
        command("start", "--tty=false", NAME)
        if args.action == "bootstrap":
            command("shell", NAME, "--", "bash", "/opt/xiaoyi/runtime/bootstrap.sh")
            command(
                "shell",
                NAME,
                "--",
                "sudo",
                "cp",
                "/opt/xiaoyi/runtime/xiaoyi-policy.service",
                "/etc/systemd/system/xiaoyi-policy.service",
            )
            command("shell", NAME, "--", "sudo", "systemctl", "daemon-reload")
            command("shell", NAME, "--", "sudo", "systemctl", "enable", "xiaoyi-policy.service")
        command("shell", NAME, "--", "sudo", "systemctl", "restart", "xiaoyi-policy.service")
        for _ in range(60):
            try:
                data = health()
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("Policy service not ready within 30 seconds; inspect guest systemd logs.")
    else:
        data = health()
    if args.action == "freeze":
        directory = ROOT / ".codex_artifacts/joint-harness-phase2-20261029"
        with (directory / "guest-pip-freeze.txt").open("w") as f:
            subprocess.run(
                [str(LIMA), "shell", NAME, "--", "/home/apple.guest/policy-env/bin/pip", "freeze"],
                env=ENV,
                stdout=f,
                check=True,
            )
        (directory / "policy-runtime-final.json").write_text(json.dumps(data, indent=2))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
