# Workflow-dispatch linking study

Measurement harness: `python3 code/evaluation/linking_study.py`. The sample answers are
used only to score candidate rules; no resource id is copied from them.

A rule is *applicable* only when the case has no identifier-linked resource of that family
(so a second copy is never invented). `recovered/available` is the share of expected
sample resources of that family that the rule retrieved. `wrong` counts links the sample
answer does not contain; `ambiguous` counts full-run cases where the rule rejected a
multi-candidate match.  The baseline excludes links made by the dispatch rule under
test, so each row measures what that rule would add on its own.

| Rule | Recovered/available | Accepted | Wrong | Ambiguous (full run) |
|---|---:|---:|---:|---:|
| `workflow_window:10:account_` | 6/16 | 6 | 0 | 53/253 |
| `workflow_window:10:analytics_` | 0/6 | 0 | 0 | 0/424 |
| `workflow_window:10:search_` | 0/0 | 0 | 0 | 8/235 |
| `workflow_window:10:support_` | 0/0 | 0 | 0 | 0/331 |
| `workflow_window:10:data_flow_` | 0/0 | 0 | 0 | 0/364 |
| `workflow_window:10:backup_` | 0/0 | 5 | 5 | 1/449 |
| `workflow_window:10:export_` | 0/0 | 0 | 0 | 0/477 |
| `workflow_window:10:tombstone_` | 0/0 | 0 | 0 | 0/499 |
| `workflow_window:15:account_` | 6/16 | 6 | 0 | 68/253 |
| `workflow_window:15:analytics_` | 0/6 | 0 | 0 | 0/424 |
| `workflow_window:15:search_` | 0/0 | 0 | 0 | 14/235 |
| `workflow_window:15:support_` | 0/0 | 0 | 0 | 0/331 |
| `workflow_window:15:data_flow_` | 0/0 | 4 | 4 | 1/364 |
| `workflow_window:15:backup_` | 0/0 | 5 | 5 | 1/449 |
| `workflow_window:15:export_` | 0/0 | 0 | 0 | 0/477 |
| `workflow_window:15:tombstone_` | 0/0 | 0 | 0 | 0/499 |
| `workflow_window:20:account_` | 6/16 | 6 | 0 | 68/253 |
| `workflow_window:20:analytics_` | 0/6 | 0 | 0 | 0/424 |
| `workflow_window:20:search_` | 0/0 | 0 | 0 | 24/235 |
| `workflow_window:20:support_` | 0/0 | 0 | 0 | 5/331 |
| `workflow_window:20:data_flow_` | 0/0 | 4 | 4 | 1/364 |
| `workflow_window:20:backup_` | 0/0 | 5 | 5 | 1/449 |
| `workflow_window:20:export_` | 0/0 | 0 | 0 | 0/477 |
| `workflow_window:20:tombstone_` | 0/0 | 0 | 0 | 0/499 |
| `workflow_window:30:account_` | 6/16 | 6 | 0 | 68/253 |
| `workflow_window:30:analytics_` | 1/6 | 6 | 5 | 66/424 |
| `workflow_window:30:search_` | 0/0 | 0 | 0 | 26/235 |
| `workflow_window:30:support_` | 0/0 | 5 | 5 | 12/331 |
| `workflow_window:30:data_flow_` | 0/0 | 4 | 4 | 1/364 |
| `workflow_window:30:backup_` | 0/0 | 5 | 5 | 1/449 |
| `workflow_window:30:export_` | 0/0 | 0 | 0 | 0/477 |
| `workflow_window:30:tombstone_` | 0/0 | 6 | 6 | 0/499 |
| `workflow_window:45:account_` | 5/16 | 5 | 0 | 68/253 |
| `workflow_window:45:analytics_` | 1/6 | 6 | 5 | 123/424 |
| `workflow_window:45:search_` | 0/0 | 0 | 0 | 28/235 |
| `workflow_window:45:support_` | 0/0 | 4 | 4 | 26/331 |
| `workflow_window:45:data_flow_` | 0/0 | 4 | 4 | 1/364 |
| `workflow_window:45:backup_` | 0/0 | 5 | 5 | 1/449 |
| `workflow_window:45:export_` | 0/0 | 1 | 1 | 0/477 |
| `workflow_window:45:tombstone_` | 0/0 | 4 | 4 | 0/499 |
| `workflow_window:60:account_` | 6/16 | 7 | 1 | 155/253 |
| `workflow_window:60:analytics_` | 1/6 | 7 | 6 | 132/424 |
| `workflow_window:60:search_` | 0/0 | 2 | 2 | 31/235 |
| `workflow_window:60:support_` | 0/0 | 11 | 11 | 39/331 |
| `workflow_window:60:data_flow_` | 0/0 | 4 | 4 | 3/364 |
| `workflow_window:60:backup_` | 0/0 | 5 | 5 | 4/449 |
| `workflow_window:60:export_` | 0/0 | 3 | 3 | 0/477 |
| `workflow_window:60:tombstone_` | 0/0 | 1 | 1 | 0/499 |
| `workflow_window:75:account_` | 6/16 | 6 | 0 | 237/253 |
| `workflow_window:75:analytics_` | 1/6 | 7 | 6 | 132/424 |
| `workflow_window:75:search_` | 0/0 | 6 | 6 | 68/235 |
| `workflow_window:75:support_` | 0/0 | 11 | 11 | 48/331 |
| `workflow_window:75:data_flow_` | 0/0 | 5 | 5 | 6/364 |
| `workflow_window:75:backup_` | 0/0 | 6 | 6 | 8/449 |
| `workflow_window:75:export_` | 0/0 | 3 | 3 | 0/477 |
| `workflow_window:75:tombstone_` | 0/0 | 0 | 0 | 2/499 |
| `workflow_window:90:account_` | 6/16 | 6 | 0 | 237/253 |
| `workflow_window:90:analytics_` | 1/6 | 5 | 4 | 160/424 |
| `workflow_window:90:search_` | 0/0 | 10 | 10 | 86/235 |
| `workflow_window:90:support_` | 0/0 | 11 | 11 | 72/331 |
| `workflow_window:90:data_flow_` | 0/0 | 5 | 5 | 6/364 |
| `workflow_window:90:backup_` | 0/0 | 6 | 6 | 8/449 |
| `workflow_window:90:export_` | 0/0 | 3 | 3 | 0/477 |
| `workflow_window:90:tombstone_` | 0/0 | 1 | 1 | 2/499 |
| `nearest_gap:60:10:account_` | 8/16 | 9 | 1 | - |
| `nearest_gap:60:20:account_` | 7/16 | 8 | 1 | - |
| `nearest_gap:60:30:account_` | 7/16 | 8 | 1 | - |
| `nearest_gap:90:10:account_` | 8/16 | 8 | 0 | - |
| `nearest_gap:90:20:account_` | 7/16 | 7 | 0 | - |
| `nearest_gap:90:30:account_` | 7/16 | 7 | 0 | - |
| `nearest_gap:120:10:account_` | 8/16 | 8 | 0 | - |
| `nearest_gap:120:20:account_` | 7/16 | 7 | 0 | - |
| `nearest_gap:120:30:account_` | 7/16 | 7 | 0 | - |
| `catalog_adjacency:60:1:account_` | 2/16 | 2 | 0 | - |
| `catalog_adjacency:60:2:account_` | 2/16 | 3 | 1 | - |
| `catalog_adjacency:60:3:account_` | 2/16 | 5 | 3 | - |
| `catalog_adjacency:60:5:account_` | 3/16 | 7 | 4 | - |
| `catalog_adjacency:60:8:account_` | 3/16 | 7 | 4 | - |
| `catalog_adjacency:90:1:account_` | 2/16 | 2 | 0 | - |
| `catalog_adjacency:90:2:account_` | 3/16 | 4 | 1 | - |
| `catalog_adjacency:90:3:account_` | 3/16 | 6 | 3 | - |
| `catalog_adjacency:90:5:account_` | 4/16 | 8 | 4 | - |
| `catalog_adjacency:90:8:account_` | 4/16 | 8 | 4 | - |
| `catalog_adjacency:120:1:account_` | 2/16 | 2 | 0 | - |
| `catalog_adjacency:120:2:account_` | 3/16 | 4 | 1 | - |
| `catalog_adjacency:120:3:account_` | 3/16 | 6 | 3 | - |
| `catalog_adjacency:120:5:account_` | 4/16 | 8 | 4 | - |
| `catalog_adjacency:120:8:account_` | 4/16 | 8 | 4 | - |

