import pytest
from app.port_cost_evidence import boundary_issues
@pytest.mark.parametrize("answer,reject",[
    ("此差额为初步预算差额，不等于项目节费，而是年度最终支出的一部分。",True),
    ("预算差额可以算作RL节费。",True),
    ("初步预算差额属于年度最终支出的一部分。",True),
    ("少支差额不是年度最终支出的一部分，也不能算作 RL 节费。",False),
    ("不能把差额计入年度最终支出。",False),
    ("同份执行表的预算差额为 39,200 千美元，不等于 RL 节省。",False),
])
def test_financial_variance_keeps_its_scope(answer,reject):
    assert bool(boundary_issues(answer,"budget2025")) is reject
