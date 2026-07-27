# 小懿 LoRA 数据边界

运行 `python scripts/build_lora_dataset.py` 后，处理结果写入
`.runtime/finetuning/xiaoyi-maritime-sft-v1/`，不会提交到 Git。

构建器读取知识库中人工明确编写的“常见问法 / 等价问法 / 直接回答”配对，
并合并 `curated_multiturn_v2.json` 中人工审核的身份、多轮追问与幻觉边界样本：

- 不让模型自动生成训练答案；
- 排除仓库固定评测中完全相同的问题；
- 以来源文档为分组切分 Train / Validation / Test，同一来源不会跨集合；
- 保存每个来源、数据集文件和清单的 SHA-256；
- LoRA 学习港航表达、澄清、拒答和步骤逻辑，时效事实仍交给 RAG。

项目、档案、笔记和专属资料可以进入 `data/kb/` 做检索，但只有经过人工审核并
显式整理为上述监督格式的内容才进入 LoRA，避免把过时规定、秘密、错误笔记和
检索文本中的指令直接写入模型参数。
