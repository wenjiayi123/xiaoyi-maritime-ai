"""A constrained next-token policy inside the real 1.7B causal language model.

The neural policy is NOT a separate router. LoRA changes the Qwen attention
projections. Harness expands the selected letter into the displayed tool call.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
import os
from pathlib import Path
import time

from .environment import LETTERS

BASE = (
    Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-1.7B/snapshots/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
)
SYSTEM = (
    "你是小懿港航工具调度员。按任务和当前状态选下一步，只输出工具字母。"
    "先读取必要状态再计算；参数必须符合用户要求；写入结果不明先核验；暂停后恢复；"
    "核验全部结果后才交付。不要重复已经完成的操作。"
)


class LanguagePolicy:
    def __init__(self, *, threads=4, seed=20261101):
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from peft import LoraConfig, get_peft_model

        self.torch = torch
        torch.set_num_threads(threads)
        torch.manual_seed(seed)
        self.tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
        base = AutoModelForCausalLM.from_pretrained(
            BASE, local_files_only=True, torch_dtype=torch.float32, low_cpu_mem_usage=True, attn_implementation="eager"
        )
        base.config.use_cache = False
        self.model = get_peft_model(
            base,
            LoraConfig(
                r=8,
                lora_alpha=16,
                lora_dropout=0.0,
                bias="none",
                task_type="CAUSAL_LM",
                target_modules=["q_proj", "v_proj"],
                layers_to_transform=list(range(base.config.num_hidden_layers - 4, base.config.num_hidden_layers)),
            ),
        )
        self.model.eval()
        self.parameters = [p for p in self.model.parameters() if p.requires_grad]
        self.ids = [self.tokenizer.encode(c, add_special_tokens=False)[0] for c in LETTERS]
        if any(len(self.tokenizer.encode(c, add_special_tokens=False)) != 1 for c in LETTERS):
            raise ValueError("action labels must be single tokens")
        self.initial = self.state()
        self.encoded = {}
        self.prefix_cache = OrderedDict()
        self.decision_cache = OrderedDict()
        self.decoder = self.model.get_base_model().model
        self.prefix_layers = len(self.decoder.layers) - 4
        if any(p.requires_grad for layer in self.decoder.layers[: self.prefix_layers] for p in layer.parameters()):
            raise ValueError("prefix caching requires completely frozen prefix layers")

    def state(self):
        return {n: p.detach().clone() for n, p in self.model.named_parameters() if p.requires_grad}

    def load_state(self, state):
        with self.torch.no_grad():
            for name, p in self.model.named_parameters():
                if p.requires_grad:
                    p.copy_(state[name])

    def fingerprint(self):
        h = hashlib.sha256()
        for n, p in self.model.named_parameters():
            if p.requires_grad:
                h.update(n.encode())
                h.update(p.detach().numpy().tobytes())
        return h.hexdigest()

    def batch(self, prompt):
        key = hashlib.sha256(prompt.encode()).hexdigest()
        if key not in self.encoded:
            text = self.tokenizer.apply_chat_template(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            batch = self.tokenizer(text, return_tensors="pt")
            if batch["input_ids"].shape[1] > 768:
                raise ValueError("prompt exceeds registered CPU experiment context")
            if len(self.encoded) > 4000:
                self.encoded.clear()
            self.encoded[key] = batch
        return self.encoded[key]

    def logits(self, prompt):
        batch = self.batch(prompt)
        key = hashlib.sha256(prompt.encode()).hexdigest()
        if key not in self.prefix_cache:

            def capture(module, args, kwargs):
                hidden = args[0] if args else kwargs["hidden_states"]
                self.prefix_cache[key] = hidden.detach().clone()
                if len(self.prefix_cache) > 64:
                    self.prefix_cache.popitem(last=False)

            hook = self.decoder.layers[self.prefix_layers].register_forward_pre_hook(capture, with_kwargs=True)
            try:
                return self.model(**batch, logits_to_keep=1).logits[0, -1, self.ids]
            finally:
                hook.remove()
        self.prefix_cache.move_to_end(key)
        # Exact reuse of frozen prefix activations, not an approximate surrogate.
        # Keep original module identities and restore the complete model before
        # gradient updates, named-parameter inspection, or checkpoint saving.
        layers = self.decoder.layers
        self.decoder.layers = self.torch.nn.ModuleList(list(layers)[self.prefix_layers :])
        try:
            return self.model(
                inputs_embeds=self.prefix_cache[key], attention_mask=batch["attention_mask"], logits_to_keep=1
            ).logits[0, -1, self.ids]
        finally:
            self.decoder.layers = layers

    def verify_prefix_cache(self, prompt):
        self.model.eval()
        with self.torch.no_grad():
            full = self.model(**self.batch(prompt), logits_to_keep=1).logits[0, -1, self.ids]
            self.logits(prompt)
            cached = self.logits(prompt)
        error = float((full - cached).abs().max())
        if error > 1e-4:
            raise RuntimeError(f"frozen-prefix cache logits mismatch: {error}")
        self.model.zero_grad(set_to_none=True)
        full = self.model(**self.batch(prompt), logits_to_keep=1).logits[0, -1, self.ids]
        self.torch.log_softmax(full, 0)[0].backward()
        full_grad = [p.grad.detach().clone() for p in self.parameters]
        self.model.zero_grad(set_to_none=True)
        self.torch.log_softmax(self.logits(prompt), 0)[0].backward()
        grad_error = max(float((p.grad - g).abs().max()) for p, g in zip(self.parameters, full_grad))
        self.model.zero_grad(set_to_none=True)
        if grad_error > 1e-4:
            raise RuntimeError(f"frozen-prefix cache gradient mismatch: {grad_error}")
        return {"logit_max_absolute_error": error, "gradient_max_absolute_error": grad_error, "verified": True}

    def choose(self, prompt, *, sample=False, temperature=1.0):
        started = time.monotonic()
        key = (self.fingerprint(), hashlib.sha256(prompt.encode()).hexdigest())
        cache_hit = key in self.decision_cache
        with self.torch.no_grad():
            if not cache_hit:
                self.decision_cache[key] = self.logits(prompt).detach()
                if len(self.decision_cache) > 256:
                    self.decision_cache.popitem(last=False)
            logits = self.decision_cache[key] / temperature
            probs = self.torch.softmax(logits, dim=0)
            idx = int(self.torch.multinomial(probs, 1)) if sample else int(probs.argmax())
        return LETTERS[idx], {
            "log_probability": float(probs[idx].log()),
            "probabilities": probs.tolist(),
            "seconds": round(time.monotonic() - started, 4),
            "input_tokens": self.batch(prompt)["input_ids"].shape[1],
            "exact_logit_cache_hit": cache_hit,
        }

    def save(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(path, safe_serialization=True)
