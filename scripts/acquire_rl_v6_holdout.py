"""Extract never-used ports from the pinned IMF export after selection freezes."""

import csv
import gzip
import json
from datetime import datetime, timezone

from app.harness import rl_v6 as study


def main():
    folder = study.DATA
    if (folder / "manifest.json").exists():
        raise ValueError("held-out source extraction is immutable")
    plan = json.loads((folder / "protocol.json").read_text())
    selection = json.loads((study.OUT / "selection-before-test.json").read_text())
    if selection["source_sha256"] != study.c.sha(study.c.BASE_DIR / "app/harness/rl_v6.py") or selection[
        "protocol_sha256"
    ] != study.c.sha(folder / "protocol.json"):
        raise ValueError("unsealed algorithm or protocol")
    prior = json.loads((study.c.BASE_DIR / "data/public/operations_v5_20261030/manifest.json").read_text())
    primary = prior["primary_export"]
    path = study.c.BASE_DIR / primary["path"]
    if study.c.sha(path) != primary["sha256"]:
        raise ValueError("pinned primary export changed")
    known, _ = study.load_development()
    ports = {p["id"]: {**p, "rows_data": []} for p in plan["new_ports"]}
    if set(ports) & set(known):
        raise ValueError("fresh-port overlap")
    with gzip.open(path, "rt", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["portid"] in ports:
                port = ports[row["portid"]]
                port["country"] = row["country"]
                port["rows_data"].append(
                    {
                        "date": row["date"].replace("/", "-"),
                        "portcalls": row["portcalls"],
                        "import": row["import"],
                        "export": row["export"],
                    }
                )
    entries = []
    for identity, port in ports.items():
        rows = sorted(port.pop("rows_data"), key=lambda r: r["date"])
        target = folder / (identity + ".csv")
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "portcalls", "import", "export"])
            writer.writeheader()
            writer.writerows(rows)
        entries.append(
            {
                **port,
                "path": str(target.relative_to(study.c.BASE_DIR)),
                "sha256": study.c.sha(target),
                "rows": len(rows),
                "start": rows[0]["date"],
                "end": rows[-1]["date"],
            }
        )
    study.c.write(
        folder / "manifest.json",
        {
            "schema": "xiaoyi-new-port-primary-sources.v6",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "protocol_sha256": study.c.sha(folder / "protocol.json"),
            "selection_sha256": study.c.sha(study.OUT / "selection-before-test.json"),
            "primary_export": primary,
            "entries": entries,
            "landing_url": prior["landing_url"],
            "latest_export_check": json.loads(
                (study.c.BASE_DIR / ".codex_artifacts/research-v6-20261030/portwatch-export-head.json").read_text()
            ),
            "live_query_failure": json.loads(
                (study.c.BASE_DIR / ".codex_artifacts/research-v6-20261030/portwatch-live-max-date.json").read_text()
            ),
            "new_source_vintage": False,
            "notice": "Eight previously unused ports, not a newer IMF export. Official HEAD matched the pinned export Last-Modified and size; live FeatureServer max-date query returned an upstream error which is retained. AIS-derived public activity indicators drive declared synthetic service physics; not actual terminal queue, capacity or financial performance.",
            "production_authority": False,
        },
    )
    print("FRESH_PORTS_EXTRACTED", len(entries), sum(e["rows"] for e in entries), flush=True)


if __name__ == "__main__":
    main()
