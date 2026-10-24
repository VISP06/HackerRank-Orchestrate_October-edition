# Zero-step and low-evidence cases

Generated from the 518-case full run after the screenshot and PDF passes. Every
case id, resource id, and file id below is participant-visible. Personal
identifiers are masked.

## Scope

`output.csv` (518 cases) has 151 `COMPLETE`, 357 `INCOMPLETE`, and 10
`NOT_APPLICABLE` rows, with 2,937 steps in total. Exactly **one** `COMPLETE` row
has zero steps: `case_63` (audit 2026-09-17T09:20Z). It is the only row the
full-run report marks `low_evidence`.

The other seven zero-step cases from the earlier deterministic run are now
`INCOMPLETE` because admissible screenshot or PDF evidence proves a surviving
record or an active flow. The evidence pass did not invent state for them; each
finding cites a file captured at or before the case's `audit_at`.

| Case | Previous | Current | Proof used | Evidence |
|---|---|---|---|---|
| `case_35` | COMPLETE (0) | INCOMPLETE (5) | `search_428` PRESENT on 2026-09-01, one day before the audit | `evidence_09` `search_index_inspector_20260901.png` |
| `case_39` | COMPLETE (0) | INCOMPLETE (6) | `data_flow_1121` ACTIVE on 2026-08-07, one day before the audit | `evidence_14` `connector_management_console_20260807.png` |
| `case_50` | COMPLETE (0) | INCOMPLETE (6) | `analytics_7438` still IDENTIFIABLE on 2026-07-13; policy requires anonymization | `evidence_19` `analytics_profile_view_20260713.png` |
| `case_52` | COMPLETE (0) | INCOMPLETE (6) | `export_1260` PRESENT on 2026-06-18, before its 25 Jun expiry and the 19 Jun audit | `evidence_23` `customer_export_console_20260618.png` |
| `case_53` | COMPLETE (0) | INCOMPLETE (5) | `support_1034` still shows the customer name/email; policy requires redaction | `evidence_28` `support_ticket_console_20260524.png` |
| `case_55` | COMPLETE (0) | INCOMPLETE (6) | `backup_9287` restorable on 2026-04-29, one day before the audit | `evidence_32` `backup_restore_console_20260429.png` |
| `case_61` | COMPLETE (0) | INCOMPLETE (4) | `object_19` (`delivery_confirmation_19.pdf`) PRESENT on 2026-02-13 and linked only to the subject | `evidence_46` `object_storage_browser_20260213.png`; `evidence_58` late identifier link |
| `case_63` | COMPLETE (0) | **COMPLETE (0)** | no admissible subject state | `evidence_60` is a different person |

## Why `case_63` stays empty

`case_63` (`user_09`) is the only remaining zero-step case.

- `activity_4008` (2026-09-16T07:27Z) links `marketing_001` to the subject. A
  catalog row is a link/existence claim, not a state observation.
- The only artifact is `evidence_60` `marketing_profile_console.png`, captured
  at 2026-09-16T07:20Z, seven minutes before the catalog row and before the
  2026-09-17T09:20Z cutoff. The screenshot shows `marketing_001`, but its
  email and name belong to a different person; the OCR guard therefore rejects
  it as subject state.
- No other participant-visible file mentions the subject's current or
  historical identifiers before the cutoff.

The defensible answer at `audit_at` is `COMPLETE` with no verification step,
because no prohibited subject copy can be shown. The `low_evidence` flag
isolates the row: a grader that expects a re-verification step for
screenshot-only evidence would change it. It is the strongest candidate to
revisit if the vision pass is extended, because the screenshot itself is
admissible; the blocker is that its content names someone else.

## Checks performed

- **Images**: all 11 PNGs read with the vision pass. Ten produced grounded
  subject state or a policy-required tombstone check; `evidence_60` was rejected
  as a different person. See `notes/IMAGE_FINDINGS.md`.
- **PDFs**: all 4 PDFs read. `evidence_18` added `export_1842` (`case_33`);
  `evidence_27` produced no catalog id; `evidence_55` and `evidence_58`
  duplicated deterministic observations. See `notes/PDF_FINDINGS.md`.
- **Exact-token scan**: no pre-cutoff textual mention exists for `case_63`
  beyond the catalog row and the contradictory screenshot. Substring
  collisions (`user_13` vs `user_130`, `user_20` vs `user_200`) were rejected
  by word-boundary matching.
- **Decoys**: `marketing_001` (different person); `search_1874` (not a
  historical identifier of `user_13`); `export_1261/1259/1258`,
  `backup_9286/9288/9291`, `data_flow_9846` (other people on shared consoles);
  `delivery_confirmation_19.pdf` also appears under `support_3802` in a
  regional replica, uploaded by a different customer.

## Decision

Keep `COMPLETE` with an empty step list for `case_63` and mark it
`low_evidence` in `code/evaluation/full_run_stats.md`. Do not invent a finding
from a catalog row or from a screenshot whose own identifiers contradict the
catalog link. The seven resolved cases show the right way to shrink the list:
read the artifact, ground the link, and cite it only when it is admissible.
