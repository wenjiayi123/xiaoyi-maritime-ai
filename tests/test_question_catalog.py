from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "小懿可询问问题库"


def test_question_catalog_contains_all_required_sections() -> None:
    expected = {
        "00_问题库使用说明.md", "01_演示必问问题.md", "02_当前运营态势问题.md",
        "03_一线日常高频问题.md", "04_港航专业知识问题.md", "05_安全应急法规问题.md",
        "06_SOP报告与决策问题.md", "07_生产系统接入后实时问题.md", "08_英文辅助问法.md",
    }
    assert CATALOG.is_dir()
    assert expected == {path.name for path in CATALOG.glob("*.md")}


def test_question_catalog_is_comprehensive_and_marks_live_boundary() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(CATALOG.glob("*.md")))
    question_lines = [line for line in text.splitlines() if (line.startswith("- ") or line[:1].isdigit()) and ("？" in line or "?" in line)]
    assert len(question_lines) >= 300
    assert "南闸口要不要增开？" in text
    assert "QC-03 当前告警是什么？" in text
    assert "IMO 海事单一窗口从哪一年起强制实施？" in text
    assert "生产系统接入后实时问题" in text
    assert "不冒充生产实绩" in text
