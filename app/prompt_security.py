from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSecurityResult:
    text: str
    detections: tuple[str, ...]

    @property
    def isolated(self) -> bool:
        return bool(self.detections)


_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override_en",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b.{0,48}"
            r"\b(?:previous|prior|above|system|developer)\b.{0,32}"
            r"\b(?:instruction|prompt|message|rule)s?\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "instruction_override_zh",
        re.compile(
            r"(?:忽略|无视|覆盖|忘记).{0,24}"
            r"(?:先前|之前|以上|上述|系统|开发者).{0,24}"
            r"(?:指令|提示词|消息|规则)",
            re.DOTALL,
        ),
    ),
    (
        "prompt_exfiltration_en",
        re.compile(
            r"\b(?:reveal|show|print|return|expose|leak)\b.{0,48}"
            r"\b(?:system|developer|hidden|secret|api[-_ ]?key)\b.{0,24}"
            r"\b(?:prompt|instruction|message|token|key)s?\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "prompt_exfiltration_zh",
        re.compile(
            r"(?:泄露|显示|打印|返回|暴露).{0,32}"
            r"(?:系统|开发者|隐藏|密钥|令牌).{0,24}"
            r"(?:提示词|指令|消息|密钥|令牌)",
            re.DOTALL,
        ),
    ),
    (
        "role_delimiter_escape",
        re.compile(
            r"(?:<\|(?:im_start|im_end)\|>|</?(?:system|developer|assistant)>|"
            r"#{2,}\s*(?:system|developer)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_execution_override",
        re.compile(
            r"(?:\byou\s+must\b|\bmust\b|必须|务必).{0,48}"
            r"(?:call|execute|run|调用|执行).{0,16}"
            r"(?:tool|function|shell|command|工具|函数|命令)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def detect_prompt_injection(text: str) -> tuple[str, ...]:
    value = str(text or "")
    return tuple(rule_id for rule_id, pattern in _INJECTION_RULES if pattern.search(value))


def isolate_untrusted_text(text: str) -> PromptSecurityResult:
    """Redact instruction-like spans only in model context, never in source records."""
    value = str(text or "")
    detections: list[str] = []
    for rule_id, pattern in _INJECTION_RULES:
        if not pattern.search(value):
            continue
        detections.append(rule_id)
        value = pattern.sub(f"[ISOLATED_UNTRUSTED_INSTRUCTION:{rule_id}]", value)
    return PromptSecurityResult(text=value, detections=tuple(detections))
