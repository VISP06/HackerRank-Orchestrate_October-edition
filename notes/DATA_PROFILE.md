# Data Profile: Ghost Data Still Exists

## 1. CSV Inventories & Distinct Categoricals
- `deletion_requests.csv`: 518 rows | `['case_id', 'email', 'requested_at', 'reported_status', 'reported_at', 'audit_at', 'request_text']`
- `sample_deletion_requests.csv`: 32 rows | Same columns as above
- `sample_output.csv` / `output.csv`: 32 rows / 0 rows (template) | `['case_id', 'deletion_status', 'steps_json']`
- `user_identities.csv`: 850 rows | `['user_id', 'name', 'email', 'phone', 'email_hash', 'updated_at']`
- `user_audit_log.csv`: 306 rows | `['audit_id', 'user_id', 'event_time', 'field_name', 'old_value', 'new_value']`
- `system_activity.csv`: 4011 rows | `['activity_id', 'event_time', 'event_type', 'source_system', 'target_system', 'resource_id', 'reported_result', 'details']`
- `evidence_files.csv`: 94 rows | `['file_id', 'file_path', 'origin', 'captured_at']`
- `deletion_rules.csv`: 15 rows | `['rule_id', 'data_category', 'condition', 'required_action']`

**Distinct Categorical Values:**
- `event_type` (17): ANONYMIZE_RECORD, BLOCK_RESTORE, CHECK_DATA_FLOW, CHECK_RESTORE_ACCESS, CLASSIFY_REQUEST, CREATE_EXPORT, DELETE_RECORD, DISABLE_DATA_FLOW, INDEX_RECORD, LINK_RESOURCE_IDENTITY, REDACT_RECORD, REFRESH_CACHE, RESTORE_BACKUP, RETAIN_RECORD, SEND_EMAIL, SYNC_RECORD, UPDATE_RECORD
- `reported_result` (3): FAILED, PARTIAL, SUCCESS
- `source_system` (11): account_service, backup_service, data_catalog, deletion_worker, export_service, integration_service, notification_service, privacy_intake, profile_service, security_service, support_platform
- `target_system` (19): account_failover_replica, account_replication_cluster, account_service, analytics_platform, archive_service, backup_service, cache_service, email_delivery_service, export_service, identity_service, integration_service, legal_service, marketing_platform, object_storage, object_store, privacy_case_management, search_service, security_service, support_platform
- `data_category` (15): ACCOUNT_TOMBSTONE, ANALYTICS_PROFILE, BACKUP_ARCHIVE, CACHE_ENTRY, EMAIL_DELIVERY_LOG, LEGAL_HOLD_RECORD, MARKETING_PROFILE, PRODUCT_TELEMETRY, SEARCH_INDEX_ENTRY, SECONDARY_IDENTIFIER, SECURITY_AUDIT_LOG, SUPPORT_ATTACHMENT, SUPPORT_MESSAGE, USER_EXPORT, USER_PROFILE
- `condition` (9): 'A supplied legal hold is active', 'Account is deleted and only a stable internal user_id is needed to preserve references to retained records', 'Always', 'Attachment belongs only to the deletion subject', 'Conversation contains shared customer, agent, or order context that must be retained', 'Log contains a user email address', 'Record is still attributable to a user', 'Record is within the supplied retention period', 'Restore access can be blocked'
- `required_action` (4): ANONYMIZE, DELETE, REDACT, RETAIN

**Full `deletion_rules.csv`:**
```csv
rule_id,data_category,condition,required_action
rule_01,USER_PROFILE,Always,DELETE
rule_02,SECONDARY_IDENTIFIER,Always,DELETE
rule_03,SEARCH_INDEX_ENTRY,Always,DELETE
rule_04,CACHE_ENTRY,Always,DELETE
rule_05,SUPPORT_MESSAGE,"Conversation contains shared customer, agent, or order context that must be retained",REDACT
rule_06,SUPPORT_ATTACHMENT,Attachment belongs only to the deletion subject,DELETE
rule_07,ANALYTICS_PROFILE,Record is still attributable to a user,ANONYMIZE
rule_08,PRODUCT_TELEMETRY,Record is still attributable to a user,ANONYMIZE
rule_09,USER_EXPORT,Always,DELETE
rule_10,MARKETING_PROFILE,Always,DELETE
rule_11,EMAIL_DELIVERY_LOG,Log contains a user email address,REDACT
rule_12,SECURITY_AUDIT_LOG,Record is within the supplied retention period,RETAIN
rule_13,LEGAL_HOLD_RECORD,A supplied legal hold is active,RETAIN
rule_14,BACKUP_ARCHIVE,Restore access can be blocked,RETAIN
rule_15,ACCOUNT_TOMBSTONE,Account is deleted and only a stable internal user_id is needed to preserve references to retained records,REDACT
```

