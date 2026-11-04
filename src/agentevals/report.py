"""Markdown (for PR comments) and JUnit XML (for CI dashboards) reports."""

from __future__ import annotations

from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from agentevals.models import RunResult


def format_ms(v: float) -> str:
    """Human latency: '<1' for in-process targets, one decimal under 10 ms, whole ms above."""
    if v < 1:
        return "<1"
    return f"{v:.1f}" if v < 10 else f"{v:.0f}"


_ICON = {"pass": "✅", "fail": "❌", "regression": "🔴", "fixed": "🟢", "new": "🆕"}


def markdown(result: RunResult) -> str:
    s = result.summary()
    lines = [
        f"## Agent evals — {result.suite}",
        "",
        f"**{s['passed']}/{s['cases']} cases pass** ({s['pass_rate']:.0%}) · "
        f"p50 {format_ms(s['p50_ms'])} ms · p95 {format_ms(s['p95_ms'])} ms · target `{result.target}`",
    ]
    if result.regressions:
        lines.append(f"\n🔴 **Regressions:** {', '.join(result.regressions)}")
    if result.fixed:
        lines.append(f"\n🟢 Fixed: {', '.join(result.fixed)}")
    lines += ["", "| | case | pass rate | p50 ms | p95 ms | failures |", "|---|---|---|---|---|---|"]
    for c in result.cases:
        fails = sorted({f for t in c.trials for f in t.failures})
        shown = "; ".join(fails[:2]) + (f" (+{len(fails) - 2})" if len(fails) > 2 else "")
        cells = [
            _ICON[c.status],
            f"`{c.case_id}`",
            f"{c.pass_rate:.0%}",
            format_ms(c.p50_ms),
            format_ms(c.p95_ms),
            escape(shown),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def junit(result: RunResult) -> str:
    suite = ET.Element(
        "testsuite",
        name=result.suite,
        tests=str(len(result.cases)),
        failures=str(sum(1 for c in result.cases if not c.passed)),
    )
    for c in result.cases:
        tc = ET.SubElement(
            suite, "testcase", name=c.case_id, classname=result.suite, time=f"{c.p50_ms / 1000:.3f}"
        )
        if not c.passed:
            fails = sorted({f for t in c.trials for f in t.failures})
            ET.SubElement(tc, "failure", message=f"pass rate {c.pass_rate:.0%}").text = "\n".join(fails)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
