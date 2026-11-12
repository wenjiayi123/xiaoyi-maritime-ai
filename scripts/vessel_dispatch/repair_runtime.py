"""Frozen vessel schedule repair shared by on-demand simulation and the published evidence."""
from pathlib import Path
import torch
from dispatch import hashfile
from repair import Repair,RepairValue

WEIGHT_SHA="8086fa22d73edc2397f6643425001fc19c464fb87792ba8d0a4acce419a0a53f"


def proposals(case,initial):
    weight=Path(__file__).with_name("repair.pt")
    if hashfile(weight)!=WEIGHT_SHA:raise ValueError("船期修复权重与登记值不符")
    actor=RepairValue();actor.load_state_dict(torch.load(weight,weights_only=True));actor.eval()
    env=Repair(case,initial)
    return {name:env.rollout(actor,mode) for name,mode in (("repair","trained"),("repair_greedy","greedy"))}


TEST_RECIPE_SEED=971
REPAIR_DATES=('2025-09-05', '2025-09-18', '2025-09-26', '2025-09-27', '2025-10-13', '2025-10-21', '2025-10-25', '2025-10-26', '2025-10-29', '2025-11-04', '2025-11-05', '2025-11-18', '2025-11-21', '2025-11-24', '2025-11-29', '2025-11-30', '2025-12-18', '2025-12-23')
