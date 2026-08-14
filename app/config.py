from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
KB_DIR = DATA_DIR / "kb"
KB_PENDING_DIR = DATA_DIR / "kb_pending"
INDEX_PATH = DATA_DIR / "xiaoyi_index.json"
VECTOR_INDEX_PATH = DATA_DIR / "xiaoyi_vector_index.json"
SOURCE_REGISTRY_PATH = DATA_DIR / "source_registry.json"
KNOWLEDGE_CATALOG_PATH = DATA_DIR / "knowledge_catalog.json"
AUTHORITY_COVERAGE_PATH = DATA_DIR / "authority_coverage.json"
EVALUATION_BENCHMARK_PATH = DATA_DIR / "evaluation" / "maritime_qa_benchmark_v1.json"
RAG_RELEASE_REPORT_PATH = BASE_DIR / "reports" / "maritime_rag_benchmark_v1_20260814_r3.json"
WEB_DIR = BASE_DIR / "web"
RUNTIME_DB_PATH = DATA_DIR / "xiaoyi_runtime.db"

APP_NAME = "小懿"
APP_VERSION = "0.4.0"
DEFAULT_TOP_K = 5

SUPPORTED_MODES = {
    "expert": "专业问答",
    "ops": "运营问答",
    "sop": "SOP 生成",
    "brief": "简报摘要",
}
