import hashlib
import json

from app.harness import calculation_evidence as evidence
from app.harness.verification import numbers


def test_unit_bound_rounding_never_accepts_other_claims():
    receipt={"unit":"%","value":35.53719008264}
    goal="合并百分比保留两位小数。"
    assert numbers(evidence.remove_rounded_value("占比为35.54%。",goal,receipt))==set()
    assert "35.55" in numbers(evidence.remove_rounded_value("占比为35.55%。",goal,receipt))
    assert "35.54" in numbers(evidence.remove_rounded_value("35.54 kW。",goal,receipt))
    assert "35.54" in numbers(evidence.remove_rounded_value("35.54%。","计算占比",receipt))
    assert "35.54" in numbers(evidence.remove_rounded_value("35.54%/h",goal,receipt))
    assert numbers("26.07 kWh；\n2. 核对") == {"26.07"}


def test_only_named_file_and_recorded_dates_supply_metadata(monkeypatch,tmp_path):
    monkeypatch.setattr(evidence,"FOLDER",tmp_path)
    raw=b"date,count\n2025-09-15,32\n"
    checksum=hashlib.sha256(raw).hexdigest()
    (tmp_path/"test.csv").write_bytes(raw)
    manifest={"schema":"shanghai-public-lab-dataset.v1","sources":[{"id":"test_2024_port","path":"test.csv","sha256":checksum}],
              "files":{"test.csv":{"sha256":checksum}}}
    (tmp_path/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    goal=f"资料编号 test_2024_port，摘要 {checksum[:12]}。2025-09-15 和 2025-09-16 的数量"
    answer="来源 test_2024_port，当日 2025-09-15。"
    assert numbers(evidence.remove_registered_metadata(answer,goal))==set()
    assert "16" in numbers(evidence.remove_registered_metadata("另称 2025-09-16",goal))
    assert numbers(evidence.remove_registered_metadata(answer,goal.replace(checksum[:12],"0"*12)))
    (tmp_path/"test.csv").write_bytes(b"date,count\n2025-09-15,99\n")
    assert numbers(evidence.remove_registered_metadata(answer,goal))


def test_historical_dispatch_requires_an_explicit_boundary():
    goal="历史挂靠数据，说明能否直接用于投放现场岸桥。"
    assert evidence.historical_dispatch_issue(goal,"该差额可用于投放现场岸桥，但需注意此为历史数据。")
    assert evidence.historical_dispatch_issue(goal,"结果是 1.5 艘次。")
    assert evidence.historical_dispatch_issue(goal,"可以直接投放现场岸桥，但不可直接据此安排。")
    assert not evidence.historical_dispatch_issue(goal,"不能直接投放现场岸桥，需要当前作业计划和有权调度人员确认。")
    assert not evidence.historical_dispatch_issue(goal,"该数值仅供参考，是否调度需核对船期、泊位和人员。")
    assert not evidence.historical_dispatch_issue("只问历史平均值。","增加 1.5 艘次。")
