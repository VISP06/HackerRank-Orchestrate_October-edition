# Usage Report — Final Full-Dataset Run

## 1. Runtime model usage

The submitted audit agent is deterministic and uses **no model provider and no
model calls at runtime**. All parsing, identity resolution, state
reconstruction, policy application, step generation, validation, and
serialization are ordinary Python code. PDFs are read locally with `pypdf`;
SQL snapshots are executed locally with `sqlite3`.

| Scope | Provider | Model | Calls | Input tokens | Output tokens | Estimated cost |
|---|---|---|---:|---:|---:|---:|
| Full-dataset run (`python3 code/main.py`) | none | none (deterministic) | 0 | 0 | 0 | $0.00 |
| Sample evaluation (`run_eval.py`) | none | none (deterministic) | 0 | 0 | 0 | $0.00 |
| Custom cases (`custom_cases.py`) | none | none (deterministic) | 0 | 0 | 0 | $0.00 |
| **Overall runtime total** | **none** | **none** | **0** | **0** | **0** | **$0.00** |

- Total tokens for the final run: **0**
- Average input tokens per request: **0**
- Average output tokens per request: **0**
- Average total tokens per request: **0**
- Estimated total cost: **$0.00**
- Estimated per-request cost: **$0.00**

No API keys, credentials, or paid services are required to reproduce the
submission.

## 2. Final full-dataset run

| Item | Value |
|---|---:|
| Requests processed | 518 |
| Output | `output.csv` (repository root) |
| `COMPLETE` | 181 |
| `INCOMPLETE` | 327 |
| `NOT_APPLICABLE` | 10 |
| Total steps emitted | 2,466 |
| Mean steps per case | 4.77 |
| Maximum steps in one case | 14 |
| Pipeline wall time | ~1.0 s |
| External network calls | 0 |
| Model calls | 0 |
| Tokens | 0 |
| Estimated cost | $0.00 |

Reproduce the run with:

```bash
python3 code/main.py
```

Reproduce the run statistics with:

```bash
python3 code/evaluation/full_run_stats.py
```

The statistics command rewrites `output.csv` and
`code/evaluation/full_run_stats.md` from the same request set, so the reported
numbers and the submitted predictions come from the same deterministic run.

## 3. Development tooling (not part of the runtime)

The code was developed with the OpenCode coding harness running the
`deepseek-v4.1-flash-free` model. That assistant was used only to inspect the
dataset, write and review code, and run tests. It is not invoked by
`code/main.py`, is not required to reproduce `output.csv`, and its usage is not
included in the runtime totals above. Token accounting for the development
session is not part of the submitted agent's execution.

## 4. Cost interpretation

Because the solution performs no model inference, the full 518-case run has no
token cost. The practical costs are local CPU time (under one second) and disk
reads of the supplied evidence. This keeps the audit reproducible and makes
every answer traceable to a deterministic rule and a participant-visible
evidence id.