## 2. SQL Snapshots & Table-to-Category Mapping
24 SQL files under `dataset/evidence/databases/` (SQLite compatible):
- **11 Inventory Snapshots** (`customer_data_inventory_*.sql`): captured monthly (Feb-Sep 2026). Contain cross-service tables: `customer_profiles`, `customer_search_documents`, `customer_analytics_profiles`, `support_records`, `customer_exports`, `connector_subscriptions`, `backup_restore_entries`, `security_audit_records`.
- **13 Replica Snapshots**: Failover, Read, Regional (`ap_south`, `eu_west`), and Reporting replicas.
- **Replica Representation**: Primary and replicas are represented as **distinct tables within the same SQLite database snapshot** (e.g., `customer_profiles_primary` vs `customer_profiles_failover_replica`; `customer_data_primary` vs `customer_data_reporting_replica`, `customer_data_read_replica`, `customer_data_replica_ap_south`, `customer_data_replica_eu_west`). Replication drift is verified by comparing row presence across these sibling tables.

| SQL Table Name | Columns | Mapped `data_category` |
|---|---|---|
| `customer_profiles` / `*_primary` / `*_failover_replica` | resource_id, user_id/customer_reference, full_name, email, phone, account_status, updated_at | `USER_PROFILE` / `ACCOUNT_TOMBSTONE` |
| `customer_search_documents` / `search_documents_primary` | resource_id, customer_reference, display_name, email, phone, email_hash, index_name, updated_at | `SEARCH_INDEX_ENTRY` |
| `customer_analytics_profiles` | resource_id, customer_reference, email, phone, email_hash, audience_cohort, updated_at | `ANALYTICS_PROFILE` |
| `support_records` | resource_id, customer_reference, requester_name, requester_email, requester_phone, message_excerpt, updated_at | `SUPPORT_MESSAGE` |
| `customer_exports` | resource_id, customer_reference, owner_email, owner_phone, object_key, updated_at | `USER_EXPORT` |
| `connector_subscriptions` | resource_id, customer_reference, customer_email, connector_name, enabled, last_delivery_status, updated_at | `DATA_FLOW` (active sync process) |
| `backup_restore_entries` | resource_id, customer_reference, customer_email, archive_key, restore_allowed, updated_at | `BACKUP_ARCHIVE` |
| `security_audit_records` | resource_id, subject_reference, event_code, retention_until, updated_at | `SECURITY_AUDIT_LOG` |
| `customer_data_*` (generic collections) | resource_id, origin_system, collection_name, record_json, updated_at | Polymorphic by collection_name |

## 3. JSON Records & Top-Level Structures
28 files in `dataset/evidence/records/` (27 JSON + 1 TXT shift handover):
1. **Multi-Service Snapshot Bundles** (`customer_data_snapshot_bundle_*.json`): Top-level `{"exported_at", "source", "snapshots": [...]}`. Each nested snapshot contains `{"captured_at", "data_store", "collection", "records": [...]}`.
2. **Per-Service Resource Exports** (`service_resource_export_*.json`): Top-level `{"exported_at", "region", "source", "service_exports": {...}}` where keys are system names (`account_service`, `analytics_platform`, `backup_service`, `export_service`, `integration_service`, `search_service`, `security_service`, `support_platform`).
3. **Dedicated Records**: `customer_analytics_report_*.json` (cohorts, metrics, direct identifiers), `connector_configurations_*.json` (recorded connectors, state), `customer_export_jobs_*.json`, `customer_export_manifest_*.json`, and `security_audit_ledger_*.json`.
- **Timestamps & Attributes**: Timestamps use ISO-8601 strings (`exported_at`, `captured_at`, `recorded_at`, `updated_at`). Connectors are indicated by `connector_name`, `enabled` (`true`/`false`), and `last_delivery_status`. Backups indicate restore risks with `archive_key`, `restore_allowed` or `eligible="true" deletion_block="false"`.

## 4. Log Signals & Format Patterns
26 files in `dataset/evidence/logs/` (`resource_lookup_trace_*.log`). Structured space-delimited and bracketed key-value logs:
- **Lookup 404 (Absent)**: `2026-07-28T05:51:21Z [INFO] [account_service] profile_lookup_completed: instance="account-5" resource_id="account_xxx" rows="0" http_status="404"`
- **Lookup 200 (Present)**: `2026-07-28T05:51:51Z [DEBUG] [account_service] profile_lookup_completed: instance="account-7" resource_id="account_xxx" rows="1" http_status="200" correlation_key="[EMAIL]"`
- **PII Scan (Exposed PII finding)**: `2026-07-28T05:51:41Z [WARN] [support_platform] message_pii_scan: instance="support-6" resource_id="support_xxx" matched_value="[EMAIL]" detector="direct_identifier"`
- **Search Index Hit (Remaining record)**: `2026-07-28T05:53:25Z [INFO] [search_service] index_query_completed: instance="search-6" resource_id="search_xxx" index="customer_directory_v3" result="hit"`
- **Connector Heartbeat (Active Data Flow)**: `2026-07-28T05:57:08Z [WARN] [integration_service] connector_heartbeat: instance="integration-1" resource_id="data_flow_xxx" enabled="true" scheduler_registered="true" last_run="success"`
- **Restore Policy Check (Restore Risk)**: `2026-07-28T05:56:08Z [ERROR] [backup_service] restore_candidate_evaluated: instance="backup-2" resource_id="backup_xxx" eligible="true" deletion_block="false"`
- **Security Audit Retention (Retained verification)**: `2026-09-26T09:40:29Z level=INFO service=security_service event=audit_record_read_completed resource_id="audit_record_xxx" rows=1 subject_reference="user_xx" retention_until="2034-09-30T23:59:59Z"`
- **Analytics Anonymization Check**: `2026-09-26T09:54:09Z level=INFO service=analytics_platform event=analytics_profile_read_completed resource_id="analytics_xxx" customer_reference=null email=null phone=null`

