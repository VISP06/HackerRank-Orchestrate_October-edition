"""Step construction and deterministic serialization."""

from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

from code.ghost.evidence_index import category_for, system_for
from code.ghost.loaders import natural_sort_key
from code.ghost.rules import (
    VERIFICATION_OP,
    VERIFICATION_STATE,
    Assessment,
    assess_state,
    load_rules,
    required_action,
)
from code.ghost.state import ResourceState

PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OPERATION_ORDER = {
    "REPORT_REMAINING_RECORD": 0,
    "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2,
    "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0,
    "BLOCK_RESTORE": 1,
    "DELETE_RECORD": 2,
    "REDACT_RECORD": 3,
    "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0,
    "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2,
    "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4,
    "VERIFY_RESTORE_BLOCKED": 5,
}
STEP_FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")


def _step(phase: str, assessment: Assessment, operation: str, state: str, evidence_id: str) -> Dict[str, object]:
    return {
        "step_no": 0,
        "phase": phase,
        "system_id": assessment.system_id,
        "resource_id": assessment.resource_id,
        "operation": operation,
        "state": state,
        "evidence_id": evidence_id,
    }


def _sort_steps(steps: List[Dict[str, object]]) -> List[Dict[str, object]]:
    steps.sort(
        key=lambda step: (
            PHASE_ORDER[step["phase"]],
            OPERATION_ORDER[step["operation"]],
            str(step["system_id"]),
            natural_sort_key(str(step["resource_id"])),
        )
    )
    for position, step in enumerate(steps, start=1):
        step["step_no"] = position
    return steps


def _dedupe(steps: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    result = []
    for step in steps:
        key = (step["system_id"], step["resource_id"], step["operation"])
        if key in seen:
            continue
        seen.add(key)
        result.append(step)
    return result


def _future_verification_steps(
    trace,
    states: Dict[str, ResourceState],
    rules: Dict[str, Dict[str, str]],
    audit_at: str,
) -> List[Dict[str, object]]:
    """Checks for resources the case reached but cannot prove a state for.

    An identifier-bearing artifact captured after ``audit_at`` can still show
    that a record exists and belongs to the subject (for example a lookup log
    naming a now-deleted account, or a retention index naming an audit row).
    Nothing about the record's current state is admissible, so the case stays
    INCOMPLETE, but the policy's required end state is known and must be
    verified after remediation.  Catalog-only links are excluded: they name a
    resource without showing the subject on it.
    """
    steps: List[Dict[str, object]] = []
    for resource_id, resource_trace in trace.resources.items():
        if resource_id in states:
            continue
        # A resource with an admissible observation already had its state
        # reconstructed; it may only be missing from ``states`` because an
        # older duplicate profile was pruned.  Do not invent future work for
        # a copy whose current state is known.
        has_eligible_observation = any(
            not (obs.captured_at and obs.captured_at > audit_at)
            and not (obs.observed_at and obs.observed_at > audit_at)
            for obs in resource_trace.observations
        )
        if has_eligible_observation:
            continue
        identifier_link = any(
            path.reason.startswith("identifier") for path in resource_trace.link_paths
        )
        if not identifier_link:
            continue
        category = category_for(resource_id, resource_trace.category)
        if category not in rules:
            continue
        system_id = system_for(resource_id, resource_trace.system_id)
        if not system_id:
            continue
        probe = ResourceState(
            resource_id=resource_id,
            system_id=system_id,
            category=category,
            state="UNKNOWN",
            evidence_id="",
            observed_at="",
        )
        action = required_action(category, probe, rules, audit_at)
        if action == "RETAIN":
            operation, end_state = "VERIFY_RECORD_PRESENT", "PRESENT"
        else:
            operation = VERIFICATION_OP.get(action)
            end_state = VERIFICATION_STATE.get(action, "")
        if not operation:
            continue
        steps.append(
            {
                "step_no": 0,
                "phase": "VERIFICATION",
                "system_id": system_id,
                "resource_id": resource_id,
                "operation": operation,
                "state": end_state,
                "evidence_id": "",
            }
        )
    return steps


def build_case_result(
    states: Dict[str, ResourceState],
    rules: Dict[str, Dict[str, str]],
    audit_at: str,
    trace=None,
) -> tuple:
    assessments: List[Assessment] = []
    for resource_id in sorted(states, key=natural_sort_key):
        assessment = assess_state(states[resource_id], rules, audit_at)
        if assessment is not None:
            assessments.append(assessment)

    findings = [a for a in assessments if a.is_finding]
    status = "INCOMPLETE" if findings else "COMPLETE"

    steps: List[Dict[str, object]] = []
    if status == "COMPLETE":
        for assessment in assessments:
            steps.append(
                _step(
                    "VERIFICATION",
                    assessment,
                    assessment.verification_op,
                    assessment.verification_state,
                    assessment.evidence_id,
                )
            )
    else:
        for assessment in findings:
            steps.append(
                _step(
                    "FINDING",
                    assessment,
                    assessment.finding_op,
                    assessment.finding_state,
                    assessment.evidence_id,
                )
            )
        for assessment in findings:
            steps.append(
                _step(
                    "REMEDIATION",
                    assessment,
                    assessment.remediation_op,
                    assessment.remediation_state,
                    "",
                )
            )
        for assessment in assessments:
            steps.append(
                _step(
                    "VERIFICATION",
                    assessment,
                    assessment.verification_op,
                    assessment.verification_state,
                    "",
                )
            )
        if trace is not None:
            steps.extend(_future_verification_steps(trace, states, rules, audit_at))

    steps = _sort_steps(_dedupe(steps))
    return status, steps


def serialize_steps(steps: List[Dict[str, object]]) -> str:
    ordered = [
        {field: step[field] for field in STEP_FIELDS}
        for step in steps
    ]
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)
