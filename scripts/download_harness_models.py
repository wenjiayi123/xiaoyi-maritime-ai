"""Download only the registered revisions; never install packages into the app environment."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="all")
    args = parser.parse_args()
    records = json.loads((ROOT / "config/open_model_candidates.json").read_text())["candidates"]
    if args.candidate != "all" and args.candidate not in {r["id"] for r in records}:
        parser.error("candidate is not registered")
    for row in records:
        if args.candidate not in {"all", row["id"]}:
            continue
        path = ROOT / row["local_path"]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(path.suffix + ".part")
            url = f"https://huggingface.co/{row['repository']}/resolve/{row['revision']}/{row['file']}?download=true"
            with urlopen(url, timeout=60) as response, part.open("wb") as handle:
                while data := response.read(1024 * 1024):
                    handle.write(data)
            part.replace(path)
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ValueError(row["id"] + " checksum or size mismatch")
        print(row["id"], "verified", actual)


if __name__ == "__main__":
    main()
