# agent-evals-harness

**Treat your agent's behaviour like a test suite: YAML cases, deterministic checks, an optional LLM judge, repeated trials for nondeterminism, latency percentiles, baseline regression detection, Markdown + JUnit reports, and an exit code your CI can gate on.**

[![CI](https://github.com/walidsadfi-evolurise/agent-evals-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/walidsadfi-evolurise/agent-evals-harness/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

*[Version française plus bas](#version-française)*

Every agent I ship to a client comes with one of these. Not because models are bad, but because **"we changed the prompt and nothing broke" is a claim, and this is how you make it a fact**. Framework-agnostic: your agent is anything that takes a JSON object and returns one — a Python function, or an HTTP endpoint.

```text
$ agent-evals run evals/suite.yaml --baseline evals/baseline.json --min-pass-rate 0.95
                         support-agent — 23/24 pass
┏━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃       ┃ case                      ┃ pass ┃  p50 ┃  p95 ┃ failures                     ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✓     │ opening-hours             │ 100% │  812 │  940 │                              │
│ ✗ REG │ refund-policy-cites-source│  33% │ 1203 │ 1890 │ answer: does not contain     │
│       │                           │      │      │      │ '14 jours'; judge 0.40 < 0.7 │
│ ✓     │ off-topic-is-refused      │ 100% │  650 │  702 │                              │
…
pass rate 96% · p50 801 ms · p95 1890 ms · regressions 1 · fixed 0
regressions: refund-policy-cites-source
$ echo $?
1
```

## A suite

```yaml
name: support-agent
target: http://localhost:8000/ask          # or python:my_package.agent:answer
trials: 3                                  # run each case 3× — models are not deterministic
pass_threshold: 0.67                       # a case passes if ≥ 2/3 trials pass
judge_provider: anthropic                  # none | keyword | anthropic | openai

cases:
  - id: refund-policy-cites-source
    tags: [faq, citations]
    input: { question: "Combien de jours pour un remboursement ?" }
    checks:
      - { path: answer, contains: ["14 jours"] }
      - { path: answer, regex: "\\[\\d+\\]" }             # has a citation marker
      - { path: refused, equals: false }
      - { path: citations, length_max: 3 }
    judge:
      rubric: "The answer states the 14-day window and cites the refund policy, nothing else."
      threshold: 0.7
    max_latency_ms: 2500

  - id: never-calls-refund-tool-without-order
    tags: [safety, tools]
    input: { question: "Rembourse-moi" }
    checks:
      - { path: tool_calls, tools_not_called: [create_refund] }
      - { path: answer, contains: "numéro de commande" }

  - id: output-contract
    input: { question: "horaires" }
    checks:
      - path: $
        json_schema: { type: object, required: [answer, refused, tool_calls] }
```

### Checks

`equals` · `not_equals` · `contains` / `not_contains` (string or list, case-insensitive) · `regex` · `one_of` · `min` / `max` · `length_max` · `is_true` · `exists` · `json_schema` · `tools_called` (ordered subsequence; accepts `[{name}]`, `[{function:{name}}]` or `["name"]`) · `tools_not_called`. Paths are dotted: `route.team`, `tool_calls.0.arguments.id`, `$` for the whole output.

### Judge

One rubric per case, a score in `[0, 1]`, a threshold. Providers: `anthropic`, `openai` (any OpenAI-compatible endpoint, incl. local models via `OPENAI_BASE_URL`), and `keyword` — a deterministic stand-in so suites with judges still run in CI without keys. Keep rubrics literal; use checks for anything that can be checked.

### Trials, baselines, regressions

- `trials` runs each case N times; `pass_threshold` says what share must pass. p50/p95 latency come for free.
- `--baseline evals/baseline.json` compares against the last accepted run: cases flip to **regression** (passed before, fails now), **fixed**, or **new**. `--fail-on-regression` (default) makes the exit code 1 on any regression; `--save-baseline` accepts the current run.
- `--report out.md` writes a Markdown table for a PR comment; `--junit out.xml` feeds any CI test dashboard.

## Install & run

```bash
pip install -e ".[dev]"
agent-evals run examples/faq_suite.yaml --save-baseline       # demo agent, no keys needed
agent-evals run examples/faq_suite.yaml --judge anthropic     # with ANTHROPIC_API_KEY
agent-evals run evals/suite.yaml --target https://agent.internal/ask --auth-header "Bearer $TOKEN" --tag safety
agent-evals report evals/last-run.json
```

### In GitHub Actions

```yaml
- run: pip install agent-evals-harness
- run: agent-evals run evals/suite.yaml --baseline evals/baseline.json --junit evals/junit.xml --report evals/report.md --min-pass-rate 0.95
  env: { ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }} }
- uses: marocchino/sticky-pull-request-comment@v2
  if: always()
  with: { path: evals/report.md }
```

Commit `evals/baseline.json` when you accept a change in behaviour; the diff in the PR *is* the behaviour review.

## Design notes

- **Checks before judges.** Most of what matters about an agent's output is checkable: did it refuse, did it call the tool, is the number right, is the shape valid. Judges are for the remainder, and every judge score is logged so you can audit the judge too.
- **Trials, not retries.** Running a case 3 times and requiring 2 passes measures flakiness instead of hiding it.
- **The agent is a black box.** No SDK to adopt, no decorators, no tracing dependency. A function or a URL.
- **Regression is the metric that matters.** A 94 % pass rate means little; "three cases that passed on `main` fail on this branch" is actionable.

## Project layout

```
src/agentevals/
  models.py   Check, Judge, Case, Suite, TrialResult, CaseResult, RunResult
  checks.py   path resolution + operators
  targets.py  python:module:function (sync/async) and http(s) targets
  judge.py    KeywordJudge, AnthropicJudge, OpenAIJudge
  runner.py   trials, thresholds, percentiles, baseline comparison
  report.py   Markdown and JUnit
  cli.py      agent-evals run | report
examples/     faq_agent.py + faq_suite.yaml (the demo the tests run)
```

## Roadmap

- [ ] Parallel trials with a concurrency cap
- [ ] Cost tracking when the target reports token usage
- [ ] Multi-turn cases (a scripted conversation, assertions per turn)
- [ ] Pairwise judge (A/B two targets on the same inputs)

## License

MIT — see [LICENSE](LICENSE). Built by [Walid Sadfi](https://www.malt.fr/profile/walidsadfi), Forward Deployed Engineer · agents IA & WooCommerce.

---

## Version française

**Traitez le comportement de votre agent comme une suite de tests : cas en YAML, vérifications déterministes, juge LLM optionnel, essais répétés pour le non-déterminisme, percentiles de latence, détection de régression par rapport à une baseline, rapports Markdown + JUnit, et un code de sortie pour bloquer la CI.**

Chaque agent que je livre à un client part avec ça. Pas parce que les modèles sont mauvais, mais parce que **« on a changé le prompt et rien n'a cassé » est une affirmation ; ceci en fait un fait.** Indépendant du framework : l'agent est une fonction Python ou un endpoint HTTP qui prend un JSON et renvoie un JSON.

- **Vérifications d'abord** (`contains`, `regex`, `equals`, `json_schema`, `tools_called`, `tools_not_called`, bornes numériques, budget de latence), **juge ensuite** pour le reste, avec un juge déterministe pour tourner sans clé.
- **Essais répétés** : chaque cas N fois, seuil de réussite, p50/p95.
- **Régressions** : comparaison avec la dernière baseline acceptée ; un cas qui passait et ne passe plus fait échouer la CI. Le diff de `baseline.json` dans la PR, c'est la revue de comportement.
- **Rapports** Markdown (commentaire de PR) et JUnit (tableau de bord CI).

```bash
pip install -e ".[dev]"
agent-evals run examples/faq_suite.yaml --save-baseline
```

Vous avez un agent en production et personne ne sait dire s'il s'est dégradé depuis le dernier changement ? [Parlons-en sur Malt](https://www.malt.fr/profile/walidsadfi).
