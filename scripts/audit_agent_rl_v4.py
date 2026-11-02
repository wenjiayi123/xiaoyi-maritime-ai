"""Replay curriculum initialization separately from model-selected actions."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import audit_agent_rl_v3 as audit  # noqa: E402
from scripts.run_agent_rl_v4 import CurriculumEnvironment, CurriculumTask  # noqa: E402

if __name__ == "__main__":
    audit.DynamicEnvironment = CurriculumEnvironment
    audit.DynamicTask = CurriculumTask
    audit.main()
