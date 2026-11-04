# Changelog

## Unreleased

- Fix: latencies under a millisecond were printed as `0.0 ms`; now `<1 ms`.

## 0.1.0 — 2026-11-04

- YAML suites with dotted-path checks (equals, contains, regex, one_of, min/max, length, exists, json_schema, tools_called/not_called).
- Python and HTTP targets (sync or async).
- Judges: keyword (deterministic), Anthropic, OpenAI-compatible.
- Trials per case with pass threshold, p50/p95 latency, latency budgets.
- Baseline comparison: regression / fixed / new statuses, CI exit codes.
- Markdown and JUnit reports; `agent-evals run | report`.
