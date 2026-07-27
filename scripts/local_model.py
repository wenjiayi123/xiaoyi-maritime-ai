from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "model_registry.json"
def _registry(model_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    selected_id = model_id or payload["default_model_id"]
    model = next(
        item for item in payload["models"] if item["model_id"] == selected_id
    )
    return payload, model


def _model_path(model: dict[str, Any]) -> Path:
    path_env = str(model.get("path_env") or "")
    configured = os.getenv(path_env, "").strip() if path_env else ""
    path = Path(configured or str(model["local_path"]))
    return path if path.is_absolute() else ROOT / path


def _configured_download_url(model: dict[str, Any]) -> str:
    url_env = str(model.get("download_url_env") or "")
    configured = os.getenv(url_env, "").strip() if url_env else ""
    if configured:
        return configured
    fallback = str(model.get("download_url") or "").strip()
    if fallback:
        return fallback
    raise RuntimeError(
        f"未配置模型下载地址；请设置 {url_env or '对应的 DOWNLOAD_URL 环境变量'}"
    )


def _configured_sha256(model: dict[str, Any]) -> str:
    sha_env = str(model.get("sha256_env") or "")
    configured = os.getenv(sha_env, "").strip().lower() if sha_env else ""
    return configured or str(model.get("sha256") or "").strip().lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_file(url: str, path: Path) -> None:
    curl = shutil.which("curl")
    path.parent.mkdir(parents=True, exist_ok=True)
    if curl:
        subprocess.run(
            [
                curl,
                "--fail",
                "--location",
                "--continue-at",
                "-",
                "--progress-bar",
                "--output",
                str(path),
                url,
            ],
            check=True,
        )
        return
    request = Request(url)
    try:
        with urlopen(request, timeout=60) as response, path.open("wb") as output:
            shutil.copyfileobj(response, output, 8 * 1024 * 1024)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"下载失败：{exc}") from exc


def verify(*, quiet: bool = False, model_id: str | None = None) -> dict[str, Any]:
    _, model = _registry(model_id)
    path = _model_path(model)
    if not path.is_file():
        raise FileNotFoundError(
            f"模型不存在：{path}\n运行：{sys.executable} scripts/local_model.py download"
        )
    actual_bytes = path.stat().st_size
    expected_bytes = int(model["expected_bytes"])
    if actual_bytes != expected_bytes:
        raise ValueError(
            f"模型大小不符：actual={actual_bytes}, expected={expected_bytes}"
        )
    actual_sha256 = _sha256(path)
    expected_sha256 = _configured_sha256(model)
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise ValueError(
            f"模型SHA-256不符：actual={actual_sha256}, expected={expected_sha256}"
        )
    result = {
        "verified": True,
        "model_id": model["model_id"],
        "path": str(path),
        "bytes": actual_bytes,
        "sha256": actual_sha256,
        "revision": model["revision"],
        "license": model["license"],
    }
    receipt_path = path.with_name(f"{model['model_id']}.receipt.json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _download_with_curl(url: str, path: Path) -> None:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("未找到 curl，无法进行可断点续传下载")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            curl,
            "--fail",
            "--location",
            "--continue-at",
            "-",
            "--progress-bar",
            "--output",
            str(path),
            url,
        ],
        check=True,
    )


def _download_with_urllib(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = path.stat().st_size if path.exists() else 0
    headers = {"Range": f"bytes={downloaded}-"} if downloaded else {}
    request = Request(url, headers=headers)
    mode = "ab" if downloaded else "wb"
    try:
        with urlopen(request, timeout=60) as response, path.open(mode) as output:
            if downloaded and getattr(response, "status", 200) != 206:
                output.close()
                path.unlink(missing_ok=True)
                return _download_with_urllib(url, path)
            while True:
                block = response.read(8 * 1024 * 1024)
                if not block:
                    break
                output.write(block)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"模型下载失败，可重新运行以断点续传：{exc}") from exc


def download(*, model_id: str | None = None) -> dict[str, Any]:
    _, model = _registry(model_id)
    path = _model_path(model)
    if path.exists() and path.stat().st_size == int(model["expected_bytes"]):
        return verify(model_id=model["model_id"])
    url = _configured_download_url(model)
    if shutil.which("curl"):
        _download_with_curl(url, path)
    else:
        _download_with_urllib(url, path)
    return verify(model_id=model["model_id"])


def install_runtime() -> dict[str, Any]:
    registry, _ = _registry()
    runtime = registry["inference_runtime"]
    archive_path = ROOT / runtime["archive_path"]
    binary_path = ROOT / runtime["local_binary"]
    if not archive_path.exists() or (
        archive_path.stat().st_size != int(runtime["expected_bytes"])
        or _sha256(archive_path) != runtime["sha256"]
    ):
        archive_path.unlink(missing_ok=True)
        _download_file(str(runtime["download_url"]), archive_path)
    if archive_path.stat().st_size != int(runtime["expected_bytes"]):
        raise ValueError("llama.cpp运行时压缩包大小不符")
    if _sha256(archive_path) != runtime["sha256"]:
        raise ValueError("llama.cpp运行时压缩包SHA-256不符")

    destination = binary_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xiaoyi-llama-runtime-") as temp:
        temp_path = Path(temp)
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk():
                    raise ValueError(f"拒绝压缩包链接项：{member.name}")
                resolved = (temp_path / member.name).resolve()
                if temp_path.resolve() not in resolved.parents and resolved != temp_path.resolve():
                    raise ValueError(f"拒绝不安全的压缩包路径：{member.name}")
            archive.extractall(temp_path)
        roots = [item for item in temp_path.iterdir() if item.is_dir()]
        if len(roots) != 1 or not (roots[0] / "llama-server").is_file():
            raise ValueError("llama.cpp压缩包结构不符合预期")
        for source in roots[0].iterdir():
            target = destination / source.name
            if source.is_file():
                shutil.copy2(source, target)
    binary_path.chmod(binary_path.stat().st_mode | 0o111)
    result = {
        "installed": True,
        "release": runtime["release"],
        "binary": str(binary_path),
        "archive_sha256": runtime["sha256"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def status(*, model_id: str | None = None) -> dict[str, Any]:
    registry, model = _registry(model_id)
    path = _model_path(model)
    result = {
        "selection_date": registry["selection_date"],
        "hardware_profile": registry["hardware_profile"],
        "model_id": model["model_id"],
        "artifact_profile": model["upstream_model"],
        "quantization": model["quantization"],
        "expected_bytes": model["expected_bytes"],
        "local_path": str(path),
        "downloaded_bytes": path.stat().st_size if path.exists() else 0,
        "llama_server": shutil.which("llama-server"),
        "bundled_llama_server": str(
            ROOT / registry["inference_runtime"]["local_binary"]
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="下载、校验并登记小懿本地开源生成模型"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("--model-id")
    subparsers.add_parser("install-runtime")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--quiet", action="store_true")
    verify_parser.add_argument("--model-id")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--model-id")
    args = parser.parse_args()
    if args.command == "download":
        download(model_id=args.model_id)
    elif args.command == "install-runtime":
        install_runtime()
    elif args.command == "verify":
        verify(quiet=args.quiet, model_id=args.model_id)
    else:
        status(model_id=args.model_id)


if __name__ == "__main__":
    main()
