"""Run a suite: trials per case, checks + judge per trial, percentiles, baseline comparison."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

import yaml

from agentevals.checks import resolve, run_check
from agentevals.judge import JudgeProvider
from agentevals.models import Case, CaseResult, RunResult, Suite, TrialResult
from agentevals.targets import Target


def load_suite(path: Path) -> Suite:
    return Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round((len(s) - 1) * p)))]


def run_trial(case: Case, target: Target, judge: JudgeProvider | None) -> TrialResult:
    t0 = time.perf_counter()
    try:
        output = target(case.input)
    except Exception as e:  # the agent crashed: that's a failed trial, not a crashed eval
        return TrialResult(
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
            error=f"{type(e).__name__}: {e}",
            failures=["agent raised"],
        )
    latency = (time.perf_counter() - t0) * 1000

    failures: list[str] = []
    for check in case.checks:
        failures.extend(run_check(check, output))
    if case.max_latency_ms is not None and latency > case.max_latency_ms:
        failures.append(f"latency {latency:.0f} ms > {case.max_latency_ms} ms")

    score: float | None = None
    if case.judge is not None:
        if judge is None:
            failures.append("case has a judge rubric but no judge provider is configured")
        else:
            judged = resolve(output, case.judge.path)
            score, reason = judge.score(case.judge.rubric, judged, case.input)
            if score < case.judge.threshold:
                failures.append(f"judge {score:.2f} < {case.judge.threshold} ({reason})")
    return TrialResult(
        ok=not failures, latency_ms=latency, output=output, failures=failures, judge_score=score
    )


def run_suite(
    suite: Suite,
    target: Target,
    judge: JudgeProvider | None = None,
    trials: int | None = None,
    only_tags: list[str] | None = None,
    baseline: RunResult | None = None,
    target_label: str = "",
) -> RunResult:
    results: list[CaseResult] = []
    base_status = {c.case_id: c.passed for c in baseline.cases} if baseline else {}
    for case in suite.cases:
        if only_tags and not set(only_tags) & set(case.tags):
            continue
        n = case.trials or trials or suite.trials
        trial_results = [run_trial(case, target, judge) for _ in range(n)]
        rate = sum(1 for t in trial_results if t.ok) / n
        passed = rate >= suite.pass_threshold
        lat = [t.latency_ms for t in trial_results]
        status: Literal["pass", "fail", "regression", "fixed", "new"] = "pass" if passed else "fail"
        if baseline:
            before = base_status.get(case.id)
            if before is None:
                status = "new"
            elif before and not passed:
                status = "regression"
            elif not before and passed:
                status = "fixed"
        results.append(
            CaseResult(
                case_id=case.id,
                tags=case.tags,
                trials=trial_results,
                pass_rate=rate,
                passed=passed,
                p50_ms=_pct(lat, 0.5),
                p95_ms=_pct(lat, 0.95),
                status=status,
            )
        )
    overall = sum(1 for c in results if c.passed) / len(results) if results else 0.0
    return RunResult(
        suite=suite.name,
        target=target_label or suite.target or "?",
        cases=results,
        pass_rate=overall,
        regressions=[c.case_id for c in results if c.status == "regression"],
        fixed=[c.case_id for c in results if c.status == "fixed"],
    )


def load_baseline(path: Path) -> RunResult | None:
    if not path.exists():
        return None
    return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


def save_json(result: RunResult, path: Path, keep_outputs: bool = False) -> None:
    data: dict[str, Any] = result.model_dump(mode="json")
    if not keep_outputs:
        for c in data["cases"]:
            for t in c["trials"]:
                t.pop("output", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
