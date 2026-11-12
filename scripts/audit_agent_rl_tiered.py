"""Replay tiered records without opening final test tasks to a model."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import audit_agent_rl_v3 as audit  # noqa:E402
from app.agent_training.environment_tiered import TieredTask, TieredEnvironment  # noqa:E402

if __name__ == "__main__":
    audit.DynamicTask = TieredTask
    audit.DynamicEnvironment = TieredEnvironment
    audit.main()
