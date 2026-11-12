"""Read managed process identities and service probes using the same registry as portai.cmd."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import manage
import psutil

def sample():
    entries=manage.services();state=manage.read_state()
    listeners={}
    for c in psutil.net_connections(kind="tcp"):
        if c.status==psutil.CONN_LISTEN and c.laddr and c.laddr.ip in ("127.0.0.1","0.0.0.0","::","::1"):
            listeners.setdefault(c.laddr.port,set()).add(c.pid)
    def probe(name):
        _,_,port,route,_=entries[name]
        proc=manage.process_for(state.get(name))
        if not proc:
            return {"state":"unmanaged" if port in listeners else "offline","port":port}
        if port is None:
            status="process_only"
        else:
            try:owners={proc.pid,*(child.pid for child in proc.children(recursive=True))}
            except (psutil.NoSuchProcess,psutil.AccessDenied):owners=set()
            if port in listeners and not owners.intersection(listeners[port]):status="unmanaged"
            else:status="ready" if port in listeners and manage.ready(port,route) else "unresponsive"
        return {"state":status,"port":port}
    with ThreadPoolExecutor(max_workers=7) as workers:
        return dict(zip(entries,workers.map(probe,entries)))
if __name__=="__main__":print(json.dumps(sample()))