## 5. PDFs & Images
**PDFs (4 files under `dataset/evidence/documents/`):**
- `account_history_report_20260718.pdf` (2 pages): Customer order statement (NST-2026-0718-1842) for user_18; contains delivery address, items, payment card ending 4821, paid billing status.
- `delivery_correction_attachment.pdf` (2 pages): Support ticket attachment (CS-4827 / support_001) with customer name, phone, email, and requested delivery address change.
- `legal_retention_register_20260529.pdf` (2 pages): Finance Operations Disputed Orders & Tax Records Register. Orders ORD-20264118 (user_08) and ORD-20264207 (user_12) flagged for 7-year retention (until May 2033).
- `security_retention_extract.pdf` (1 page): Compliance journal signed entry (CJX-20260905-0630) confirming `audit_record_003` for user_03 must be retained until 2027-08-25.

**Images (11 PNG files under `dataset/evidence/images/`):**
- `account_admin_console_20260926.png` (124,989 B) | `analytics_profile_view_20260713.png` (129,362 B)
- `backup_restore_console_20260429.png` (155,587 B) | `connector_management_console_20260807.png` (130,271 B)
- `customer_export_console_20260618.png` (134,597 B) | `deleted_account_reference_20260310.png` (136,696 B)
- `marketing_profile_console.png` (129,711 B) | `object_storage_browser_20260213.png` (154,193 B)
- `search_index_inspector_20260901.png` (121,101 B) | `security_audit_explorer_20260905.png` (147,699 B)
- `support_ticket_console_20260524.png` (135,008 B)

## 6. Evidence-ID Consistency Check
| Evidence ID | Path & Origin | Captured At | Citing Cases & `audit_at` | Latest File at/before `audit_at`? |
|---|---|---|---|---|
| `evidence_54` | `evidence/databases/customer_accounts_failover_replica_20260902.sql` (`customer_account_failover_replica_capture`) | 2026-09-02T23:00:00Z | `case_01` (09-03 11:30), `case_02` (09-04 15:00), `case_04` (09-07 10:20), `case_05` (09-08 13:40) | **Yes** (Only capture of this replica) |
| `evidence_56` | `evidence/records/customer_analytics_report_20260907.json` (`analytics_platform`) | 2026-09-07T09:45:00Z | `case_04` (09-07 10:20) | **Yes** (Captured 35m before audit cutoff) |
| `evidence_94` | `evidence/logs/resource_lookup_trace_20260926_103856.log` (`service_readback_logs`) | 2026-09-26T10:38:56Z | `case_03` (09-26 11:00), `case_18` (09-26 11:00), `case_20` (09-26 11:00) | **Yes** (Latest in 11-log trace series at or before audit) |

**Conclusion:** In all sample cases, cited evidence is strictly the latest relevant evidence file captured at or before `audit_at`.

## 7. Reverse-Engineered Logic & Grounding
- **`case_01` (COMPLETE)**:
  - Step 1: `VERIFY_RECORD_ABSENT` on `account_service / account_001` -> `evidence_54` proves `account_001` is absent from both `customer_profiles_primary` and `customer_profiles_failover_replica`.
- **`case_05` (INCOMPLETE)**:
  - Step 1: `REPORT_REMAINING_RECORD` on `account_service / account_005` -> `evidence_54` proves replication drift: `account_005` was deleted from primary but remained in `customer_profiles_failover_replica`.
  - Step 2: `DELETE_RECORD` on `account_service / account_005` (Remediation, `evidence_id: ""`).
  - Step 3: `VERIFY_RECORD_ABSENT` on `account_service / account_005` (Post-remediation verification, `evidence_id: ""`).
- **`case_11` (INCOMPLETE - 14 Steps)**:
  - Grounded in `evidence_03` (`customer_account_handover_20261001.txt`):
    - Finding 1: `REPORT_REMAINING_RECORD` on `search_service / search_052` (`search_service | search_052 | FOUND`).
    - Finding 2: `REPORT_EXPOSED_PII` on `analytics_platform / analytics_2034` (`IDENTIFIABLE`).
    - Finding 3: `REPORT_EXPOSED_PII` on `support_platform / support_864` (`IDENTIFIABLE`).
    - Finding 4: `REPORT_ACTIVE_DATA_FLOW` on `integration_service / data_flow_9522` (`DATA_FLOW | ACTIVE`).
  - Remediation (ordered: active flows first, then deletions/redactions/anonymizations):
    - Step 5: `DISABLE_DATA_FLOW`, Step 6: `DELETE_RECORD`, Step 7: `REDACT_RECORD`, Step 8: `ANONYMIZE_RECORD`.
  - Verification: covers remediated records + already compliant records (`account_4248` absent, `audit_record_9394` retained).
