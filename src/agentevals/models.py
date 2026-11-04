from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Check(BaseModel):
    """One deterministic assertion on the agent's JSON output.

    `path` is a dotted path into the output ("answer", "route.team", "tool_calls.0.name").
    Exactly one operator is set.
    """

    path: str = "$"
    equals: Any | None = None
    not_equals: Any | None = None
    contains: str | list[str] | None = None
    not_contains: str | list[str] | None = None
    regex: str | None = None
    one_of: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    length_max: int | None = None
    is_true: bool | None = None
    json_schema: dict[str, Any] | None = None
    tools_called: list[str] | None = Field(
        default=None, description="Tool names that must appear, in order, in the list at `path`"
    )
    tools_not_called: list[str] | None = None
    exists: bool | None = None
    description: str | None = None


class Judge(BaseModel):
    """Optional LLM-as-judge rubric. Score 0–1 compared against `threshold`."""

    rubric: str
    threshold: float = 0.7
    path: str = "$"


class Case(BaseModel):
    id: str
    input: dict[str, Any]
    checks: list[Check] = Field(default_factory=list)
    judge: Judge | None = None
    tags: list[str] = Field(default_factory=list)
    max_latency_ms: int | None = None
    trials: int | None = Field(default=None, description="Override suite trials for this case")
    note: str = ""


class Suite(BaseModel):
    name: str
    target: str | None = Field(default=None, description="python:module:function | http://host/path")
    trials: int = 1
    pass_threshold: float = Field(
        default=1.0, description="Share of trials that must pass for a case to pass"
    )
    timeout_s: float = 60.0
    judge_provider: str | None = None
    cases: list[Case]


class TrialResult(BaseModel):
    ok: bool
    latency_ms: float
    output: Any = None
    failures: list[str] = Field(default_factory=list)
    judge_score: float | None = None
    error: str | None = None


class CaseResult(BaseModel):
    case_id: str
    tags: list[str]
    trials: list[TrialResult]
    pass_rate: float
    passed: bool
    p50_ms: float
    p95_ms: float
    status: Literal["pass", "fail", "regression", "fixed", "new"] = "pass"


class RunResult(BaseModel):
    suite: str
    target: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cases: list[CaseResult]
    pass_rate: float
    regressions: list[str] = Field(default_factory=list)
    fixed: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        lat = [t.latency_ms for c in self.cases for t in c.trials if t.error is None]
        lat.sort()
        return {
            "cases": len(self.cases),
            "passed": sum(1 for c in self.cases if c.passed),
            "pass_rate": self.pass_rate,
            "regressions": len(self.regressions),
            "fixed": len(self.fixed),
            "p50_ms": lat[len(lat) // 2] if lat else 0.0,
            "p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0.0,
        }
