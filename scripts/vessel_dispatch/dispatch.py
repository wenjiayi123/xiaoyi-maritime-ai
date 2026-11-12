"""Construct complete hourly Shanghai vessel schedules by selecting a vessel and a feasible slot."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import numpy as np
import torch
from torch import nn

WORK=Path(__file__).resolve().parent
DEPLOY=Path("G:/AI/WindowsDeploy")
APP=DEPLOY/"apps/xiaoyi"
ROOT=Path("G:/AI/Runs/gullmate-next-20261106/vessel-dispatch")
sys.path.insert(0,str(APP))
from integrations.shanghai_lab_v1.planning import objective
from integrations.shanghai_lab_v1.protocol import validate_plan

torch.set_num_threads(1)
FEATURES=("arrival","duration","slack","cranes","shore","priority","remaining_jobs","start","wait","late",
          "service_energy_cost","objective","dynamic_crane_margin","dynamic_import_margin","next_free_berths","progress")


def read(p):return json.loads(p.read_bytes())
def hashfile(p):return sha256(p.read_bytes()).hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+"."+uuid4().hex+".part")
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


@contextmanager
def sandbox():
    proc=subprocess.Popen([str(DEPLOY/"tools/node.exe"),"--experimental-strip-types",str(WORK/"native.mjs"),"worker"],
                          stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding="utf-8",creationflags=subprocess.CREATE_NO_WINDOW)
    def ask(case,plan=None):
        proc.stdin.write(json.dumps({"case":case,"plan":plan},ensure_ascii=True,separators=(",",":"))+"\n");proc.stdin.flush()
        reply=proc.stdout.readline()
        if not reply:raise RuntimeError("Native sandbox worker terminated")
        return json.loads(reply)
    try:yield ask
    finally:
        proc.stdin.close();proc.wait(timeout=30);proc.stdout.close()
        if proc.returncode:raise RuntimeError("Native reviewer worker exited abnormally")


class Actor(nn.Module):
    def __init__(self):
        super().__init__()
        self.network=nn.Sequential(nn.Linear(len(FEATURES),48),nn.Tanh(),nn.Linear(48,24),nn.Tanh(),nn.Linear(24,1))

    def forward(self,items):return self.network(items).squeeze(-1)


class Job:
    def __init__(self,case,source):
        self.data=source
        r,e=case["resources"],case["energy"]
        self.duration=source["duration_hours"]
        starts=np.arange(source["arrival_hour"],25-self.duration)
        self.slots=np.array([(s,b) for s in starts for b in range(r["berths"])],dtype=int).reshape(-1,2)
        self.hours=self.slots[:,0,None]+np.arange(self.duration)
        self.kw=source["shore_kw"]+source["cranes"]*e["crane_kw"]
        self.static=np.array(r["channel_open"])[self.slots[:,0]] & (self.slots[:,1,None]<np.array(r["berth_capacity"])[self.hours]).all(axis=1)
        self.tariff=np.array(e["price_cny_kwh"])[self.hours].sum(axis=1)*self.kw
        self.wait=self.slots[:,0]-source["arrival_hour"]
        self.late=np.maximum(0,self.slots[:,0]+self.duration-source["deadline_hour"])
        self.cost=self.tariff+self.wait*50*source["priority"]+self.late*case["delay_cny_vessel_hour"]


class Schedule:
    def __init__(self,case):
        self.case=case
        self.jobs=[Job(case,j) for j in case["jobs"]]
        r,e=case["resources"],case["energy"]
        self.max_starts=min(r["channel_concurrency"],r["pilots"],r["tugs"]//2)
        self.power_available=np.array(e["grid_limit_kw"])-np.array(e["base_kw"])+np.array(e["pv_kw"])

    def run(self,actor,mode):
        r=self.case["resources"];used=np.zeros((r["berths"],24),dtype=bool)
        power=self.power_available.copy();cranes=np.full(24,r["cranes"],dtype=int);starts=np.zeros(24,dtype=int)
        remaining=list(self.jobs);steps=[];logps=[];entropy=[];total=wait=late=0.
        while remaining:
            options=[];features=[]
            for job in remaining:
                j=job.data;h=job.hours;b=job.slots[:,1]
                ok=job.static & (starts[job.slots[:,0]]<self.max_starts) & (~used[b[:,None],h]).all(axis=1)
                ok &= (cranes[h]>=j["cranes"]).all(axis=1) & (power[h]>=job.kw-1e-8).all(axis=1)
                indices=np.flatnonzero(ok)
                if not len(indices):continue
                first=indices[0]
                near=indices[job.slots[indices,0]<=job.slots[first,0]+2]
                cheap=near[np.argmin(job.cost[near])]
                for idx in dict.fromkeys((first,cheap)):
                    start,berth=job.slots[idx];hours=h[idx]
                    features.append([j["arrival_hour"]/24,job.duration/6,(j["deadline_hour"]-start-job.duration)/12,j["cranes"]/4,
                        j["shore_kw"]/800,j["priority"]/3,len(remaining)/15,start/24,job.wait[idx]/12,job.late[idx]/8,
                        job.tariff[idx]/5000,job.cost[idx]/5000,cranes[hours].min()/r["cranes"],power[hours].min()/10000,
                        (~used[:,start]).sum()/r["berths"],len(steps)/len(self.jobs)])
                    options.append((job,idx))
            if not options:break
            if mode=="immediate_cost":
                i=min(range(len(options)),key=lambda k:options[k][0].cost[options[k][1]])
            else:
                logits=actor(torch.tensor(features,dtype=torch.float32))
                if mode=="sample":
                    dist=torch.distributions.Categorical(logits=logits)
                    choice=dist.sample();logps.append(dist.log_prob(choice));entropy.append(dist.entropy());i=choice.item()
                else:i=int(logits.argmax())
            job,idx=options[i];j=job.data;s,b=map(int,job.slots[idx]);h=job.hours[idx]
            used[b,h]=True;power[h]-=job.kw;cranes[h]-=j["cranes"];starts[s]+=1
            steps.append({"job_id":j["id"],"start_hour":s,"end_hour":s+job.duration,"berth":b})
            total+=job.cost[idx];wait+=job.wait[idx];late+=job.late[idx];remaining.remove(job)
        plan={"schema":"shanghai-plan.v1","port_id":self.case["port_id"],"trial_id":self.case["trial_id"],
              "source_snapshot_sha256":self.case["snapshot_sha256"],"scheduled":steps,"method":mode,"production_authority":False}
        # Energy per completed call is variable. An incomplete schedule must score below any completed candidate.
        penalty=total/1500.+wait*.5+late*3. if not remaining else 150.+len(remaining)*10
        return plan,-float(penalty),logps,entropy


def measures(case,plan):
    if plan is None or len(plan["scheduled"])!=len(case["jobs"]):return None
    valid=validate_plan(case,plan)
    for h,load in enumerate(valid["load_kw"]):
        if load-case["energy"]["pv_kw"][h]>case["energy"]["grid_limit_kw"][h]+1e-6:raise ValueError("Import capacity exceeded")
    return {k:valid[k] for k in ("wait_vessel_hours","late_vessel_hours","processed_teu","shore_kwh","crane_hours")}|{"objective_cny":objective(case,plan)}


def gates(metric,baseline):
    if metric is None or baseline is None:return {"complete_pair":False}
    return {"complete_pair":True,"handled_teu":metric["processed_teu"]==baseline["processed_teu"],
            "wait":metric["wait_vessel_hours"]<=baseline["wait_vessel_hours"],"late":metric["late_vessel_hours"]<=baseline["late_vessel_hours"],
            "service":metric["shore_kwh"]==baseline["shore_kwh"] and metric["crane_hours"]==baseline["crane_hours"],
            "strict_cost":metric["objective_cny"]<baseline["objective_cny"]-1e-6}
