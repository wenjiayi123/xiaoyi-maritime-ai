import json
from types import SimpleNamespace
import pytest
from app.exercise_records import from_command
from app.quantity_dialogue import review

REC=SimpleNamespace(source="shift-02",facts="历史工时共 5 小时，本例上限 6 小时。")
QUESTION="作业时长是多少小时？是否满足上限？"


def result(body,field,value,finish="stop",source="shift-02"):
    message={"role":"assistant","content":json.dumps({field:value,"source":source})}
    return {"finish_reason":finish,"message":message},7


def test_two_stage_uses_actual_generated_number():
    seen=[]
    def upstream(body):
        seen.append(body["messages"][-1]["content"])
        if len(seen)==1:return result(body,"value",5)
        assert "第一次数值回答为 5" in seen[-1]
        return result(body,"decision","ALLOW")
    r=review(REC,QUESTION,"private",upstream)
    assert (r["value"],r["decision"],r["completion_tokens"])==(5,"ALLOW",14)
    assert [c["max_tokens"] for c in r["calls"]]==[1024,1024]


def test_length_retries_pair_once_and_rebinds_latest_number():
    seen=[]
    def upstream(body):
        seen.append(body)
        if len(seen)==1:return result(body,"value",0,"length")
        if len(seen)==2:
            assert "第一次没有得到可核验的数值" in body["messages"][1]["content"]
            return result(body,"decision","UNKNOWN")
        if len(seen)==3:return result(body,"value",5)
        assert "第一次数值回答为 5" in body["messages"][1]["content"]
        return result(body,"decision","ALLOW")
    r=review(REC,QUESTION,"private",upstream)
    assert [c["max_tokens"] for c in r["calls"]]==[1024,1024,2048,2048]
    assert (r["decision"],r["value"])==("ALLOW",5)


@pytest.mark.parametrize("bad",[None,True,{"x":1},10**80])
def test_closed_non_numeric_output_is_withheld_without_retry(bad):
    seq=iter([("value",bad),("decision","ALLOW")])
    r=review(REC,QUESTION,"private",lambda body:result(body,*next(seq)))
    assert len(r["calls"])==2 and r["decision"]=="UNKNOWN" and r["value"] is None


def test_wrong_source_does_not_bind():
    seq=iter([("value",5),("decision","ALLOW")])
    r=review(REC,QUESTION,"private",lambda body:result(body,*next(seq),source="somewhere-else"))
    assert r["decision"]=="UNKNOWN" and r["reason"]=="incomplete_or_invalid"


def test_ambiguous_question_has_no_generation():
    def forbidden(body):raise AssertionError("Unexpected generation")
    r=review(REC,"请分析历史工况。","private",forbidden)
    assert r["calls"]==[] and "model" not in r


def test_exercise_parser_preserves_specialist_priority():
    cmd="/演练推理 test-02\n事实：作业负荷 1400 kW，储能可持续放电 300 kW，并网功率上限 1200 kW。\n问题：并网功率多少 kW？是否满足上限？"
    old=from_command(cmd);new=from_command(cmd.replace("/演练推理","/分步复算"))
    assert old==new and old.kind=="power"
