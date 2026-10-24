"""Output schema and constraint validator for Ghost Data Still Exists challenge."""

import csv
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .loaders import natural_sort_key

# Allowed phases in strict workflow order
ALLOWED_PHASES = ["FINDING", "REMEDIATION", "VERIFICATION"]

# Allowed operations and required states per AGENTS.md §6.4
ALLOWED_OPERATIONS: Dict[str, Dict[str, str]] = {
    "FINDING": {
        "REPORT_REMAINING_RECORD": "PRESENT",
        "REPORT_EXPOSED_PII": "PRESENT",
        "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
        "REPORT_RESTORE_RISK": "ACTIVE",
    },
    "REMEDIATION": {
        "DISABLE_DATA_FLOW": "DISABLED",
        "BLOCK_RESTORE": "BLOCKED",
        "DELETE_RECORD": "ABSENT",
        "REDACT_RECORD": "REDACTED",
        "ANONYMIZE_RECORD": "ANONYMIZED",
    },
    "VERIFICATION": {
        "VERIFY_RECORD_ABSENT": "ABSENT",
        "VERIFY_RECORD_PRESENT": "PRESENT",
        "VERIFY_RECORD_REDACTED": "REDACTED",
        "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
        "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
        "VERIFY_RESTORE_BLOCKED": "BLOCKED",
    },
}

REQUIRED_STEP_KEYS = {
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
}

EXPECTED_HEADER = ["case_id", "deletion_status", "steps_json"]


def validate_step(step: Dict[str, Any], case_id: str, expected_step_no: int, deletion_status: str) -> List[str]:
    """Validate a single step object."""
    errors = []
    
    # Key check
    keys = set(step.keys())
    missing_keys = REQUIRED_STEP_KEYS - keys
    if missing_keys:
        errors.append(f"[{case_id}] Step {expected_step_no} is missing required keys: {missing_keys}")
    extra_keys = keys - REQUIRED_STEP_KEYS
    if extra_keys:
        errors.append(f"[{case_id}] Step {expected_step_no} has extraneous keys: {extra_keys}")

    # step_no check
    step_no = step.get("step_no")
    if step_no != expected_step_no:
        errors.append(f"[{case_id}] Step numbering mismatch: expected {expected_step_no}, got {step_no}")

    phase = step.get("phase")
    if phase not in ALLOWED_PHASES:
        errors.append(f"[{case_id}] Step {expected_step_no} invalid phase '{phase}'. Must be one of {ALLOWED_PHASES}")
        return errors

    operation = step.get("operation")
    state = step.get("state")
    evidence_id = step.get("evidence_id", "")

    # Operation and state checks
    valid_ops_for_phase = ALLOWED_OPERATIONS.get(phase, {})
    if operation not in valid_ops_for_phase:
        errors.append(f"[{case_id}] Step {expected_step_no} invalid operation '{operation}' for phase '{phase}'")
    else:
        expected_state = valid_ops_for_phase[operation]
        if state != expected_state:
            errors.append(f"[{case_id}] Step {expected_step_no} invalid state '{state}' for operation '{operation}'. Expected '{expected_state}'")

    # Evidence ID rules
    if deletion_status == "COMPLETE":
        if phase != "VERIFICATION":
            errors.append(f"[{case_id}] COMPLETE case cannot contain phase '{phase}', only VERIFICATION")
        if not evidence_id or not isinstance(evidence_id, str) or not evidence_id.strip():
            errors.append(f"[{case_id}] COMPLETE case step {expected_step_no} must cite a non-empty evidence_id")
    elif deletion_status == "INCOMPLETE":
        if phase == "FINDING":
            if not evidence_id or not isinstance(evidence_id, str) or not evidence_id.strip():
                errors.append(f"[{case_id}] INCOMPLETE finding step {expected_step_no} must cite a non-empty evidence_id")
        elif phase in ["REMEDIATION", "VERIFICATION"]:
            if evidence_id != "":
                errors.append(f"[{case_id}] INCOMPLETE {phase} step {expected_step_no} must have an empty evidence_id, got '{evidence_id}'")

    return errors


