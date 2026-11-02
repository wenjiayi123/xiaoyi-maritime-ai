"""Gap-aware harmonic fits, interannual calibration and strictly causal short replay."""

import argparse
import csv
import gzip
import io
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import utide
from scipy.stats import theilslopes

from app.harness import physical_v2 as files
from app.harness import long_twin_v6 as previous
from app.harness.physical_v3 import decode, reconstruct

DATA = files.BASE_DIR / "data/public/twin_v7_20261031"
UTC = timezone.utc


def load(phase):
    manifest = json.loads((DATA / f"{phase}-manifest.json").read_text())
    if manifest["protocol_sha256"] != files.sha(DATA / "protocol.json"):
        raise ValueError("source protocol changed")
    groups = {}
    for e in manifest["entries"]:
        p = files.BASE_DIR / e["path"]
        if files.sha(p) != e["sha256"]:
            raise ValueError("primary response changed")
        g = groups.setdefault(
            e["station_id"],
            {
                "site": e["site"],
                "provider": e["provider"],
                "observed": {},
                "quality": Counter(),
                "rejected": Counter(),
                "datums": set(),
                "records": set(),
                "last_rq_dates": set(),
                "errors": [],
            },
        )
        body = gzip.decompress(p.read_bytes()) if e["compression"] != "none" else p.read_bytes()
        if e["provider_error"] or body.lstrip().startswith(b"Error {"):
            g["errors"].append(
                {
                    "path": e["path"],
                    "label": e["label"],
                    "http_status": e["http_status"],
                    "returned_error": body.decode(e["encoding"], errors="replace")[:800],
                }
            )
            continue
        text = body.decode(e["encoding"])
        noaa = e["provider"] == "noaa"
        if noaa:
            raw = json.loads(text)
            rows = raw["data"]
            g["lat"] = float(raw["metadata"]["lat"])
            g["datums"].add("MLLW")
        else:
            reader = csv.DictReader(io.StringIO(text))
            next(reader)
            rows = reader
        for row in rows:
            at = (
                datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                if noaa
                else datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            )
            try:
                value = float(row["v"]) if noaa else float(row["sea_level"]) / 1000
                good = (
                    (row.get("q", "v") == "v" and all(f == "0" for f in row["f"].split(",")))
                    if noaa
                    else int(row["quality"]) >= 3
                )
            except (ValueError, TypeError):
                value, good = math.nan, False
            if not good or not math.isfinite(value) or value <= -32 or at.minute:
                g["rejected"][str(at.year)] += 1
                continue
            if at in g["observed"] and abs(g["observed"][at] - value) > 0.001001:
                raise ValueError("conflicting observations; no accuracy-based source choice")
            g["observed"][at] = value
            g["quality"][row.get("q", "verified_hourly") if noaa else row["quality"]] += 1
            if not noaa:
                g["lat"] = float(row["latitude"])
                g["datums"].add(row["reference_datum"])
                g["records"].add(row["record_id"])
                g["last_rq_dates"].add(row["last_rq_date"])
        if len(g["datums"]) > 1 or len(g["records"]) > 1:
            raise ValueError("changing datum/record needs an explicit reconciliation")
    return manifest, groups


def provenance(g):
    return {
        "quality_counts": dict(g["quality"]),
        "rejected_by_year": dict(g["rejected"]),
        "datums": sorted(g["datums"]),
        "record_ids": sorted(g["records"]),
        "last_rq_dates": sorted(g["last_rq_dates"]),
        "source_errors": g["errors"],
    }


def year_coordinate(times):
    return np.asarray(
        [
            t.year
            + (t - datetime(t.year, 1, 1, tzinfo=UTC)).total_seconds()
            / ((datetime(t.year + 1, 1, 1, tzinfo=UTC) - datetime(t.year, 1, 1, tzinfo=UTC)).total_seconds())
            for t in times
        ]
    )