- **Inferred Rules**:
  1. For `COMPLETE`, include ONLY verification steps, each citing a valid `evidence_id`.
  2. For `INCOMPLETE`, include all findings (with `evidence_id`), full remediation plan (`evidence_id=""`), and post-remediation verifications (`evidence_id=""`).
  3. Ordering strictly adheres to: `FINDING` -> `REMEDIATION` -> `VERIFICATION`; within phase by operation table order; tie-broken by `system_id` ASC, then `resource_id` ASC.

## 8. Non-Deletion Requests & Detection
Scanning all 518 evaluation requests in `deletion_requests.csv` reveals **exactly 10 non-deletion requests** (`case_533` to `case_542`, all reported as `NOT_STARTED`):
1. `case_533`: "The mobile number on my profile is out of date. Please replace it with the new one and leave the account active." (Correction)
2. `case_534`: "Please stop the promotional emails. I still need the account and my order history, so I am not asking for deletion." (Opt-out)
3. `case_535`: "I'd like to download my account information in a portable format. Please keep the account as it is." (Export/Portability)
4. `case_536`: "I can't access my profile and need help resetting the login. Do not close the account." (Access/Support)
5. `case_537`: "My surname is misspelled on the account. Can you correct it without removing any of my records?" (Correction)
6. `case_538`: "Please remove me from marketing lists only. I still want receipts and service messages for this account." (Opt-out)
7. `case_539`: "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it." (Access)
8. `case_540`: "I need a copy of last year's invoices for my records. Please leave my profile and purchase history in place." (Export)
9. `case_541`: "Please change the email address used for this account. I want to continue using the service." (Correction)
10. `case_542`: "Could you send me a copy of the information held on my account? I still use it, so please don't delete or change anything." (Access/Export)
- **Detection Method**: Multilingual intent classification rule: flag requests expressing retention intent ("leave active", "keep account", "don't delete", "not asking for deletion", "information request") or specific non-deletion rights (marketing opt-out, access, rectification). Mark status as `NOT_APPLICABLE` and emit `steps_json=[]`.

## 9. Review of PROJECT_STATE.md (Sections 4b & 4c)
- **4b Submission URL Note vs AGENTS.md Conflict**: PROJECT_STATE.md §4b notes `AGENTS.md has a typo-looking submission URL (wwww.): use the link from the HackerRank challenge page, not the one in AGENTS.md`. However, AGENTS.md §4.1 contains a strict, mandatory instruction requiring the exact URL (`https://wwww...`) to be printed whenever asked.
- **4b Language Diversity**: 4b states requests can be in any language. The 518 dataset cases contain only **English (492)** and **Portuguese (26)** (`Solicito a exclusão...`).
- **4c Case Sorting**: 4c asks how IDs mixing 2 and 3 digits affect "sorted by case_id". In `deletion_requests.csv`, rows are sorted **naturally / numerically** (`case_33` .. `case_550`), not lexicographically (`case_100` before `case_33`).
- **4c Verification Kinds**: Correctly identified; must also include `VERIFY_RECORD_REDACTED` (for support messages / tombstones) and `VERIFY_DATA_FLOW_DISABLED` / `VERIFY_RESTORE_BLOCKED`.
- **4c Replication Representation**: Replicas are distinct tables within the same SQLite snapshot file, not separate schema attachments.


## 10. System Activity Event Types & Details Analysis
The 4,011 rows in `system_activity.csv` span 17 event types. Across all 17 types, **only `LINK_RESOURCE_IDENTITY` explicitly links a `resource_id` to a `user_id`, email, or hash in `details`** (12 occurrences). All other events reference `resource_id` directly, with some operational events (`RESTORE_BACKUP`, `SYNC_RECORD`) naming downstream affected resources.

