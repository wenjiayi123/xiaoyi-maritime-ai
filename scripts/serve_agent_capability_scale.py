"""Expanded30 task UI; shares one base model and preserves the accepted version."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_capability_demo as core  # noqa: E402
from scripts import run_agent_capability_demo_v2 as wording  # noqa: E402

from scripts.serve_agent_capability_demo import PAGE as ACCEPTED_PAGE  # noqa: E402

ACCEPTED_BASE = core.BASE
core.BASE = ROOT / ".codex_artifacts/agent-rl-capability-scale-20261102"
PAGE = ACCEPTED_PAGE.replace("value='D_rl'", "value='D_scale_rl'").replace("交给舷鸥完成一项港航任务", "舷鸥 · 30项港航任务演示").replace("SFT＋RL 版</option>", "SFT＋RL 扩展版（新增64次更新）</option>")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--round", type=Path, default=core.BASE / "live-registration")
    parser.add_argument("--port", type=int, default=18790)
    args = parser.parse_args()
    core.prompt_for = wording.prompt_for
    protocol = core.verify(args.round.resolve())
    # Follow the local publication symlink per request so a verified new
    # showcase can replace the previous edition without restarting the model.
    report = args.report.absolute()
    live_root = core.BASE / "live-demo"
    live_root.mkdir(exist_ok=True)
    busy = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(report), **kw)

        def reply(self, status, value):
            payload = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/control":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(PAGE.encode())
            elif path == "/api/status":
                try:
                    h = core.live.local_request("http://127.0.0.1:18781", "/health", timeout=3)
                    ready = all(h["weights"].get(g) == protocol["models"][g]["parameter_fingerprint"] for g in protocol["groups"])
                except Exception:
                    ready = False
                self.reply(200, {"ready": ready, "protocol": protocol, "model_loaded_in_this_service": False})
            elif path.startswith("/api/jobs/"):
                ident = path.split("/")[-1]
                if len(ident) != 37 or not ident.startswith("live-") or not all(c in "0123456789abcdef" for c in ident[5:]):
                    return self.reply(404, {"error": "任务不存在"})
                p = live_root / ident / "job.json"
                self.reply(200, core.read(p)) if p.exists() else self.reply(404, {"error": "任务不存在"})
            elif path.startswith("/evidence/"):
                parts = path.split("/")
                if len(parts) != 4 or parts[2] in {"", ".", ".."} or parts[3] in {"", ".", ".."}:
                    return self.reply(404, {"error": "文件不存在"})
                p = (live_root / parts[2] / parts[3]).resolve()
                if live_root not in p.parents or not p.is_file() or p.suffix not in {".json", ".html"}:
                    return self.reply(404, {"error": "文件不存在"})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8" if p.suffix == ".html" else "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(p.read_bytes())
            else:
                super().do_GET()

        def do_POST(self):
            if self.path != "/api/jobs":
                return self.reply(404, {"error": "未知接口"})
            if (self.headers.get("Origin") not in {f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"}
                    or self.headers.get("X-Capability-Demo") != "1"
                    or not self.headers.get("Content-Type", "").startswith("application/json")):
                return self.reply(403, {"error": "请通过本机演示页面提交任务"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length < 12000:
                    raise ValueError("请求长度超限")
                body = json.loads(self.rfile.read(length))
                group = body["group"]
                if group not in protocol["groups"]:
                    raise ValueError("未知模型版本")
                fault = body.get("inject_read_fault", False)
                if not isinstance(fault, bool):
                    raise ValueError("错误的故障选项")
                task = core.live.parse_goal(body["goal"], inject_read_fault=fault)
                if task.family == "clock_restore":
                    raise ValueError("此演示入口暂不包含时钟控制，请使用所列任务")
                if not busy.acquire(blocking=False):
                    return self.reply(409, {"error": "当前已有任务执行中，请稍候"})
                ident = "live-" + uuid4().hex
                job = {"id": ident, "goal": body["goal"], "task": asdict(task), "group": group,
                       "status": "queued", "success": False, "steps": [], "evidence": [],
                       "experiment": "capability-scale-adaptation-002", "environment": core.REVISION,
                       "expected_adapter_sha256": protocol["models"][group]["parameter_fingerprint"],
                       "production_authority": False, "fault_injection_requested": fault,
                       "origin": "interactive_browser_demo", "protocol": str(args.round / "PROTOCOL.json")}
                folder = live_root / ident
                core.live.save(folder / "job.json", job)

                def work():
                    try:
                        with (ACCEPTED_BASE / "execution.lock").open("a") as lock:
                            import fcntl
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            core.verify(args.round.resolve())
                            finished = core.execute(job, folder, protocol)
                            core.live.save(folder / "AUDIT.json", core.audit_job(finished, folder, protocol))
                    except Exception as exc:
                        job.update(status="failed", success=False, error=str(exc))
                        core.live.save(folder / "job.json", job)
                    finally:
                        busy.release()
                threading.Thread(target=work, daemon=True).start()
                self.reply(202, job)
            except Exception as exc:
                self.reply(400, {"error": str(exc)[:300]})

        def log_message(self, *args):
            pass

    print(json.dumps({"ready": True, "url": f"http://127.0.0.1:{args.port}/control", "model_loaded": False}), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
