"""Bimonthly container throughput, using only results available by the issue date."""
from datetime import date
from math import ceil
from statistics import mean, median
from functools import lru_cache

METHODS=("last","season","season_per_day","recent_per_day","growth","blend")
BASE=METHODS[:4]


def date_of(v): return date.fromisoformat(v)


def days(start):
    start=date_of(start)
    after=date(start.year+(start.month==11),(start.month+1)%12+1,1)
    return (after-start).days


class Forecaster:
    def __init__(self,blocks):
        self.blocks=sorted(blocks,key=lambda r:r["start"])
        assert len({r["start"] for r in self.blocks})==len(self.blocks)
        assert all(r["start"]<r["available"] and r["teu"]>0 for r in self.blocks)
        self.truth={r["start"]:r for r in self.blocks}
        self.cache={}

    def components(self,target,cutoff):
        key=(target,cutoff)
        if key in self.cache:return self.cache[key]
        td=date_of(target)
        assert td.month%2 and td.day==1 and cutoff<=target
        history=[r for r in self.blocks if r["available"]<=cutoff and r["start"]<target]
        by_date={r["start"]:r for r in history}
        prior=by_date.get(td.replace(year=td.year-1).isoformat())
        if not prior or len(history)<6:return None
        last=history[-1]
        recent=median(r["teu"]/days(r["start"]) for r in history[-3:])*days(target)
        cal=prior["teu"]/days(prior["start"])*days(target)
        ratios=[]
        for r in history[-6:]:
            t=date_of(r["start"])
            old=by_date.get(t.replace(year=t.year-1).isoformat())
            if old:ratios.append((r["teu"]/days(r["start"]))/(old["teu"]/days(old["start"])))
        factor=min(1.15,max(.85,median(ratios))) if ratios else 1.0
        values=dict(last=last["teu"],season=prior["teu"],season_per_day=cal,recent_per_day=recent,growth=cal*factor)
        result=(values,history)
        self.cache[key]=result
        return result

    def predict(self,target,cutoff):
        current=self.components(target,cutoff)
        if current is None:return None
        values,history=current
        # Fit one convex weight against earlier issue-date predictions whose targets have now been published.
        pairs=[]
        for r in history[-36:]:
            past=self.components(r["start"],r["start"])
            if past:
                f=past[0]
                pairs.append(((f["growth"]-f["recent_per_day"])/r["teu"],1-f["recent_per_day"]/r["teu"]))
        prior=.025
        weight=min(1,max(0,(prior*.5+sum(x*y for x,y in pairs))/(prior+sum(x*x for x,_ in pairs))))
        return dict(pred={**values,"blend":values["recent_per_day"]*(1-weight)+values["growth"]*weight},
                    learned_weight=weight,fit_pairs=len(pairs),latest_input=history[-1]["start"],
                    latest_available=max(r["available"] for r in history),inputs=len(history))

    def score(self):
        rows=[]
        for r in self.blocks:
            result=self.predict(r["start"],r["start"])
            if result:rows.append(dict(start=r["start"],actual=r["teu"],available=r["available"],**result))
        dev=[r for r in rows if "2023"<=r["start"]<"2025" and r["available"]<="2025-01-01"]
        assert len(dev)>=6, len(dev)
        def mae(method,subset):return mean(abs(r["actual"]-r["pred"][method]) for r in subset)
        method=min(METHODS,key=lambda k:mae(k,dev))
        baseline=min(BASE,key=lambda k:mae(k,dev))
        test=[r for r in rows if "2025"<=r["start"]]
        assert len(test)==10, [r["start"] for r in test]
        for r in test:
            residuals=[abs(q["actual"]-q["pred"][method]) for q in rows
                       if q["start"]<r["start"] and q["available"]<=r["start"]][-18:]
            if len(residuals)>=8:
                margin=sorted(residuals)[min(len(residuals),ceil((len(residuals)+1)*.80))-1]
                r["low"]=max(0,r["pred"][method]-margin)
                r["high"]=r["pred"][method]+margin
        calibrated=[r for r in test if "low" in r]
        return dict(method=method,baseline=baseline,development_n=len(dev),test_n=len(test),
                    development_mae={k:mae(k,dev) for k in METHODS},test_mae={k:mae(k,test) for k in METHODS},
                    wape=sum(abs(r["actual"]-r["pred"][method]) for r in test)/sum(r["actual"] for r in test),
                    interval_n=len(calibrated),covered=sum(r["low"]<=r["actual"]<=r["high"] for r in calibrated),test=test)
