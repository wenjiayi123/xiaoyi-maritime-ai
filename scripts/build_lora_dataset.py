from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "data" / "kb"
REGISTRY_PATH = ROOT / "data" / "source_registry.json"
EVALUATION_DIR = ROOT / "data" / "evaluation"
DEFAULT_OUTPUT = ROOT / ".runtime" / "finetuning" / "xiaoyi-maritime-sft-v4"
CURATED_MULTITURN_PATH = ROOT / "data" / "finetuning" / "curated_multiturn_gullmate_v3.json"
CURATED_SUPERVISION_PATHS = (
    CURATED_MULTITURN_PATH,
    ROOT / "data" / "finetuning" / "curated_workforce_daily_v3.json",
    ROOT / "data" / "finetuning" / "curated_maritime_gaps_v3.json",
)
SYSTEM_PROMPT = (
    "你是港航专业助手「舷鸥 · GullMate」，日常称呼是「小鸥」。问候时自称小鸥。用自然、直接、专业的中文回答，优先给出判断和下一步。"
    "生活、健康、情绪、天气、通勤等日常问题先正常回答，再说明对港航当班与现场"
    "作业的影响，并针对船员、引航、调度中控、装卸堆场、闸口、维修等岗位给出"
    "安全建议；纯问候、身份、致谢或告别无需生硬扩展。"
    "遇到缺少业务对象的问题先简短澄清；没有经验证的实时数据时明确说明缺口，"
    "不得编造船期、生产状态、法规条款、数值或已执行动作。"
    "回答涉及高风险操作、法规和生产写入时保留人工复核与权限边界。"
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalize_question(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:（）()\"'`]", "", text).lower()


def _walk_questions(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "question" and isinstance(item, str):
                yield item
            yield from _walk_questions(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_questions(item)


def held_out_questions(evaluation_dir: Path = EVALUATION_DIR) -> set[str]:
    questions: set[str] = set()
    for path in sorted(evaluation_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions.update(
            normalized
            for question in _walk_questions(payload)
            if (normalized := _normalize_question(question))
        )
    return questions


def _split_questions(text: str) -> list[str]:
    cleaned = text.strip().rstrip("。")
    parts = re.split(r"[；;]\s*", cleaned)
    return [part.strip() for part in parts if len(part.strip()) >= 2]


def _registry_documents() -> dict[str, dict[str, Any]]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    defaults = dict(payload.get("defaults") or {})
    documents: dict[str, dict[str, Any]] = {}
    for name, overrides in (payload.get("documents") or {}).items():
        documents[name] = {**defaults, **(overrides or {})}
    return documents


def _sections(path: Path) -> list[tuple[str, list[str]]]:
    title = path.stem
    lines: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("## "):
            if lines:
                sections.append((title, lines))
            title = raw_line[3:].strip()
            lines = []
        elif raw_line.startswith("# "):
            continue
        else:
            lines.append(raw_line.rstrip())
    if lines:
        sections.append((title, lines))
    return sections


def _extract_examples(
    path: Path,
    *,
    excluded_questions: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = excluded_questions or set()
    examples: list[dict[str, Any]] = []
    for section, lines in _sections(path):
        questions: list[str] = []
        answer_lines: list[str] = []
        collecting_answer = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("常见问法："):
                questions.extend(_split_questions(stripped.split("：", 1)[1]))
                collecting_answer = False
            elif stripped.startswith("等价问法："):
                questions.extend(_split_questions(stripped.split("：", 1)[1]))
                collecting_answer = False
            elif stripped.startswith("直接回答："):
                answer_lines.append(stripped.split("：", 1)[1].strip())
                collecting_answer = True
            elif collecting_answer and stripped:
                answer_lines.append(stripped)
        answer = "\n".join(answer_lines).strip()
        if not questions or len(answer) < 12:
            continue
        for question in dict.fromkeys(questions):
            if _normalize_question(question) in excluded:
                continue
            example_id = _sha256_bytes(
                f"{path.name}\n{section}\n{question}\n{answer}".encode("utf-8")
            )[:20]
            examples.append(
                {
                    "id": example_id,
                    "source": path.name,
                    "section": section,
                    "question": question,
                    "answer": answer,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ],
                }
            )
    return examples


def _source_splits(sources: list[str], seed: int) -> dict[str, str]:
    ranked = sorted(
        sources,
        key=lambda source: hashlib.sha256(
            f"{seed}:{source}".encode("utf-8")
        ).hexdigest(),
    )
    if len(ranked) < 3:
        raise ValueError("至少需要3个含明确问答的内部来源才能建立隔离分区")
    validation_count = max(1, round(len(ranked) * 0.1))
    test_count = max(1, round(len(ranked) * 0.1))
    train_end = len(ranked) - validation_count - test_count
    validation_end = train_end + validation_count
    return {
        source: (
            "train"
            if index < train_end
            else "validation"
            if index < validation_end
            else "test"
        )
        for index, source in enumerate(ranked)
    }


def _curated_multiturn_examples(
    *,
    excluded_questions: set[str],
) -> list[dict[str, Any]]:
    curated: list[dict[str, Any]] = []
    for path in CURATED_SUPERVISION_PATHS:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for raw in payload.get("examples") or []:
            messages = list(raw.get("messages") or [])
            if not messages or messages[-1].get("role") != "assistant":
                raise ValueError("人工监督样本必须以assistant回答结束")
            user_messages = [
                str(message.get("content") or "").strip()
                for message in messages
                if message.get("role") == "user"
            ]
            if not user_messages or any(
                _normalize_question(question) in excluded_questions
                for question in user_messages
            ):
                continue
            answer = str(messages[-1].get("content") or "").strip()
            if len(answer) < 12:
                raise ValueError("人工监督样本回答过短")
            curated.append(
                {
                    "id": str(raw["id"]),
                    "source": str(raw["source"]),
                    "section": "curated_multiturn",
                    "question": user_messages[-1],
                    "answer": answer,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *messages,
                    ],
                    "split": str(raw.get("split") or "train"),
                    "source_file": path.name,
                    "source_sha256": _sha256_file(path),
                }
            )
    return curated


def prompt_key(item: dict[str, Any]) -> str:
    """Include preceding turns so context-dependent followups remain distinct."""
    return json.dumps([
        [message["role"], _normalize_question(message["content"])]
        for message in item["messages"][:-1]
    ], ensure_ascii=False)


def separate_repeated_prompts(examples: list[dict]) -> tuple[list[dict], list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in examples:
        groups[prompt_key(item)].append(item)
    retained, quarantine = [], []
    for group in groups.values():
        reason = ""
        if len({item["split"] for item in group}) > 1:
            reason = "identical_prompt_across_splits"
        elif len({_normalize_question(item["answer"]) for item in group}) > 1:
            reason = "conflicting_answers_for_identical_prompt"
        if reason:
            quarantine.extend({"reason": reason, "example": item} for item in group)
        else:
            retained.append(group[0])
            quarantine.extend({"reason": "duplicate_prompt_and_answer", "example": item} for item in group[1:])
    return retained, quarantine


def valid_example(item: dict, split: str) -> bool:
    try:
        messages = item["messages"]
        if not isinstance(messages, list) or len(messages) < 2:
            return False
        if not all(m["role"] in {"system", "user", "assistant"}
                   and isinstance(m["content"], str) and m["content"].strip() for m in messages):
            return False
        users = [m["content"] for m in messages if m["role"] == "user"]
        return bool(
            messages[-1]["role"] == "assistant" and item["answer"] == messages[-1]["content"]
            and users and item["question"] == users[-1] and item["split"] == split
            and isinstance(item["id"], str) and item["id"]
            and isinstance(item["source"], str) and item["source"]
            and re.fullmatch(r"[0-9a-f]{64}", item["source_sha256"])
        )
    except (KeyError, TypeError):
        return False


def audit_dataset(directory: Path) -> dict[str, Any]:
    """Validate frozen files and split isolation before loading a training model."""
    errors: list[str] = []
    drift: set[str] = set()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {Path(name).name: value for name, value in manifest.get("artifact_sha256", {}).items()}
    counts, hashes, ids = {}, {}, set()
    sources: dict[str, set[str]] = defaultdict(set)
    prompts: dict[str, set[str]] = defaultdict(set)
    evaluation_questions = held_out_questions()
    source_hashes: dict[Path, str | None] = {}
    for split in ("train", "validation", "test"):
        path = directory / f"{split}.jsonl"
        if not path.is_file():
            errors.append(f"missing_partition:{split}")
            continue
        payload = path.read_bytes()
        hashes[split] = _sha256_bytes(payload)
        if hashes[split] != expected.get(path.name):
            errors.append(f"partition_hash_mismatch:{split}")
        rows = []
        for line_no, line in enumerate(payload.decode("utf-8").splitlines(), 1):
            try:
                item = json.loads(line)
            except ValueError:
                item = None
            if not valid_example(item, split):
                errors.append(f"invalid_example:{split}:{line_no}")
                continue
            users = [m["content"] for m in item["messages"] if m["role"] == "user"]
            rows.append(item)
            if item["id"] in ids:
                errors.append(f"duplicate_id:{item['id']}")
            ids.add(item["id"])
            sources[item["source"]].add(split)
            prompts[prompt_key(item)].add(split)
            if any(_normalize_question(question) in evaluation_questions for question in users):
                errors.append(f"evaluation_question_overlap:{item['id']}")
            source_name = item.get("source_file", item["source"])
            source = ROOT / "data" / ("finetuning" if item.get("source_file") else "kb") / source_name
            if Path(source_name).name != source_name:
                errors.append(f"invalid_source_path:{item['id']}")
                continue
            if source not in source_hashes:
                source_hashes[source] = _sha256_file(source) if source.is_file() else None
            if source_hashes[source] != item["source_sha256"]:
                drift.add(source_name)
        counts[split] = len(rows)
        if not rows:
            errors.append(f"empty_partition:{split}")
    cross_sources = sorted(source for source, splits in sources.items() if len(splits) > 1)
    cross_prompts = sum(len(splits) > 1 for splits in prompts.values())
    if cross_sources:
        errors.append("source_crosses_partitions")
    if cross_prompts:
        errors.append("identical_prompt_crosses_partitions")
    if counts != manifest.get("split_counts") or sum(counts.values()) != manifest.get("example_count"):
        errors.append("manifest_count_mismatch")
    if manifest.get("source_registry_sha256") != _sha256_file(REGISTRY_PATH):
        drift.add("source_registry.json")
    if "quarantine_sha256" in manifest:
        quarantine = directory / "quarantine.jsonl"
        if not quarantine.is_file() or _sha256_file(quarantine) != manifest["quarantine_sha256"]:
            errors.append("quarantine_hash_mismatch")
    return {
        "schema_version": "1.0", "dataset": str(directory.resolve()),
        "manifest_sha256": _sha256_file(manifest_path), "split_counts": counts, "partition_sha256": hashes,
        "errors": errors, "source_drift": sorted(drift),
        "cross_split_sources": cross_sources, "cross_split_prompt_count": cross_prompts,
        "ready_for_training": not errors and not drift,
        "scope": "Exact input, source, split and file integrity checks. Domain expertise and semantic overlap require separate review.",
    }


def build_dataset(output_dir: Path = DEFAULT_OUTPUT, *, seed: int = 20260727, dataset_id: str = "xiaoyi-maritime-sft-v4") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = output_dir / ".dataset-build.lock"
    lock.open("x", encoding="utf-8").close()
    try:
        return _build_dataset(output_dir, seed=seed, dataset_id=dataset_id)
    finally:
        # Keep partial files for diagnosis. Close the handle before unlinking
        # on Windows. A failed build must use a new output directory.
        lock.unlink()


def _build_dataset(output_dir: Path, *, seed: int, dataset_id: str) -> dict[str, Any]:
    if any((output_dir / name).exists() for name in ("manifest.json", "train.jsonl", "validation.jsonl", "test.jsonl")):
        raise FileExistsError("数据目录已有版本，请指定新的输出目录以保留原始数据")
    registry = _registry_documents()
    held_out = held_out_questions()
    examples_by_source: dict[str, list[dict[str, Any]]] = {}
    included_sources: list[str] = []
    excluded_sources: dict[str, str] = {}
    for path in sorted(KB_DIR.glob("*.md")):
        metadata = registry.get(path.name, {})
        if metadata.get("provenance_type", "internal_curated") != "internal_curated":
            excluded_sources[path.name] = "not_internal_curated"
            continue
        source_examples = _extract_examples(
            path,
            excluded_questions=held_out,
        )
        if not source_examples:
            continue
        included_sources.append(path.name)
        examples_by_source[path.name] = source_examples

    split_by_source = _source_splits(included_sources, seed)
    examples: list[dict[str, Any]] = []
    for source, source_examples in examples_by_source.items():
        for item in source_examples:
            item["split"] = split_by_source[source]
            item["source_sha256"] = _sha256_file(KB_DIR / source)
            examples.append(item)
    curated_examples = _curated_multiturn_examples(
        excluded_questions=held_out,
    )
    examples.extend(curated_examples)
    examples, quarantine = separate_repeated_prompts(examples)

    output_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter(item["split"] for item in examples)
    artifact_hashes: dict[str, str] = {}
    for split in ("train", "validation", "test"):
        destination = output_dir / f"{split}.jsonl"
        payload = "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in examples
            if item["split"] == split
        )
        destination.write_text(payload, encoding="utf-8")
        try:
            artifact_name = destination.relative_to(ROOT).as_posix()
        except ValueError:
            artifact_name = destination.name
        artifact_hashes[artifact_name] = _sha256_file(destination)

    quarantine_path = output_dir / "quarantine.jsonl"
    quarantine_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                       for row in quarantine), encoding="utf-8")

    manifest = {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "purpose": "LoRA learns maritime language, answer structure, clarification and refusal behavior; RAG remains the authority for current or private facts.",
        "generator": "scripts/build_lora_dataset.py",
        "generator_sha256": _sha256_file(Path(__file__)),
        "seed": seed,
        "split_policy": "source-grouped deterministic 80/10/10 hash split; paraphrases from one source never cross splits",
        "example_count": len(examples),
        "split_counts": dict(sorted(counts.items())),
        "included_source_count": len(included_sources),
        "included_sources": included_sources,
        "curated_multiturn_example_count": len(curated_examples),
        "curated_multiturn_source_count": len(
            {item["source"] for item in curated_examples}
        ),
        "curated_supervision_sha256": {
            path.name: _sha256_file(path)
            for path in CURATED_SUPERVISION_PATHS
            if path.is_file()
        },
        "excluded_source_count": len(excluded_sources),
        "held_out_question_count": len(held_out),
        "evaluation_exclusion_policy": (
            "Exact normalized questions from data/evaluation/*.json are excluded "
            "before the source-grouped split."
        ),
        "source_registry_sha256": _sha256_file(REGISTRY_PATH),
        "artifact_sha256": artifact_hashes,
        "quarantined_count": len(quarantine),
        "quarantine_sha256": _sha256_file(quarantine_path),
        "prompt_isolation_policy": "Quarantine all identical prompts spanning partitions or carrying conflicting answers; preserve preceding conversational turns.",
        "limitations": [
            "Repository-authored supervision, not an independent blinded set reviewed by operational participants excluded from development.",
            "No raw private material is exported by this builder.",
            "A training loss change is not evidence of field accuracy or production benefit.",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从内部整理的明确问答段落构建可审计的LoRA SFT数据集"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dataset-id", default="xiaoyi-maritime-sft-v4", help="新不可变版本的标识")
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--audit-dir", type=Path, help="只读核验一个已有的数据版本")
    args = parser.parse_args()
    if args.audit_dir:
        result = audit_dataset(args.audit_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ready_for_training"] else 1)
    manifest = build_dataset(args.output_dir, seed=args.seed, dataset_id=args.dataset_id)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
