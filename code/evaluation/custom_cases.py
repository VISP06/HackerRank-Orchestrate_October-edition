#!/usr/bin/env python3
"""Participant-authored evaluation cases.

These are small synthetic scenarios, independent of the challenge's golden
answers.  Each one isolates a rule that matters in the audit: request intent,
tombstone redaction, active data flows, restore risk, analytics anonymization,
and the temporal guard on snapshot-based absence.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code.ghost.evidence_index import Coverage, EvidenceIndex, Observation
from code.ghost.intent import authorizes_deletion
from code.ghost.linker import CaseTrace, LinkPath, ResourceTrace
from code.ghost.rules import load_rules
from code.ghost.state import reconstruct_state
from code.ghost.steps import build_case_result

AUDIT_AT = "2026-06-10T00:00:00Z"
RULES = load_rules(os.path.join(REPO_ROOT, "dataset", "deletion_rules.csv"))
FAILURES = []


def _obs(
    resource_id,
    category,
    system_id,
    *,
    captured_at="2026-06-01T00:00:00Z",
    observed_at="2026-06-01T00:00:00Z",
    identifiers=None,
    attrs=None,
    present=True,
    raw_state="",
    file_id="evidence_synthetic",
):
    return Observation(
        file_id=file_id,
        captured_at=captured_at,
        observed_at=observed_at,
        system_id=system_id,
        store="synthetic",
        collection="synthetic",
        record_type=category,
        resource_id=resource_id,
        identifiers={
            key: set(values) for key, values in (identifiers or {}).items()
        },
        attrs=attrs or {},
        present=present,
        raw_state=raw_state,
    )


def _run(name, expected_status, expected_steps, observations, coverage=None):
    index = EvidenceIndex()
    for cov in coverage or []:
        index.add_coverage(cov)
    trace = CaseTrace(case_id="synthetic", user_id="user_synthetic")
    for obs in observations:
        trace.add_observation(
            obs,
            LinkPath(resource_id=obs.resource_id, reason="synthetic", evidence_id=obs.file_id),
        )
        trace.resources[obs.resource_id].note_known_at(obs.observed_at)
    states = reconstruct_state(index, trace, AUDIT_AT)
    status, steps = build_case_result(states, RULES, AUDIT_AT)
    actual = [
        (step["phase"], step["resource_id"], step["operation"], step["state"], step["evidence_id"])
        for step in steps
    ]
    ok = status == expected_status and actual == expected_steps
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: status={status} steps={len(steps)}")
    if not ok:
        FAILURES.append(name)
        print(f"  expected status={expected_status}")
        for step in expected_steps:
            print(f"    expected {step}")
        for step in actual:
            print(f"    actual   {step}")


def case_intent():
    deletion = authorizes_deletion(
        "Please permanently delete my account and all personal data."
    )
    access = authorizes_deletion("Please send me a copy of all my personal data.")
    ok = deletion and not access
    print(f"[{'PASS' if ok else 'FAIL'}] non-deletion request is NOT_APPLICABLE")
    if not ok:
        FAILURES.append("intent")


def case_tombstone():
    _run(
        "redacted tombstone keeps only the stable user_id",
        "COMPLETE",
        [
            (
                "VERIFICATION",
                "tombstone_9001",
                "VERIFY_RECORD_REDACTED",
                "REDACTED",
                "evidence_synthetic",
            )
        ],
        [
            _obs(
                "tombstone_9001",
                "ACCOUNT_TOMBSTONE",
                "identity_service",
                identifiers={"user_id": {"user_900"}},
            )
        ],
    )


def case_data_flow():
    _run(
        "active sync flow is reported, disabled, then verified",
        "INCOMPLETE",
        [
            (
                "FINDING",
                "data_flow_9001",
                "REPORT_ACTIVE_DATA_FLOW",
                "ACTIVE",
                "evidence_synthetic",
            ),
            (
                "REMEDIATION",
                "data_flow_9001",
                "DISABLE_DATA_FLOW",
                "DISABLED",
                "",
            ),
            (
                "VERIFICATION",
                "data_flow_9001",
                "VERIFY_DATA_FLOW_DISABLED",
                "DISABLED",
                "",
            ),
        ],
        [
            _obs(
                "data_flow_9001",
                "DATA_FLOW",
                "integration_service",
                attrs={"enabled": "true"},
            )
        ],
    )


def case_restore_risk():
    _run(
        "unblocked backup is a restore risk and must be blocked",
        "INCOMPLETE",
        [
            (
                "FINDING",
                "backup_9001",
                "REPORT_RESTORE_RISK",
                "ACTIVE",
                "evidence_synthetic",
            ),
            ("REMEDIATION", "backup_9001", "BLOCK_RESTORE", "BLOCKED", ""),
            (
                "VERIFICATION",
                "backup_9001",
                "VERIFY_RESTORE_BLOCKED",
                "BLOCKED",
                "",
            ),
        ],
        [
            _obs(
                "backup_9001",
                "BACKUP_ARCHIVE",
                "backup_service",
                attrs={"restore_allowed": "true"},
            )
        ],
    )


def case_analytics():
    _run(
        "analytics record without identifiers is already anonymized",
        "COMPLETE",
        [
            (
                "VERIFICATION",
                "analytics_9001",
                "VERIFY_RECORD_ANONYMIZED",
                "ANONYMIZED",
                "evidence_synthetic",
            )
        ],
        [_obs("analytics_9001", "ANALYTICS_PROFILE", "analytics_platform")],
    )


def case_temporal_guard():
    index = EvidenceIndex()
    index.add_coverage(
        Coverage(
            file_id="evidence_before_link",
            captured_at="2026-05-01T00:00:00Z",
            system_id="account_service",
            store="customer_profiles_primary",
            observed_at="2026-05-01T00:00:00Z",
        )
    )
    trace = CaseTrace(case_id="synthetic", user_id="user_synthetic")
    trace.link_resource(
        "account_9001",
        LinkPath(resource_id="account_9001", reason="synthetic", evidence_id=""),
    )
    trace.resources["account_9001"].note_known_at("2026-06-01T00:00:00Z")
    states = reconstruct_state(index, trace, AUDIT_AT)
    before = not states
    index.add_coverage(
        Coverage(
            file_id="evidence_after_link",
            captured_at="2026-06-05T00:00:00Z",
            system_id="account_service",
            store="customer_profiles_primary",
            observed_at="2026-06-05T00:00:00Z",
        )
    )
    states = reconstruct_state(index, trace, AUDIT_AT)
    after = states.get("account_9001")
    ok = before and after is not None and after.state == "ABSENT"
    print(f"[{'PASS' if ok else 'FAIL'}] snapshot before the link cannot prove absence")
    if not ok:
        FAILURES.append("temporal_guard")


def main():
    case_intent()
    case_tombstone()
    case_data_flow()
    case_restore_risk()
    case_analytics()
    case_temporal_guard()
    print(f"\nCustom cases: {6 - len(FAILURES)}/6 passed")
    if FAILURES:
        print("Failures: " + ", ".join(FAILURES))
        sys.exit(1)


if __name__ == "__main__":
    main()
