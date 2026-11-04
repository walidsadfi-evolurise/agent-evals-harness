"""Deterministic assertions. Each returns a list of human-readable failures (empty = pass)."""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator

from agentevals.models import Check

_MISSING = object()


def resolve(output: Any, path: str) -> Any:
    if path in ("$", ""):
        return output
    cur = output
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, _MISSING)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else _MISSING
        else:
            return _MISSING
        if cur is _MISSING:
            return _MISSING
    return cur


def _text(v: Any) -> str:
    return v if isinstance(v, str) else str(v)


def run_check(check: Check, output: Any) -> list[str]:
    value = resolve(output, check.path)
    where = check.path
    fails: list[str] = []

    if check.exists is not None:
        if (value is not _MISSING) != check.exists:
            fails.append(f"{where}: expected {'present' if check.exists else 'absent'}")
        return fails
    if value is _MISSING:
        return [f"{where}: missing in output"]

    if check.equals is not None and value != check.equals:
        fails.append(f"{where}: expected {check.equals!r}, got {value!r}")
    if check.not_equals is not None and value == check.not_equals:
        fails.append(f"{where}: must not equal {check.not_equals!r}")
    if check.contains is not None:
        needles = [check.contains] if isinstance(check.contains, str) else check.contains
        hay = _text(value).lower()
        for n in needles:
            if n.lower() not in hay:
                fails.append(f"{where}: does not contain {n!r}")
    if check.not_contains is not None:
        needles = [check.not_contains] if isinstance(check.not_contains, str) else check.not_contains
        hay = _text(value).lower()
        for n in needles:
            if n.lower() in hay:
                fails.append(f"{where}: must not contain {n!r}")
    if check.regex is not None and not re.search(check.regex, _text(value), re.S):
        fails.append(f"{where}: does not match /{check.regex}/")
    if check.one_of is not None and value not in check.one_of:
        fails.append(f"{where}: {value!r} not in {check.one_of!r}")
    if check.min is not None and (not isinstance(value, int | float) or value < check.min):
        fails.append(f"{where}: {value!r} < {check.min}")
    if check.max is not None and (not isinstance(value, int | float) or value > check.max):
        fails.append(f"{where}: {value!r} > {check.max}")
    if (
        check.length_max is not None
        and len(_text(value) if not isinstance(value, list | dict) else value) > check.length_max
    ):
        fails.append(f"{where}: length > {check.length_max}")
    if check.is_true is not None and bool(value) != check.is_true:
        fails.append(f"{where}: expected truthiness {check.is_true}")
    if check.json_schema is not None:
        errs = sorted(Draft202012Validator(check.json_schema).iter_errors(value), key=lambda e: list(e.path))
        fails.extend(f"{where}: schema — {e.message}" for e in errs[:5])
    if check.tools_called is not None or check.tools_not_called is not None:
        names = _tool_names(value)
        if check.tools_called is not None:
            it = iter(names)
            if not all(any(t == n for n in it) for t in check.tools_called):
                fails.append(f"{where}: tools {names} do not include {check.tools_called} in order")
        if check.tools_not_called is not None:
            forbidden = [t for t in check.tools_not_called if t in names]
            if forbidden:
                fails.append(f"{where}: forbidden tools called: {forbidden}")
    return fails


def _tool_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for k in ("name", "tool", "tool_name", "function"):
                if k in item:
                    v = item[k]
                    out.append(v["name"] if isinstance(v, dict) and "name" in v else str(v))
                    break
    return out
