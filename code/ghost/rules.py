"""Policy application: map a reconstructed resource state to a verdict.

``deletion_rules.csv`` is the source of truth for the required action per
category.  The conditions in that file are evaluated against the observed
record; the workflow's own claims are never consulted.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Dict, List, Optional

from code.ghost.state import ResourceState

VALID_ACTIONS = {"DELETE", "REDACT", "ANONYMIZE", "RETAIN"}

# Operations emitted per verdict.
FINDING_OP = {
    "DELETE": "REPORT_REMAINING_RECORD",
    "REDACT": "REPORT_EXPOSED_PII",
    "ANONYMIZE": "REPORT_EXPOSED_PII",
}
FINDING_STATE = {
    "DELETE": "PRESENT",
    "REDACT": "PRESENT",
    "ANONYMIZE": "PRESENT",
}
REMEDIATION_OP = {
    "DELETE": "DELETE_RECORD",
    "REDACT": "REDACT_RECORD",
    "ANONYMIZE": "ANONYMIZE_RECORD",
}
REMEDIATION_STATE = {
    "DELETE": "ABSENT",
    "REDACT": "REDACTED",
    "ANONYMIZE": "ANONYMIZED",
}
VERIFICATION_OP = {
    "DELETE": "VERIFY_RECORD_ABSENT",
    "REDACT": "VERIFY_RECORD_REDACTED",
    "ANONYMIZE": "VERIFY_RECORD_ANONYMIZED",
}
VERIFICATION_STATE = {
    "DELETE": "ABSENT",
    "REDACT": "REDACTED",
    "ANONYMIZE": "ANONYMIZED",
}


@dataclass
class Assessment:
    resource_id: str
    system_id: str
    category: str
    finding_op: Optional[str]
    finding_state: Optional[str]
    remediation_op: Optional[str]
    remediation_state: Optional[str]
    verification_op: str
    verification_state: str
    evidence_id: str
    observed_state: str
    observed_at: str

    @property
    def is_finding(self) -> bool:
        return self.finding_op is not None


def load_rules(path: str) -> Dict[str, Dict[str, str]]:
    rules: Dict[str, Dict[str, str]] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            category = (row.get("data_category") or "").strip()
            if category:
                rules[category] = row
    return rules


def required_action(
    category: str,
    state: ResourceState,
    rules: Dict[str, Dict[str, str]],
    audit_at: str,
) -> str:
    rule = rules.get(category)
    if not rule:
        # Categories without an explicit policy row.
        if category in {"DATA_FLOW", "SECONDARY_IDENTIFIER"}:
            return "DELETE"
        return "RETAIN"
    action = (rule.get("required_action") or "").strip().upper()
    if action not in VALID_ACTIONS:
        return "RETAIN"

    if category in {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}:
        retention = state.attrs.get("retention_until") or state.attrs.get("retained_until")
        if retention and str(retention) < audit_at:
            # Retention window has expired; the record is no longer required.
            return "DELETE"
        return "RETAIN"
    if category == "ANALYTICS_PROFILE" or category == "PRODUCT_TELEMETRY":
        # "Record is still attributable to a user" -> ANONYMIZE; an already
        # anonymized record needs no action, while an absent record is verified
        # as absent by the generic branch below.
        if state.state == "ANONYMIZED":
            return "RETAIN"
        return "ANONYMIZE"
    return action


def assess_state(
    state: ResourceState,
    rules: Dict[str, Dict[str, str]],
    audit_at: str,
) -> Optional[Assessment]:
    category = state.category
    action = required_action(category, state, rules, audit_at)

    if category == "DATA_FLOW":
        if state.state == "ACTIVE":
            return Assessment(
                resource_id=state.resource_id,
                system_id=state.system_id or "integration_service",
                category=category,
                finding_op="REPORT_ACTIVE_DATA_FLOW",
                finding_state="ACTIVE",
                remediation_op="DISABLE_DATA_FLOW",
                remediation_state="DISABLED",
                verification_op="VERIFY_DATA_FLOW_DISABLED",
                verification_state="DISABLED",
                evidence_id=state.evidence_id,
                observed_state=state.state,
                observed_at=state.observed_at,
            )
        if state.state == "DISABLED":
            return Assessment(
                resource_id=state.resource_id,
                system_id=state.system_id or "integration_service",
                category=category,
                finding_op=None,
                finding_state=None,
                remediation_op=None,
                remediation_state=None,
                verification_op="VERIFY_DATA_FLOW_DISABLED",
                verification_state="DISABLED",
                evidence_id=state.evidence_id,
                observed_state=state.state,
                observed_at=state.observed_at,
            )
        if state.state == "ABSENT":
            return Assessment(
                resource_id=state.resource_id,
                system_id=state.system_id or "integration_service",
                category=category,
                finding_op=None,
                finding_state=None,
                remediation_op=None,
                remediation_state=None,
                verification_op="VERIFY_RECORD_ABSENT",
                verification_state="ABSENT",
                evidence_id=state.evidence_id,
                observed_state=state.state,
                observed_at=state.observed_at,
            )
        return None

    if category == "BACKUP_ARCHIVE":
        if state.state == "ACTIVE":
            return Assessment(
                resource_id=state.resource_id,
                system_id=state.system_id or "backup_service",
                category=category,
                finding_op="REPORT_RESTORE_RISK",
                finding_state="ACTIVE",
                remediation_op="BLOCK_RESTORE",
                remediation_state="BLOCKED",
                verification_op="VERIFY_RESTORE_BLOCKED",
                verification_state="BLOCKED",
                evidence_id=state.evidence_id,
                observed_state=state.state,
                observed_at=state.observed_at,
            )
        if state.state == "BLOCKED":
            return Assessment(
                resource_id=state.resource_id,
                system_id=state.system_id or "backup_service",
                category=category,
                finding_op=None,
                finding_state=None,
                remediation_op=None,
                remediation_state=None,
                verification_op="VERIFY_RESTORE_BLOCKED",
                verification_state="BLOCKED",
                evidence_id=state.evidence_id,
                observed_state=state.state,
                observed_at=state.observed_at,
            )
        if state.state == "ABSENT":
            return Assessment(
                resource_id=state.resource_id,
                system_id=state.system_id or "backup_service",
                category=category,
                finding_op=None,
                finding_state=None,
                remediation_op=None,
                remediation_state=None,
                verification_op="VERIFY_RECORD_ABSENT",
                verification_state="ABSENT",
                evidence_id=state.evidence_id,
                observed_state=state.state,
                observed_at=state.observed_at,
            )
        return None

    if action == "RETAIN":
        if state.state == "PRESENT":
            op = "VERIFY_RECORD_PRESENT"
            verdict = "PRESENT"
        elif state.state == "REDACTED":
            op = "VERIFY_RECORD_REDACTED"
            verdict = "REDACTED"
        elif state.state == "ANONYMIZED":
            op = "VERIFY_RECORD_ANONYMIZED"
            verdict = "ANONYMIZED"
        else:
            return None
        return Assessment(
            resource_id=state.resource_id,
            system_id=state.system_id,
            category=category,
            finding_op=None,
            finding_state=None,
            remediation_op=None,
            remediation_state=None,
            verification_op=op,
            verification_state=verdict,
            evidence_id=state.evidence_id,
            observed_state=state.state,
            observed_at=state.observed_at,
        )

    if state.state == "ABSENT":
        return Assessment(
            resource_id=state.resource_id,
            system_id=state.system_id,
            category=category,
            finding_op=None,
            finding_state=None,
            remediation_op=None,
            remediation_state=None,
            verification_op="VERIFY_RECORD_ABSENT",
            verification_state="ABSENT",
            evidence_id=state.evidence_id,
            observed_state=state.state,
            observed_at=state.observed_at,
        )

    treated = (
        (action == "REDACT" and state.state == "REDACTED")
        or (action == "ANONYMIZE" and state.state == "ANONYMIZED")
    )
    if treated:
        return Assessment(
            resource_id=state.resource_id,
            system_id=state.system_id,
            category=category,
            finding_op=None,
            finding_state=None,
            remediation_op=None,
            remediation_state=None,
            verification_op=VERIFICATION_OP[action],
            verification_state=VERIFICATION_STATE[action],
            evidence_id=state.evidence_id,
            observed_state=state.state,
            observed_at=state.observed_at,
        )

    return Assessment(
        resource_id=state.resource_id,
        system_id=state.system_id,
        category=category,
        finding_op=FINDING_OP[action],
        finding_state=FINDING_STATE[action],
        remediation_op=REMEDIATION_OP[action],
        remediation_state=REMEDIATION_STATE[action],
        verification_op=VERIFICATION_OP[action],
        verification_state=VERIFICATION_STATE[action],
        evidence_id=state.evidence_id,
        observed_state=state.state,
        observed_at=state.observed_at,
    )
