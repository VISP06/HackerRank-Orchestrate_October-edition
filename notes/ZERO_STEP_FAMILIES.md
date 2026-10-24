# Zero-step and low-evidence families

Generated from the 518-case full run. Every case id, resource id, and file id below is
participant-visible. Personal identifiers are masked.

## Scope

`output.csv` (518 cases) has 159 `COMPLETE`, 349 `INCOMPLETE`, and 10 `NOT_APPLICABLE`
rows, with 2,885 steps in total. Eight `COMPLETE` rows have zero steps. The full-run
report marks each of them `low_evidence` (no linked resource, or links but no admissible
state at `audit_at`):

| Case | Audit cutoff | Links | Link reasons |
|---|---|---:|---|
| `case_35` | 2026-09-02T08:00Z | 3 | `identifier_late` |
| `case_39` | 2026-08-08T10:00Z | 4 | `identifier_late` |
| `case_50` | 2026-07-14T12:00Z | 4 | `identifier_late` |
| `case_52` | 2026-06-19T14:00Z | 4 | `catalog_link`, `identifier_late` |
| `case_53` | 2026-05-25T09:00Z | 3 | `identifier_late` |
| `case_55` | 2026-04-30T11:00Z | 4 | `identifier_late` |
| `case_61` | 2026-02-14T10:00Z | 2 | `catalog_link`, `identifier_late` |
| `case_63` | 2026-09-17T09:20Z | 1 | `catalog_link` |

An earlier snapshot of the pipeline had 22 cases with no link at all and 8 more with
links but no state. The no-link group disappeared after unbounded identity discovery
(`identifier_late`) and the syslog trace-join fix described in Family C. The remaining
eight are the genuine zero-step families below.

Method: exact-token scan of all 396 manifest files for each subject's current email and
stable `user_id` (word boundaries, not substrings), manifest capture times compared with
`audit_at`, PDF text extraction with `pypdf`, and PNG filename/chunk checks.

## Family A — post-cutoff consolidated readback (6 cases)

`case_35`, `case_39`, `case_50`, `case_52`, `case_53`, `case_55`.

Each subject appears in **exactly one file in the entire participant corpus**, and that
file is captured after the case's cutoff:

| Case | Sole artifact | Captured | After cutoff by |
|---|---|---|---|
| `case_35` | `evidence_01` `service_events_ap_south_20260915.log` | 2026-09-15T11:59Z | 13 days |
| `case_39` | `evidence_01` same log | 2026-09-15T11:59Z | 38 days |
| `case_50` | `evidence_01` same log | 2026-09-15T11:59Z | 62 days |
| `case_52` | `evidence_01` same log | 2026-09-15T11:59Z | 87 days |
| `case_53` | `evidence_02` `customer_data_snapshot_bundle_20260917.json` | 2026-09-17T12:00Z | 115 days |
| `case_55` | `evidence_01` same log | 2026-09-15T11:59Z | 138 days |

The artifacts are readbacks: `evidence_01` contains `profile_lookup_completed` /
`index_query_completed` / `audit_record_read_completed` rows with `resource_id` and a
404/FOUND result; `evidence_02` is a records-assurance snapshot bundle with the same
shape. They ground the links (`account_8491`, `search_428`, `audit_record_8925`, …) but
are inadmissible as state because `captured_at > audit_at`.

Why no step is emitted:

1. `_eligible` rejects every observation from these files (artifact capture is after the
   cutoff even when the internal `observed_at` is earlier).
2. No pre-cutoff file contains the subject's email or `user_id`.
3. Coverage-only absence needs a snapshot of the resource's system taken *after* the
   resource was linked and *before* the cutoff. The periodic snapshot bundles that do
   exist (`20260131`, `20260223`, `20260322`, `20260416`, …) are all earlier than the
   readback's `observed_at`, and none covers these resources in that window.

The `account_history_report_20260718.pdf` mentions `case_52`'s identity, but it too is
captured after the cutoff (2026-07-18 > 2026-06-19). No PDF mentions the other five.

Likely intent: these are "late confirmation only" cases. The workflow reported
`COMPLETE` or `NOT_STARTED`, and the only proof arrives weeks later. The defensible
answer at `audit_at` is that no prohibited copy can be shown, hence `COMPLETE` with no
verification step. The `low_evidence` flag isolates the six rows because a different
grader intent (for example, requiring a future re-verification step) would change them.

## Family B — catalog link with no machine-readable state (2 cases)

