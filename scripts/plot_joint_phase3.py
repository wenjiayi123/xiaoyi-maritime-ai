"""Plot retained local test observations; no smoothing or inferred field KPI."""

from __future__ import annotations
import csv
import datetime as dt
import json
from pathlib import Path
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ART = Path(__file__).resolve().parents[1] / ".codex_artifacts/joint-harness-phase3-20261029"


def ndjson(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    samples = ndjson(ART / "soak-accepted-2h/samples.ndjson")
    events = ndjson(ART / "native-business-soak/events.ndjson")
    start = samples[0]["epoch"]
    fig, axes = plt.subplots(
        3, 1, figsize=(14, 12), constrained_layout=True, gridspec_kw={"height_ratios": [1, 1, 1.5]}
    )
    health_rows = []
    for name in samples[0]["health"]:
        points = [
            (s["elapsed_seconds"] / 60, s["health"][name]["seconds"] * 1000, s["health"][name]["ok"]) for s in samples
        ]
        axes[0].plot([p[0] for p in points], [p[1] for p in points], label=name, linewidth=0.9, alpha=0.8)
        for minute, ms, ok in points:
            health_rows.append([minute, name, ms, ok])
            if not ok:
                axes[0].scatter(minute, ms, color="red", marker="x", s=45)
    axes[0].set(
        ylabel="Probe latency (ms)",
        xlabel="Minutes since start",
        title="Local service probes (raw observations; failures marked red)",
    )
    axes[0].legend(ncol=5, fontsize=8)
    axes[0].grid(alpha=0.2)

    series = {}
    rss_rows = []
    for s in samples:
        for line in s.get("processes", []):
            m = re.match(r"\s*(\d+)\s+\d+\s+(\d+)\s+[\d.]+\s+\S+\s+(.+)", line)
            if not m:
                continue
            pid, rss, cmd = m.groups()
            label = (
                "generation"
                if "--alias xiaoyi-local-4b" in cmd
                else "embedding"
                if "--alias xiaoyi-embedding-0.6b" in cmd
                else "GullMate API"
                if "--port 8010" in cmd
                else "energy API"
                if "--port 8808" in cmd
                else "Linux VM host"
                if "Virtualization.VirtualMachine" in cmd
                else None
            )
            if label:
                t, value = s["elapsed_seconds"] / 60, int(rss) / 1024
                series.setdefault((label, pid), []).append((t, value))
                rss_rows.append([t, label, pid, value])
    for (label, pid), points in series.items():
        axes[1].plot([p[0] for p in points], [p[1] for p in points], linewidth=1, label=f"{label} (PID {pid})")
    axes[1].set(
        xlabel="Minutes since start",
        ylabel="Process RSS (MiB)",
        title="Selected long-lived processes (per PID; peaks are not additive)",
    )
    axes[1].legend(ncol=3, fontsize=8)
    axes[1].grid(alpha=0.2)

    created = {e["id"]: e for e in events if e["kind"] == "created"}
    finished = [e for e in events if e["kind"] == "cycle_finished"]
    cycle_rows = []
    for index, event in enumerate(finished):
        c = created[event["id"]]
        begin = (c["epoch"] - start) / 60
        duration = (event["epoch"] - c["epoch"]) / 60
        color = "#2463a7" if event["mode"] == "enterprise" else "#148d73"
        axes[2].barh(index, duration, left=begin, color=color, height=0.65)
        axes[2].text(begin + duration + 0.2, index, f"{event['wall_seconds']:.1f}s", va="center", fontsize=7)
        cycle_rows.append(
            [
                event["id"],
                event["mode"],
                event["scene"],
                begin,
                duration,
                event["status"],
                event["passed"],
                event.get("test_cleanup_status"),
            ]
        )
    axes[2].set_yticks(range(len(finished)), [f"{i + 1}. {e['scene']} / {e['mode']}" for i, e in enumerate(finished)])
    axes[2].tick_params(axis="y", labelsize=8)
    axes[2].invert_yaxis()
    if cycle_rows:
        axes[2].set_xlim(min(r[3] for r in cycle_rows) - 0.5, max(r[3] + r[4] for r in cycle_rows) + 2)
    axes[2].set(
        xlabel="Minutes since probe-window start",
        title="Native full-business cycles (blue=enterprise, green=research; mobile ACK omitted)",
    )
    axes[2].grid(axis="x", alpha=0.2)
    fig.suptitle("GullMate local simulation acceptance — measured test observations", fontsize=15)
    fig.savefig(ART / "stability-evidence.png", dpi=160)
    fig.savefig(ART / "stability-evidence.svg")
    for filename, header, rows in [
        ("health-timeseries.csv", ["minute", "service", "latency_ms", "ok"], health_rows),
        ("rss-timeseries.csv", ["minute", "process", "pid", "rss_mib"], rss_rows),
        (
            "native-cycle-times.csv",
            [
                "id",
                "mode",
                "scene",
                "start_minute",
                "duration_minute",
                "backend_status",
                "passed",
                "test_cleanup_status",
            ],
            cycle_rows,
        ),
    ]:
        with (ART / filename).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
    (ART / "plot-metadata.json").write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "samples": len(samples),
                "completed_native_cycles": len(finished),
                "sources": ["soak-accepted-2h/samples.ndjson", "native-business-soak/events.ndjson"],
                "processing": "raw line observations; no smoothing, resampling or confidence interval",
                "boundary": "Local simulation tests, not port field KPIs, total-machine memory or 24/7 SLA.",
            },
            indent=2,
        )
    )
    print("Saved stability-evidence.png/.svg and three traceable CSV files")


if __name__ == "__main__":
    main()
