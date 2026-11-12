"""Apply a 168-hour schedule to the isolated battery meter and settle its bill."""
import math


def settle(record,config):
    asset = config["asset"]
    grid = config["grid"]
    columns = ["base_kw","price","carbon_factor","pcc_kw","soc","battery_kw","flex_kw",
               "backlog_kwh","service_short_kw","reserve_short_kw","overdue_kwh","guardrail","physical"]
    if record["columns"] != columns or len(record["hourly"]) != 168:
        raise ValueError("沙箱需要连续 168 小时且字段一致的原生指令")
    soc = asset["soc_initial"]
    previous = 0.0
    peak = energy = carbon_total = variable_cost = throughput = 0.0
    changed = 0
    for hour,row in enumerate(record["hourly"]):
        if len(row)!=len(columns) or not all(math.isfinite(x) for x in row):
            raise ValueError(f"第 {hour} 小时指令不可读")
        base,price,carbon,expected_grid,expected_soc,battery,flex,backlog,*flags=row
        imported = base-battery+flex
        soc += (max(-battery,0)*asset["charge_efficiency"]-max(battery,0)/asset["discharge_efficiency"])/asset["rated_energy_kwh"]
        if (abs(imported-expected_grid)>1e-5 or abs(soc-expected_soc)>1e-7 or
            not -1e-6<=imported<=grid["hard_pcc_limit_kw"]+1e-5 or abs(battery)>asset["rated_power_kw"]+1e-5 or
            abs(battery-previous)>asset["ramp_kw_per_hour"]+1e-5 or not asset["soc_min"]-1e-7<=soc<=asset["soc_max"]+1e-7 or
            any(abs(v)>1e-7 for v in flags)):
            raise ValueError(f"第 {hour} 小时越过设备、服务或功率约束")
        previous=battery
        energy+=imported
        peak=max(peak,imported)
        carbon_total+=imported*carbon
        throughput+=abs(battery)
        variable_cost+=imported*price
        changed+=int(abs(battery)>1e-5 or abs(flex)>1e-5)
    if abs(soc-asset["soc_initial"])>1e-7 or abs(backlog)>1e-7:
        raise ValueError("周末未结清")
    bill=variable_cost+throughput*asset["cycle_cost_cny_per_kwh"]+peak*grid["demand_charge_cny_per_kw_month"]*7/30.4375
    result={"total_cost_cny":bill,"carbon_kg":carbon_total,"peak_kw":peak}
    for name,value in result.items():
        if abs(value-record["metrics"][name])>1e-5:
            raise ValueError("与原生孪生结算不符："+name)
    return {**result,"import_kwh":energy,"storage_throughput_kwh":throughput,"terminal_soc":soc,
            "terminal_backlog_kwh":backlog,"hours":168,"hours_with_action":changed}
