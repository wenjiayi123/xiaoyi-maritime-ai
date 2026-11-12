import pytest
from app import monthly_energy_rule as rule
from app.exercise_records import from_command,verify,summary

Q="按海危防〔2022〕164号第六条，这艘船能否选择按月报告能耗？"
BASE="历史核验日=2025-02-08；国籍=中国；总吨=400；航行类别=国内海船；船舶用途=普通商船；固定水域=否；固定航线=是；单航次最长航时=24小时"


def calc(facts,q=Q):
    cmd=f"/演练核验 ENERGY-1\n事实：{facts}\n问题：{q}"
    record=from_command(cmd)
    assert record.kind=="energy_monthly"
    r=verify(record,cmd)
    assert r["production_authority"] is False
    return r


@pytest.mark.parametrize(("facts","expected"),[(BASE,"ELIGIBLE"),(BASE.replace("24小时","24小时1分钟"),"INELIGIBLE"),
    (BASE.replace("400","399"),"OUTSIDE"),(BASE.replace("固定航线=是","固定航线=待补"),"UNKNOWN"),
    (BASE.replace("普通商船","渔业船舶").replace("总吨=400","总吨=待补"),"OUTSIDE"),
    (BASE.replace("固定水域=否","固定水域=未知"),"ELIGIBLE")])
def test_legal_monthly_facts(facts,expected):
    r=calc(facts)
    assert r["decision"]==expected and r["sources"]==rule.sources()
    assert r["sources"][0]["url"] in summary(r)
    for s in r["references"]:
        assert facts[s["start"]:s["end"]]==s["text"]


def test_conflicting_or_different_tonnage():
    for facts in (BASE+"；国籍=外国",BASE.replace("总吨","载重吨"),BASE.replace("2025-02-08","2026-11-07")):
        assert calc(facts)["decision"]=="UNKNOWN"


def test_named_scope_and_source_tampering(tmp_path,monkeypatch):
    assert not rule.applicable(BASE,"能否办理年度能耗报告？")
    assert calc(BASE,Q.rstrip("？")+"并且是否满足其他义务？")["decision"]=="UNKNOWN"
    for p in rule.ROOT.iterdir():
        if p.is_file():(tmp_path/p.name).write_bytes(p.read_bytes())
    (tmp_path/"msa.html").write_bytes(b"bad source revision")
    monkeypatch.setattr(rule,"ROOT",tmp_path)
    receipt=calc(BASE)
    assert receipt["decision"]=="UNKNOWN" and "sources" not in receipt
