import argparse
import copy
import hashlib
import json

import pytest

from scripts import build_lora_dataset as builder
from scripts import train_lora


def test_new_dataset_is_clean_and_existing_version_is_preserved(tmp_path):
    manifest = builder.build_dataset(tmp_path)
    assert manifest["dataset_id"] == "xiaoyi-maritime-sft-v4"
    assert manifest["quarantined_count"] >= 2
    audit = builder.audit_dataset(tmp_path)
    assert audit["ready_for_training"], audit
    before = (tmp_path / "train.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        builder.build_dataset(tmp_path)
    assert (tmp_path / "train.jsonl").read_bytes() == before


def test_changed_dataset_is_rejected_before_training_dependencies(tmp_path, monkeypatch):
    builder.build_dataset(tmp_path)
    with (tmp_path / "train.jsonl").open("a", encoding="utf-8") as file:
        file.write('{}\n')
    monkeypatch.setattr(train_lora, "_require_dependencies", lambda: pytest.fail("model loading reached"))
    with pytest.raises(ValueError, match="训练数据核验未通过"):
        train_lora.train(argparse.Namespace(dataset_dir=tmp_path))


def test_regenerating_manifest_hash_does_not_hide_split_leakage(tmp_path):
    builder.build_dataset(tmp_path)
    example = json.loads((tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    example.update(id="copied-to-validation", split="validation", source="separate-source")
    path = tmp_path / "validation.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(example, ensure_ascii=False) + "\n")
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"]["validation.jsonl"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["split_counts"]["validation"] += 1
    manifest["example_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    audit = builder.audit_dataset(tmp_path)
    assert audit["cross_split_prompt_count"] > 0
    assert not audit["ready_for_training"]


def test_followup_context_distinguishes_identical_short_questions():
    def example(question, split):
        return {"messages": [{"role": "user", "content": question},
                {"role": "assistant", "content": "已核对需求"},
                {"role": "user", "content": "然后呢"},
                {"role": "assistant", "content": "请复核来源"}],
                "answer": "请复核来源", "split": split}
    distinct = [example("岸电容量", "train"), example("泊位吃水", "test")]
    retained, quarantine = builder.separate_repeated_prompts(distinct)
    assert len(retained) == 2 and not quarantine
    repeated = copy.deepcopy(distinct[0])
    repeated["split"] = "validation"
    retained, quarantine = builder.separate_repeated_prompts([distinct[0], repeated])
    assert not retained and len(quarantine) == 2


def test_conflicting_targets_are_retained_in_quarantine():
    prompt = {"role": "user", "content": "哪一项满足要求"}
    first = {"messages": [prompt, {"role":"assistant", "content":"A"}], "answer":"A", "split":"train"}
    second = {"messages": [prompt, {"role":"assistant", "content":"B"}], "answer":"B", "split":"train"}
    retained, quarantine = builder.separate_repeated_prompts([first, second])
    assert not retained
    assert all(row["reason"] == "conflicting_answers_for_identical_prompt" for row in quarantine)


def test_concurrent_build_lock_is_respected(tmp_path):
    (tmp_path / ".dataset-build.lock").write_text("in-progress")
    with pytest.raises(FileExistsError):
        builder.build_dataset(tmp_path)
    assert not (tmp_path / "manifest.json").exists()


def test_loading_rechecks_the_exact_audited_bytes(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"answer":"original"}\n', encoding="utf-8")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert train_lora._load_jsonl(path, expected)[0]["answer"] == "original"
    path.write_text('{"answer":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="发生变更"):
        train_lora._load_jsonl(path, expected)


@pytest.mark.parametrize("value", [None, 4, [], {}, {"messages": []}])
def test_malformed_records_are_rejected(value):
    assert builder.valid_example(value, "train") is False
