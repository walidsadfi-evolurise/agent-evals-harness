from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from agentevals.cli import app
from agentevals.judge import KeywordJudge, make_judge
from agentevals.models import Case, Check, Judge, Suite
from agentevals.report import junit, markdown
from agentevals.runner import load_baseline, load_suite, run_suite, save_json
from agentevals.targets import load_target

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "examples" / "faq_suite.yaml"


def test_example_suite_passes_end_to_end(tmp_path: Path) -> None:
    suite = load_suite(SUITE)
    result = run_suite(suite, load_target(suite.target or ""), KeywordJudge())
    assert result.pass_rate == 1.0 and len(result.cases) == 5
    assert all(len(c.trials) == 2 for c in result.cases)
    md = markdown(result)
    assert "5/5 cases pass" in md and "`order-status-uses-tool`" in md
    xml = junit(result)
    assert 'tests="5"' in xml and 'failures="0"' in xml and "<failure" not in xml
    save_json(result, tmp_path / "r.json")
    assert "output" not in json.dumps(json.load((tmp_path / "r.json").open())["cases"][0]["trials"][0])


def _flaky_factory(fail_every: int) -> Any:
    n = {"i": 0}

    def agent(payload: dict[str, Any]) -> dict[str, Any]:
        n["i"] += 1
        return {"answer": "bad" if n["i"] % fail_every == 0 else "good"}

    return agent


def test_trials_pass_threshold_and_percentiles() -> None:
    suite = Suite(
        name="t",
        trials=4,
        pass_threshold=0.75,
        cases=[Case(id="c", input={}, checks=[Check(path="answer", equals="good")])],
    )
    res = run_suite(suite, _flaky_factory(4))  # 1 of 4 fails → 75 % → passes
    assert res.cases[0].pass_rate == 0.75 and res.cases[0].passed
    res = run_suite(suite, _flaky_factory(2))  # 2 of 4 fail → 50 %
    assert not res.cases[0].passed and res.pass_rate == 0.0
    assert res.cases[0].p95_ms >= res.cases[0].p50_ms >= 0


def test_agent_exception_is_a_failed_trial_not_a_crash() -> None:
    def boom(payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("provider down")

    res = run_suite(Suite(name="t", cases=[Case(id="c", input={})]), boom)
    t = res.cases[0].trials[0]
    assert not t.ok and t.error and "provider down" in t.error


def test_latency_budget_and_judge_without_provider() -> None:
    import time

    def slow(payload: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.03)
        return {"answer": "ok"}

    suite = Suite(name="t", cases=[Case(id="c", input={}, max_latency_ms=5, judge=Judge(rubric="x"))])
    res = run_suite(suite, slow, judge=None)
    fails = res.cases[0].trials[0].failures
    assert any("latency" in f for f in fails) and any("no judge provider" in f for f in fails)


def test_regression_detection(tmp_path: Path) -> None:
    suite = Suite(
        name="t",
        cases=[
            Case(id="a", input={}, checks=[Check(path="x", equals=1)]),
            Case(id="b", input={}, checks=[Check(path="x", equals=2)]),
        ],
    )
    good = run_suite(suite, lambda p: {"x": 1})
    assert [c.status for c in good.cases] == ["pass", "fail"]
    save_json(good, tmp_path / "base.json")
    base = load_baseline(tmp_path / "base.json")
    later = run_suite(
        Suite(name="t", cases=suite.cases + [Case(id="c", input={})]), lambda p: {"x": 2}, baseline=base
    )
    assert [c.status for c in later.cases] == ["regression", "fixed", "new"]
    assert later.regressions == ["a"] and later.fixed == ["b"]
    assert "🔴 **Regressions:** a" in markdown(later)


def test_tag_filter_and_async_target() -> None:
    async def agent(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    suite = Suite(name="t", cases=[Case(id="a", input={}, tags=["x"]), Case(id="b", input={}, tags=["y"])])
    res = run_suite(suite, load_target("python:tests.test_runner_and_cli:_async_agent"), only_tags=["y"])
    assert [c.case_id for c in res.cases] == ["b"] and res.cases[0].passed


async def _async_agent(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True}


def test_http_target_and_cli(tmp_path: Path) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from examples.faq_agent import answer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            assert self.headers.get("authorization") == "Bearer t"
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            data = json.dumps(answer(body)).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/answer"
    try:
        runner = CliRunner()
        base = tmp_path / "base.json"
        r = runner.invoke(
            app,
            [
                "run",
                str(SUITE),
                "--target",
                url,
                "--auth-header",
                "Bearer t",
                "--baseline",
                str(base),
                "--out",
                str(tmp_path / "r.json"),
                "--save-baseline",
                "--report",
                str(tmp_path / "r.md"),
                "--junit",
                str(tmp_path / "r.xml"),
                "--min-pass-rate",
                "1.0",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "5/5 pass" in r.output and base.exists() and (tmp_path / "r.xml").exists()
        # a target that never refuses must show up as a regression against the saved baseline
        r = runner.invoke(
            app,
            [
                "run",
                str(SUITE),
                "--target",
                "python:tests.test_runner_and_cli:_never_refuses",
                "--baseline",
                str(base),
                "--out",
                str(tmp_path / "r2.json"),
            ],
        )
        assert r.exit_code == 1 and "regressions" in r.output
        r = runner.invoke(app, ["report", str(tmp_path / "r.json")])
        assert r.exit_code == 0 and "## Agent evals" in r.output
    finally:
        srv.shutdown()
        srv.server_close()


def _never_refuses(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": "Bien sûr, voici la recette : …",
        "refused": False,
        "tool_calls": [{"name": "get_order", "arguments": {"id": "0"}}],
        "confidence": 0.99,
    }


def test_make_judge() -> None:
    assert make_judge(None) is None and make_judge("none") is None
    assert isinstance(make_judge("keyword"), KeywordJudge)
    try:
        make_judge("anthropic")
    except ValueError as e:
        assert "ANTHROPIC_API_KEY" in str(e)
