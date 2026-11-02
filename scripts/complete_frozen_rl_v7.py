"""Complete the existing, previously frozen V7 study without modifying its policy."""

import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import rl_v7 as study  # noqa: E402


def main():
    plan = json.loads((study.DATA / "protocol.json").read_text())
    frozen_path = study.OUT / "selection-before-test.json"
    frozen = json.loads(frozen_path.read_text())
    assert frozen["source_hashes"] == study.sources()
    manifest_path = study.DATA / "manifest.json"
    if not manifest_path.exists():
        primary = json.loads((ROOT / "data/public/operations_v5_20261030/manifest.json").read_text())["primary_export"]
        path = ROOT / primary["path"]
        assert study.c.sha(path) == primary["sha256"]
        ports = {p["id"]: {**p, "data": []} for p in plan["new_ports"]}
        assert not (set(ports) & set(plan["train_ports"]))
        with gzip.open(path, "rt", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if row["portid"] in ports:
                    ports[row["portid"]]["data"].append(
                        {
                            "date": row["date"].replace("/", "-"),
                            "portcalls": row["portcalls"],
                            "import": row["import"],
                            "export": row["export"],
                        }
                    )
        entries = []
        for identity, port in ports.items():
            rows = sorted(port.pop("data"), key=lambda r: r["date"])
            path = study.DATA / (identity + ".csv")
            with path.open("x") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "portcalls", "import", "export"])
                writer.writeheader()
                writer.writerows(rows)
            entries.append(
                {
                    **port,
                    "path": str(path.relative_to(ROOT)),
                    "sha256": study.c.sha(path),
                    "rows": len(rows),
                    "start": rows[0]["date"],
                    "end": rows[-1]["date"],
                }
            )
        with manifest_path.open("x") as handle:
            json.dump(
                {
                    "schema": "xiaoyi-new-rl-ports.v7",
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "selection_sha256": study.c.sha(frozen_path),
                    "protocol_sha256": study.c.sha(study.DATA / "protocol.json"),
                    "primary_export": primary,
                    "entries": entries,
                    "new_source_vintage": False,
                    "production_authority": False,
                },
                handle,
                indent=2,
            )
        print("EXTRACTED", len(entries), flush=True)
    study.assess()


if __name__ == "__main__":
    main()
