from bisect import bisect_left,insort
from collections import defaultdict
TURN=10

def first_gap(slots,eta,duration,turn):
    # Slots are reserved by issue time; later requests may use a gap ahead of another booking.
    i=bisect_left(slots,(eta,))
    start=max(eta,slots[i-1][1]+turn) if i else eta
    for a,b,_ in slots[i:]:
        if start+duration+turn<=a:break
        start=max(start,b+turn)
    return start

def reserve(requests,profiles,*,corrected,flexible,turn=TURN):
    calendars=defaultdict(list);bookings={}
    for r in sorted(requests,key=lambda v:(v["issue"],v["call"])):
        opts=profiles.get(f'{r["port"]}|{r["imo"]}',[])
        if not opts:continue
        eta=max(r["issue"],r["picked"] if corrected else r["eta"])
        choices=[]
        for opt in (opts if flexible else opts[:1]):
            b=opt["berth"];slots=calendars[r["port"],b]
            start=first_gap(slots,eta,opt["duration"],turn)
            choices.append((start,-opt["count"],b,opt["duration"]))
        start,_,berth,duration=min(choices)
        insort(calendars[r["port"],berth],(start,start+duration,r["call"]))
        bookings[r["call"]]=dict(call=r["call"],port=r["port"],berth=berth,start=start,end=start+duration,
                                 eta=eta,issue=r["issue"],options=len(opts))
    for slots in calendars.values():
        assert all(b+turn<=na+1e-8 for (_,b,_),(na,_,_) in zip(slots,slots[1:]))
    return bookings
