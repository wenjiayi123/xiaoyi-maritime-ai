import pytest
from app.exercise_records import from_command,verify,summary

Q="净避免的排放量是多少 kg？项目是否达标？"


def calc(facts,q=Q):
    text=f"/演练推理 GHG-1\n事实：{facts}\n问题：{q}"
    record=from_command(text)
    assert record.kind=="batch_emissions"
    receipt=verify(record,text)
    assert receipt["production_authority"] is False
    for span in receipt.get("references",[]):
        assert facts[span["start"]:span["end"]]==span["text"]
    return receipt


def test_net_avoided_amount():
    r=calc("一个独立的仿真项目回收 28 批余热，每批替代 8 kg 排放；配套运输新增 16 kg 排放。项目目标至少净避免 209 kg。")
    assert (r["value"],r["decision"])==(208,"HOLD")
    assert r["proof"]["gross"]==224 and r["proof"]["added"]==16


@pytest.mark.parametrize(("op","decision"),[("严格高于","HOLD"),("不低于","ALLOW"),("至多","ALLOW")])
def test_units_and_equal_target(op,decision):
    facts=f"目标{op}净避免 0.09 吨 CO2e；配套运输新增 10 kg CO2e；利用 2 批废热，每批避免 0.05 吨 CO2e。"
    r=calc(facts,"净减排量为多少吨 CO2e？是否达标？")
    assert (r["value"],r["decision"])==(.09,decision)


@pytest.mark.parametrize("change",["未披露的边界条件","吨位改算","口径不同"])
def test_unregistered_adjustments(change):
    facts="回收 4 批余热，每批替代 2 kg 排放；配套运输新增 2 kg 排放；目标至少净避免 6 kg。"
    if change=="未披露的边界条件":facts+="尚有甲烷泄漏未计。"
    if change=="吨位改算":facts=facts.replace("每批替代","每次替代")
    if change=="口径不同":facts=facts.replace("配套运输新增 2 kg","配套运输新增 2 kg CO2e")
    assert calc(facts)["decision"]=="UNKNOWN"


def test_concise_number_preserves_its_exact_value():
    r=calc("回收 3456 批余热，每批替代 521 kg 排放；配套运输新增 2 kg 排放；目标至少净避免 7 kg。")
    assert str(3456*521-2) in summary(r)


def test_unrepresentable_large_product():
    r=calc("回收 9999999999 批余热，每批替代 9999999999 kg 排放；配套运输新增 2 kg 排放；目标至少净避免 7 kg。")
    assert r["decision"]=="UNKNOWN" and r["reason"]=="carbon_precision"
