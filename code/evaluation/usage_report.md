# Usage Report — Final Full-Dataset Run

## 1. Summary

| Item | Value |
|---|---|
| Provider | Google (Gemini API, official `google-genai` SDK) |
| Model | `gemini-3.1-flash-lite` |
| Settings | temperature `0.0`, JSON response mode, disk cache |
| Final output run | 15 model calls (11 screenshots + 4 PDFs), then 518 deterministic cases |
| Final output run wall time | 73.6 s (fresh extraction); 1.36 s cache-only rerun |
| Final output | `output.csv`, SHA-256 `a8aea02c6c1dd6e01ef3caf05fdf91c07e3e69e34970ae48eec0f1443bd83435` |
| Rows | 518: 151 `COMPLETE`, 357 `INCOMPLETE`, 10 `NOT_APPLICABLE` |
| Steps | 2,937 (mean 5.67, maximum 14) |
| Invariant violations | 0 |
| Output-changing model decisions | 0; the model only supplies grounded observations |

The audit decision, policy application, step ordering, and serialization are
deterministic Python. The model converts the 11 PNG screenshots and 4 PDFs into
structured observations and provides a second opinion on request intent. It
cannot override `authorizes_deletion` or the `CLASSIFY_REQUEST` activity.

Pricing source: <https://ai.google.dev/gemini-api/docs/pricing>, checked
2026-10-24. Standard paid-tier rates: **$0.25 per 1M input tokens** and
**$1.50 per 1M output tokens**. No cached-input discount is assumed, so the
estimate is conservative. The run used the paid tier; the free tier is $0 but
rate-limited.

## 2. Final full-dataset run

The authoritative run was:

```bash
python3 code/main.py --fresh --llm-tasks screenshots,pdfs --out output.csv
```

It made exactly 15 fresh extraction calls, one per artifact, then processed all
518 requests deterministically. A second run with the populated cache produced a
byte-identical file and made zero API calls.

| Task | Calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---:|---:|---:|---:|---:|
| Screenshot extraction (11 PNGs) | 11 | 23,687 | 15,669 | 39,356 | $0.029424 |
| PDF extraction (4 PDFs) | 4 | 3,836 | 2,971 | 6,807 | $0.005416 |
| **Final output run total** | **15** | **27,523** | **18,640** | **46,163** | **$0.034841** |

Derived per-request figures for the final run (518 requests):

| Metric | Value |
|---|---:|
| Average input tokens per request | 53.1 |
| Average output tokens per request | 36.0 |
| Average total tokens per request | 89.1 |
| Average model calls per request | 0.029 |
| Estimated total cost | $0.034841 |
| Estimated cost per request | $0.0000673 |
| Estimated cost per extracted artifact | $0.002323 |

The model does not see the 518 request rows; it sees one image or PDF at a time.
The per-request figures therefore describe the amortized cost of producing the
evidence index, not 518 separate prompts.

### Cache behaviour

- Fresh run: 15 calls, 0 cache hits, 73.6 s wall time (the client enforces a
  4-second minimum interval and retries HTTP 429).
- Cache-only rerun: 0 calls, 15 cache hits, 1.36 s wall time.
- Cache entries: keyed by `sha256(model + prompt_version + prompt + input_bytes)`.
  A keyless checkout resolves the same model name and reads the same entries, so
  `output.csv` is reproducible offline.

## 3. Intent cross-check (diagnostic, not output-changing)

The 518 requests contain 375 unique texts after masking embedded email addresses
(80 texts are shared by 2–14 cases). Each unique text was classified once with
the same model.

| Task | Calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---:|---:|---:|---:|---:|
| Intent classification | 375 | 92,784 | 15,074 | 107,858 | $0.045807 |

| Result | Count |
|---|---:|
| Deterministic `DELETION` | 365 |
| Deterministic `NON_DELETION` | 10 |
| LLM `DELETION` | 365 |
| LLM `NON_DELETION` | 10 |
| LLM `UNCLEAR` | 0 |
| Disagreements | **0** |

All ten non-deletion texts are `case_533`–`case_542`; the model agreed on every
one. The cross-check is retained as evidence of classifier agreement, but it is
not consulted when writing a row. Disabling it (`--llm-tasks screenshots,pdfs`)
does not change `output.csv`.

Average per unique text: 287.6 tokens and $0.0001222. Amortized over 518
requests: 208.2 tokens and $0.0000884 per request.

## 4. Combined model usage

| Scope | Calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---:|---:|---:|---:|---:|
| Final output run (15 artifacts) | 15 | 27,523 | 18,640 | 46,163 | $0.034841 |
| Intent cross-check (375 texts) | 375 | 92,784 | 15,074 | 107,858 | $0.045807 |
| **Total model work behind the submission** | **390** | **120,307** | **33,714** | **154,021** | **$0.080648** |

Amortized over 518 requests: **297.3 tokens** and **$0.0001557** per request.

## 5. Validation, tuning, and diagnostic calls

The usage log also contains calls that are not part of the 390 calls above: the
cached extraction pass that preceded the fresh run, the first screenshot prompt
version, a model-availability test on `gemini-3.8-flash`, and duplicate intent
retests while the quota was rate-limited. They are reported for completeness but
are not needed to reproduce the submission.

| Category | Calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---:|---:|---:|---:|---:|
| Cached extraction pass (same 15 artifacts) | 15 | 27,523 | 18,640 | 46,163 | $0.034841 |
| Screenshot prompt v1 tests (11 on 3.1, 1 on 3.8) | 12 | 19,876 | 10,634 | 30,510 | $0.022622 |
| Duplicate intent retests | 39 | 9,500 | 1,635 | 11,135 | $0.004827 |
| **Validation and tuning total** | **66** | **66,899** | **40,909** | **107,808** | **$0.062290** |

| Overall project usage | Calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---:|---:|---:|---:|---:|
| All logged model calls | 456 | 177,206 | 64,623 | 241,829 | $0.142938 |

The model split is one call on `gemini-3.8-flash` (the availability test) and
455 calls on `gemini-3.1-flash-lite`. The overall cost uses each model's own
rate. Failed HTTP 429 attempts are retried by the client and are not counted as
successful calls; only responses with token metadata are logged.

The coding harness used to build the solution was OpenCode with
`deepseek-v4.1-flash-free`. That usage is development tooling, not part of the
submitted agent, and is not included in these totals.

## 6. Cost interpretation

The submitted output costs about **$0.035** in extraction calls. The intent
cross-check doubles the model work but changes no answer; it can be disabled to
halve cost. Re-running the audit from the included cache costs **$0.00** and
takes about **1.4 seconds** for all 518 cases.

No API key, credential, or paid service is required to reproduce `output.csv`.
The key is read only from `GEMINI_API_KEY` (or an uncommitted `.env`) and is never
logged, printed, or written to the cache. The cache contains only prompts,
public participant-facing artifact bytes, and structured model responses.