| Event Type (Count) | 2 Masked Example Rows (`activity_id`, `source` -> `target`, `resource_id`, `result`, `details`) | What `details` Conveys & Focus Notes |
|---|---|---|
| `ANONYMIZE_RECORD` (204) | 1. `activity_19` \| `deletion_worker` -> `analytics_platform` \| `analytics_7277` \| `SUCCESS` \| "Policy action completed for analytics_7277."<br>2. `activity_80` \| `deletion_worker` -> `analytics_platform` \| `analytics_4804` \| `SUCCESS` \| "Policy action completed for analytics_4804." | Confirms deletion worker executed anonymization on analytics or telemetry record. Does not link user directly. |
| `BLOCK_RESTORE` (36) | 1. `activity_96` \| `deletion_worker` -> `backup_service` \| `backup_6344` \| `SUCCESS` \| "Policy action completed for backup_6344."<br>2. `activity_323` \| `deletion_worker` -> `backup_service` \| `backup_7706` \| `SUCCESS` \| "Policy action completed for backup_7706." | Confirms deletion block applied to backup archive to prevent restoration. |
| `CHECK_DATA_FLOW` (89) | 1. `activity_48` \| `deletion_worker` -> `integration_service` \| `data_flow_3518` \| `SUCCESS` \| "Connector status check confirmed that data flow data_flow_3518 remains enabled."<br>2. `activity_131` \| `deletion_worker` -> `integration_service` \| `data_flow_9556` \| `SUCCESS` \| "Connector status check confirmed that data flow data_flow_9556 remains enabled." | **Focus**: Records audit verification that an active connector/sync process is still enabled (identifying active data flow risk). |
| `CHECK_RESTORE_ACCESS` (28) | 1. `activity_49` \| `deletion_worker` -> `backup_service` \| `backup_8264` \| `SUCCESS` \| "Restore-access check confirmed that archive backup_8264 can still be restored."<br>2. `activity_97` \| `deletion_worker` -> `backup_service` \| `backup_3382` \| `SUCCESS` \| "Restore-access check confirmed that archive backup_3382 can still be restored." | **Focus**: Records audit verification that backup archive is still eligible for restore (identifying restore risk). |
| `CLASSIFY_REQUEST` (10) | 1. `activity_3486` \| `privacy_intake` -> `privacy_case_management` \| `account_2461` \| `SUCCESS` \| "Privacy intake classified request for account_2461 as non-deletion; no destructive action was authorized."<br>2. `activity_3512` \| `privacy_intake` -> `privacy_case_management` \| `account_2176` \| `SUCCESS` \| "Privacy intake classified request for account_2176 as non-deletion; no destructive action was authorized." | **Focus**: Explicitly flags requests as non-deletion (`NOT_APPLICABLE`). The 10 entries correspond 1:1 with cases `case_533` to `case_542`. |
| `CREATE_EXPORT` (155) | 1. `activity_28` \| `export_service` -> `object_store` \| `export_388` \| `SUCCESS` \| "Scheduled account export processed export_388."<br>2. `activity_43` \| `export_service` -> `object_store` \| `export_5603` \| `SUCCESS` \| "Scheduled account export processed export_5603." | Records creation of user export archives in object store. |
| `DELETE_RECORD` (890) | 1. `activity_18` \| `deletion_worker` -> `account_service` \| `account_1482` \| `SUCCESS` \| "Deletion worker submitted primary profile account_1482 to account_service."<br>2. `activity_45` \| `deletion_worker` -> `account_service` \| `account_4979` \| `FAILED` \| "Deletion worker submitted primary profile account_4979 to account_service." | Reports deletion workflow dispatch and claimed result (SUCCESS/FAILED) across primary or downstream stores. |
| `DISABLE_DATA_FLOW` (36) | 1. `activity_95` \| `deletion_worker` -> `integration_service` \| `data_flow_6987` \| `SUCCESS` \| "Policy action completed for data_flow_6987."<br>2. `activity_322` \| `deletion_worker` -> `integration_service` \| `data_flow_2893` \| `SUCCESS` \| "Policy action completed for data_flow_2893." | Confirms connector pipeline or webhook synchronization was disabled. |
| `INDEX_RECORD` (400) | 1. `activity_01` \| `account_service` -> `search_service` \| `search_9729` \| `SUCCESS` \| "Customer search-index refresh processed search_9729."<br>2. `activity_02` \| `account_service` -> `search_service` \| `search_6919` \| `SUCCESS` \| "Customer search-index refresh processed search_6919." | Conveys search index document ingestion/refresh from account service. |
| `LINK_RESOURCE_IDENTITY` (12) | 1. `activity_4000` \| `data_catalog` -> `account_service` \| `account_5762` \| `SUCCESS` \| "Data catalog linked account_5762 (account_5762) to [EMAIL] and user_11."<br>2. `activity_4001` \| `data_catalog` -> `search_service` \| `search_428` \| `SUCCESS` \| "Data catalog linked search_428 (search_428) to [EMAIL] and user_13." | **Focus**: **Only event linking resource to identity.** Explicitly bridges `resource_id` with `user_id` and `email` across cataloged resources (`account`, `search`, `data_flow`, `analytics`, `export`, `support`, `backup`, `object`, `marketing`, `audit_record`, `tombstone`). |
| `REDACT_RECORD` (173) | 1. `activity_50` \| `deletion_worker` -> `support_platform` \| `support_9251` \| `FAILED` \| "Deletion worker received the final result for support_9251 from support_platform."<br>2. `activity_94` \| `deletion_worker` -> `support_platform` \| `support_7724` \| `SUCCESS` \| "Policy action completed for support_7724." | Reports redaction execution on support tickets or delivery logs. |
| `REFRESH_CACHE` (284) | 1. `activity_27` \| `account_service` -> `cache_service` \| `cache_9558` \| `SUCCESS` \| "Profile cache refresh processed cache_9558."<br>2. `activity_31` \| `account_service` -> `cache_service` \| `cache_5395` \| `SUCCESS` \| "Profile cache refresh processed cache_5395." | Conveys cache store population from account service. |
| `RESTORE_BACKUP` (1) | 1. `activity_3387` \| `backup_service` -> `search_service` \| `backup_9287` \| `SUCCESS` \| "Restore job repopulated downstream resource search_4882." | Conveys active recreation event: restore operation repopulated a downstream resource (`search_4882`) from a backup archive. |
| `RETAIN_RECORD` (206) | 1. `activity_06` \| `security_service` -> `archive_service` \| `audit_record_7206` \| `SUCCESS` \| "Security-event archival processed audit_record_7206."<br>2. `activity_26` \| `security_service` -> `archive_service` \| `audit_record_163` \| `SUCCESS` \| "Security-event archival processed audit_record_163." | **Focus**: Records archival transfer of security audit logs for compliance retention (supporting `rule_12`). |
| `SEND_EMAIL` (368) | 1. `activity_08` \| `notification_service` -> `email_delivery_service` \| `email_delivery_354` \| `SUCCESS` \| "Transactional email delivery processed email_delivery_354."<br>2. `activity_09` \| `notification_service` -> `email_delivery_service` \| `email_delivery_9741` \| `PARTIAL` \| "Transactional email delivery processed email_delivery_9741." | Reports outbound transactional notifications. |
| `SYNC_RECORD` (447) | 1. `activity_12` \| `account_service` -> `analytics_platform` \| `analytics_1390` \| `SUCCESS` \| "Customer profile synchronization processed analytics_1390."<br>2. `activity_3434` \| `integration_service` -> `search_service` \| `data_flow_1121` \| `SUCCESS` \| "Active connector repopulated downstream resource search_4801." | Conveys synchronization pipelines between systems; highlights data flow recreation when connectors repopulate downstream stores. |
| `UPDATE_RECORD` (672) | 1. `activity_04` \| `support_platform` -> `search_service` \| `support_4185` \| `SUCCESS` \| "Support-case index update processed support_4185."<br>2. `activity_05` \| `profile_service` -> `account_service` \| `account_2689` \| `FAILED` \| "Profile preference update processed account_2689." | Conveys routine record updates and metadata syncs across platforms. |

