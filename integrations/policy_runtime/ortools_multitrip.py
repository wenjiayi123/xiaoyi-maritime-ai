"""Same-contract OR-Tools reference with optional, vehicle-specific reload visits.
Reload negative demand + capacity slack follows the official CVRP reload formulation.
Every converted route is checked by the separate SI validator, including energies and windows.
"""
import math
from contracts import Route

def solve_multitrip(case,milliseconds):
 from ortools.constraint_solver import pywrapcp,routing_enums_pb2
 jobs=[case.depot,*case.jobs];nodes=list(jobs);owners={}
 # At most N trips per vehicle represents every nonempty partition of the N jobs.
 # Every clone is optional; the bound does not force extra journeys.
 for v in range(len(case.vehicles)):
  for _ in range(len(case.jobs)-1):
   owners[len(nodes)]=v;nodes.append(case.depot)
 manager=pywrapcp.RoutingIndexManager(len(nodes),len(case.vehicles),0);routing=pywrapcp.RoutingModel(manager)
 forbidden=set(case.forbidden_edges)
 def distance(a,b):
  n,m=nodes[manager.IndexToNode(a)],nodes[manager.IndexToNode(b)]
  if (n.id,m.id) in forbidden:return 1_000_000_000
  return round(math.hypot(n.x_m-m.x_m,n.y_m-m.y_m)*1000)
 idx=routing.RegisterTransitCallback(distance);routing.SetArcCostEvaluatorOfAllVehicles(idx)
 capacity_callbacks=[]
 for v,vehicle in enumerate(case.vehicles):
  def demand(a,cap=vehicle.capacity):
   node=manager.IndexToNode(a)
   return -round(cap*1000) if node in owners else round(nodes[node].demand*1000)
  capacity_callbacks.append(routing.RegisterUnaryTransitCallback(demand))
 routing.AddDimensionWithVehicleTransitAndCapacity(capacity_callbacks,round(max(v.capacity for v in case.vehicles)*1000),[round(v.capacity*1000) for v in case.vehicles],True,'Capacity')
 load=routing.GetDimensionOrDie('Capacity')
 for i in range(1,len(nodes)):
  index=manager.NodeToIndex(i)
  if i in owners:
   routing.SetAllowedVehiclesForIndex([owners[i]],index);routing.AddDisjunction([index],0)
  else:load.SlackVar(index).SetValue(0)
 timing_callbacks=[]
 for vehicle in case.vehicles:
  timing_callbacks.append(routing.RegisterTransitCallback(lambda a,b,speed=vehicle.speed_mps:round(distance(a,b)/1000/speed+nodes[manager.IndexToNode(a)].service_seconds)))
 routing.AddDimensionWithVehicleTransitAndCapacity(timing_callbacks,86400,[round(v.shift_end_seconds) for v in case.vehicles],False,'Time');timing=routing.GetDimensionOrDie('Time')
 for i,node in enumerate(jobs):
  if i:timing.CumulVar(manager.NodeToIndex(i)).SetRange(round(node.window_start_seconds),round(node.window_end_seconds))
 for v in range(len(case.vehicles)):timing.CumulVar(routing.Start(v)).SetValue(0)
 if case.objective=='makespan_seconds':
  
  for v,callback in enumerate(timing_callbacks):routing.SetArcCostEvaluatorOfVehicle(callback,v)
  timing.SetGlobalSpanCostCoefficient(1_000_000)
 options=pywrapcp.DefaultRoutingSearchParameters();options.first_solution_strategy=routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION;options.local_search_metaheuristic=routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH;options.time_limit.FromMilliseconds(milliseconds)
 solution=routing.SolveWithParameters(options)
 if solution is None:return [],{'solver_status':routing.status(),'compute_budget_ms':milliseconds,'same_contract_reload_nodes':True,'reload_nodes':len(owners)}
 routes=[]
 for v,vehicle in enumerate(case.vehicles):
  index=routing.Start(v);stops=[]
  while not routing.IsEnd(index):
   name=nodes[manager.IndexToNode(index)].id
   if name!=case.depot.id or not stops or stops[-1]!=name:stops.append(name)
   index=solution.Value(routing.NextVar(index))
  if stops[-1]!=case.depot.id or len(stops)==1:stops.append(case.depot.id)
  routes.append(Route(vehicle_id=vehicle.id,stops=stops))
 return routes,{'solver_status':routing.status(),'compute_budget_ms':milliseconds,'same_contract_reload_nodes':True,'reload_nodes':len(owners),'formulation':'optional vehicle-specific depot nodes; capacity slack resets load; one continuous clock per physical vehicle'}
