from datetime import datetime,timezone
from pathlib import Path
import json,os,subprocess
from app.config import BASE_DIR

def component_snapshot():
    root=BASE_DIR.parent.parent;manager=root/"envs/manager/Scripts/python.exe"
    checked=lambda:datetime.now(timezone.utc).isoformat()
    if os.name!="nt" or not manager.is_file() or not (root/"manage.py").is_file():
        from app.model_gateway import model_gateway
        from app.system_api import readiness_payload
        ready = readiness_payload()["status"] == "ready"
        provider = model_gateway.status()["provider"]
        return {
            "checked_at": checked(), "state": "checked", "scope": "application",
            "services": {"xiaoyi": {"state": "ready" if ready else "unresponsive", "port": None}},
            "inference": {"state": "not_configured" if provider == "local_rules" else "unverified"},
            "ready_http_services": int(ready), "http_service_count": 1, "production_authority": False,
        }
    try:
        raw=subprocess.check_output([manager,"-X","utf8",Path(__file__).with_name("managed_probe.py")],
            timeout=12,encoding="utf-8",creationflags=subprocess.CREATE_NO_WINDOW)
        services=json.loads(raw)
    except (ValueError,OSError,subprocess.SubprocessError):
        return {"checked_at":checked(),"state":"unavailable","services":{},"inference":{"state":"unverified"}}
    llm=services.get("llm",{}).get("state")
    if llm=="ready":
        try:
            from app.harness.gullmate_14b import inventory
            identity=inventory()["live"]
        except (ValueError,OSError,KeyError):
            identity={"state":"unverified"}
    else:identity={"state":"offline" if llm=="offline" else "unverified"}
    return {"state":"checked","checked_at":checked(),"services":services,"inference":identity,
            "ready_http_services":sum(v["state"]=="ready" for v in services.values()),
            "http_service_count":sum(v["port"] is not None for v in services.values()),"production_authority":False}