def validate_output_rows(rows: List[Dict[str, str]], expected_cases: Optional[List[str]] = None, allow_empty_steps: bool = False) -> Tuple[bool, List[str]]:
    """Validate a list of prediction row dictionaries."""
    errors = []
    seen_cases = []

    for i, row in enumerate(rows):
        case_id = row.get("case_id", f"row_{i+1}")
        seen_cases.append(case_id)
        status = row.get("deletion_status", "")
        steps_json = row.get("steps_json", "")

        if status not in ["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]:
            errors.append(f"[{case_id}] Invalid deletion_status '{status}'. Must be COMPLETE, INCOMPLETE, or NOT_APPLICABLE")

        # JSON parsing
        try:
            steps = json.loads(steps_json)
        except Exception as e:
            errors.append(f"[{case_id}] steps_json is not valid JSON: {e}")
            continue

        if not isinstance(steps, list):
            errors.append(f"[{case_id}] steps_json must parse to a JSON array, got {type(steps).__name__}")
            continue

        # NOT_APPLICABLE must be []
        if status == "NOT_APPLICABLE":
            if len(steps) != 0:
                errors.append(f"[{case_id}] NOT_APPLICABLE must have empty steps_json '[]', found {len(steps)} steps")
            continue

        # Baseline empty check
        if len(steps) == 0:
            if not allow_empty_steps:
                errors.append(f"[{case_id}] Status '{status}' has empty steps list")
            continue

        # Validate step order and contents
        current_phase_idx = 0
        for step_idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                errors.append(f"[{case_id}] Step {step_idx} must be a JSON object, got {type(step).__name__}")
                continue

            step_errors = validate_step(step, case_id, step_idx, status)
            errors.extend(step_errors)

            # Phase monotonic ordering
            phase = step.get("phase")
            if phase in ALLOWED_PHASES:
                phase_idx = ALLOWED_PHASES.index(phase)
                if phase_idx < current_phase_idx:
                    errors.append(f"[{case_id}] Phase order violation at step {step_idx}: '{phase}' appeared after '{ALLOWED_PHASES[current_phase_idx]}'")
                else:
                    current_phase_idx = phase_idx

    # Check case ordering
    if seen_cases != sorted(seen_cases, key=natural_sort_key):
        errors.append("Output rows are not sorted in natural numeric order by case_id")

    # Check duplicates
    if len(seen_cases) != len(set(seen_cases)):
        errors.append("Output contains duplicate case_ids")

    # Check expected cases if provided
    if expected_cases is not None:
        if seen_cases != expected_cases:
            missing = set(expected_cases) - set(seen_cases)
            extra = set(seen_cases) - set(expected_cases)
            if missing:
                errors.append(f"Missing expected case_ids ({len(missing)} total, e.g. {sorted(list(missing))[:5]})")
            if extra:
                errors.append(f"Unexpected case_ids ({len(extra)} total, e.g. {sorted(list(extra))[:5]})")
            if not missing and not extra and seen_cases != expected_cases:
                errors.append("Case IDs match set of expected cases but are ordered differently")

    return (len(errors) == 0, errors)


def validate_output_file(file_path: str, expected_cases: Optional[List[str]] = None, allow_empty_steps: bool = False) -> Tuple[bool, List[str]]:
    """Validate an output CSV file against the competition contract."""
    errors = []
    if not os.path.exists(file_path):
        return False, [f"Output file does not exist: {file_path}"]

    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return False, ["Output file is empty"]

        if header != EXPECTED_HEADER:
            errors.append(f"Invalid CSV header: expected {EXPECTED_HEADER}, got {header}")

        rows = []
        for line_no, row_values in enumerate(reader, start=2):
            if len(row_values) != 3:
                errors.append(f"Line {line_no}: expected 3 columns, got {len(row_values)}")
                continue
            rows.append({
                "case_id": row_values[0].strip(),
                "deletion_status": row_values[1].strip(),
                "steps_json": row_values[2].strip(),
            })

    is_valid, row_errors = validate_output_rows(rows, expected_cases=expected_cases, allow_empty_steps=allow_empty_steps)
    errors.extend(row_errors)

    return (len(errors) == 0, errors)
