from pathlib import Path

from app.knowledge_api import get_knowledge_status


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "XIAOYI_FRONTLINE_OPERATOR_SYSTEM_GUIDE.md"
INDEX_HTML = ROOT / "web" / "index.html"


def test_frontline_operator_guide_covers_actual_workflow_and_safety_boundary() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    required_sections = (
        "每班开始前的标准检查",
        "智能对话的正确使用方法",
        "运营态势和数据分析",
        "预警与异常处置",
        "知识库使用",
        "任务中心",
        "交接班标准操作",
        "一线人员禁止事项",
        "熟练度考核清单",
    )
    for section in required_sections:
        assert section in guide

    assert "SANDBOX" in guide
    assert "不是现场生产实绩" in guide
    assert "生产动作必须人工确认" in guide
    assert "http://127.0.0.1:8010" in guide


def test_guide_menu_labels_match_current_frontend() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    labels = (
        "智能对话",
        "决策建议",
        "数据分析",
        "知识库",
        "任务中心",
        "接口中心",
        "智能联动中心",
        "RAG评测闭环",
        "真实RL训练实验室",
    )
    for label in labels:
        assert label in guide
        assert label in html


def test_guide_inventory_snapshot_matches_runtime_index() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    status = get_knowledge_status()

    assert f"{status.document_count}份已登记知识文档" in guide
    assert f"{status.chunk_count}个检索片段" in guide
    assert f"{status.official_verified_documents}份经发布机构页面核验的来源资料" in guide
