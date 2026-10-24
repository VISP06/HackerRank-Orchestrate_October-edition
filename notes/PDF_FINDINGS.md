# PDF evidence findings (Step 3)

The four participant-visible PDFs are text-layer documents.  The deterministic
parser already handled two of them (`evidence_55`, `evidence_58`).  The LLM
pass is only allowed to add a resource when the id, or an explicit catalog
alias, is printed in the document.  Ids invented from a customer name, an
order line, or an attachment label are rejected.

Run used for this note:

```text
python3 code/main.py --out /tmp/opencode/combined2.csv --llm-tasks screenshots,pdfs
python3 code/evaluation/run_eval.py \
  --requests dataset/sample_deletion_requests.csv \
  --out /tmp/opencode/combined_sample.csv --llm-tasks screenshots,pdfs
```

## Per-file result

| File | Captured | What it proves | Converted observations |
|---|---|---|---|
| `evidence_18` `account_history_report_20260718.pdf` | 2026-07-18T11:00Z | Customer statement `NST-2026-0718-1842` for `user_18`, order `ORD-20261260`, with name, email, delivery address, and order timeline | `export_1842` (`USER_EXPORT`, PRESENT, captured 11:00) |
| `evidence_27` `legal_retention_register_20260529.pdf` | 2026-05-29T08:00Z | Six disputed-order rows (`ORD-20264118` … `ORD-20264600`) for `user_08/12/17/21/24/29`, retain-until 2033 | none (order numbers are not catalog resource ids) |
| `evidence_55` `security_retention_extract.pdf` | 2026-09-05T06:30Z | `audit_record_003` for `user_03`, recorded 2026-08-25, retain until 2027-08-25 | `audit_record_003` (duplicate of deterministic parser, skipped) |
| `evidence_58` `delivery_correction_attachment.pdf` | 2026-09-12T07:30Z | Support reference `CS-4827 / support_001` for `user_07`, with name, email, phone, order `ORD-20264827`, and the delivery-correction attachment | `support_001` (duplicate of deterministic parser, skipped) |

## Grounding rules added

1. A resource id from the model is accepted only when the exact token appears
   in the PDF text and matches the catalog grammar.
2. A printed business reference is mapped only through an explicit
   `LINK_RESOURCE_IDENTITY` alias.  `NST-2026-0718-1842` is listed as the alias
   of `export_1842`; `ORD-…`, `CS-…`, and customer names are not ids.
3. A bare `user_N` mention is an identity, never proof that the document is an
   account tombstone.  This stopped the `user_17` row in the legal register
   from becoming `tombstone_17`.
4. When two lines of one document resolve to the same resource, the richest
   record wins.  This removed the duplicate attachment line for `evidence_18`.
5. PDF observations use the manifest `captured_at` as their observation time;
   a printed record date is kept in `attrs.recorded_at`.  This keeps the
   `captured_at <= audit_at` admissibility rule exact.

## Effect on cases

Only one case changes, and it is the intended post-deletion export:

- `case_33` (audit 2026-07-19T13:00Z): COMPLETE (1 step) → INCOMPLETE
  (7 steps).  The statement was generated on 2026-07-18 at 11:00, after the
  workflow reported COMPLETE at 02:00, and the catalog linked `export_1842` to
  the subject at 11:07.  Finding cites `evidence_18`; remediation deletes
  `export_1842`; verification covers `account_2373`, `export_1260`,
  `export_1842`, `search_2352`, and retained `audit_record_8486`.

No other case changes versus the screenshot-only run:

```text
screenshots only : 152 COMPLETE / 356 INCOMPLETE / 10 NOT_APPLICABLE, 2,930 steps
screenshots+PDFs : 151 COMPLETE / 357 INCOMPLETE / 10 NOT_APPLICABLE, 2,937 steps
difference       : case_33 only (+6 steps)
```

## Temporal guard

`case_52` is the earlier Ingrid Dahl request (audit 2026-06-19).  The same PDF
was captured on 2026-07-18, after that cutoff.  Without a guard, the late
artifact added a spurious `VERIFY_RECORD_ABSENT` for `export_1842`, which did
not exist at the earlier audit.  `steps.py` now excludes a late-only
`USER_EXPORT` when no pre-cutoff catalog link grounds it: an export package is
the artifact itself, so a post-cutoff artifact with no earlier link is not a
copy that existed at `audit_at`.

## Rejected model output

Raw extraction (before grounding) proposed:

- `evidence_18`: `account_18`, `object_20261260` — neither token is printed in
  the statement.  Re-keyed to the catalog alias `export_1842`.
- `evidence_27`: six `ORD-…` rows — not catalog ids; no observations.
- `evidence_58`: `support_4827`, `object_4827` — neither token is printed.
  Resolved to the printed `support_001`; the attachment line was dropped.

Keeping the raw output would have added three spurious steps to sample
`case_07` (`support_4827` finding, remediation, verification) and reduced
sample precision below 1.0.
