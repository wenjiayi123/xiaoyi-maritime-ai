"""Explicit local adapter contracts; no model-generated URLs or arbitrary tools."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCENARIOS = {
    "normal": "正常运行", "peak-arrivals": "集中到港", "channel-closure": "航道关闭",
    "equipment-failure": "设备故障", "extreme-weather": "恶劣天气",
    "channel-congestion": "航道拥堵", "yard-saturation": "堆场饱和", "data-loss": "数据失联",
}
PORT_SCENARIOS = {
    "strategy": "当前策略", "high_density_berthing": "高密靠泊",
    "channel_congestion": "航道拥堵", "equipment_degradation": "设备降级",
    "heatwave_reefer": "高温冷藏负荷", "typhoon_closure": "台风封航",
    "island_grid": "孤网需量受限", "tariff_carbon_spike": "电价碳因子峰值",
}


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EmptyParameters(Parameters):
    pass


class EnergyParameters(Parameters):
    baseline_green_preference: float = Field(.5, ge=0, le=1, title="基准绿色偏好", description="0 表示效率侧，1 表示低碳侧")
    green_preference: float = Field(.82, ge=0, le=1, title="候选绿色偏好")
    carbon_price_cny_per_ton: float = Field(85, ge=0, le=5000, title="试算碳价（元/吨）", description="试算假设；不是实时市场报价")


class PortParameters(Parameters):
    scenario: str = Field("strategy", title="评估情景", json_schema_extra={"enum": list(PORT_SCENARIOS), "enumNames": list(PORT_SCENARIOS.values())})
    horizon_min: int = Field(60, ge=15, le=360, title="评估窗口（分钟）")
    step_min: int = Field(15, ge=1, le=60, title="采样步长（分钟）")

    @model_validator(mode="after")
    def check_window(self):
        if self.scenario not in PORT_SCENARIOS or self.step_min > self.horizon_min or self.horizon_min / self.step_min > 120:
            raise ValueError("情景必须已登记，采样步长不得超过窗口，最多 120 个评估点")
        return self


class ScenarioParameters(Parameters):
    scenario: str = Field("peak-arrivals", title="目标情景", json_schema_extra={"enum": list(SCENARIOS), "enumNames": list(SCENARIOS.values())})

    @model_validator(mode="after")
    def check_scenario(self):
        if self.scenario not in SCENARIOS:
            raise ValueError("目标情景未登记")
        return self


class ControlParameters(Parameters):
    action: str = Field("stop", title="模拟时钟", json_schema_extra={"enum": ["start", "stop"], "enumNames": ["运行", "暂停"]})

    @model_validator(mode="after")
    def check_action(self):
        if self.action not in {"start", "stop"}:
            raise ValueError("只允许运行或暂停模拟时钟")
        return self


ACTIONS: dict[str, dict[str, Any]] = {
    "port.observe": {"target": "port-dt-multi", "label": "观测数字孪生", "model": EmptyParameters},
    "port.evaluate": {"target": "port-dt-multi", "label": "数字孪生情景评估", "model": PortParameters},
    "energy.observe": {"target": "energy-cockpit", "label": "观测能碳运行状态", "model": EmptyParameters},
    "energy.compare": {"target": "energy-cockpit", "label": "能碳参数对比试算", "model": EnergyParameters},
    "malacca.observe": {"target": "malacca-sandbox", "label": "观测马六甲运行状态", "model": EmptyParameters},
    "malacca.scenario": {"target": "malacca-sandbox", "label": "调整马六甲模拟情景", "model": ScenarioParameters, "mutates": True},
    "malacca.clock": {"target": "malacca-sandbox", "label": "运行或暂停马六甲模拟时钟", "model": ControlParameters, "mutates": True},
    "sailing.observe": {"target": "sailing-simulator", "label": "核验航行模拟器隔离状态", "model": EmptyParameters},
}


def catalog() -> list[dict[str, Any]]:
    return [{"id": key, "target": row["target"], "label": row["label"], "mutates": bool(row.get("mutates")),
             "parameters": row["model"].model_json_schema()["properties"]} for key, row in ACTIONS.items()]


def parse_command(command: str) -> dict[str, Any] | None:
    """Conservative imperative parser. Unknown parameters remain a clarification."""
    compact = re.sub(r"\s+", "", command)
    if re.search(r"[?？]|是什么|为什么|如何|怎么|能否|是否|不要|别|不能", compact):
        return None
    if not re.search(r"观测|观察|监测|读取|查看|核验|调节|调整|切换|设置|暂停|恢复|试算|评估|对比", compact):
        return None
    targets = ["能碳" in compact, "马六甲" in compact, "数字孪生" in compact or "孪生系统" in compact, "航行模拟器" in compact]
    if sum(targets) > 1:
        return {"clarification": "请每次指定一个目标系统，分别预览其参数与执行范围。"}
    if "能碳" in compact:
        if re.search(r"调节|调整|设置|试算|对比", compact):
            params: dict[str, Any] = {}
            for key, pattern in [("green_preference", r"绿色偏好(?:调到|调整到|调整为|设为|为|到|=|：)?(-?\d+(?:\.\d+)?)(%?)"),
                                 ("carbon_price_cny_per_ton", r"碳价(?:调到|调整到|调整为|设为|为|到|=|：)?(-?\d+(?:\.\d+)?)")]:
                match = re.search(pattern, compact)
                if match:
                    value = float(match[1])
                    params[key] = value / 100 if key == "green_preference" and match[2] == "%" else value
            if "低碳优先" in compact:
                params.setdefault("green_preference", .82)
            if not params and "默认" not in compact:
                return {"clarification": "请明确绿色偏好（0～1）或试算碳价，例如：能碳绿色偏好调到 0.8，碳价 100，进行对比试算。"}
            return {"action_id": "energy.compare", "parameters": params}
        return {"action_id": "energy.observe", "parameters": {}}
    if "马六甲" in compact:
        # Search once, without backtracking over repeated user-supplied words.
        if "暂停" in compact or "时钟" in compact.partition("恢复")[2]:
            return {"action_id": "malacca.clock", "parameters": {"action": "stop" if "暂停" in compact else "start"}}
        if re.search(r"调节|调整|切换|设置", compact):
            matches = [key for key, label in SCENARIOS.items() if key in compact or label in compact]
            if len(matches) != 1:
                return {"clarification": "请指定一个已登记情景：" + "、".join(SCENARIOS.values())}
            return {"action_id": "malacca.scenario", "parameters": {"scenario": matches[0]}}
        return {"action_id": "malacca.observe", "parameters": {}}
    if "数字孪生" in compact or "孪生系统" in compact:
        if "评估" in compact:
            selected = next((key for key, label in PORT_SCENARIOS.items() if label in compact or key in compact), "strategy")
            params = {"scenario": selected}
            window = re.search(r"(?:窗口|评估)(\d+)分钟", compact)
            if window:
                params["horizon_min"] = int(window[1])
            return {"action_id": "port.evaluate", "parameters": params}
        if re.search(r"调节|调整|切换|设置|暂停|恢复", compact):
            return {"clarification": "数字孪生已接入观测和情景评估，可设置本次评估窗口与步长；尚未接入全局运行参数写入。请选择情景评估。"}
        return {"action_id": "port.observe", "parameters": {}}
    if "航行模拟器" in compact and re.search(r"核验|观测|查看|读取", compact):
        return {"action_id": "sailing.observe", "parameters": {}}
    return None
