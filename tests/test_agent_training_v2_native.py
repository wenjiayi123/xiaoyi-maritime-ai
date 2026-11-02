from dataclasses import asdict
import pytest

from app.agent_training.environment import TaskEnvironment, make_task
from app.agent_training.environment_v2 import REVISION, ProgressEnvironment
from app.agent_training.live import environment_for_job


def test_native_uses_registered_experiment_environment_without_changing_legacy():
    job = {"task": asdict(make_task("acceptance", "joint", 0))}
    old = environment_for_job(job)
    new = environment_for_job({**job, "environment": REVISION})
    assert type(old) is TaskEnvironment
    assert type(new) is ProgressEnvironment
    assert "任务缺项" in new.prompt() and "任务缺项" not in old.prompt()
    with pytest.raises(ValueError, match="unregistered"):
        environment_for_job({**job, "environment": "unknown"})
