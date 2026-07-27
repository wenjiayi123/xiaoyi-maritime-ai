from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.model_gateway import ModelGateway
from app.settings import Settings
from app.vector_retrieval import DenseVectorIndex, EmbeddingClient
from scripts import build_vector_index as vector_builder
from scripts.build_lora_dataset import (
    build_dataset,
    held_out_questions,
)


ROOT = Path(__file__).resolve().parents[1]


def test_model_registry_pins_open_model_artifact_and_adapter_base() -> None:
    registry = json.loads(
        (ROOT / "data" / "model_registry.json").read_text(encoding="utf-8")
    )
    model = registry["models"][0]

    assert registry["default_model_id"] == model["model_id"]
    assert model["repository"] == "configured-outside-repository"
    assert model["revision"] == "private-pinned-artifact"
    assert model["quantization"] == "Q4_K_M"
    assert model["expected_bytes"] == 2_497_280_256
    assert model["sha256_env"] == "XIAOYI_LOCAL_MODEL_SHA256"
    assert model["path_env"] == "XIAOYI_LOCAL_MODEL_PATH"
    assert model["download_url_env"] == "XIAOYI_LOCAL_MODEL_DOWNLOAD_URL"
    assert model["license"] == "Apache-2.0"
    training_model = next(
        item
        for item in registry["models"]
        if item["model_id"] == registry["local_training_model_id"]
    )
    assert (
        registry["adapter_contract"]["training_base"]
        == training_model["upstream_model"]
        == "xiaoyi-local-training-1.7b"
    )
    adapter = registry["adapter_contract"]
    assert adapter["rank"] == 96
    assert adapter["alpha"] == 192
    assert adapter["trainable_parameters"] == 104_595_456
    assert adapter["all_parameters_with_adapter"] == 1_825_170_432
    assert len(adapter["adapter_sha256"]) == 64
    assert len(adapter["inference_adapter_sha256"]) == 64
    embedding_model = next(
        item
        for item in registry["models"]
        if item["role"] == "local_dense_embedding"
    )
    assert embedding_model["embedding_dimensions"] == 1024
    assert embedding_model["expected_bytes"] == 639_150_592


def test_lora_examples_are_human_curated_and_exclude_fixed_questions(
    tmp_path: Path,
) -> None:
    held_out = held_out_questions()
    manifest = build_dataset(tmp_path)
    examples = [
        json.loads(line)
        for split in ("train", "validation", "test")
        for line in (tmp_path / f"{split}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert len(examples) >= 100
    assert manifest["held_out_question_count"] == len(held_out)
    normalized_questions = {
        "".join(
            character
            for character in item["messages"][1]["content"].lower()
            if character.isalnum()
        )
        for item in examples
    }
    assert "如何削峰" not in normalized_questions


def test_lora_split_has_no_source_leakage() -> None:
    registry = json.loads(
        (ROOT / "data" / "model_registry.json").read_text(encoding="utf-8")
    )
    assert registry["local_training_model_id"] != registry["default_model_id"]
    assert registry["adapter_contract"]["training_base"] == "xiaoyi-local-training-1.7b"


def test_loopback_model_is_local_generation_without_data_egress() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_external_data_allowed=False,
    )
    gateway = ModelGateway(configuration)
    status = gateway.status()

    assert status["architecture"] == "open_weight_llm_rag_lora"
    assert status["request_scope"] == "local_device"
    assert status["local_generation_enabled"] is True
    assert status["external_request_enabled"] is False


def test_dense_vector_index_scores_only_matching_chunk_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "vectors.json"
    path.write_text(
        json.dumps(
            {
                "manifest": {"dimensions": 2},
                "records": [
                    {
                        "chunk_id": "a",
                        "content_hash": "hash-a",
                        "vector": [1.0, 0.0],
                    },
                    {
                        "chunk_id": "b",
                        "content_hash": "old-hash",
                        "vector": [0.0, 1.0],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda self, texts, query=False: [[1.0, 0.0]],
    )
    index = DenseVectorIndex(
        path,
        base_url="http://127.0.0.1:11436/v1",
        model="embedding-test",
    )
    scores = index.scores(
        "泊位冲突",
        [
            SimpleNamespace(id="a", content_hash="hash-a"),
            SimpleNamespace(id="b", content_hash="hash-b"),
        ],
    )

    assert scores == {"a": 1.0}


def test_vector_index_resumes_only_missing_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chunks = [
        SimpleNamespace(id="a", content_hash="hash-a", title="A", text="alpha"),
        SimpleNamespace(id="b", content_hash="hash-b", title="B", text="beta"),
    ]
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "index_id": "xiaoyi-dense-vector-v1",
                        "model": "embedding-test",
                    }
                ),
                json.dumps(
                    {
                        "chunk_id": "a",
                        "content_hash": "hash-a",
                        "vector": [1.0, 0.0],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(vector_builder, "load_chunks", lambda: chunks)
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda self, texts, query=False: (
            calls.append(list(texts)) or [[0.0, 1.0]]
        ),
    )
    output = tmp_path / "vectors.json"

    manifest = vector_builder.build_vector_index(
        base_url="http://127.0.0.1:11436/v1",
        model="embedding-test",
        output_path=output,
        checkpoint_path=checkpoint,
        batch_size=8,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["chunk_count"] == 2
    assert calls == [["B\nbeta"]]
    assert [item["chunk_id"] for item in payload["records"]] == ["a", "b"]
    assert checkpoint.exists() is False
