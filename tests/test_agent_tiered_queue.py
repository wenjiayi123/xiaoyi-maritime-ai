import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import run_agent_rl_tiered_queue as queue


@pytest.mark.skipif(sys.platform!="win32",reason="uses the Windows command-line provider")
def test_windows_process_identity_preserves_unicode_in_the_actual_child_arguments():
    marker="G:/工作站临时验证/有空格的样本.py"
    child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(25)",marker])
    try:
        assert marker in queue.command(child.pid)
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ps locale regression")
def test_process_identity_preserves_chinese_paths_under_c_utf8():
    marker = "/tmp/舷鸥 · GullMate/scripts/serve_agent_rl_v1.py"
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker])
    try:
        with patch.dict(queue.os.environ, {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}):
            assert marker in queue.command(child.pid)
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_unverified_model_is_never_terminated():
    with (
        patch.object(queue, "health", return_value={"service": "different-service"}),
        patch.object(queue.os, "kill") as kill,
    ):
        with pytest.raises(RuntimeError, match="identity differs"):
            queue.stop_old_worker()
        kill.assert_not_called()


def test_only_owned_expected_worker_is_stopped(tmp_path):
    registry = tmp_path / ".runtime/agent-rl-v1/launch/processes.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"experiment": str(queue.OLD), "owned_pids": [101, 102]}))
    expected = str(tmp_path / "scripts/serve_agent_rl_v1.py") + " --experiment " + str(queue.OLD)
    with (
        patch.object(queue, "ROOT", tmp_path),
        patch.object(queue, "BASE", tmp_path / "artifacts"),
        patch.object(
            queue, "health", side_effect=[{"service": "xiaoyi-language-agent-rl", "experiment": "experiment-004"}, None]
        ),
        patch.object(queue, "command", side_effect=[expected, "unrelated-process", ""]),
        patch.object(queue.os, "kill") as kill,
    ):
        queue.stop_old_worker()
        kill.assert_called_once_with(101, queue.signal.SIGTERM)


def test_closed_health_port_does_not_mean_model_process_has_exited(tmp_path):
    registry = tmp_path / ".runtime/agent-rl-v1/launch/processes.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"experiment": str(queue.OLD), "owned_pids": [101]}))
    expected = str(tmp_path / "scripts/serve_agent_rl_v1.py") + " --experiment " + str(queue.OLD)
    with (
        patch.object(queue, "ROOT", tmp_path),
        patch.object(queue, "BASE", tmp_path / "artifacts"),
        patch.object(
            queue, "health", side_effect=[{"service": "xiaoyi-language-agent-rl", "experiment": "experiment-004"}, None, None]
        ),
        patch.object(queue, "command", side_effect=[expected, expected, ""]),
        patch.object(queue.os, "kill"),
        patch.object(queue.time, "sleep") as sleep,
    ):
        queue.stop_old_worker()
        sleep.assert_called_once_with(1)


def test_active_trainer_blocks_second_model():
    with patch.object(
        queue.subprocess,
        "check_output",
        return_value="12 python /project/scripts/run_agent_rl_v4.py develop --output /experiment",
    ):
        with pytest.raises(RuntimeError, match="another trainer"):
            queue.ensure_no_other_trainer()
