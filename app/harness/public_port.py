"""Verified local public evidence and reproducible historical port scenario studies."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.config import BASE_DIR
from app.harness.contracts import StrictModel, digest
from app.harness import portcall, twin_validation

FOLDER = BASE_DIR / "data/public/port_evidence_20261030"


class ReplayArgs(StrictModel):
    site: Literal["los_angeles", "singapore"] = "los_angeles"
    scenario: Literal["historical_baseline", "peak_month_demand", "resource_outage", "observed_high_wind"] = (
        "historical_baseline"
    )


def _verified(path, checksum):
    path = (BASE_DIR / path).resolve()
    if not path.is_relative_to((BASE_DIR / "data/public").resolve()):
        raise ValueError("public evidence path is outside registered data directory")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise ValueError("公开数据摘要不一致，请重新核查来源，不继续使用旧结果")
    return raw


def entries():
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    if manifest["schema"] != "xiaoyi-public-port-evidence.v1":
        raise ValueError("公开证据清单版本不支持")
    return manifest, {e["id"]: e for e in manifest["entries"]}


def load(name):
    _, index = entries()
    if name not in index:
        raise ValueError("公开数据未登记")
    e = index[name]
    raw = _verified(e["path"], e["sha256"])
    if e.get("raw_path"):
        _verified(e["raw_path"], e["raw_sha256"])
    for binding in e.get("source_bindings", []):
        _verified(binding["path"], binding["sha256"])
        parent = next((item for item in index.values() if item["path"] == binding["path"]), None)
        if parent and parent.get("raw_path"):
            _verified(parent["raw_path"], parent["raw_sha256"])
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows) != e["rows"]:
        raise ValueError("公开数据行数与清单不一致")
    return e, rows


def catalog():
    manifest, index = entries()
    items = []
    for name, e in index.items():
        try:
            _, rows = load(name)
            item = {**e, "integrity_valid": True, "columns": list(rows[0]), "preview": [rows[0], rows[-1]]}
            if "month" in rows[0]:
                item.update(time_start=rows[0]["month"], time_end=rows[-1]["month"])
        except (ValueError, OSError) as exc:
            item = {**e, "integrity_valid": False, "error": str(exc)}
        items.append(item)
    return {
        **manifest,
        "entries": items,
        "manifest_sha256": digest(manifest),
        "scope": "真实公开历史数据+显式工程参数的仿真接口；不代表接入港口生产TOS/PCS。",
    }


def forecast_validation():
    e, raw = load("noaa_la_water_level")
    rows = [r for r in raw if r["quality"] == "v" and all(f == "0" for f in r["flags"].split(","))]
    pairs = []
    for a, b, c in zip(rows, rows[1:], rows[2:]):
        times = [datetime.fromisoformat(r["timestamp"]) for r in [a, b, c]]
        if times[1] - times[0] != timedelta(minutes=6) or times[2] - times[1] != timedelta(minutes=6):
            continue
        prev, current, actual = map(lambda r: float(r["value"]), [a, b, c])
        pairs.append(
            {
                "issued_at": times[1],
                "target_at": times[2],
                "linear": current * 2 - prev,
                "persistence": current,
                "actual": actual,
                "source_row": c["timestamp"],
            }
        )
    cutoff = int(len(pairs) * 0.6)
    calibration, holdout = pairs[:cutoff], pairs[cutoff:]
    if min(len(calibration), len(holdout)) < 30:
        raise ValueError("公开水位时序不足以进行留出验证")
    chosen = min(
        ["persistence", "linear"], key=lambda name: statistics.mean(abs(r[name] - r["actual"]) for r in calibration)
    )
    errors = sorted(abs(r[chosen] - r["actual"]) for r in calibration)
    # Width and model selected on calibration only, before opening holdout observations.
    radius = errors[min(len(errors) - 1, math.ceil((len(errors) + 1) * 0.90) - 1)]

    def convert(rs):
        return [
            {
                "issued_at": r["issued_at"],
                "target_at": r["target_at"],
                "predicted": r[chosen],
                "baseline": r["persistence"],
                "actual": r["actual"],
                "lower": r[chosen] - radius,
                "upper": r[chosen] + radius,
                "source_row": r["source_row"],
            }
            for r in rs
        ]

    request = twin_validation.ValidationRequest(
        site_id="NOAA.9410660",
        variable="water_level",
        unit="m MLLW",
        model_version="causal_6min_" + chosen + ".v1",
        source_sha256=e["sha256"],
        frozen_at=calibration[-1]["target_at"],
        maximum_mae=0.10,
        maximum_interval_width=0.60,
        minimum_coverage=0.8,
        calibration=convert(calibration),
        holdout=convert(holdout),
    )
    result = twin_validation.validate(request)
    return {
        **result,
        "evidence_origin": "local_frozen_NOAA_raw_and_derived_hashes_verified",
        "source": e,
        "forecast_horizon_minutes": 6,
        "nominal_interval_coverage": 0.9,
        "interval_method": "calibration_absolute_residual_quantile; serial dependence, no exchangeability guarantee",
        "frozen_at": request.frozen_at.isoformat(),
        "selected_on_calibration": chosen,
        "preview": request.model_dump(mode="json")["holdout"][:12],
        "notice": "公开历史站点水位的6分钟前推留出验证；模型与区间仅由前60%校准段确定。并非全港物理孪生或海图/UKC验证。",
    }


def replay(args: ReplayArgs):
    if args.site == "singapore" and args.scenario == "observed_high_wind":
        raise ValueError("当前没有已登记的新加坡同期风速，不得移用洛杉矶风速伪装新加坡实测")
    monthly_id = "port_la_teu_2024" if args.site == "los_angeles" else "singapore_cargo_monthly"
    monthly_e, monthly = load(monthly_id)
    value_key = "total_teu" if args.site == "los_angeles" else "cargo_throughput"
    as_of = datetime(2024, 12, 25, 6, tzinfo=timezone.utc)

    def assumed_month_release(row):
        year, month = map(int, row["month"].split("-"))
        next_month = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        return next_month + timedelta(days=45)

    months = [r for r in monthly if r["month"].startswith("2024-") and assumed_month_release(r) <= as_of]
    if len(months) < 6:
        raise ValueError("历史决策时钟前可用月度资料不足")
    values = [float(r[value_key]) for r in months]
    ratio = max(values) / statistics.mean(values)
    sources, derived = (
        [monthly_e],
        {
            "peak_month_to_available_month_mean_ratio": ratio,
            "peak_month": months[values.index(max(values))]["month"],
            "monthly_periods_used": [r["month"] for r in months],
            "monthly_availability_assumption": "月末后45天才可用；不是已核实的历史发布日期。现取档案可能含后续修订，不能声称当时实时可得。",
        },
    )
    base_count, wind, power = 6, None, 6000
    if args.site == "los_angeles":
        ais_e, ais = load("noaa_la_lb_ais_weather_2024_12_25")
        ais = [r for r in ais if datetime.fromisoformat(r["timestamp"]) <= as_of]
        if not ais:
            raise ValueError("历史决策时钟前没有AIS观测")
        sources.append(ais_e)
        mean_anchor = statistics.mean(float(r["anchored_vessels"]) for r in ais)
        base_count = max(3, min(10, math.ceil(mean_anchor / 10)))
        winds = [float(r["wind_speed_mps"]) for r in ais if r["wind_speed_mps"]]
        wind = max(winds) if winds else None
        derived.update(
            mean_ais_anchored_or_moored_proxy=mean_anchor,
            maximum_joined_station_wind_mps=wind,
            wind_missing_fraction=sum(not r["wind_speed_mps"] for r in ais) / len(ais),
            observation_cutoff=as_of.isoformat(),
            last_used_ais_observation=ais[-1]["timestamp"],
            ais_observed_buckets_used=len(ais),
        )
    count = min(16, math.ceil(base_count * ratio)) if args.scenario == "peak_month_demand" else base_count
    calls, events = [], []
    for i in range(count):
        call_id = f"scenario-call-{i + 1:02d}"
        calls.append(portcall.Call(call_id=call_id, service_minutes=60 + (i % 3) * 15, deadline_minutes=240 + i * 20))
        events.append(
            portcall.Event(
                event_id=call_id + ".eta",
                call_id=call_id,
                classifier="ESTIMATED",
                revision=1,
                event_time=as_of + timedelta(minutes=i * 20),
                received_at=as_of,
                source_party="declared_scenario_generator",
                source_reference=monthly_e["sha256"],
            )
        )
    closures = []
    if args.scenario == "resource_outage":
        closures = [
            portcall.Closure(resource="berth", start_minutes=0, end_minutes=180, unavailable=1),
            portcall.Closure(resource="crane", start_minutes=0, end_minutes=180, unavailable=2),
        ]
    if args.scenario == "observed_high_wind":
        if wind is None:
            raise ValueError("没有有效的同期观测风速，不能推演实测风速情景")
        # Explicit sensitivity threshold, not a port operating limit or observed closure.
        if wind >= 8:
            closures = [portcall.Closure(resource="channel", start_minutes=0, end_minutes=60, unavailable=1)]
    capacities = {**portcall.CAPACITIES, "power_kw": power}
    request = portcall.PlanRequest(
        site_id=args.site + ".historical-study",
        as_of=as_of,
        capacities=capacities,
        calls=calls,
        events=events,
        closures=closures,
        evidence_class="historical_public_data_driven_scenario",
    )
    plan = portcall.plan(request)
    return {
        "schema": "xiaoyi-historical-port-study.v1",
        "config": args.model_dump(),
        "sources": sources,
        "source_binding_sha256": digest([{k: e[k] for k in ["id", "sha256"]} for e in sources]),
        "historical_clock": as_of.isoformat(),
        "derived_inputs": derived,
        "plan": plan,
        "scenario_input": request.model_dump(mode="json"),
        "production_authority": False,
        "field_lineage": [
            {
                "fields": "monthly volume, AIS status/count/speed, available station weather",
                "class": "public_historical_measurement_or_aggregate",
            },
            {
                "fields": "demand ratio, as-of station join, anchored/moored proxy",
                "class": "derived_from_public_records",
            },
            {
                "fields": "scenario-call IDs, ETA, service durations, deadlines, capacities, outage, 8m/s sensitivity threshold",
                "class": "declared_engineering_assumption",
            },
            {"fields": "planned time, wait, lateness, resource use", "class": "simulation_output"},
        ],
        "missing_for_site_validation": [
            "真实挂靠服务事件",
            "船舶尺度与UKC",
            "设备遥测与维护",
            "堆场与危险品规则",
            "闸口铁路实绩",
            "现场能源计量",
            "独立样本与真实岗位验收",
        ],
        "notice": "真实公开历史数据驱动工程场景；只用历史决策时钟前的观测，月度信息另设45天可用延迟假设。现取档案可能含修订，不等于当时实时可得。scenario-call不是识别出的真实挂靠；跨月需求映射用于敏感性实验。新加坡未确认单位尺度，仅用无量纲月度比例。",
    }
