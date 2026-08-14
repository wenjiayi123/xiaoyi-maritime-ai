# 小懿 LoRA 工程与质量准入报告 v1

生成时间：2026-08-14T01:00:50+00:00
来源run_id：`lora-20260727T033445Z`

| 门禁 | 结果 | 当前证据 | 晋级要求 |
|---|---|---|---|
| `artifact_integrity` | PASS | manifest, training report, PEFT adapter and GGUF hashes recorded | all training and inference artifacts are content-addressed |
| `real_local_generation_probe` | PASS | 44 completion tokens plus one RAG-to-LoRA probe | matching-base adapter loads and produces tokens through the local runtime |
| `multi_seed_training` | BLOCKED | 1 seed (20260727) | >=3 independently trained seeds |
| `heldout_generation_quality` | BLOCKED | validation/test loss use 8/8 sampled cases; no blinded preference study by operational participants excluded from training | >=100 source-isolated unseen generation cases plus blinded review by operational participants excluded from training |
| `lora_attributable_benchmark` | BLOCKED | model benchmark provider counts are {'local_grounded_rag': 30, 'local_policy_boundary': 5, 'local_workforce_guidance': 16}; they do not isolate adapter causal lift | same-base baseline vs LoRA paired benchmark with 95% CI and no safety regression |
| `training_depth` | BLOCKED | 64 optimizer steps on one CPU run | predeclared convergence budget with multi-seed stability and early-stop evidence |

## 结论

- 工程完整性：`true`；质量准入：`false`。
- 当前定位：`engineering_only_quality_blocked`。这是PEFT LoRA/SFT适配器训练，不是从零训练基础模型。
- 训练快照：1个种子、64步、622/94/125条来源隔离样本；loss仅抽取8/8例计算。
- 适配器SHA-256：`d277abd0cc6155f682e3fd2293a56da2bead7a047fbf8d3678dce2a30e3bd46a`；GGUF SHA-256：`2160da946ab4adcada579d9db0fa1d812285c7fbd418f6c09679bd95e546edfb`。
- `production_authority=false`。loss下降不等于回答准确率、独立业务人员偏好、港口KPI或法律正确性。
