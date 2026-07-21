from app.xiaoyi import XiaoyiAI


def test_xiaoyi_can_answer_port_question() -> None:
    engine = XiaoyiAI()
    result = engine.ask("集装箱码头 TOS 负责什么？")
    assert result.evidence
    assert "TOS" in result.answer or "码头" in result.answer


def test_common_incident_questions_hit_playbooks() -> None:
    engine = XiaoyiAI()
    cases = [
        ("港口失火怎么办", "港口失火怎么办", "立即报警"),
        ("码头着火怎么办", "码头着火怎么办", "停止受影响泊位"),
        ("堆场冒烟怎么办", "堆场冒烟怎么办", "冒烟对象"),
        ("危险品箱冒烟怎么办", None, "UN 编号"),
        ("港口漏油怎么办", "港口漏油怎么办", "围油栏"),
        ("港区有人受伤怎么办", "港区有人受伤怎么办", "急救"),
        ("港区车辆事故怎么办", "港区车辆事故怎么办", "事故道路"),
    ]

    for question, expected_title, expected_answer in cases:
        result = engine.ask(question)
        titles = [item.title for item in result.evidence]
        assert result.intent == "sop"
        if expected_title is None:
            assert any(item.official for item in result.evidence)
            assert any(item.source == "79_imo_imdg_code.md" for item in result.evidence)
            assert result.requires_human_review is True
        else:
            assert expected_title in titles
        assert expected_answer in result.answer
        assert "港口定义" not in titles[:3]
        assert "1. 港口基础与港口体系" not in titles[:3]
