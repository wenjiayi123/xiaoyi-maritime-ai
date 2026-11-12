"""Fixed port-call ETA corrections and prediction intervals, in UTC minutes."""
from collections import defaultdict
from math import ceil
from statistics import median,mean

METHODS=("declared","port_bias","vessel_bias","timetable_bias")


def groups(port,imo,kind,eta):
    p=port
    c=f"{p}|{kind}"
    if not imo:return [p,c]
    ship=f"{p}|imo|{imo}"
    return [p,c,ship,f"{ship}|slot|{int(eta%1440)//120}"]


def fit(rows):
    buckets=defaultdict(list)
    for r in rows:
        for key in groups(r["port"],r["imo"],r["kind"],r["eta"]):
            buckets[key].append(r["ata"]-r["eta"])
    return {key:[len(v),median(v)] for key,v in sorted(buckets.items())}


def predict(weights,port,imo,kind,eta):
    keys=groups(port,imo,kind,eta)
    bias,ship=0,0
    for i,key in enumerate(keys):
        n,m=weights.get(key,(0,0))
        if i==0: bias=m;port_bias=m
        elif n:
            bias=(n*m+8*bias)/(n+8)
        if i<=2:ship=bias
    return dict(declared=eta,port_bias=eta+port_bias,vessel_bias=eta+ship,timetable_bias=eta+bias)


def quantile(values,q):
    return sorted(values)[max(0,min(len(values)-1,ceil(q*len(values))-1))]


def metrics(rows,method):
    err=[r["pred"][method]-r["ata"] for r in rows]
    ae=[abs(x) for x in err]
    return dict(n=len(err),mae=mean(ae),medae=median(ae),p90=quantile(ae,.9),
                bias=mean(err),within30=sum(a<=30 for a in ae)/len(ae))
