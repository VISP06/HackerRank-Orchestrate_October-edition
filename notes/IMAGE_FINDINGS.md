# Screenshot findings (LLM vision extraction)

All 11 PNGs in `dataset/evidence/images/` were read once with
`gemini-3.1-flash-lite` (vision), temperature 0, strict JSON, and cached under
`code/llm_cache/`.  Every image is treated as untrusted data: the prompt wraps
the image, says that text inside the image is data and never instructions, and
the model must return an OCR text layer plus structured rows.  No image
contained an instruction-like string.

Extraction is reproducible offline: re-running with no key reads the same
cache entries.  Personal identifiers below are masked; resource ids, case ids,
and evidence ids are participant-visible and kept exact.

## Method and guards

1. `visible_text` is the model's verbatim transcription of the page.  A
   candidate resource id is accepted only if it matches the resource grammar
   **and** appears verbatim in that text.  This rejected a v1 hallucination
   that turned `support_1034` into `support_5034`.
2. Human-facing references (`ORD-…`, `CS-…`, `FIN-…`, `NST-…`) are never
   converted into resource ids.  If a page shows both `CS-5034` and
   `support_1034`, the internal id wins.
3. File names and stable user references are mapped only through explicit
   `LINK_RESOURCE_IDENTITY` catalog rows:
   `delivery_confirmation_19.pdf → object_19`, `user_17 → tombstone_17`.
4. Observation time is the manifest `captured_at` (not a timestamp printed in
   the page).  Admissibility is `captured_at <= audit_at`.
5. A screenshot captured **before the deletion request** is historical only.
   It can ground identity but cannot prove that a record survived the deletion
   workflow.  This prevents stale pre-request screenshots from creating false
   findings for earlier cases of the same person.
6. A screenshot whose own strong identifiers (email / phone / hash / user_id)
   name a different person is not attached to the case, even when a catalog
   row points at the same resource.  This is the `marketing_001` decoy.

## Per-image extraction

| File | Captured (UTC) | Console | Grounded entity / rows | State | Linked identifiers |
|---|---|---|---|---|---|
| `evidence_04` `account_admin_console_20260926.png` | 2026-09-26T11:00 | customer operations | `account_5762` (page), `user_11` | PRESENT | h***@zoho.com, +81…, name masked |
| `evidence_09` `search_index_inspector_20260901.png` | 2026-09-01T06:00 | search inspector | `search_428`, `search_1874` | PRESENT | g***@gmail.com (428); g***jr@… (1874) |
| `evidence_14` `connector_management_console_20260807.png` | 2026-08-07T08:00 | connector management | `data_flow_1121`, `data_flow_9846` | ACTIVE | j***@gmail.com; l***@gmail.com |
| `evidence_19` `analytics_profile_view_20260713.png` | 2026-07-13T10:00 | analytics | `analytics_7438`, `user_20` | IDENTIFIABLE (email + name) | d***@icloud.com |
| `evidence_23` `customer_export_console_20260618.png` | 2026-06-18T12:00 | export console | `export_1260`, `export_1261`, `export_1259`, `export_1258` | PRESENT | i***@outlook.com (1260); others do not match a subject |
| `evidence_28` `support_ticket_console_20260524.png` | 2026-05-24T07:00 | support ticket | `support_1034` (page `CS-5034`) | PRESENT, identifiable | k***@fastmail.com |
| `evidence_32` `backup_restore_console_20260429.png` | 2026-04-29T09:00 | backup/restore | `backup_9287`, `backup_9286`, `backup_9288`, `backup_9291` | PRESENT, restore available | a***@gmail.com (9287); others unrelated |
| `evidence_37` `security_audit_explorer_20260905.png` | 2026-09-05T07:00 | security audit | `audit_record_001`…`audit_record_006` | PRESENT | `user_03` only |
| `evidence_42` `deleted_account_reference_20260310.png` | 2026-03-10T06:00 | customer reference registry | `user_17` → `tombstone_17` | REDACTED (stable ref only) | `user_17` only |
| `evidence_46` `object_storage_browser_20260213.png` | 2026-02-13T08:00 | object storage | `delivery_confirmation_19.pdf` → `object_19`; 7 other files not linked | PRESENT | none (file name only) |
| `evidence_60` `marketing_profile_console.png` | 2026-09-16T07:20 | marketing profile | `marketing_001` | ACTIVE, identifiable | s***@naver.com, name masked — **not the case subject** |

