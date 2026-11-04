"""LLM-as-judge: a rubric, an output, a score in [0, 1] with a one-line reason.

Judges are the fuzzy part of an eval, so they are kept narrow: one rubric per
case, a numeric score, and a fake judge for tests and CI without keys.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

JUDGE_SYSTEM = """You grade an AI agent's output against a rubric.
Return ONLY JSON: {"score": <number 0..1>, "reason": "<one sentence>"}.
1 = fully meets the rubric, 0 = fails it. Be strict and literal; do not reward verbosity."""


class JudgeProvider(ABC):
    name = "base"

    @abstractmethod
    def score(self, rubric: str, output: Any, inp: dict[str, Any]) -> tuple[float, str]: ...


class KeywordJudge(JudgeProvider):
    """Deterministic stand-in: fraction of rubric words (≥ 5 letters) present in the output."""

    name = "keyword"

    def score(self, rubric: str, output: Any, inp: dict[str, Any]) -> tuple[float, str]:
        words = {w for w in re.findall(r"[a-zà-ÿ]{5,}", rubric.lower())}
        text = json.dumps(output, ensure_ascii=False).lower()
        if not words:
            return 1.0, "empty rubric"
        hit = sum(1 for w in words if w in text)
        return hit / len(words), f"{hit}/{len(words)} rubric terms present"


class AnthropicJudge(JudgeProvider):
    name = "anthropic"

    def __init__(self, model: str, api_key: str, base_url: str = "https://api.anthropic.com") -> None:
        self.model = model
        self.client = httpx.Client(
            base_url=base_url, timeout=60, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        )

    def score(self, rubric: str, output: Any, inp: dict[str, Any]) -> tuple[float, str]:
        user = _user(rubric, output, inp)
        r = self.client.post(
            "/v1/messages",
            json={
                "model": self.model,
                "max_tokens": 200,
                "temperature": 0,
                "system": JUDGE_SYSTEM,
                "messages": [{"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        return _parse(text)


class OpenAIJudge(JudgeProvider):
    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str | None) -> None:
        self.model = model
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=60,
            headers={"authorization": f"Bearer {api_key}"} if api_key else {},
        )

    def score(self, rubric: str, output: Any, inp: dict[str, Any]) -> tuple[float, str]:
        user = _user(rubric, output, inp)
        r = self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return _parse(str(r.json()["choices"][0]["message"]["content"]))


def _user(rubric: str, output: Any, inp: dict[str, Any]) -> str:
    return (
        f"Rubric:\n{rubric}\n\nInput:\n{json.dumps(inp, ensure_ascii=False)}"
        f"\n\nOutput:\n{json.dumps(output, ensure_ascii=False)}"
    )


def _parse(text: str) -> tuple[float, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return 0.0, "judge returned no JSON"
    try:
        data = json.loads(m.group(0))
        return max(0.0, min(1.0, float(data.get("score", 0)))), str(data.get("reason", ""))[:200]
    except (ValueError, TypeError):
        return 0.0, "judge JSON unreadable"


def make_judge(
    provider: str | None, model: str | None = None, api_key: str | None = None, base_url: str | None = None
) -> JudgeProvider | None:
    if provider in (None, "", "none"):
        return None
    if provider == "keyword":
        return KeywordJudge()
    if provider == "anthropic":
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY required for the anthropic judge")
        return AnthropicJudge(model or "claude-sonnet-4-5", api_key)
    if provider == "openai":
        return OpenAIJudge(model or "gpt-4o-mini", base_url or "https://api.openai.com/v1", api_key)
    raise ValueError(f"unknown judge provider {provider}")
