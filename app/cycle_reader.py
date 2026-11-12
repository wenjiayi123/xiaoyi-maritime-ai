"""Verify the selected work order and its source bytes on every read."""
import hashlib
import json
import re
from pathlib import Path


def checked(path, expected):
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("工单证据指纹不符：" + path.name)
    return content


def read_case(directory: Path, registry_sha: str, case_id: str):
    registry = json.loads(checked(directory / "index.json", registry_sha))
    if case_id not in registry:
        raise ValueError("找不到已登记工单：" + case_id)
    entry = registry[case_id]
    for name, fingerprint in entry["parents"].items():
        if not re.fullmatch("[a-f0-9]{64}", fingerprint):
            raise ValueError("无效原件指纹：" + name)
        checked(directory / "objects" / fingerprint, fingerprint)
    receipt = entry["receipt"]
    if receipt["工单编号"] != case_id:
        raise ValueError("回执与工单编号不一致")
    return receipt
