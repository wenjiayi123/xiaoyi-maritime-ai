"""Clarify the port task noun phrase; retain model choice and original grading."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_capability_demo as core  # noqa: E402

ORIGINAL_PROMPT = core.prompt_for
DIAGNOSTIC = core.BASE / "port-prompt-diagnostic"
MODE = "port_task_nouns"
OLD_SENTENCE = "读取港口状态并评估靠泊情景，核验后交付报告。"
NEW_SENTENCE = "读取港口，完成港口情景评估，核验后交付报告。"


def prompt_for(env, mode):
    if mode == MODE:
        return ORIGINAL_PROMPT(env, "baseline").replace(OLD_SENTENCE, NEW_SENTENCE)
    return ORIGINAL_PROMPT(env, mode)


def prepare(out):
    diagnostic = core.read(DIAGNOSTIC / "RESULTS.json")
    registered = core.read(DIAGNOSTIC / "PROTOCOL.json")
    choices = {
        name: [r for r in diagnostic["rows"] if r["variant"] == name]
        for name, sentence in registered["variants"]
    }
    qualifying = [name for name in choices if len(choices[name]) == 2
                  and {r["group"] for r in choices[name]} == set(core.GROUPS)
                  and all(r["chosen_tool"] == "port.evaluate" for r in choices[name])]
    if not qualifying or qualifying[0] != MODE:
        raise ValueError("Diagnostic does not support the registered first-qualifying choice")
    draft = out.with_name(out.name + ".preparing")
    core.SOURCE_FILES = [*core.SOURCE_FILES, "scripts/run_agent_capability_demo_v2.py",
                         str((DIAGNOSTIC / "PROTOCOL.json").relative_to(ROOT)),
                         str((DIAGNOSTIC / "RESULTS.json").relative_to(ROOT))]
    p = core.prepare(draft, "baseline")
    p.update(prompt_mode=MODE, prompt_change_is_harness_change_not_training=True,
             wording_change={"before": OLD_SENTENCE, "after": NEW_SENTENCE,
                             "selection": "First qualifying wording in six-call, three-variant engineering diagnostic; all candidates retained.",
                             "semantics": "Same port observation, same scenario evaluation and parameters, same verification and report. No extra task, action mask, ordering or rule-selected action.",
                             "scope": "Input wording adaptation, not a learned weight improvement or independent generalization test."})
    core.live.save(draft / "PROTOCOL.json", p)
    core.live.save(draft / "LOCK.json", {n: core.sha(draft / n) for n in ["PROTOCOL.json", "SOURCES.json"]})
    draft.rename(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    core.prompt_for = prompt_for
    if args.command == "prepare":
        prepare(args.output.resolve())
    else:
        core.run(args.output.resolve())


if __name__ == "__main__":
    main()