def fit(g, years, count, plan):
    times = sorted(t for t in g["observed"] if t.year in years)
    rule = plan["fit"]
    if len(times) < rule["minimum_total_hours"] or (times[-1] - times[0]).days < rule["minimum_span_days"]:
        raise ValueError("insufficient actual historical hours/span")
    if any(sum((t.month - 1) // 3 == q for t in times) < rule["minimum_quarter_hours"] for q in range(4)):
        raise ValueError("historical seasons do not identify the annual basis")
    coef = utide.solve(
        np.asarray([t.replace(tzinfo=None) for t in times], dtype="datetime64[ns]"),
        np.asarray([g["observed"][t] for t in times]),
        lat=g["lat"],
        constit=previous.NAMES[:count],
        method="ols",
        conf_int="none",
        trend=False,
        nodal=True,
        verbose=False,
    )
    fitted = reconstruct(times, coef)
    residual = np.asarray([g["observed"][t] for t in times]) - fitted
    means = {
        y: float(np.mean([r for t, r in zip(times, residual) if t.year == y]))
        for y in years
        if sum(t.year == y for t in times) >= 500
    }
    if len(means) < 2:
        raise ValueError("insufficient observed years for residual level/trend")
    latest = max(means)
    slope = float(theilslopes(list(means.values()), [y + 0.5 for y in means]).slope)
    # Frequency-only sampling condition is a diagnostic, not UTide's complete Jacobian.
    sample = times[:: max(1, len(times) // 3000)]
    h = np.asarray([(t - times[0]).total_seconds() / 3600 for t in sample])
    phase = h[:, None] * np.asarray(coef.aux.frq)[None, :] * 2 * math.pi
    matrix = np.column_stack([np.ones(len(h)), np.sin(phase), np.cos(phase)])
    condition = float(np.linalg.cond(matrix))
    if not math.isfinite(condition) or condition > 1e8:
        raise ValueError("historical sampling does not identify harmonic frequencies")
    return {
        "coef": coef,
        "last_year_mean_residual_m": means[latest],
        "last_year_midpoint": latest + 0.5,
        "annual_residual_means_m": {str(y): v for y, v in means.items()},
        "residual_slope_m_per_year": slope,
        "training_hours": len(times),
        "fit_availability": {str(y): sum(t.year == y for t in times) / len(previous.hours(y)) for y in years},
        "frequency_sampling_condition_proxy": condition,
        "condition_scope": "frequency-only sampling proxy; not full physical identifiability or a field uncertainty certificate",
    }


def predictions(times, model, choice):
    values = reconstruct(times, model["coef"])
    return (
        values
        + choice["level_weight"] * model["last_year_mean_residual_m"]
        + choice["trend_weight"]
        * model["residual_slope_m_per_year"]
        * (year_coordinate(times) - model["last_year_midpoint"])
    )


def quarter_errors(times, values, observed):
    return [
        float(np.mean([abs(value - observed[t]) for t, value in zip(times, values) if (t.month - 1) // 3 == q]))
        for q in range(4)
    ]


def choose(g, case, plan):
    folds = []
    for year in case["selection_years"]:
        target = [t for t in previous.hours(year) if t in g["observed"]]
        if len(target) / len(previous.hours(year)) < 0.8 or any(
            sum((t.month - 1) // 3 == q for t in target) < 400 for q in range(4)
        ):
            raise ValueError("selection year/quarter has insufficient true observations")
        fitted = {count: fit(g, list(range(year - 3, year)), count, plan) for count in [8, 20]}
        folds.append((target, fitted))
    candidates = []
    for count in [8, 20]:
        for level in [0, 0.5, 1]:
            for trend in [0, 0.5, 1]:
                choice = {"count": count, "level_weight": level, "trend_weight": trend}
                qs = [
                    e
                    for times, fitted in folds
                    for e in quarter_errors(times, predictions(times, fitted[count], choice), g["observed"])
                ]
                candidates.append({**choice, "quarter_mae_m": qs, "objective": float(np.mean(qs) + 0.25 * max(qs))})
    baseline = min(
        [c for c in candidates if not c["level_weight"] and not c["trend_weight"]], key=lambda c: c["objective"]
    )
    eligible = [
        c
        for c in candidates
        if baseline["objective"] - c["objective"] >= 0.001
        and all(a <= b + 0.005 for a, b in zip(c["quarter_mae_m"], baseline["quarter_mae_m"]))
    ]
    selected = min(eligible, key=lambda c: c["objective"]) if eligible else baseline
    quarter_radii, bias_means, calibration = {}, [], []
    for year in case["calibration_years"]:
        model = fit(g, list(range(year - 3, year)), selected["count"], plan)
        times = [t for t in previous.hours(year) if t in g["observed"]]
        values = predictions(times, model, selected)
        errors = [(t, float(v - g["observed"][t])) for t, v in zip(times, values)]
        if len(errors) < 400:
            raise ValueError("interval calibration year lacks actual residuals")
        bias_means.append(float(np.mean([e for _, e in errors])))
        row = {"year": year, "n": len(errors), "quarter_radius_m": {}}
        for q in range(4):
            subset = [e for t, e in errors if (t.month - 1) // 3 == q]
            if len(subset) < 200:
                raise ValueError("interval calibration quarter lacks true residuals")
            radius = files.radius(subset, plan["interval"]["quantile"]) * plan["interval"]["margin"]
            row["quarter_radius_m"][str(q + 1)] = radius
            quarter_radii[str(q + 1)] = max(0.02, quarter_radii.get(str(q + 1), 0), radius)
        calibration.append(row)
    bias_spread = max(bias_means) - min(bias_means)
    quarter_radii = {k: max(v, bias_spread * 1.1) for k, v in quarter_radii.items()}
    chosen_model = fit(g, case["fit_years"], selected["count"], plan)
    base_model = fit(g, case["fit_years"], baseline["count"], plan)
    return selected, baseline, candidates, quarter_radii, calibration, chosen_model, base_model


def short_value(at, observed, tide, horizon, memory):
    cutoff = at - timedelta(hours=horizon)
    times = [cutoff - timedelta(hours=i) for i in range(memory)]
    if any(t not in observed or t not in tide for t in times) or at not in tide:
        return None
    return tide[at] + statistics_mean([observed[t] - tide[t] for t in times]), cutoff


def statistics_mean(values):
    return sum(values) / len(values)


def short_develop(g, chosen_model, selected):
    times = sorted(t for t in g["observed"] if t.year == 2025)
    tide = dict(zip(times, predictions(times, chosen_model, selected).tolist()))
    choices = []
    for horizon in [1, 6]:
        rows = []
        for memory in [1, 3, 6, 12]:
            values = {t: short_value(t, g["observed"], tide, horizon, memory) for t in times}
            dev = [t for t, v in values.items() if v and t.month % 2]
            if not dev:
                continue
            rows.append(
                {"memory": memory, "mae_m": statistics_mean([abs(values[t][0] - g["observed"][t]) for t in dev])}
            )
        if not rows:
            choices.append({"horizon": horizon, "blocked": True})
            continue
        best = min(rows, key=lambda r: r["mae_m"])
        errors = [(t, short_value(t, g["observed"], tide, horizon, best["memory"])) for t in times if not t.month % 2]
        errors = [v[0] - g["observed"][t] for t, v in errors if v]
        if len(errors) < 200:
            choices.append({"horizon": horizon, "blocked": True})
            continue
        dev = [t for t in times if t.month % 2 and t - timedelta(hours=horizon) in g["observed"]]
        base = {
            "persistence": statistics_mean(
                [abs(g["observed"][t - timedelta(hours=horizon)] - g["observed"][t]) for t in dev]
            ),
            "astronomical": statistics_mean([abs(tide[t] - g["observed"][t]) for t in dev]),
        }
        choices.append(
            {
                "horizon": horizon,
                "memory": best["memory"],
                "baseline": min(base, key=base.get),
                "baselines_development_mae_m": base,
                "radius_m": max(0.003, files.radius(errors, 0.9) * 1.1),
                "calibration_n": len(errors),
                "candidates": rows,
                "blocked": False,
            }
        )
    return choices


def develop():
    target = DATA / "selection-before-test.json"
    if target.exists():
        raise ValueError("selection frozen")
    plan = json.loads((DATA / "protocol.json").read_text())
    manifest, groups = load("history")
    models = []
    for sid, g in groups.items():
        is_annual = sid in plan["new_annual_stations"]
        case = plan["annual2025"] if is_annual else plan["july2026"]
        try:
            selected, baseline, candidates, radii, calibration, chosen, base = choose(g, case, plan)
            files_out = {}
            for label, fitted in [("selected", chosen), ("baseline", base)]:
                path = DATA / f"coefficients-{sid}-{label}.json"
                files.write(path, files.encode(fitted["coef"]))
                files_out[label] = {
                    "path": str(path.relative_to(files.BASE_DIR)),
                    "sha256": files.sha(path),
                    **{k: v for k, v in fitted.items() if k != "coef"},
                }
            # 2025 residual replay must use coefficients fitted before 2025.
            short = [] if is_annual else short_develop(g, fit(g, [2022, 2023, 2024], selected["count"], plan), selected)
            model = {
                "status": "frozen",
                "selected": selected,
                "baseline": baseline,
                "candidates": candidates,
                "quarter_radii_m": radii,
                "calibration": calibration,
                "models": files_out,
                "short": short,
            }
        except ValueError as exc:
            model = {
                "status": "blocked",
                "reason": str(exc),
                "short": [{"horizon": h, "blocked": True} for h in [1, 6]],
            }
        model.update(
            station_id=sid,
            site=g["site"],
            provider=g["provider"],
            annual_new_station=is_annual,
            forecast_origin=case["origin"],
            **provenance(g),
        )
        models.append(model)
        print("V7_TWIN_SELECTED", sid, model["status"], model.get("selected"), model.get("reason"), flush=True)
    files.write(
        target,
        {
            "schema": "xiaoyi-twin-selection.v7",
            "frozen_at": datetime.now(UTC).isoformat(),
            "source_sha256": files.sha(Path(__file__)),
            "protocol_sha256": files.sha(DATA / "protocol.json"),
            "history_manifest_sha256": files.sha(DATA / "history-manifest.json"),
            "models": models,
            "test_labels_used": False,
            "production_authority": False,
        },
    )


def reconstruct_model(meta):
    p = files.BASE_DIR / meta["path"]
    if files.sha(p) != meta["sha256"]:
        raise ValueError("frozen coefficients changed")
    return {"coef": decode(json.loads(p.read_text())), **meta}


def assess():
    target = DATA / "report.json"
    if target.exists():
        raise ValueError("never overwrite a viewed held-out result")
    sealed = json.loads((DATA / "selection-before-test.json").read_text())
    plan = json.loads((DATA / "protocol.json").read_text())
    for k, path in [
        ("source_sha256", Path(__file__)),
        ("protocol_sha256", DATA / "protocol.json"),
        ("history_manifest_sha256", DATA / "history-manifest.json"),
    ]:
        if files.sha(path) != sealed[k]:
            raise ValueError("selection input changed after freezing")
    manifest, groups = load("test")
    rows = []
    trace = DATA / "predictions.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for model in sealed["models"]:
            sid = model["station_id"]
            g = groups[sid]
            annual = model["annual_new_station"]
            expected = (
                previous.hours(2025)
                if annual
                else [datetime(2026, 7, 9, tzinfo=UTC) + timedelta(hours=i) for i in range(23 * 24)]
            )
            modes = ["long_open_loop"] if annual else ["long_open_loop", "short1", "short6"]
            observed = g["observed"]
            fitted = model["status"] == "frozen"
            if (
                fitted
                and observed
                and (set(model["datums"]) != g["datums"] or set(model["record_ids"]) != g["records"])
            ):
                raise ValueError("held-out datum/record change")
            tide, base = {}, {}
            if fitted:
                chosen, baseline = (
                    reconstruct_model(model["models"]["selected"]),
                    reconstruct_model(model["models"]["baseline"]),
                )
                # Include context for short forecasts; long predictions never inspect water labels.
                times = (
                    expected
                    if annual
                    else [datetime(2026, 7, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(31 * 24)]
                )
                tide = dict(zip(times, predictions(times, chosen, model["selected"]).tolist()))
                base = dict(zip(times, predictions(times, baseline, model["baseline"]).tolist()))
            for mode in modes:
                points = []
                short = (
                    None
                    if mode == "long_open_loop"
                    else next(c for c in model["short"] if c["horizon"] == int(mode[-1]))
                )
                matured = []
                # Residual labels only become eligible once their target has actually occurred.
                prior_points = []
                if short and fitted and not short["blocked"]:
                    for at in sorted(tide):
                        value = short_value(at, observed, tide, short["horizon"], short["memory"])
                        if value and at in observed:
                            prior_points.append((at, value[0] - observed[at]))
                cursor = 0
                for at in expected:
                    value, bvalue, radius, cutoff = None, None, None, None
                    if fitted and mode == "long_open_loop":
                        value, bvalue, radius = (
                            tide[at],
                            base[at],
                            model["quarter_radii_m"][str((at.month - 1) // 3 + 1)],
                        )
                    elif fitted and not short["blocked"]:
                        prediction = short_value(at, observed, tide, short["horizon"], short["memory"])
                        if prediction:
                            value, cutoff = prediction
                            bvalue = observed[cutoff] if short["baseline"] == "persistence" else tide[at]
                            while cursor < len(prior_points) and prior_points[cursor][0] <= cutoff:
                                matured.append(prior_points[cursor])
                                cursor += 1
                            recent = [e for t, e in matured if t >= cutoff - timedelta(days=14)]
                            radius = max(short["radius_m"], files.radius(recent, 0.9) * 1.1 if len(recent) >= 24 else 0)
                    point = {
                        "station_id": sid,
                        "mode": mode,
                        "at": at.isoformat(),
                        "forecast_origin": model["forecast_origin"]
                        if mode == "long_open_loop"
                        else (cutoff.isoformat() if cutoff else None),
                        "actual_m": observed.get(at),
                        "predicted_m": value,
                        "baseline_m": bvalue,
                        "radius_m": radius,
                        "test_water_used_as_long_input": False,
                        "short_latest_input": cutoff.isoformat() if cutoff else None,
                        "interval_latest_residual_target": matured[-1][0].isoformat() if matured else None,
                    }
                    handle.write(json.dumps(point, allow_nan=False) + "\n")
                    points.append(point)
                periods = (
                    [("annual2025", points)]
                    + [(f"2025Q{q + 1}", [p for p in points if (int(p["at"][5:7]) - 1) // 3 == q]) for q in range(4)]
                    if annual
                    else [("2026July09-31", points)]
                )
                limits = plan["limits"] if mode == "long_open_loop" else plan["short_limits"][mode[-1]]
                for period, subset in periods:
                    metrics = previous.metrics(subset, limits)
                    rows.append(
                        {
                            "station_id": sid,
                            "site": model["site"],
                            "provider": model["provider"],
                            "period": period,
                            "mode": mode,
                            "new_station": annual,
                            "model_status": model["status"],
                            "observed_points": sum(p["actual_m"] is not None for p in subset),
                            "forecast_origin": model["forecast_origin"]
                            if mode == "long_open_loop"
                            else "rolling causal event-time",
                            **metrics,
                            **provenance(g),
                        }
                    )
            print(
                "V7_TWIN_HELDOUT",
                sid,
                [(r["period"], r["mode"], r["passed"], r["blockers"]) for r in rows if r["station_id"] == sid],
                flush=True,
            )

    def summary(subset):
        return {
            "passed": sum(r["passed"] for r in subset),
            "total": len(subset),
            "all_passed": bool(subset) and all(r["passed"] for r in subset),
        }

    files.write(
        target,
        {
            "schema": "xiaoyi-twin-report.v7",
            "protocol": plan,
            "selection": sealed,
            "selection_sha256": files.sha(DATA / "selection-before-test.json"),
            "sources": {"history": json.loads((DATA / "history-manifest.json").read_text()), "test": manifest},
            "results": rows,
            "annual": summary([r for r in rows if r["period"] == "annual2025"]),
            "quarters": summary([r for r in rows if "Q" in r["period"]]),
            "new_periods": summary([r for r in rows if not r["new_station"] and r["mode"] == "long_open_loop"]),
            "short": summary([r for r in rows if r["mode"].startswith("short")]),
            "trace_path": str(trace.relative_to(files.BASE_DIR)),
            "trace_sha256": files.sha(trace),
            "notice": "New6station complete2025year and previously unseen16station July9..31 separately qualified. Missing observations/models stay failures. Short replay assumes event-time local observations; long mode never initializes/updates on test water. OldV6failures preserved; no field, bathymetry, equipment or production qualification.",
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    {"develop": develop, "assess": assess}[parser.parse_args().phase]()