## 11. End-to-End User-to-Resource Linking Traces & General Algorithm

### Trace for Sample Cases
1. **`case_01` (COMPLETE)**:
   - Request email `[EMAIL]` resolves directly in `user_identities.csv` to `user_01`.
   - Baseline account mapping pairs `user_01` with `account_001` (also confirmed by deletion submission `activity_3342`).
   - At `audit_at` (2026-09-03), latest relevant evidence is `evidence_54` (`customer_accounts_failover_replica_20260902.sql`).
   - Querying `customer_profiles_primary` and `customer_profiles_failover_replica` returns 0 rows for `account_001` / `user_01`.
   - Output: 1 step (`VERIFY_RECORD_ABSENT` on `account_service / account_001`, `evidence_54`).
2. **`case_04` (COMPLETE)**:
   - Request email `[EMAIL]` resolves in `user_identities.csv` to `user_04`.
   - `account_004` is verified absent in `evidence_54` (0 rows in primary and failover replica).
   - In `system_activity.csv`, `activity_3463` reports `ANONYMIZE_RECORD` on `analytics_901`.
   - At `audit_at` (2026-09-07T10:20:00Z), `evidence_56` (`customer_analytics_report_20260907.json`, captured 09:45:00Z) contains `analytics_901` with `user_id: null`, `email: null`, `phone: null`, `email_hash: null`.
   - Output: 2 verification steps (`account_004` absent via `evidence_54`, `analytics_901` anonymized via `evidence_56`).
3. **`case_05` (INCOMPLETE)**:
   - Request email `[EMAIL]` resolves in `user_identities.csv` to `user_05`.
   - Target resource is `account_005`.
   - In `evidence_54` (`customer_accounts_failover_replica_20260902.sql`), `customer_profiles_primary` has 0 rows (deleted), but `customer_profiles_failover_replica` contains an active row with `resource_id='account_005'`, `user_id='user_05'`, full name, email, and phone.
   - Proves replication drift.
   - Output: 3 steps (Finding: `REPORT_REMAINING_RECORD` with `evidence_54`; Remediation: `DELETE_RECORD`; Future Verification: `VERIFY_RECORD_ABSENT`).
4. **`case_11` (INCOMPLETE)**:
   - Request email `[EMAIL]` resolves in `user_identities.csv` to `user_32`.
   - At `audit_at` (2026-10-01T12:00:00Z), latest evidence is `evidence_03` (`customer_account_handover_20261001.txt`).
   - `evidence_03` directly maps user identifiers across 6 resources:
     - `[EMAIL]` -> `search_service | search_052 | SEARCH_INDEX_ENTRY | FOUND` (`REPORT_REMAINING_RECORD`)
     - `[EMAIL]` -> `analytics_platform | analytics_2034 | ANALYTICS_PROFILE | IDENTIFIABLE` (`REPORT_EXPOSED_PII`)
     - `[EMAIL]` -> `support_platform | support_864 | SUPPORT_MESSAGE | IDENTIFIABLE` (`REPORT_EXPOSED_PII`)
     - `[EMAIL]` -> `integration_service | data_flow_9522 | DATA_FLOW | ACTIVE` (`REPORT_ACTIVE_DATA_FLOW`)
     - `[EMAIL]` -> `account_service | account_4248 | USER_PROFILE | NOT_FOUND` (`VERIFY_RECORD_ABSENT`)
     - `user_32` -> `security_service | audit_record_9394 | SECURITY_AUDIT_LOG | FOUND` (`VERIFY_RECORD_PRESENT`)
   - Output: 14 steps (4 Findings with `evidence_03` -> 4 Remediation steps with `""` -> 6 Verification steps with `""`).

