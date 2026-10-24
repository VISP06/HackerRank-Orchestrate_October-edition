# Intent cross-check

The request text is the gate between `NOT_APPLICABLE` and an audit. The
deterministic classifier in `code/ghost/intent.py` uses explicit deletion and
non-deletion cues plus the `CLASSIFY_REQUEST` activity. This note records an
independent model check of that gate.

## Method

- Mask embedded email addresses, then deduplicate the 518 requests. This yields
  **375 unique texts**; 80 texts are shared by 2–14 cases (for example, mail-merge
  variants of the same template).
- Ask `gemini-3.1-flash-lite` for strict JSON:
  `intent` ∈ {`DELETION`, `NON_DELETION`, `UNCLEAR`}, `language` (ISO 639-1), and
  a one-line reason. Temperature 0; the prompt says the request is data, never
  instructions.
- Compare the model label with `authorizes_deletion` for the same text.
- The model is a **cross-check only**. `authorizes_deletion` and the
  `CLASSIFY_REQUEST` activity keep precedence in `code/main.py`; a disagreement
  would be logged, not applied.

Run used:

```bash
python3 /tmp/opencode/run_intent2.py   # iterates the 375 unique texts; cache-aware
```

## Result

| Label | Deterministic | LLM |
|---|---:|---:|
| `DELETION` | 365 | 365 |
| `NON_DELETION` | 10 | 10 |
| `UNCLEAR` | — | 0 |
| **Disagreements** | | **0 / 375** |

The ten non-deletion groups map one-to-one to `case_533`–`case_542`. They are
access, correction, export, marketing opt-out, and similar requests, not
deletion. The model agreed on all ten; no deletion case was reclassified as
non-deletion.

Detected languages: English (370), Portuguese (1), Korean (1), Spanish (1),
Japanese (1), French (1). The deterministic classifier already handles these
languages, and the model did not flag any text as ambiguous.

## Cost and cache

- 375 successful classifications: 92,784 input / 15,074 output tokens,
  **$0.045807** at $0.25/$1.50 per 1M.
- The cache stores one response per unique text; reruns make zero calls.
- During the run the free-tier quota returned HTTP 429; the client retried with
  exponential backoff. All 375 texts eventually received a label.
- 39 duplicate calls in the usage log are retests, not extra texts.

## What this does and does not prove

It proves that the model and the deterministic rules agree on every request in
the supplied set, including all ten `NOT_APPLICABLE` cases. It does not prove
that either classifier is correct on unseen languages or on adversarial
requests. The deterministic gate remains authoritative, so a future model change
cannot silently flip a case to `NOT_APPLICABLE`.
