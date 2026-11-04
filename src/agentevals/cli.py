from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agentevals.judge import make_judge
from agentevals.report import format_ms as _ms
from agentevals.report import junit, markdown
from agentevals.runner import load_baseline, load_suite, run_suite, save_json
from agentevals.targets import load_target

app = typer.Typer(
    help="Evaluate an LLM agent against a YAML suite, with trials, judges and regression detection.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def run(
    suite_file: Path = typer.Argument(..., exists=True),
    target: str = typer.Option(None, help="Override the suite's target (python:mod:fn or http://…)"),
    trials: int = typer.Option(None, help="Override trials per case"),
    tag: list[str] = typer.Option([], help="Only cases with one of these tags"),
    judge: str = typer.Option(
        None, help="none | keyword | anthropic | openai (default: suite.judge_provider)"
    ),
    judge_model: str = typer.Option(None),
    baseline: Path = typer.Option(
        Path("evals/baseline.json"), help="Previous results for regression detection"
    ),
    save_baseline: bool = typer.Option(False, help="Overwrite the baseline with this run"),
    out: Path = typer.Option(Path("evals/last-run.json")),
    report: Path = typer.Option(None, help="Write a Markdown report here"),
    junit_out: Path = typer.Option(None, "--junit", help="Write JUnit XML here"),
    min_pass_rate: float = typer.Option(0.0, help="Exit 1 below this overall pass rate"),
    fail_on_regression: bool = typer.Option(
        True, help="Exit 1 if a case that passed in the baseline now fails"
    ),
    keep_outputs: bool = typer.Option(False, help="Store raw agent outputs in the JSON results"),
    auth_header: str = typer.Option(None, help="Authorization header value for HTTP targets"),
) -> None:
    suite = load_suite(suite_file)
    spec = target or suite.target
    if not spec:
        raise typer.BadParameter("no target: set `target:` in the suite or pass --target")
    headers = {"authorization": auth_header} if auth_header else None
    tgt = load_target(spec, timeout_s=suite.timeout_s, headers=headers)
    provider = judge if judge is not None else suite.judge_provider
    jp = make_judge(
        provider,
        judge_model,
        os.environ.get("ANTHROPIC_API_KEY") if provider == "anthropic" else os.environ.get("OPENAI_API_KEY"),
        os.environ.get("OPENAI_BASE_URL"),
    )
    base = load_baseline(baseline)
    result = run_suite(suite, tgt, jp, trials=trials, only_tags=tag or None, baseline=base, target_label=spec)

    table = Table(title=f"{suite.name} — {result.summary()['passed']}/{result.summary()['cases']} pass")
    for col in ("", "case", "pass", "p50", "p95", "failures"):
        table.add_column(col, justify="right" if col in ("pass", "p50", "p95") else "left")
    for c in result.cases:
        fails = sorted({f for t in c.trials for f in t.failures})
        icon = {
            "pass": "[green]✓[/]",
            "fail": "[red]✗[/]",
            "regression": "[red]✗ REG[/]",
            "fixed": "[green]✓ fixed[/]",
            "new": "[cyan]new[/]",
        }[c.status]
        table.add_row(
            icon, c.case_id, f"{c.pass_rate:.0%}", _ms(c.p50_ms), _ms(c.p95_ms), "; ".join(fails[:2])
        )
    console.print(table)

    save_json(result, out, keep_outputs=keep_outputs)
    if save_baseline:
        save_json(result, baseline)
        console.print(f"baseline saved → {baseline}")
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(markdown(result), encoding="utf-8")
    if junit_out:
        junit_out.parent.mkdir(parents=True, exist_ok=True)
        junit_out.write_text(junit(result), encoding="utf-8")

    s = result.summary()
    console.print(
        f"pass rate {s['pass_rate']:.0%} · p50 {_ms(s['p50_ms'])} ms · p95 {_ms(s['p95_ms'])} ms"
        f" · regressions {s['regressions']} · fixed {s['fixed']}"
    )
    if s["pass_rate"] < min_pass_rate:
        console.print(f"[red]pass rate below {min_pass_rate:.0%}[/]")
        raise typer.Exit(1)
    if fail_on_regression and result.regressions:
        console.print(f"[red]regressions: {', '.join(result.regressions)}[/]")
        raise typer.Exit(1)


@app.command()
def report(results: Path = typer.Argument(Path("evals/last-run.json"), exists=True)) -> None:
    """Print the Markdown report for a saved run."""
    from agentevals.models import RunResult

    typer.echo(markdown(RunResult.model_validate_json(results.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    app()
