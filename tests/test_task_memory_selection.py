import json
from app.harness.contracts import encoded
from app.harness.task_memory import add_task_memories


def test_relevant_older_note_beats_unrelated_recent_notes():
    recent = [{"label": "泊位", "text": "泊位复核" + str(i)} for i in range(8)]
    target = {"label": "冷链", "text": "青舟冷箱验收要读双探头", "id": "ice"}
    task = {"goal": "原拟复核泊位", "inputs": [{"text":"改查青舟冷箱验收双探头"}], "use_memory": True}
    packet = json.loads(add_task_memories(task, recent + [target], {}, 4000))
    assert packet["memory"][0]["id"] == "ice" and len(packet["memory"]) == 6
    assert "memory" not in json.loads(add_task_memories({**task,"use_memory":False}, [target], {}, 4000))


def test_mandatory_tool_observation_survives_oversized_memory():
    base = {"tool_results": [{"id":"T1", "summary":"已复核原始观测"}]}
    task = {"goal":"泊位费率", "use_memory": True}
    notes = [{"label":"泊位费率", "text":"很长" * 500}, {"label":"交班", "text":"查原单"}]
    room = len(encoded({**base, "memory":[notes[1]]}))
    selected = json.loads(add_task_memories(task,notes,base,room))
    assert selected["tool_results"] == base["tool_results"] and selected["memory"] == [notes[1]]
    assert json.loads(add_task_memories(task,notes,base,len(encoded(base)))) == base


def test_cost_inputs_use_the_authorized_project_edition():
    from types import SimpleNamespace
    from app.harness.task_memory import memory_cost_issue
    task = {"goal":"按我保存的白鹭岸电计算模拟电费", "inputs":[], "allowed_tools":["calculate"]}
    own = {"id":"one", "label":"白鹭岸电", "text":"演练用量 37 kWh，单价 4 元/kWh"}
    foreign = {"id":"two", "label":"另一个项目", "text":"演练用量 2000 kWh，单价 50 元/kWh"}
    messages = [{"content":encoded({"memory":[own,foreign]})}]
    def issue(expression, current):
        action = SimpleNamespace(kind="tool",tool="calculate",arguments={"expression":expression})
        return memory_cost_issue(task,action,messages,current)
    assert issue("37*4",[own,foreign]) is None
    assert issue("2000*50",[own,foreign]) == "unverified_operands"
    assert issue("37*5",[own,foreign]) == "unverified_operands"
    assert issue("37*4",[{**own,"text":"旧数据已撤回"}]) == "missing_inputs"
    task["inputs"] = [{"text":"本轮临时单价为5元"}]
    assert issue("37*5",[own,foreign]) is None
