from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import INDEX_PATH, KB_DIR  # noqa: E402
from app.retrieval import build_index  # noqa: E402


def main() -> None:
    chunks = build_index(KB_DIR, INDEX_PATH)
    print(f"小懿索引构建完成：{len(chunks)} 个知识片段")
    print(f"索引文件：{INDEX_PATH}")


if __name__ == "__main__":
    main()
