# HackerRank Orchestrate - October 2026

## Ghost Data Still Exists

Build an AI agent that audits whether a user's personal data was actually deleted.

A deletion workflow may report **Complete** while data still exists in databases, logs, support attachments, exports, search indexes, archives, or backups. Sync and restore processes may also bring deleted data back.

For each request, the agent must first determine whether deletion was actually requested. It then returns `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`, reports any remaining data or recreation risk, and produces the ordered remediation and verification steps required to finish an authorized deletion safely.

Read [`problem_statement.md`](./problem_statement.md) for the complete challenge contract.

---

## Quick Start

Clone the repository and move into the project directory:

```bash
git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26.git
cd hackerrank-orchestrate-october26
```

Start your AI coding tool from the **repository root** so it automatically reads [`AGENTS.md`](./AGENTS.md) and logs your session turns to `log.txt` in the root directory.

Build your solution in `code/main.py`, or use another language and document its setup and run command clearly in your README.

---

## How to Run

### 1. Environment Setup
Python 3.10+ is supported. The engine uses the Python standard library plus
`pypdf` for reading PDF evidence. SQL snapshots are executed locally with
`sqlite3`. No model provider or API key is required.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Deletion Audit Pipeline
To process the 518 evaluation requests and write `output.csv` at the repository root:
```bash
python3 code/main.py
```

To specify custom input or output paths:
```bash
python3 code/main.py --requests dataset/sample_deletion_requests.csv --out scratch/test_output.csv
```

To inspect how one case was linked and reconstructed:
```bash
python3 code/main.py --explain case_01
```

The pipeline automatically validates the output against the challenge schema, ordering, and state constraints upon completion. It also runs label-free invariant checks (phase order, allowed operation/state pairs, evidence recency, evidence rules) and reports the count.

### Solution architecture

The solution is deterministic and makes no model calls at runtime.

| Module | Responsibility |
|---|---|
| `code/ghost/loaders.py` | Load request, identity, audit, activity, rule, and manifest CSVs |
| `code/ghost/identity.py` | Resolve a request email to current and historical identifiers |
| `code/ghost/evidence_index.py` | Parse SQL, JSON, logs, text, and PDFs into normalized observations and coverage records |
| `code/ghost/linker.py` | Link each case to resources through identifiers, catalog links, propagation, and a narrow workflow-window fallback; record the link path and `known_at` time |
| `code/ghost/state.py` | Reconstruct the state of every linked resource at `audit_at`; reject future observations; use snapshots for absence only when the snapshot is at or after the link |
| `code/ghost/rules.py` | Apply `deletion_rules.csv` to each reconstructed state |
| `code/ghost/steps.py` | Build ordered FINDING / REMEDIATION / VERIFICATION steps, deduplicate, and serialize |
| `code/ghost/invariants.py` | Label-free contract and temporal checks over every output row |
| `code/ghost/intent.py` | Multilingual deletion-versus-non-deletion request classifier |
| `code/main.py` | End-to-end CLI and validator |

Workflow statuses and `reported_result` values are treated as claims. Every
finding and every `COMPLETE` verification cites a participant-visible evidence
file captured at or before the case's `audit_at`.

### 3. Run the Evaluation Harness
To benchmark the agent against the 32 public sample cases and ground truth:
```bash
python3 code/evaluation/run_eval.py --splits
```

