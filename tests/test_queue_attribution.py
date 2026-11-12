import pytest
from app.queue_evidence import boundary_issues
@pytest.mark.parametrize("text,bad",[
 ("该预测由美国交通统计局（BTS）提供，目标是全美等泊船数。",True),
 ("BTS 发布的本次预测是 7 艘。",True),
 ("这不是由美国交通统计局提供的预测；舷鸥使用 BTS 的历史观测。",False),
 ("本次预测由舷鸥生成。美国交通统计局提供历史船数。",False),
 ("模型预测为 7 艘，BTS 没有发布该概率。",False)])
def test_forecast_attribution(text,bad):
    assert bool(boundary_issues(text,"forward"))==bad