## Recovered examples (account / analytics windows)

- `workflow_window:15:account_` -> `case_01:['account_001']`
- `workflow_window:15:account_` -> `case_02:['account_002']`
- `workflow_window:15:account_` -> `case_06:['account_006']`
- `workflow_window:15:account_` -> `case_07:['account_007']`
- `workflow_window:15:account_` -> `case_08:['account_008']`
- `workflow_window:30:analytics_` -> `case_21:['analytics_5335']`

## Wrong-link examples

- `workflow_window:10:backup_`: `case_03:['backup_6266']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`; `case_25:['backup_3120']`
- `workflow_window:15:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:15:backup_`: `case_03:['backup_6266']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`; `case_25:['backup_3120']`
- `workflow_window:20:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:20:backup_`: `case_03:['backup_6266']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`; `case_25:['backup_3120']`
- `workflow_window:30:analytics_`: `case_09:['analytics_5718']`; `case_13:['analytics_037']`; `case_19:['analytics_3264']`; `case_20:['analytics_2265']`; `case_23:['analytics_5335']`
- `workflow_window:30:support_`: `case_03:['support_1066']`; `case_09:['support_6334']`; `case_20:['support_1097']`; `case_24:['support_4715']`; `case_25:['support_4715']`
- `workflow_window:30:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:30:backup_`: `case_03:['backup_6266']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`; `case_25:['backup_3120']`
- `workflow_window:30:tombstone_`: `case_14:['tombstone_440']`; `case_21:['tombstone_8774']`; `case_23:['tombstone_8774']`; `case_24:['tombstone_3963']`; `case_25:['tombstone_3963']`
- `workflow_window:45:analytics_`: `case_09:['analytics_5718']`; `case_13:['analytics_037']`; `case_19:['analytics_3264']`; `case_20:['analytics_2265']`; `case_23:['analytics_5335']`
- `workflow_window:45:support_`: `case_03:['support_1066']`; `case_09:['support_6334']`; `case_24:['support_4715']`; `case_25:['support_4715']`
- `workflow_window:45:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:45:backup_`: `case_03:['backup_6266']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`; `case_25:['backup_3120']`
- `workflow_window:45:export_`: `case_21:['export_7364']`
- `workflow_window:45:tombstone_`: `case_14:['tombstone_440']`; `case_24:['tombstone_3963']`; `case_25:['tombstone_3963']`; `case_26:['tombstone_3963']`
- `workflow_window:60:account_`: `case_28:['account_7012']`
- `workflow_window:60:analytics_`: `case_09:['analytics_5718']`; `case_13:['analytics_037']`; `case_16:['analytics_4440']`; `case_19:['analytics_3264']`; `case_20:['analytics_2265']`
- `workflow_window:60:search_`: `case_04:['search_6302']`; `case_21:['search_898']`
- `workflow_window:60:support_`: `case_03:['support_1066']`; `case_09:['support_6334']`; `case_14:['support_4887']`; `case_16:['support_835']`; `case_21:['support_1034']`
- `workflow_window:60:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:60:backup_`: `case_03:['backup_6266']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`; `case_25:['backup_3120']`
- `workflow_window:60:export_`: `case_13:['export_7689']`; `case_19:['export_1260']`; `case_21:['export_7364']`
- `workflow_window:60:tombstone_`: `case_14:['tombstone_440']`
- `workflow_window:75:analytics_`: `case_09:['analytics_5718']`; `case_13:['analytics_037']`; `case_16:['analytics_4440']`; `case_19:['analytics_3264']`; `case_20:['analytics_2265']`
- `workflow_window:75:search_`: `case_04:['search_6302']`; `case_14:['search_3200']`; `case_25:['search_5577']`; `case_26:['search_5577']`; `case_31:['search_3200']`
- `workflow_window:75:support_`: `case_03:['support_1066']`; `case_09:['support_6334']`; `case_14:['support_4887']`; `case_16:['support_835']`; `case_21:['support_1034']`
- `workflow_window:75:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_13:['data_flow_4713']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:75:backup_`: `case_03:['backup_6266']`; `case_13:['backup_7809']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`
- `workflow_window:75:export_`: `case_13:['export_7689']`; `case_19:['export_1260']`; `case_21:['export_7364']`
- `workflow_window:90:analytics_`: `case_09:['analytics_5718']`; `case_16:['analytics_4440']`; `case_19:['analytics_3264']`; `case_23:['analytics_5335']`
- `workflow_window:90:search_`: `case_04:['search_6302']`; `case_14:['search_3200']`; `case_15:['search_4882']`; `case_17:['search_4882']`; `case_25:['search_5577']`
- `workflow_window:90:support_`: `case_03:['support_1066']`; `case_09:['support_6334']`; `case_14:['support_4887']`; `case_16:['support_835']`; `case_21:['support_1034']`
- `workflow_window:90:data_flow_`: `case_03:['data_flow_223']`; `case_09:['data_flow_6846']`; `case_13:['data_flow_4713']`; `case_24:['data_flow_6244']`; `case_25:['data_flow_6244']`
- `workflow_window:90:backup_`: `case_03:['backup_6266']`; `case_13:['backup_7809']`; `case_18:['backup_7809']`; `case_20:['backup_7809']`; `case_24:['backup_3120']`
- `workflow_window:90:export_`: `case_13:['export_7689']`; `case_19:['export_1260']`; `case_21:['export_7364']`
- `workflow_window:90:tombstone_`: `case_10:['tombstone_3963']`

## Later-observation identity links

- Sample cases: accepted 6, correct 6, wrong 0, recovered 6/35
- Recovered: `case_09:['account_3960', 'audit_record_4902']`; `case_23:['audit_record_4128']`; `case_24:['audit_record_7095']`; `case_29:['audit_record_3954']`; `case_30:['audit_record_1707']`

## Decision

Production uses `WORKFLOW_FAMILIES = {account: DELETE_RECORD, analytics: ANONYMIZE_RECORD}`
with one tight 15-minute window. That row adds 6 correct account links and no wrong
link on the sample; 30 minutes adds nothing new, 45 loses one, and 60 adds one wrong
link. For analytics, 15 minutes adds nothing (the sample analytics copies are already
reached by identifier), while 30 minutes accepts 6 links of which 5 are wrong.
A widening 15->30->60->90 fallback was measured separately: 15 correct / 11 wrong
resource links, so it was rejected. The nearest-gap variant accepts 8 links, but in
5 of the 9 cases where it disagrees with the unique rule the nearest dispatch belongs
to another request in the same batch; it is rejected. Ambiguous dispatch batches are
never guessed.

