import pytest
from app.xiaoyi import XiaoyiAI


@pytest.mark.parametrize(("q","expected"),[
    ("这里只有演练轨迹。设备此刻的现场读数是多少？",True),
    ("What is the physical crane load at this moment?",True),
    ("历史仿真回放此刻的岸桥读数是多少？",False),
    ("How can I check the physical crane sensor at this moment?",False),
])
def test_live_observation_clock_is_separate_from_replay_and_methods(q,expected):
    assert XiaoyiAI()._is_realtime_question(q) is expected
