"""Simulated vessel rescheduling with resource-checked single moves and pair exchanges."""
from dataclasses import dataclass
import numpy as np
import torch
from torch import nn

BUDGET=5
FEATURES=("immediate_saving","relative_saving","remaining_depth","wait_margin","lateness_margin","cost_to_anchor",
          "two_calls","shift_one","shift_two","old_start","new_start","duration_one","duration_two","priority_one",
          "priority_two","resource_slack","arrival_count","active_berths","neighborhood_best","neighborhood_density")


@dataclass
class Menu:
    states:np.ndarray
    cost:np.ndarray
    features:np.ndarray
    proposed:int


class RepairValue(nn.Module):
    def __init__(self):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(len(FEATURES),48),nn.Tanh(),nn.Linear(48,24),nn.Tanh(),nn.Linear(24,1))

    def forward(self,features):
        # Immediate savings are known; fit the return from later changes.
        return features[:,0]+self.net(features).squeeze(-1)


class Repair:
    def __init__(self,case,base):
        self.case=case;self.base=base;self.jobs=case["jobs"]
        self.n=len(self.jobs);r=case["resources"];e=case["energy"];self.berths=r["berths"]
        self.ids=np.arange(self.n);self.ij=np.array(np.triu_indices(self.n,1)).T
        self.arr=np.array([j["arrival_hour"] for j in self.jobs]);self.dur=np.array([j["duration_hours"] for j in self.jobs])
        self.priority=np.array([j["priority"] for j in self.jobs])
        deadline=np.array([j["deadline_hour"] for j in self.jobs]);cranes=np.array([j["cranes"] for j in self.jobs])
        kw=np.array([j["shore_kw"] for j in self.jobs])+cranes*e["crane_kw"]
        self.power=np.asarray(e["grid_limit_kw"])-e["base_kw"]+e["pv_kw"]
        starts=np.tile(np.arange(24),self.berths);berths=np.repeat(np.arange(self.berths),24);hours=np.arange(24)
        active=(starts[None,:,None]<=hours)&(hours<starts[None,:,None]+self.dur[:,None,None])
        berths_used=active[:,:,None,:] & (berths[:,None]==np.arange(self.berths))[None,:,:,None]
        entries=np.broadcast_to((starts[:,None]==hours)[None],active.shape)
        self.loads=np.concatenate([berths_used.reshape(self.n,len(starts),-1),active*cranes[:,None,None],
                                   entries,active*kw[:,None,None]],axis=2)
        self.capacity=np.concatenate([np.ones(self.berths*24),np.full(24,r["cranes"]),
             np.full(24,min(r["channel_concurrency"],r["pilots"],r["tugs"]//2)),self.power])
        self.valid=(starts>=self.arr[:,None]) & (starts+self.dur[:,None]<=24) & np.array(r["channel_open"])[starts]
        self.valid &= ((berths[None,:,None]<np.array(r["berth_capacity"]))|~active).all(axis=-1)
        self.wait=starts-self.arr[:,None];self.late=np.maximum(0,starts+self.dur[:,None]-deadline[:,None])
        self.prices=self.wait*50*self.priority[:,None]+self.late*case["delay_cny_vessel_hour"]+kw[:,None]*(active@np.array(e["price_cny_kwh"]))
        self.move_i,self.move_slot=np.where(self.valid)
        by_id={v["job_id"]:v for v in base["scheduled"]}
        self.initial=np.array([by_id[j["id"]]["berth"]*24+by_id[j["id"]]["start_hour"] for j in self.jobs])
        self.base_cost,self.base_wait,self.base_late=self.metric(self.initial)
        assert self.valid[self.ids,self.initial].all() and (self.loads[self.ids,self.initial].sum(axis=0)<=self.capacity+1e-6).all()

    def metric(self,state):
        return tuple(float(a[self.ids,state].sum()) for a in (self.prices,self.wait,self.late))

    def menu(self,state,remaining,seen):
        curr,wait,late=self.metric(state)
        a,b=self.ij.T
        # Move a call, exchange complete slots, or exchange only the time while
        # keeping each berth. All other vessel commitments keep their positions.
        first=np.concatenate([self.move_i,a,a])
        second=np.concatenate([self.move_i,b,b])
        new_first=np.concatenate([self.move_slot,state[b],24*(state[a]//24)+state[b]%24])
        new_second=np.concatenate([state[self.move_i],state[a],24*(state[b]//24)+state[a]%24])
        double=first!=second
        old_first,old_second=state[first],state[second]
        ok=self.valid[first,new_first] & self.valid[second,new_second] & ((old_first!=new_first)|(double&(old_second!=new_second)))
        def delta(table):
            return table[first,new_first]-table[first,old_first]+double*(table[second,new_second]-table[second,old_second])
        dc=delta(self.prices);dw=delta(self.wait);dl=delta(self.late)
        ok &= (wait+dw<=self.base_wait)&(late+dl<=self.base_late)&(curr+dc<=1.01*self.base_cost+1e-6)
        proposed=len(ok);inds=np.flatnonzero(ok)
        first,second,new_first,new_second,old_first,old_second,double,dc,dw,dl=(x[inds] for x in (first,second,new_first,new_second,old_first,old_second,double,dc,dw,dl))
        load=self.loads[self.ids,state].sum(axis=0)+self.loads[first,new_first]-self.loads[first,old_first]
        load+=double[:,None]*(self.loads[second,new_second]-self.loads[second,old_second])
        feasible=(load<=self.capacity+1e-6).all(axis=1)
        indices=np.flatnonzero(feasible)
        states=np.tile(state,(len(indices),1))
        rows=np.arange(len(indices))
        states[rows,first[indices]]=new_first[indices]
        multi=double[indices];states[rows[multi],second[indices[multi]]]=new_second[indices[multi]]
        unique=set(seen);keep=[]
        for pos,s in enumerate(states):
            key=s.tobytes()
            if key not in unique:unique.add(key);keep.append(pos)
        take=indices[keep];states=states[keep];n=len(take)
        dc=dc[take];dw=dw[take];dl=dl[take];a,b=first[take],second[take];pair=double[take]
        old=old_first[take]%24;new=new_first[take]%24
        best=max(0.,-float(dc.min()))/1000 if n else 0.
        features=np.column_stack([-dc/1000,-dc/self.base_cost*10,np.full(n,remaining/BUDGET),
            (self.base_wait-wait-dw)/10,(self.base_late-late-dl)/5,(self.base_cost-curr-dc)/1000,pair,
            (new-old)/8,pair*(new_second[take]%24-old_second[take]%24)/8,old/24,new/24,self.dur[a]/5,
            pair*self.dur[b]/5,self.priority[a]/3,pair*self.priority[b]/3,
            ((self.power-load[take,-24:])/np.maximum(1.,self.power)).min(axis=1),np.full(n,self.n/15),
            np.full(n,self.berths/5),np.full(n,best),np.full(n,np.log1p(n)/5)]).astype(np.float32)
        return Menu(states,curr+dc,features,proposed)

    def plan(self,state,label):
        return {"schema":"shanghai-plan.v1","port_id":self.case["port_id"],"trial_id":self.case["trial_id"],
                "source_snapshot_sha256":self.case["snapshot_sha256"],"method":label,"production_authority":False,
                "scheduled":[{"job_id":j["id"],"berth":int(slot//24),"start_hour":int(slot%24),"end_hour":int(slot%24+j["duration_hours"])}
                             for j,slot in zip(self.jobs,state,strict=True)]}

    @torch.inference_mode()
    def rollout(self,actor,mode):
        state=self.initial.copy();seen={state.tobytes()};best=state.copy();low=self.base_cost;path=[]
        for remaining in range(BUDGET,0,-1):
            menu=self.menu(state,remaining,seen)
            if not len(menu.cost):break
            if mode=="greedy":idx=int(menu.cost.argmin())
            else:idx=int(actor(torch.from_numpy(menu.features)).argmax())
            prior=state;state=menu.states[idx].copy();score=float(menu.cost[idx]);seen.add(state.tobytes())
            changed=np.flatnonzero(prior!=state)
            path.append({"step":len(path)+1,"proposals":menu.proposed,"feasible_unvisited":len(menu.cost),"objective_cny":score,
                         "changes":[{"job":self.jobs[i]["id"],"from":[int(prior[i]//24),int(prior[i]%24)],
                                     "to":[int(state[i]//24),int(state[i]%24)]} for i in changed]})
            if score<low-1e-6:best=state.copy();low=score
        return self.plan(best,mode),path