This evaluates and reports:
- Overall and per-status accuracy (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`)
- Step-level Precision, Recall, and F1 score on exact 6-tuples `(phase, system_id, resource_id, operation, state, evidence_id)`
- Field-level accuracy for all six step fields
- Exact sequence accuracy across all cases
- Dev (24 cases) and held-out (8 cases, `case_id % 4 == 0`) metrics separately
- Compact failure diffs identifying missing and extraneous steps

Run the participant-authored edge cases:
```bash
python3 code/evaluation/custom_cases.py
```

Run the full 518-case pipeline and regenerate the coverage and runtime report:
```bash
python3 code/evaluation/full_run_stats.py
```

The reports are written to `code/evaluation/evaluation_report.md`,
`code/evaluation/usage_report.md`, and `code/evaluation/full_run_stats.md`.
Copies of the two required reports also live in the top-level `evaluation/`
directory.



## Dataset

All participant-facing files are in `dataset/`:

| File | Contents |
| --- | --- |
| `deletion_requests.csv` | 518 requests |
| `sample_deletion_requests.csv` | 32 sample requests |
| `sample_output.csv` | Correct sample answers |
| `user_identities.csv` | Current user identities |
| `user_audit_log.csv` | Historical identity changes |
| `system_activity.csv` | Activity across services and data processes |
| `deletion_rules.csv` | Required treatment for each data category |
| `evidence_files.csv` | Manifest of supplied evidence files |
| `output.csv` | Blank output template |

Evidence is stored under `dataset/evidence/` and may include PDFs, images, logs, JSON, plain text, or SQL snapshot exports. SQL captures may contain a primary database, regional replicas, a reporting replica, or a failover replica so replication drift can be investigated directly. The `.sql` files are readable as text and executable with SQLite.

Only `deletion_requests.csv` requires answers. The other files provide evidence and context.

---

## Output

Create `output.csv` with these columns in this exact order:

```text
case_id,deletion_status,steps_json
```

Produce exactly one row per request. `deletion_status` is `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`. `steps_json` is an ordered JSON array containing findings, remediation actions, and verification checks. Use an empty array (`[]`) for `NOT_APPLICABLE`. Evidence references may be a `file_id`, `activity_id`, or `audit_id`. Determine the resource state at `audit_at` from the available evidence; reported workflow statuses and operation results are claims. Use `dataset/sample_output.csv` as the format reference.

The final file must contain 518 data rows sorted by `case_id` (plus the header row). The grader parses `steps_json` as JSON, so object-key order and whitespace do not matter; array order does. Order findings, remediation, and verification in that phase order. Within a phase, follow the operation order in the problem statement, then sort by `system_id` and `resource_id`.

---

## Evaluation

`output.csv` will be compared with hidden canonical answers. Scoring considers:

- deletion assessment accuracy;
- current and historical identity resolution;
- discovery of remaining data and recreation risks;
- correct policy application and evidence references; and
- completeness and ordering of remediation and verification steps.

Your `code.zip` must include:

```text
code/evaluation/evaluation_report.md
code/evaluation/usage_report.md
```

- `evaluation_report.md` must cover case, row, field, and sequence accuracy, at least three additional evaluation cases created by you, failures found, and improvements made.
- `usage_report.md` must cover the final full-dataset run, including model providers and names, model calls, input and output tokens, total and average tokens per request, and estimated total and per-request cost. Include per-model and overall totals when using multiple models.

**Important:** Place `evaluation_report.md` and `usage_report.md` inside `code/evaluation/` (matching `code/evaluation/main.py` in this starter layout), write your complete evaluation metrics, custom evaluation test cases, and token/cost breakdowns directly inside those Markdown files, and keep prompts in source code or Markdown files. Automated code evaluation ignores raw data files (`.csv`, `.tsv`, `.json`, `.jsonl`, `.sql`, `.log`), so content stored only in those formats will not be visible to the code judge or AI interviewer.

---

## Chat Transcript

This repository includes [`AGENTS.md`](./AGENTS.md), which instructs compatible AI coding tools to append conversation summaries to `log.txt` in the repository root:

| Platform | Path |
| --- | --- |
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

- Always launch your AI coding agent from the repository root (or explicitly ask it to read `./AGENTS.md` first) so every turn is logged to `log.txt` with the required `User Prompt`, `Agent Response Summary`, `Actions`, and `Context` sections.
- Upload `log.txt` directly as your `chat_transcript` submission on HackerRank.
- Do not include API keys, tokens, credentials, or secrets in prompts, code, configuration, or `log.txt`.

---

## Packaging `code.zip` and Submission

| Item | Description |
| --- | --- |
| `code.zip` | Runnable solution, prompts, configuration, `README.md`, and `evaluation/` reports |
| `output.csv` | One answer row for each of the 518 requests in `dataset/deletion_requests.csv` |
| `chat_transcript` | The root `log.txt` file generated by your coding agent |
| AI interview | Live explanation of your architecture, approach, and evaluation |

You may use any programming language, model, framework, or retrieval approach. Include clear setup and execution instructions in `README.md` inside `code.zip`.

To package `code.zip` from the repository root without bundling the dataset:

**macOS / Linux:**

```bash
zip -r code.zip README.md code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store"
```

**Windows (PowerShell):**

```powershell
Compress-Archive -Path README.md, code -DestinationPath code.zip -Force
```

When packaging `code.zip`:

- Keep your evaluation reports in `code/evaluation/` so they are bundled automatically with `code` (or add `evaluation` to the archive command above if you placed them in a top-level `evaluation/` directory).
- Do **not** include `dataset/`, virtual environments (`.venv`, `venv`, `node_modules`), or build caches (`__pycache__`). On Windows, keep `.venv` at the repository root (outside `code/`) and remove any `code/__pycache__` folders before running `Compress-Archive`.
- Do **not** include nested archives (`.zip`, `.tar`, `.gz`, `.tgz`, `.7z`, `.rar`) inside `code.zip` — submissions containing nested archive files will be rejected.

Before submitting, confirm that:

- `output.csv` has the exact header `case_id,deletion_status,steps_json` and contains all 518 data rows sorted by `case_id`;
- every `steps_json` value is a valid JSON array with consecutive step numbers starting at `1`;
- findings cite valid evidence IDs, and `COMPLETE` verification steps cite evidence proving the current state;
- proposed remediation and future verification steps use an empty `evidence_id` (`""`);
- `code.zip` includes your runnable code, `README.md`, `code/evaluation/evaluation_report.md`, and `code/evaluation/usage_report.md`;
- `log.txt` follows the `AGENTS.md` turn format and is uploaded to the `chat_transcript` slot; and
- no API keys, credentials, real personal data, or sensitive configuration values are included.
