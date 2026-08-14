import json
from pathlib import Path

from scripts.build_lora_dataset import build_dataset
from scripts.train_lora import _encode_example, _training_contract


def test_lora_dataset_is_source_grouped_and_auditable(tmp_path: Path) -> None:
    manifest = build_dataset(tmp_path)

    assert manifest["example_count"] > 0
    assert manifest["split_counts"]["train"] > 0
    assert manifest["split_counts"]["validation"] > 0
    assert manifest["split_counts"]["test"] > 0
    source_splits: dict[str, set[str]] = {}
    for split in ("train", "validation", "test"):
        path = tmp_path / f"{split}.jsonl"
        assert manifest["artifact_sha256"]
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            source_splits.setdefault(item["source"], set()).add(split)
            assert item["messages"][-1]["role"] == "assistant"
            assert item["answer"]
    assert all(len(splits) == 1 for splits in source_splits.values())
    assert manifest["curated_multiturn_example_count"] >= 10


def test_curated_multiturn_data_teaches_identity_and_followups(tmp_path: Path) -> None:
    build_dataset(tmp_path)
    train_items = [
        json.loads(line)
        for line in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    curated = [
        item for item in train_items
        if item["section"] == "curated_multiturn"
    ]

    assert curated
    assert any("谁研发的" in item["question"] for item in curated)
    assert any(
        "温家懿" in item["answer"]
        for item in curated
    )
    assert any(
        len([message for message in item["messages"] if message["role"] == "user"]) > 1
        for item in curated
    )


def test_lora_contract_does_not_mislabel_4b_as_trained() -> None:
    contract = _training_contract()

    assert contract["model_id"].endswith("maritime-training-1.7b")
    assert contract["artifact_profile"] == "xiaoyi-local-training-1.7b"
    assert contract["inference_model_id"] == "xiaoyi-local-1.7b-q8-0"


def test_encoding_masks_prompt_tokens() -> None:
    class FakeTokenizer:
        def apply_chat_template(
            self,
            messages: list[dict[str, str]],
            *,
            tokenize: bool,
            add_generation_prompt: bool,
        ) -> list[int]:
            assert tokenize is True
            if add_generation_prompt:
                return [1, 2, 3]
            return [1, 2, 3, 4, 5]

    item = {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
    }
    encoded = _encode_example(FakeTokenizer(), item, 10)

    assert encoded["input_ids"] == [1, 2, 3, 4, 5]
    assert encoded["labels"] == [-100, -100, -100, 4, 5]


def test_encoding_keeps_assistant_tokens_when_truncated() -> None:
    class FakeTokenizer:
        def apply_chat_template(
            self,
            messages: list[dict[str, str]],
            *,
            tokenize: bool,
            add_generation_prompt: bool,
        ) -> list[int]:
            assert tokenize is True
            prompt = list(range(1, 101))
            return prompt if add_generation_prompt else prompt + [101, 102, 103, 104]

    item = {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
    }
    encoded = _encode_example(FakeTokenizer(), item, 32)

    assert len(encoded["input_ids"]) == 32
    assert encoded["input_ids"][-4:] == [101, 102, 103, 104]
    assert encoded["labels"][-4:] == [101, 102, 103, 104]
    assert any(label != -100 for label in encoded["labels"])
