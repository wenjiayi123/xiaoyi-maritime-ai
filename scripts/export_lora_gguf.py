from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADAPTER = ROOT / "artifacts" / "lora" / "xiaoyi-maritime-1.7b"
DEFAULT_OUTPUT = DEFAULT_ADAPTER / "xiaoyi-maritime-1.7b-f16.gguf"
DEFAULT_BASE_MODEL = ROOT / ".runtime" / "models" / "maritime-training-1.7b"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把PEFT LoRA适配器转换为llama.cpp可加载的GGUF适配器"
    )
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--llama-cpp-root",
        type=Path,
        default=ROOT / ".runtime" / "vendor" / "llama.cpp",
    )
    args = parser.parse_args()
    converter = args.llama_cpp_root / "convert_lora_to_gguf.py"
    if not converter.is_file():
        git = shutil.which("git")
        if not git:
            raise SystemExit("未找到git，不能获取llama.cpp转换器")
        args.llama_cpp_root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                git,
                "clone",
                "--branch",
                "b10107",
                "--depth",
                "1",
                "https://github.com/ggml-org/llama.cpp.git",
                str(args.llama_cpp_root),
            ],
            check=True,
        )
    if not (args.adapter_dir / "adapter_config.json").is_file():
        raise SystemExit("未找到PEFT适配器；先运行 scripts/train_lora.py")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(converter),
            "--base-model-id",
            os.getenv("XIAOYI_LORA_BASE_MODEL", str(DEFAULT_BASE_MODEL)),
            "--outtype",
            "f16",
            "--outfile",
            str(args.output),
            str(args.adapter_dir),
        ],
        check=True,
    )
    print(f"GGUF LoRA适配器：{args.output}")


if __name__ == "__main__":
    main()
