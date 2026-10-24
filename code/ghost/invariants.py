"""Label-free invariant checks applied to every generated row.

These checks do not compare against golden answers.  They verify the output
contract, temporal evidence bounds, phase/operation vocabulary, and the
finding-versus-future-work evidence rules from the problem statement.
"""

from __future__ import annotations

import csv
import json
from typing import Dict, List

ALLOWED_STATUS = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
ALLOWED_FINDINGS = {
    ("REPORT_REMAINING_RECORD", "PRESENT"),
    ("REPORT_EXPOSED_PII", "PRESENT"),
    ("REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("REPORT_RESTORE_RISK", "ACTIVE"),
}
ALLOWED_REMEDIATION = {
    ("DISABLE_DATA_FLOW", "DISABLED"),
    ("BLOCK_RESTORE", "BLOCKED"),
    ("DELETE_RECORD", "ABSENT"),
    ("REDACT_RECORD", "REDACTED"),
    ("ANONYMIZE_RECORD", "ANONYMIZED"),
}
ALLOWED_VERIFICATION = {
    ("VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
}
STEP_FIELDS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}


def check_rows(
    rows: List[Dict[str, str]],
    expected_case_ids: List[str],
    evidence_dates: Dict[str, str],
    audit_dates: Dict[str, str],
) -> List[str]:
    violations: List[str] = []
    seen_cases = set()
    for row in rows:
        case_id = row.get("case_id", "")
        status = row.get("deletion_status", "")
        raw_steps = row.get("steps_json", "")
        if case_id in seen_cases:
            violations.append(f"{case_id}: duplicate row")
        seen_cases.add(case_id)
        if status not in ALLOWED_STATUS:
            violations.append(f"{case_id}: invalid status {status!r}")
            continue
        try:
            steps = json.loads(raw_steps)
        except json.JSONDecodeError as exc:
            violations.append(f"{case_id}: invalid steps_json ({exc})")
            continue
        if not isinstance(steps, list):
            violations.append(f"{case_id}: steps_json is not a list")
            continue
        if status == "NOT_APPLICABLE":
            if steps:
                violations.append(f"{case_id}: NOT_APPLICABLE with steps")
            continue
        if not steps:
            # A COMPLETE case can have no linked resources at all when no
            # eligible evidence names the subject.  That is an evidence
            # coverage gap tracked in the full-run report, not a contract
            # violation.  INCOMPLETE without any finding or plan is invalid.
            if status == "INCOMPLETE":
                violations.append(f"{case_id}: INCOMPLETE with no steps")
            continue
        if status == "COMPLETE":
            for step in steps:
                if step.get("phase") != "VERIFICATION":
                    violations.append(f"{case_id}: COMPLETE contains non-verification step")
                if not step.get("evidence_id"):
                    violations.append(f"{case_id}: COMPLETE verification without evidence")
        previous_phase = -1
        previous_step_no = 0
        seen_keys = set()
        for step in steps:
            if set(step) != STEP_FIELDS:
                violations.append(f"{case_id}: step has wrong fields {sorted(step)}")
                continue
            if not isinstance(step["step_no"], int) or step["step_no"] != previous_step_no + 1:
                violations.append(f"{case_id}: non-consecutive step_no {step['step_no']!r}")
            previous_step_no = step["step_no"] if isinstance(step["step_no"], int) else previous_step_no
            phase = step["phase"]
            if phase not in PHASE_ORDER:
                violations.append(f"{case_id}: invalid phase {phase!r}")
                continue
            if PHASE_ORDER[phase] < previous_phase:
                violations.append(f"{case_id}: phase order regression at step {step['step_no']}")
            previous_phase = max(previous_phase, PHASE_ORDER[phase])
            pair = (step["operation"], step["state"])
            if phase == "FINDING" and pair not in ALLOWED_FINDINGS:
                violations.append(f"{case_id}: invalid finding {pair}")
            if phase == "REMEDIATION" and pair not in ALLOWED_REMEDIATION:
                violations.append(f"{case_id}: invalid remediation {pair}")
            if phase == "VERIFICATION" and pair not in ALLOWED_VERIFICATION:
                violations.append(f"{case_id}: invalid verification {pair}")
            if phase in {"FINDING", "REMEDIATION"} and status == "COMPLETE":
                violations.append(f"{case_id}: COMPLETE contains {phase}")
            key = (step["system_id"], step["resource_id"], step["operation"])
            if key in seen_keys:
                violations.append(f"{case_id}: duplicate step {key}")
            seen_keys.add(key)
            evidence_id = str(step.get("evidence_id", ""))
            if phase == "FINDING":
                if not evidence_id:
                    violations.append(f"{case_id}: finding without evidence")
                elif evidence_id.startswith("evidence_"):
                    if evidence_id not in evidence_dates:
                        violations.append(f"{case_id}: finding cites unknown evidence {evidence_id}")
                    elif evidence_dates[evidence_id] > audit_dates.get(case_id, "9999"):
                        violations.append(f"{case_id}: finding cites future evidence {evidence_id}")
            elif phase == "VERIFICATION" and status == "COMPLETE":
                if evidence_id.startswith("evidence_"):
                    if evidence_id not in evidence_dates:
                        violations.append(
                            f"{case_id}: verification cites unknown evidence {evidence_id}"
                        )
                    elif evidence_dates[evidence_id] > audit_dates.get(case_id, "9999"):
                        violations.append(
                            f"{case_id}: verification cites future evidence {evidence_id}"
                        )
            else:
                if evidence_id and status == "INCOMPLETE":
                    violations.append(f"{case_id}: future work carries evidence {evidence_id}")
    missing = set(expected_case_ids) - seen_cases
    extra = seen_cases - set(expected_case_ids)
    if missing:
        violations.append(f"missing rows: {sorted(missing)[:5]} (+{max(0, len(missing) - 5)} more)")
    if extra:
        violations.append(f"unexpected rows: {sorted(extra)[:5]} (+{max(0, len(extra) - 5)} more)")
    return violations


def load_output(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
