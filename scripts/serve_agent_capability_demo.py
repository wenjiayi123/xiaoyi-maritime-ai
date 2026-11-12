"""Local demonstration UI; shares the existing single 1.7B inference worker."""
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

PAGE = """<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>舷鸥港航任务演示</title>
<style>*{box-sizing:border-box}body{margin:0;font:16px/1.7 -apple-system,BlinkMacSystemFont,sans-serif;background:#f3f6f8;color:#173044}main{max-width:1000px;margin:auto;padding:32px 24px}header{padding-bottom:20px;border-bottom:2px solid #285065}h1{font-size:30px;margin:8px 0}h2{font-size:21px}p{margin:8px 0}.muted{color:#586e7d}.panel{background:white;padding:24px;margin-top:22px;border:1px solid #dce5e9;border-radius:10px}.row{display:flex;gap:18px;flex-wrap:wrap}.row label{flex:1;min-width:220px}label{display:block;font-weight:600}select,textarea,button{font:inherit}select,textarea{display:block;width:100%;padding:10px;border:1px solid #b8c8d1;border-radius:5px;background:white;color:#173044}textarea{min-height:140px;resize:vertical;margin-top:8px}button{margin-top:16px;padding:10px 24px;border:0;border-radius:5px;background:#087f80;color:white;cursor:pointer}button:disabled{opacity:.55;cursor:wait}a{color:#087675}#status{padding:12px 0;font-weight:600}ol{padding-left:24px}li{margin:10px 0}li span{display:block;color:#586e7d;font-size:14px}#report{font-weight:600}code{overflow-wrap:anywhere}details{margin-top:18px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}footer{margin:24px 0;font-size:14px;color:#586e7d}@media(max-width:600px){main{padding:20px 12px}.panel{padding:16px}h1{font-size:25px}}</style>
<main><header><p class='muted'>舷鸥 · SFT 与 SFT＋RL 双路线</p><h1>交给舷鸥完成一项港航任务</h1><p>选择模型、下达指令，查看工具调用过程和最终报告。</p></header>
<section class='panel'><div class='row'><label>模型版本<select id='model'><option value='E_more_sft'>SFT 版</option><option value='D_rl'>SFT＋RL 版</option></select></label><label>示例任务<select id='example'></select></label></div><label style='margin-top:16px'>任务指令<textarea id='goal'></textarea></label><p class='muted' id='fault'></p><button id='run'>开始执行</button><div id='status' role='status' aria-live='polite'>正在检查模型服务……</div></section>
<section class='panel'><h2>执行过程</h2><p class='muted'>每一步由所选模型决定，完成后可打开带来源和核验结果的报告。</p><ol id='steps'></ol><p id='report'></p><details><summary>查看完整决策记录</summary><pre id='raw'>尚未开始任务。</pre></details></section>
<footer>本入口调用本机工程模拟系统，不控制生产设备。支持已登记任务类型；报告数值来自工具返回结果。<br><a href='/index.html'>查看训练曲线、参数更新及全部复验证据</a></footer></main>
<script>
let protocol, active=null;const el=id=>document.getElementById(id);const toolNames={'port.read':'读取港口状态','energy.read':'读取能碳状态','traffic.read':'读取交通状态','port.evaluate':'执行港口情景评估','energy.compare':'比较能碳方案','execution.verify':'核验结果','artifact.report':'交付报告','execution.diagnose':'诊断接口'};
function fill(){const c=protocol.cases[Number(el('example').value)];el('goal').value=c.goal;el('fault').textContent=c.fault?'此示例包含一次可恢复的读取故障，用于演示异常处理。':'此示例使用正常接口流程。'}
async function init(){try{const r=await fetch('/api/status');if(!r.ok)throw new Error('服务不可用');const s=await r.json();protocol=s.protocol;for(const [i,c] of protocol.cases.entries()){const o=document.createElement('option');o.value=i;o.textContent=c.title;el('example').append(o)}fill();el('status').textContent=s.ready?'模型服务就绪，可以开始执行。':'模型服务暂未就绪。';el('run').disabled=!s.ready}catch(e){el('status').textContent=e.message;el('run').disabled=true}}
el('example').onchange=fill;
function render(job){el('steps').replaceChildren();for(const s of job.steps){const li=document.createElement('li'),title=document.createElement('b'),text=document.createElement('span');title.textContent=(toolNames[s.action.tool]||s.action.tool);text.textContent=(s.ok?'完成':'返回反馈')+' · '+s.feedback;li.append(title,text);el('steps').append(li)}el('raw').textContent=JSON.stringify(job,null,2);el('status').textContent=job.status==='running'?'执行中 · 已完成 '+job.steps.length+' 个决策步骤':job.status==='completed'?'任务完成，结果已核验。':job.status==='queued'?'任务已提交。':'本次任务未完成，记录已保留。';if(job.status==='completed'){const a=document.createElement('a');a.href='/evidence/'+job.id+'/report.html';a.target='_blank';a.rel='noopener';a.textContent='打开完整任务报告';el('report').replaceChildren(a)}if(['completed','failed'].includes(job.status)){active=null;el('run').disabled=false;el('example').disabled=false;el('model').disabled=false;el('goal').disabled=false}}
async function poll(){if(!active)return;try{const r=await fetch('/api/jobs/'+active);const job=await r.json();if(!r.ok)throw new Error(job.error||'读取失败');render(job)}catch(e){el('status').textContent='读取进度暂时失败：'+e.message}if(active)setTimeout(poll,1200)}
el('run').onclick=async()=>{el('run').disabled=true;el('report').replaceChildren();el('steps').replaceChildren();try{const r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-Capability-Demo':'1'},body:JSON.stringify({group:el('model').value,goal:el('goal').value,inject_read_fault:protocol.cases[Number(el('example').value)].fault})});const j=await r.json();if(!r.ok)throw new Error(j.error||'提交失败');active=j.id;el('example').disabled=true;el('model').disabled=true;el('goal').disabled=true;render(j);poll()}catch(e){el('status').textContent=e.message;el('run').disabled=false}};init();
</script></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--round", type=Path, default=core.BASE / "round-004")
    parser.add_argument("--port", type=int, default=18789)
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
                       "experiment": "experiment-004", "environment": core.REVISION,
                       "expected_adapter_sha256": protocol["models"][group]["parameter_fingerprint"],
                       "production_authority": False, "fault_injection_requested": fault,
                       "origin": "interactive_browser_demo", "protocol": str(args.round / "PROTOCOL.json")}
                folder = live_root / ident
                core.live.save(folder / "job.json", job)

                def work():
                    try:
                        with (core.BASE / "execution.lock").open("a") as lock:
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
