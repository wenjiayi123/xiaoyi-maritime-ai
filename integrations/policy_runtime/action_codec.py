"""PARCO HCVRP distinguishes staying at the current node from a second visit.
Matches upstream HCVRPEnv._step stay_flag, without deleting nonconsecutive revisits.
"""
def parco_stops(agent, actions, depot_id, job_ids, agents):
    previous=agent
    stops=[depot_id]; waits=[]
    for tick,index in enumerate(actions):
        if isinstance(index,bool) or not isinstance(index,int) or not 0 <= index < agents+len(job_ids):
            raise ValueError('unknown PARCO node index')
        if index < agents and index != agent:
            raise ValueError('PARCO agent selected another agent depot')
        if index == previous:
            waits.append({'tick':tick,'node_index':index})
            continue
        name=depot_id if index < agents else job_ids[index-agents]
        stops.append(name)
        previous=index
    if stops[-1] != depot_id or len(stops)==1: stops.append(depot_id)
    return stops,waits