### General Linking Algorithm
1. **Identifier Resolution**:
   - Match request `email` against `user_identities.csv` (`email`) and `user_audit_log.csv` (`old_value` where `field_name='email'`).
   - Extract the full identity cluster: canonical `user_id`, current and former emails, current and former phone numbers, names, and `email_hash` values.
2. **Catalog / Activity Discovery**:
   - Query `system_activity.csv` for `LINK_RESOURCE_IDENTITY` events matching any identifier in the cluster to retrieve cataloged `resource_id`s.
   - Query `system_activity.csv` for workflow events dispatching operations on resources linked to the request window.
3. **Evidence Scanning at or before `audit_at`**:
   - Identify candidate evidence files with `captured_at <= audit_at`.
   - **SQL**: Search tables by `user_id`, `customer_reference`, `subject_reference`, `email`, `phone`, `email_hash`.
   - **JSON / Text / Logs**: Match records against all resolved emails, phone strings, hashes, and `user_id`s.
4. **Baseline Resource Conventions**:
   - For primary account profiles without overrides, canonical resource mapping aligns `user_{NNN}` to `account_{NNN}`.

## 12. Resource ID Prefix to System & Data Category Mapping

| Resource Prefix | System ID | Data Category | Evidence Types | Ambiguities & Edge Cases |
|---|---|---|---|---|
| `account_` | `account_service` | `USER_PROFILE` / `ACCOUNT_TOMBSTONE` | SQL, JSON, Logs, Text | **Ambiguity**: Baseline profiles require deletion (`rule_01`), but tombstoned accounts require redaction (`rule_15`). Verified absent via SQL/JSON/log 404. |
| `analytics_` | `analytics_platform` | `ANALYTICS_PROFILE` / `PRODUCT_TELEMETRY` | JSON, SQL, Logs, Text | **Ambiguity**: Policy requires `ANONYMIZE` (`rule_07`/`rule_08`), but some historical workflows issued `DELETE_RECORD` (e.g. `case_12`). Must verify identifiers are nulled. |
| `audit_record_` | `security_service` | `SECURITY_AUDIT_LOG` | SQL, JSON, Logs, Text, PDF | Retained under `rule_12` if retention period unexpired. Verification requires `VERIFY_RECORD_PRESENT`. |
| `backup_` | `backup_service` | `BACKUP_ARCHIVE` | SQL, JSON, Logs, Text | Retained under `rule_14` only if restore access is blocked (`restore_allowed=false`, `deletion_block=true`). Unblocked archives trigger `REPORT_RESTORE_RISK`. |
| `cache_` | `cache_service` | `CACHE_ENTRY` | JSON, Logs | `rule_04`: Always `DELETE`. Transient entries refreshed from account service. |
| `data_flow_` | `integration_service` | `DATA_FLOW` (Active Sync) | SQL, JSON, Logs, Text | Active connectors (`enabled=true`) trigger `REPORT_ACTIVE_DATA_FLOW`. Remediation requires `DISABLE_DATA_FLOW` before downstream record cleanup. |
| `email_delivery_` | `email_delivery_service` | `EMAIL_DELIVERY_LOG` | Logs, JSON | `rule_11`: Requires `REDACT` when containing user email. |
| `export_` | `export_service` | `USER_EXPORT` | SQL, JSON, Text, PDF | `rule_09`: Always `DELETE`. PII archive files in object storage. |
| `legal_hold_` | `legal_service` | `LEGAL_HOLD_RECORD` | PDF, SQL, JSON | `rule_13`: Retained while legal hold is active (`VERIFY_RECORD_PRESENT`). |
| `marketing_` | `marketing_platform` | `MARKETING_PROFILE` | JSON, SQL, Logs | `rule_10`: Always `DELETE`. Unsubscribing alone is insufficient; full marketing profile must be erased. |
| `object_` | `object_storage` / `support_platform` | `SUPPORT_ATTACHMENT` / `USER_EXPORT` | PDF, JSON, Activity | **Ambiguity**: Shared attachments vs user-only attachments (`rule_06`: DELETE only if belonging solely to deletion subject). |
| `search_` | `search_service` | `SEARCH_INDEX_ENTRY` | SQL, JSON, Logs, Text | `rule_03`: Always `DELETE`. High recreation risk via upstream connector `SYNC_RECORD`. |
| `support_` | `support_platform` | `SUPPORT_MESSAGE` / `SUPPORT_ATTACHMENT` | SQL, JSON, Logs, Text, PDF | **Ambiguity**: Conversation text requires `REDACT` when shared order/agent context exists (`rule_05`), but standalone user attachments require `DELETE` (`rule_06`). |
| `tombstone_` | `identity_service` | `ACCOUNT_TOMBSTONE` | JSON, SQL, Activity | `rule_15`: `REDACT`. Preserves stable user identifier while stripping direct PII. Residual PII triggers `REPORT_EXPOSED_PII`. |

