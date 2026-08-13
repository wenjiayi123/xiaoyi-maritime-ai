from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LOCK = ROOT / "requirements.lock"
DEV_LOCK = ROOT / "requirements-dev.lock"
OUTPUT = ROOT / "reports/sbom/xiaoyi-python-lock-snapshot.cdx.json"
PROJECT_VERSION = "0.4.0"
PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^;\s]+)(?:;\s*(.+))?$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_lock(path: Path) -> dict[str, dict[str, str | None]]:
    packages: dict[str, dict[str, str | None]] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-r ", "--hash=")):
            continue
        if line.endswith("\\"):
            line = line[:-1].rstrip()
        match = PIN_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(f"unsupported non-exact requirement in {path.name}: {line}")
        raw_name, version, marker = match.groups()
        name = re.sub(r"[-_.]+", "-", raw_name).lower()
        packages[name] = {"name": raw_name, "version": version, "marker": marker}
    return packages


def _component(name: str, item: dict[str, str | None], scope: str) -> dict[str, object]:
    version = str(item["version"])
    purl = f"pkg:pypi/{quote(name)}@{quote(version)}"
    properties = [{"name": "xiaoyi:dependency-scope", "value": scope}]
    if item.get("marker"):
        properties.append({"name": "xiaoyi:environment-marker", "value": str(item["marker"])})
    return {
        "type": "library",
        "bom-ref": purl,
        "name": str(item["name"]),
        "version": version,
        "purl": purl,
        "properties": properties,
    }


def build_payload() -> dict[str, object]:
    runtime = _parse_lock(RUNTIME_LOCK)
    development = _parse_lock(DEV_LOCK)
    combined = {**runtime, **development}
    components = [
        _component(name, combined[name], "runtime" if name in runtime else "development-only")
        for name in sorted(combined)
    ]
    root_ref = f"pkg:github/wenjiayi123/xiaoyi-maritime-ai@{PROJECT_VERSION}"
    identity = "\n".join(
        [PROJECT_VERSION, _sha256(RUNTIME_LOCK), _sha256(DEV_LOCK)]
        + [str(component["bom-ref"]) for component in components]
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, identity)}",
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "xiaoyi-lock-sbom-builder",
                        "version": "1.0.0",
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": "xiaoyi-maritime-ai",
                "version": PROJECT_VERSION,
                "purl": root_ref,
            },
            "properties": [
                {"name": "xiaoyi:requirements-lock-sha256", "value": _sha256(RUNTIME_LOCK)},
                {"name": "xiaoyi:requirements-dev-lock-sha256", "value": _sha256(DEV_LOCK)},
                {
                    "name": "xiaoyi:dependency-graph-boundary",
                    "value": "flat lock snapshot; transitive parent-child edges are not inferred",
                },
            ],
        },
        "components": components,
        "dependencies": [
            {"ref": root_ref, "dependsOn": [str(item["bom-ref"]) for item in components]}
        ],
    }


def _render() -> str:
    return json.dumps(build_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the committed Python lockfile SBOM.")
    parser.add_argument("command", choices=("build", "verify"))
    args = parser.parse_args()
    rendered = _render()
    if args.command == "build":
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8")
        print(f"SBOM written: {OUTPUT.relative_to(ROOT)} sha256={_sha256(OUTPUT)}")
        return 0
    if not OUTPUT.is_file():
        print(f"SBOM missing: {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
        return 1
    if OUTPUT.read_text(encoding="utf-8") != rendered:
        print("SBOM is stale; run `python scripts/build_sbom.py build`.", file=sys.stderr)
        return 1
    print(f"SBOM verified: {OUTPUT.relative_to(ROOT)} sha256={_sha256(OUTPUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
