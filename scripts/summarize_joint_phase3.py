"""Summarize retained phase-three observations without changing their verdicts."""

from __future__ import annotations

import collections
import csv
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".codex_artifacts/joint-harness-phase3-20261029"


def read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def lines(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    soak = ART / "soak-accepted-2h"
    samples = lines(soak / "samples.ndjson")
    workloads = lines(soak / "workloads.ndjson")
    records = collections.defaultdict(list)
    for sample in samples:
        for line in sample.get("processes", []):
            match = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\S+)\s+(.+)", line)
            if not match:
                continue
            pid, _, rss, _, state, cmd = match.groups()
            label = (
                "generation"
                if "--alias xiaoyi-local-4b" in cmd
                else "embedding"
                if "--alias xiaoyi-embedding-0.6b" in cmd
                else "xiaoyi_api"
                if "--port 8010" in cmd
                else "energy_api"
                if "--port 8808" in cmd
                else "linux_vm_host"
                if "Virtualization.VirtualMachine" in cmd
                else "godot_headless"
                if "Godot --headless" in cmd
                else "mobile_web"
                if "http.server 7357" in cmd
                else "other_sampled_process"
            )
            records[(label, pid)].append((sample["elapsed_seconds"], int(rss) / 1024, state))
    process_summary = []
    for (label, pid), values in sorted(records.items()):
        process_summary.append(
            {
                "label": label,
                "pid": int(pid),
                "samples": len(values),
                "first_elapsed_seconds": values[0][0],
                "last_elapsed_seconds": values[-1][0],
                "first_rss_mib": round(values[0][1], 2),
                "last_rss_mib": round(values[-1][1], 2),
                "peak_rss_mib": round(max(v[1] for v in values), 2),
                "last_state": values[-1][2],
            }
        )
    gaps = [b["elapsed_seconds"] - a["elapsed_seconds"] for a, b in zip(samples, samples[1:])]
    native_dir = ART / "native-business-soak"
    native = read(native_dir / "summary.json", read(native_dir / "progress.json", {}))
    prior = read(ART.parent / "joint-harness-phase2-20261029/native-voyages/matrix.json", {})
    actors = {r["scene"]: r["receipt"]["actor_sha256"] for r in prior.get("results", [])}
    actor_sources = {scene: "phase2/native-voyages/matrix.json" for scene in actors}
    # The initial open-water run was retained in accepted mission exports,
    # while the later dedicated matrix contains the other six scenarios.
    for file in sorted((ART.parent / "joint-harness-phase2-20261029").glob("*accepted-export.json")):
        mission = read(file, {}).get("mission", {})
        raw = mission.get("results", {}).get("sailing", {}).get("data", {}).get("raw", {})
        if raw.get("execution_scope") == "isolated_full_native_mission" and raw.get("actor_sha256"):
            scene = raw["scenario"]
            if scene in actors and actors[scene] != raw["actor_sha256"]:
                raise ValueError("conflicting retained phase-two policy baselines: " + scene)
            actors[scene] = raw["actor_sha256"]
            actor_sources[scene] = "phase2/" + file.name
    voyage_rows = []
    for result in native.get("results", []):
        if not result.get("id"):
            continue
        receipt = read(native_dir / (result["id"] + ".json"), {})
        raw = receipt.get("mission", {}).get("results", {}).get("sailing", {}).get("data", {}).get("raw", {})
        if not raw:
            continue
        validation = raw["validation"]
        voyage_rows.append(
            {
                "id": result["id"],
                "scene": result["scene"],
                "mode": result["mode"],
                "safe_pass": validation["safePass"],
                "reached_destination": validation["reachedDestination"],
                "collision_count": validation["collisionCount"],
                "teleporting": raw["trajectory_teleporting"],
                "physics_frames": raw["physics_frames"],
                "inference_count": raw["inference_count"],
                "simulation_seconds": validation["simulatedDurationSeconds"],
                "actor_matches_phase2": actors.get(result["scene"]) == raw["actor_sha256"],
                "actor_baseline_source": actor_sources.get(result["scene"]),
                "ukc_observed": validation.get("ukc_observed"),
                "minimum_ukc_m": validation.get("minimum_ukc_m"),
                "bank_observed": validation.get("bank_observed"),
                "minimum_bank_clearance_m": validation.get("minimum_bank_clearance_m"),
            }
        )
    if voyage_rows:
        with (ART / "native-voyage-matrix.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(voyage_rows[0]))
            writer.writeheader()
            writer.writerows(voyage_rows)
    policy = [w for w in workloads if w.get("kind") == "policy" and w.get("status") == "completed"]
    summary = {
        "schema": "xiaoyi-phase3-evidence-summary.v1",
        "soak": read(soak / "summary.json", {"in_progress": True, **read(soak / "progress.json", {})}),
        "sample_window_seconds": samples[-1]["elapsed_seconds"] - samples[0]["elapsed_seconds"],
        "max_sample_gap_seconds": max(gaps) if gaps else None,
        "workload_counts": dict(
            collections.Counter((w["kind"] + ":" + w.get("status", "recorded")) for w in workloads)
        ),
        "completed_policy_selections": dict(collections.Counter(w["comparison"]["selected"]["model"] for w in policy)),
        "process_rss_by_pid": process_summary,
        "resource_boundary": "RSS covers matched processes, not every system or total machine memory; process peaks are not additive and this is not a memory-leak proof.",
        "native_business": native,
        "native_voyages": {
            "rows": voyage_rows,
            "all_software_checks_pass": bool(voyage_rows)
            and all(
                r["safe_pass"]
                and r["reached_destination"]
                and r["collision_count"] == 0
                and r["teleporting"] is False
                and r["actor_matches_phase2"]
                for r in voyage_rows
            ),
            "boundary": "Software voyage checks only; missing observations remain null, and human bridge procedures/certification are not inferred.",
        },
        "original_integrity": {
            k: v
            for k, v in read(
                ART / "original-integrity-phase3-final.json", read(ART / "original-integrity-phase3.json", {})
            ).items()
            if k != "items"
        },
        "cleanup_regression": read(ART / "soak-cleanup-regression/summary.json"),
        "ui_coverage": read(ART / "ui-coverage.json"),
        "policy_service_continuity": read(
            ART / "policy-service-continuity-final.json", read(ART / "policy-service-continuity-interim.json")
        ),
        "native_gui": "skipped_by_user_not_passed",
        "production_authority": False,
    }
    (ART / "evidence-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "soak": summary["soak"],
                "native_cycles": len(native.get("results", [])),
                "native_passed": sum(bool(r.get("passed")) for r in native.get("results", [])),
                "workload_counts": summary["workload_counts"],
                "sampled_pids": len(process_summary),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
