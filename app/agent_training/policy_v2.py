"""Exact frozen-prefix disk cache; retains V1 model architecture and output.

Only immutable first-24-layer activations are cached. Learned layers always run
with the currently loaded adapter. Cache files are reproducible accelerators,
separate from immutable training evidence; no inference predictions are reused
across parameter fingerprints.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np

from .policy import BASE, SYSTEM, LanguagePolicy


class CachedLanguagePolicy(LanguagePolicy):
    def __init__(self, *, cache_dir, threads=4, seed=20261101, cache_limit_gib=3):
        super().__init__(threads=threads, seed=seed)
        identity = {
            "base_snapshot": str(BASE.resolve()),
            "config_sha256": hashlib.sha256((BASE / "config.json").read_bytes()).hexdigest(),
            "system": SYSTEM,
            "torch": self.torch.__version__,
            "dtype": "float32",
            "attention": "eager",
            "prefix_layers": self.prefix_layers,
            "cache_revision": "exact-frozen-prefix-npy.v1",
        }
        namespace = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.disk_dir = Path(cache_dir) / namespace
        self.disk_dir.mkdir(parents=True, exist_ok=True)
        manifest = self.disk_dir / "identity.json"
        if manifest.exists() and json.loads(manifest.read_text()) != identity:
            raise ValueError("prefix cache identity mismatch")
        if not manifest.exists():
            manifest.write_text(json.dumps(identity, indent=2) + "\n")
        self.disk_bytes = sum(p.stat().st_size for p in self.disk_dir.glob("*.npy"))
        self.disk_limit = int(cache_limit_gib * 1024**3)
        self.cache_stats = {"memory_hits": 0, "disk_hits": 0, "misses": 0, "writes": 0, "capacity_skips": 0}

    def logits(self, prompt):
        key = hashlib.sha256(prompt.encode()).hexdigest()
        batch = self.batch(prompt)
        token_hash = hashlib.sha256(batch["input_ids"].numpy().tobytes()).hexdigest()
        file = self.disk_dir / (token_hash + ".npy")
        if key in self.prefix_cache:
            self.cache_stats["memory_hits"] += 1
        elif file.exists():
            data = np.load(file, allow_pickle=False)
            expected = (1, batch["input_ids"].shape[1], self.model.config.hidden_size)
            if data.dtype != np.float32 or data.shape != expected or not np.isfinite(data).all():
                raise ValueError("invalid frozen prefix cache array")
            recorded = file.with_suffix(".sha256").read_text().strip()
            if hashlib.sha256(data.tobytes()).hexdigest() != recorded:
                raise ValueError("prefix cache checksum mismatch")
            self.prefix_cache[key] = self.torch.from_numpy(data)
            self.cache_stats["disk_hits"] += 1
        else:
            self.cache_stats["misses"] += 1
        result = super().logits(prompt)
        if not file.exists():
            data = self.prefix_cache[key].detach().numpy()
            if self.disk_bytes + data.nbytes + 256 <= self.disk_limit:
                temporary = file.with_suffix(".tmp")
                with temporary.open("wb") as stream:
                    np.save(stream, data, allow_pickle=False)
                temporary.replace(file)
                file.with_suffix(".sha256").write_text(hashlib.sha256(data.tobytes()).hexdigest() + "\n")
                self.disk_bytes += file.stat().st_size
                self.cache_stats["writes"] += 1
            else:
                self.cache_stats["capacity_skips"] += 1
        while len(self.prefix_cache) > 16:
            self.prefix_cache.popitem(last=False)
        return result
