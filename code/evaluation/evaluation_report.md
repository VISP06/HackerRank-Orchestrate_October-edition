# Evaluation Report — Ghost Data Still Exists

## 1. What was evaluated

The submitted agent is a deterministic audit engine. It reads the participant
dataset only, reconstructs state at each case's `audit_at`, applies
`deletion_rules.csv`, and emits findings, remediation, and verification steps.
It makes no model calls, so every run is reproducible.

Evaluation used the 32 public sample requests and their published answers in
`dataset/sample_output.csv`. That file was used only for measurement; the
engine never reads it. To avoid tuning on every sample, the samples were split
by case number:

- **dev** — `int(case_id) % 4 != 0` (24 cases)
- **held-out** — `int(case_id) % 4 == 0` (8 cases: 04, 08, 12, 16, 20, 24, 28, 32)

Held-out cases were measured after each change but were not used to select
individual case behaviour. All fixes were general rules.

Reproduce with:

```bash
python3 code/evaluation/run_eval.py --splits
python3 code/evaluation/custom_cases.py
python3 code/evaluation/full_run_stats.py
```

## 2. Headline metrics

### Overall (32 samples)

| Metric | Result |
|---|---:|
| Deletion-status accuracy | **32/32 (100.0%)** |
| Exact sequence accuracy | **17/32 (53.1%)** |
| Step precision (exact 6-tuples) | **1.0000** |
| Step recall | **0.8964 (173/193)** |
| Step F1 | **0.9454** |
| Field accuracy, aligned (missing steps count wrong) | **0.896** per field |
| Field accuracy, emitted steps only | **1.000** per field |

A step tuple is `(phase, system_id, resource_id, operation, state, evidence_id)`.
Precision 1.0 means every step the engine emitted matches the published answer
exactly. All remaining loss is missing steps, not wrong or misordered steps.

### Dev and held-out

| Split | Cases | Status | Sequence | Precision | Recall | F1 | Truth/Pred/TP steps |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dev | 24 | 24/24 (100%) | 13/24 (54.2%) | 1.0000 | 0.9060 | 0.9507 | 149 / 135 / 135 |
| Held-out | 8 | 8/8 (100%) | 4/8 (50.0%) | 1.0000 | 0.8636 | 0.9268 | 44 / 38 / 38 |

The held-out result is slightly lower than dev because the held-out split
contains a larger share of the batch-ambiguous account and analytics ids
described in §5. No held-out-specific rule was added.

### Per status (32 samples)

| Status | Truth | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| COMPLETE | 10 | 10 | 1.000 | 1.000 | 1.000 |
| INCOMPLETE | 22 | 22 | 1.000 | 1.000 | 1.000 |
| NOT_APPLICABLE | 0 | 0 | — | — | — |

The sample set has no non-deletion request. The full request set has 10
`NOT_APPLICABLE` cases; the intent classifier was checked to emit exactly those
10 and no others.

## 3. Field-level results

Two field views are reported:

1. **Aligned over truth** — each truth step is aligned to a predicted step by
   exact tuple, then phase/resource/operation, then resource/operation, then
   resource. A missing step makes every field wrong. This is the strict view.
2. **Emitted steps only** — only predicted steps are scored. This isolates
   field correctness from recall.

| Field | Aligned | Emitted |
|---|---:|---:|
| `phase` | 0.896 | 1.000 |
| `system_id` | 0.896 | 1.000 |
| `resource_id` | 0.896 | 1.000 |
| `operation` | 0.896 | 1.000 |
| `state` | 0.896 | 1.000 |
| `evidence_id` | 0.896 | 1.000 |

Every emitted step has the correct phase, system, resource, operation, state,
and evidence reference. There were no partial-field errors and no ordering
errors among emitted steps.

## 4. Participant-authored evaluation cases

`code/evaluation/custom_cases.py` contains six synthetic cases independent of
the published sample answers. They test the decision boundaries that matter
most for the contract.

| # | Case | Expected behaviour | Result |
|---|---|---|---|
| 1 | Access request ("send me a copy of my data") | Not a deletion request → `NOT_APPLICABLE`, `[]` | PASS |
| 2 | Tombstone with only stable `user_id` | `COMPLETE`, `VERIFY_RECORD_REDACTED` | PASS |
| 3 | Active sync flow | `INCOMPLETE`, finding → disable → verify disabled | PASS |
| 4 | Unblocked backup | `INCOMPLETE`, restore-risk finding → block → verify blocked | PASS |
| 5 | Analytics record with no identifiers | Already anonymized → `COMPLETE`, `VERIFY_RECORD_ANONYMIZED` | PASS |
| 6 | Snapshot captured before the case linked the resource | Must not prove absence; a later snapshot does | PASS |

Result: **6/6 passed**.

## 5. Failures found and improvements made

### Fixed during development