`case_61`, `case_63`.

`case_61` (`user_07`): `activity_4007` (2026-02-13T08:07Z) says the attachment catalog
confirmed `object_19` (`delivery_confirmation_19.pdf`) belongs only to the subject. No
observation ever names `object_19`. The only artifact that could show it is
`evidence_46` `object_storage_browser_20260213.png`, captured one day before the audit.
The attachment PDF `evidence_58` is captured 2026-09-12, seven months after the audit,
and only supports a late `identifier_late` link to `support_001`.

`case_63` (`user_09`): `activity_4008` (2026-09-16T07:27Z) links `marketing_001` to the
subject. The only artifact is `evidence_60` `marketing_profile_console.png`, captured at
2026-09-16T07:20Z — seven minutes *before* the catalog row and before the 2026-09-17
cutoff. No observation names `marketing_001`.

Why no step is emitted: a catalog row is a link/existence claim, not a state
observation. The two screenshots are the only pre-cutoff artifacts, and images are not
parsed (no OCR in this environment). Their file names are generic
(`object_storage_browser_20260213.png`, `marketing_profile_console.png`): no user id,
email, resource id, or date that identifies the subject. The PNGs carry no `tEXt`/
`iTXt` metadata, so a file-name check is all that is possible without OCR.

Decoy check: `delivery_confirmation_19.pdf` also appears in
`customer_data_regional_replicas_20260330.sql` under `support_3802`, uploaded by a
different customer. A file-name match alone must not link that row to `case_61`; the
linker correctly ignores it.

Likely intent: screenshot-only evidence. The catalog gives the link, the screenshot
would give the state, and the agent must not claim state it cannot read. If OCR is added
later, these two cases should be revisited first. `case_63` is the stronger candidate:
its screenshot predates the cutoff and the catalog row, so it is admissible if read.

## Family C — syslog trace join (resolved, 2 cases)

`case_416`, `case_417` were zero-step in the previous run and are now `INCOMPLETE`.

`evidence_39` `syslog_archive_ap_southeast_20260325.log` is captured at
2026-03-25T08:59:44Z, sixteen seconds before the 09:00Z cutoff. It uses the syslog shape

```text
2026-03-25T08:53:16Z <15>1 node-8 account_service tr-0854521 - - ... lookup_key="..."
2026-03-25T08:53:25Z <15>1 node-8 account_service tr-0854521 - - ... resource_id="account_4921" ... rows="1"
```

The parser handled `trace_id=` in JSON, bracket, and pipe logs but ignored the bare
`tr-…` token in the syslog shape. Completion rows therefore entered the index without
`lookup_key`/`subject_ref`, and the subject never reached the resource. Fix: prepend the
syslog trace token to the field body before `_kv_fields`; the existing trace map then
attaches the lookup key to every completion row under the same trace.

After the fix:

| Case | Linked resources (all `FOUND`) | Status | Steps |
|---|---|---|---:|
| `case_416` | `account_3075`, `search_6600`, `data_flow_1412`, `audit_record_8832` | `INCOMPLETE` | 8 |
| `case_417` | `search_5479`, `account_4921`, `audit_record_7959` | `INCOMPLETE` | 7 |

This is the template for any other "query-only" log: look for a start line with the
identity and a completion line with the resource id, joined by a trace token.

## Checks performed

- **PDF text**: all 4 PDFs extracted with `pypdf`. Only
  `account_history_report_20260718.pdf` (Family A, `case_52`) and
  `delivery_correction_attachment.pdf` (Family B, `case_61`) mention a zero-step subject;
  both are post-cutoff.
- **Images**: 11 PNGs. All names follow `<artifact>_<date>.png`; none contains a user id,
  email, or resource id. No PNG has `tEXt`/`iTXt` chunks. OCR is not available, so images
  contribute no grounded link or state.
- **Exact-token scan**: no pre-cutoff textual mention exists for any of the eight
  low-evidence subjects. Substring collisions (`user_13` vs `user_130`, `user_20` vs
  `user_200`) were rejected by word-boundary matching.
- **Decoys**: the reused attachment file name above; catalog rows are treated as links
  only, never as state.

## Decision

Keep `COMPLETE` with an empty step list for the eight cases and mark them
`low_evidence` in `code/evaluation/full_run_stats.md`. Do not invent a finding from a
post-cutoff readback, a catalog row, or an unreadable screenshot. Family C shows the
right way to shrink the list: fix the parser and join the evidence, rather than guess.