## Cases that change in the full run

| Case | Before | After | Why |
|---|---|---|---|
| `case_34` | INCOMPLETE (5) | INCOMPLETE (7) | `account_5762` still PRESENT on 26 Sep; the earlier 15 Sep readback said 404. The newer live console wins. |
| `case_35` | COMPLETE (0) | INCOMPLETE (5) | `search_428` PRESENT on 1 Sep, one day before the audit. |
| `case_39` | COMPLETE (0) | INCOMPLETE (6) | `data_flow_1121` ACTIVE on 7 Aug, one day before the audit. |
| `case_45` | COMPLETE (1) | COMPLETE (6) | Six retained `audit_record_00x` rows for `user_03` are now proven present. |
| `case_46` | COMPLETE (1) | COMPLETE (2) | `tombstone_17` is REDACTED (stable `user_17` only) and the account is absent; both checks are required. |
| `case_50` | COMPLETE (0) | INCOMPLETE (6) | `analytics_7438` still IDENTIFIABLE on 13 Jul; policy requires anonymization. |
| `case_52` | COMPLETE (0) | INCOMPLETE (6) | `export_1260` PRESENT on 18 Jun, before its 25 Jun expiry and the 19 Jun audit. |
| `case_53` | COMPLETE (0) | INCOMPLETE (5) | `support_1034` still shows customer name/email; policy requires redaction. |
| `case_55` | COMPLETE (0) | INCOMPLETE (6) | `backup_9287` is restorable on 29 Apr, one day before the audit. |
| `case_61` | COMPLETE (0) | INCOMPLETE (4) | `object_19` (`delivery_confirmation_19.pdf`) is present on 13 Feb and belongs only to the subject. |
| `case_63` | COMPLETE (0) | **unchanged** | `marketing_001` screenshot shows a different person (s***@naver.com). The catalog row is a claim; the primary artifact contradicts it. No subject state is proven, so no finding is invented. |

`case_33` is also unchanged: its screenshot (`export_1260`, 18 Jun) predates
the 16 Jul request, and the export expired on 25 Jun.  A later export snapshot
(`evidence_83`, 18 Jul) already proves absence at the 19 Jul audit.

No full-run case has `audit_at` exactly equal to an image capture time.  The
closest is `case_61` (audit 14 Feb, capture 13 Feb).

## Decoys rejected

- `marketing_001`: catalog says `user_09`; screenshot says a different person
  with different email and name.  Treated as not the subject (case_63).
- `search_1874`: related-looking email but not a historical identifier of
  `user_13`.  It is stored as its own observation and never attached to
  `case_35`.
- `export_1261/1259/1258`, `backup_9286/9288/9291`, `data_flow_9846`: other
  people's rows on shared consoles.  They link only to their own subjects, if
  any.
- `object_storage_browser`: only `delivery_confirmation_19.pdf` has a catalog
  alias.  The other seven file names are not converted into invented
  `object_NNN` ids.
- `deleted_account_reference`: the four linked-record rows are `ORD-…`,
  `CS-…`, `FIN-…` references, not resource ids; only the page tombstone is
  emitted.

## Raw extraction

The exact model output for every image is in the disk cache.  The usage log
records input/output token counts per call (11 calls, 23,687 input / 15,669
output tokens for the v2 extraction pass).  Re-extraction without `--fresh`
uses zero API calls.