| Failure | Root cause | Fix |
|---|---|---|
| Missing states in log-backed cases | Escaped quotes inside log lines truncated fields; trace lines were not grouped by `requestId` | Quote-aware log parser and `requestId` trace grouping |
| Missing identifiers in SQL snapshots | Nested `record_json` columns were treated as opaque strings | Recursive JSON decoding inside SQL rows |
| Missed links for renamed/merged identities | Only a subset of correlation keys was recognized | Added `subject_ref`, `subject_key`, `owner_key`, and `correlation_key` |
| Wrong `system_id` on log observations | System inferred from the file rather than the resource | Derive system from the resource prefix and store metadata |
| Decoy/stale account profile in one sample | Every account observation for an identity was kept | Keep one current profile: prefer present profiles, then direct observations, then newest |
| Account/analytics deletions with no identifier in evidence | No participant-visible link to the resource id | Unique `deletion_worker` dispatch for `account_*` (`DELETE_RECORD`) or `analytics_*` (`ANONYMIZE_RECORD`) within ±15 minutes of `reported_at`; state still comes from evidence; ambiguous batches are rejected |
| Syslog lookups never reached their resource | The bare `tr-…` token in syslog lines was not carried into the field parser, so completion rows had no `lookup_key` | Prepend the token as `trace_id`; the existing trace join now attaches `lookup_key`/`subject_ref` to every completion row |
| Stateless identifier links produced no future check | An identifier seen only in a post-cutoff artifact stayed invisible after a case was already `INCOMPLETE` | Emit the policy's end-state `VERIFY_*` step with an empty `evidence_id`; catalog-only links are excluded |
| Dispatch window too wide | 30–90 minute windows linked neighbouring requests that shared a workflow batch | Single 15-minute window; measured in `notes/LINK_RULE_STUDY.md` (6 correct / 0 wrong versus 15 correct / 11 wrong for a widening fallback) |
| Snapshot absence used before the resource was known | A snapshot taken before the link cannot prove later absence | Added `known_at` to every link and require the snapshot to be at or after it |
| Absent analytics record produced no verification | Policy treated `ABSENT` as already anonymized | Absent records now verify `ABSENT`; only `ANONYMIZED` is retained as-is |
| Unchecked future evidence on `COMPLETE` | Invariants only checked findings | Invariants now validate evidence existence and capture time for findings and `COMPLETE` verifications |

### Remaining failure categories

All 20 missing sample steps fall into three evidence-linkage families:

| Family | Missing steps | Why it cannot be linked safely |
|---|---:|---|
| Account profile ids (`account_*`) | 12 | The id appears only in the workflow's deletion dispatch; no participant-visible identifier, hash, or resource link names it. The unique 15-minute window abstains when several unrelated dispatches share the batch. One id (`account_004`) appears nowhere in participant data. |
| Analytics profiles (`analytics_*`) | 6 | Anonymized records are dispatched in pairs about 28–29 minutes before the report time; the record's identifiers are gone, so the pair cannot be split without guessing. One of the pair is the subject, the other belongs to a neighbouring request. |
| Security audit records (`audit_record_*`) | 2 | The retained record carries no user identifier, hash, or stable correlation key anywhere in participant evidence (`audit_record_6645`, `audit_record_5569`). |

A deliberate choice was made not to use the `user_N → account_N` numbering
convention. It happens to fit the first seeded users but fails elsewhere (for
example, a sample user with `user_61` maps to `account_3960`). Using it would
raise sample recall while adding unsupported steps on the hidden set.

### Full-dataset behaviour

The final 518-case run is documented in
`code/evaluation/full_run_stats.md`. Summary:

- 518 rows: 159 `COMPLETE`, 349 `INCOMPLETE`, 10 `NOT_APPLICABLE`
- 2,885 steps, mean 5.57 per case, maximum 14
- Every case now reaches at least one resource; 8 reach a resource but have no
  admissible state at `audit_at` (the `low_evidence` flag)
- Those 8 `COMPLETE` cases therefore have zero verification steps; they are
  evidence-coverage gaps, not findings, and are analysed in
  `notes/ZERO_STEP_FAMILIES.md`
- 0 label-free invariant violations
- Runtime: under 1 second on the full set

## 6. What could not be resolved

1. **Unlinkable resource ids.** The three families above require knowledge that
   is not present in participant-facing evidence. Emitting them would be a
   guess, so the engine omits them and keeps precision at 1.0.
2. **Zero-step `COMPLETE` cases.** Eight full-run cases have links but no
   admissible state at `audit_at` (six post-cutoff consolidated readbacks and
   two catalog-only links whose sole artifacts are screenshots). The engine
   keeps the status, cites nothing it cannot prove, and marks the rows
   `low_evidence`; see `notes/ZERO_STEP_FAMILIES.md`.
3. **Ambiguous workflow windows.** When several account deletions occur near a
   reported time, the engine refuses to choose. This is the main recall
   ceiling on account verifications.

## 7. Open questions

- Should an evidence-sparse `COMPLETE` case be reported as `INCOMPLETE` because
  verification is impossible, or stay `COMPLETE` because no remaining data is
  proven? The engine currently chooses `COMPLETE`; the published samples do not
  contain this situation.
- Is a catalog link plus a later full-system snapshot without the resource
  considered sufficient proof of absence by the grader? The engine accepts it
  only when the snapshot is at or after the link time.
- For replicated stores, should a row missing from the primary but present in a
  stale replica always be a finding? The engine treats every replica row as a
  remaining copy and reports it.
