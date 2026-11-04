"""How to call the agent under test.

python:package.module:function   → function(input: dict) -> dict (sync or async)
http://host/path                 → POST JSON input, expect JSON output
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import sys
from collections.abc import Callable
from typing import Any

import httpx

Target = Callable[[dict[str, Any]], Any]


def load_target(spec: str, timeout_s: float = 60.0, headers: dict[str, str] | None = None) -> Target:
    if spec.startswith("python:"):
        _, module, func = spec.split(":", 2)
        cwd = os.getcwd()
        if cwd not in sys.path:  # resolve modules relative to where the suite is run from
            sys.path.insert(0, cwd)
        fn = getattr(importlib.import_module(module), func)

        def call_python(payload: dict[str, Any]) -> Any:
            result = fn(payload)
            if inspect.iscoroutine(result):
                return asyncio.run(result)
            return result

        return call_python
    if spec.startswith(("http://", "https://")):
        client = httpx.Client(timeout=timeout_s, headers=headers or {})

        def call_http(payload: dict[str, Any]) -> Any:
            r = client.post(spec, json=payload)
            r.raise_for_status()
            return r.json()

        return call_http
    raise ValueError(f"unknown target {spec!r}: use python:module:function or http(s)://…")