## 13. Evidence Manifest vs. Disk Files Audit
- **Manifest File Count**: 94 rows in `dataset/evidence_files.csv`.
- **Disk File Count**: 94 files under `dataset/evidence/`.
- **Mismatches**: **0 mismatches**. Every file declared in `evidence_files.csv` exists at the exact path on disk, and no undeclared files exist on disk.
- **Physical Breakdown**:
  - `databases/`: 24 `.sql` snapshots (11 inventories, 13 replicas)
  - `records/`: 27 `.json` resource snapshots + 1 `.txt` shift handover
  - `logs/`: 26 `.log` trace files
  - `images/`: 11 `.png` console captures
  - `documents/`: 4 `.pdf` documents
  - Root: 1 `.csv` manifest

## 14. Evidence-ID Rules Verification Across Sample Cases
All 32 sample cases in `sample_output.csv` (75 total cited steps) were validated:
1. **Temporal Constraint (`captured_at <= audit_at`)**:
   - **0 violations** (75 / 75 cited steps strictly adhere to `captured_at <= audit_at`).
2. **Resource-ID Containment**:
   - **71 steps (94.7%)** explicitly contain the step's `resource_id` within the cited evidence file.
   - **4 steps (5.3%)** do not contain the string literal of `resource_id`. In all 4 instances (`case_01`, `case_02`, `case_04`, `case_31`), the step is `VERIFY_RECORD_ABSENT` on `account_service`. The cited database snapshot or snapshot bundle proves that the record was removed (query returns 0 rows), confirming compliant deletion.
3. **Distribution of Cited File Types (75 cited steps)**:
   - `.json`: 42 steps (56.0%)
   - `.log`: 15 steps (20.0%)
   - `.sql`: 10 steps (13.3%)
   - `.txt`: 7 steps (9.3%)
   - `.pdf`: 1 step (1.3%)
   - `.png`: 0 steps (0.0%)

## 15. Language Verification in `deletion_requests.csv`
A complete re-verification of all 518 evaluation requests in `deletion_requests.csv` reveals **6 distinct languages** (correcting the earlier hypothesis in Section 9 that only English and Portuguese were present):
- **English**: 456 cases (446 deletion requests + 10 non-deletion requests in `case_533` to `case_542`)
- **Portuguese**: 14 cases (`case_54`, `case_93`, `case_132`, ...)
- **Spanish**: 12 cases (`case_69`, `case_108`, `case_147`, ...)
- **French**: 12 cases (`case_84`, `case_123`, `case_162`, ...)
- **Korean**: 12 cases (`case_66`, `case_105`, `case_144`, ...)
- **Japanese**: 12 cases (`case_78`, `case_117`, `case_156`, ...)

### 3 Masked Examples per Requested Language:
1. **Spanish (`es`)**:
   - `[case_69]`: "Solicito la eliminación permanente de la cuenta asociada a este correo. Revisen los identificadores actuales y anteriores según su política de privacidad. Por favor, confirmen el resultado cuando termine la revisión."
   - `[case_108]`: "Solicito la eliminación permanente de la cuenta asociada a este correo. Revisen los identificadores actuales y anteriores según su política de privacidad. Por favor, confirmen el resultado cuando termine la revisión."
   - `[case_147]`: "Solicito la eliminación permanente de la cuenta asociada a este correo. Revisen los identificadores actuales y anteriores según su política de privacidad. Por favor, confirmen el resultado cuando termine la revisión."
2. **French (`fr`)**:
   - `[case_84]`: "Je demande la suppression définitive du compte associé à cette adresse e-mail. Veuillez examiner les identifiants actuels et antérieurs conformément à votre procédure de confidentialité. Merci de confirmer le résultat une fois la vérification terminée."
   - `[case_123]`: "Je demande la suppression définitive du compte associé à cette adresse e-mail. Veuillez examiner les identifiants actuels et antérieurs conformément à votre procédure de confidentialité. Merci de confirmer le résultat une fois la vérification terminée."
   - `[case_162]`: "Je demande la suppression définitive du compte associé à cette adresse e-mail. Veuillez examiner les identifiants actuels et antérieurs conformément à votre procédure de confidentialité. Merci de confirmer le résultat une fois la vérification terminée."
3. **English (`en`)**:
   - `[case_33]`: "Please close my account and process the associated personal-data deletion. Please handle any copies that fall within the scope of the deletion request. Please confirm when the review is complete."
   - `[case_34]`: "I would like the account associated with this address to be erased. Please handle any copies that fall within the scope of the deletion request. Please contact me if you need information to verify the request."
   - `[case_35]`: "Please close my account and process the associated personal-data deletion. Please check the records connected to the account before confirming completion. Please contact me if you need information to verify the request."
4. **Portuguese (`pt`)**:
   - `[case_54]`: "Solicito a exclusão permanente da conta associada a este e-mail. Verifiquem os identificadores atuais e anteriores conforme o processo de privacidade. Por favor, confirmem o resultado quando a análise terminar."
   - `[case_93]`: "Solicito a exclusão permanente da conta associada a este e-mail. Verifiquem os identificadores atuais e anteriores conforme o processo de privacidade. Por favor, confirmem o resultado quando a análise terminar."
   - `[case_132]`: "Solicito a exclusão permanente da conta associada a este e-mail. Verifiquem os identificadores atuais e anteriores conforme o processo de privacidade. Por favor, confirmem o resultado quando a análise terminar."
