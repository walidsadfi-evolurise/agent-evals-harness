from __future__ import annotations

from agentevals.checks import resolve, run_check
from agentevals.models import Check

OUT = {
    "answer": "Livraison en 2 à 4 jours ouvrés.",
    "refused": False,
    "confidence": 0.9,
    "tool_calls": [{"name": "search_faq", "arguments": {}}, {"function": {"name": "get_order"}}, "notify"],
    "nested": {"a": {"b": [10, 20]}},
}


def test_resolve_paths() -> None:
    assert resolve(OUT, "$") is OUT
    assert resolve(OUT, "nested.a.b.1") == 20
    assert resolve(OUT, "tool_calls.0.name") == "search_faq"
    assert run_check(Check(path="nested.a.zzz", exists=False), OUT) == []
    assert run_check(Check(path="nested.a.zzz", equals=1), OUT) == ["nested.a.zzz: missing in output"]


def test_operators() -> None:
    assert run_check(Check(path="answer", contains=["livraison", "JOURS"]), OUT) == []
    assert run_check(Check(path="answer", contains="express"), OUT) == ["answer: does not contain 'express'"]
    assert run_check(Check(path="answer", not_contains="express"), OUT) == []
    assert run_check(Check(path="answer", regex=r"\d+ à \d+"), OUT) == []
    assert run_check(Check(path="refused", equals=False), OUT) == []
    assert run_check(Check(path="refused", is_true=True), OUT) != []
    assert run_check(Check(path="confidence", min=0.8, max=1.0), OUT) == []
    assert run_check(Check(path="confidence", min=0.95), OUT) == ["confidence: 0.9 < 0.95"]
    assert run_check(Check(path="answer", length_max=10), OUT) == ["answer: length > 10"]
    assert run_check(Check(path="refused", one_of=[True]), OUT) == ["refused: False not in [True]"]
    assert run_check(Check(path="nested.a.b", length_max=2), OUT) == []


def test_tool_call_assertions_accept_common_shapes() -> None:
    assert run_check(Check(path="tool_calls", tools_called=["search_faq", "get_order"]), OUT) == []
    assert (
        run_check(Check(path="tool_calls", tools_called=["get_order", "search_faq"]), OUT) != []
    )  # order matters
    assert run_check(Check(path="tool_calls", tools_called=["notify"]), OUT) == []
    assert run_check(Check(path="tool_calls", tools_not_called=["delete_order"]), OUT) == []
    assert run_check(Check(path="tool_calls", tools_not_called=["notify"]), OUT) == [
        "tool_calls: forbidden tools called: ['notify']"
    ]


def test_json_schema() -> None:
    schema = {
        "type": "object",
        "required": ["answer", "missing"],
        "properties": {"confidence": {"type": "string"}},
    }
    fails = run_check(Check(path="$", json_schema=schema), OUT)
    assert len(fails) == 2 and all(f.startswith("$: schema") for f in fails)
