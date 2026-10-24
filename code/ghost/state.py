"""Point-in-time state reconstruction for one case.

Workflow statuses are never proof.  State comes from evidence observations
captured at or before ``audit_at``; the newest observation that proves a fact
wins (ties broken by capture time and then by file id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from code.ghost.evidence_index import EvidenceIndex, Observation, prefixed_identifiers
from code.ghost.linker import CaseTrace, ResourceTrace
from code.ghost.loaders import natural_sort_key

DIRECT_IDENTIFIER_KEYS = {"email", "phone", "email_hash", "user_id", "name"}


@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    category: str
    state: str  # PRESENT | ABSENT | IDENTIFIABLE | REDACTED | ANONYMIZED | ACTIVE | DISABLED | BLOCKED | UNKNOWN
    evidence_id: str
    observed_at: str
    attrs: Dict[str, str] = field(default_factory=dict)
    trace: Optional[ResourceTrace] = None
    link_path: str = ""
    direct_identifiers: bool = False

    def sign(self):
        return (
            self.resource_id,
            self.system_id,
            self.category,
            self.state,
            self.evidence_id,
        )


def _has_direct_identifiers(obs: Observation) -> bool:
    return any(obs.identifiers.get(key) for key in ("email", "phone", "email_hash", "user_id"))


def _has_redaction_identifiers(obs: Observation) -> bool:
    """Fields that policy-required redaction must remove.

    A stable internal ``user_id`` is the permitted reference that survives a
    redaction (support messages and account tombstones), so it is not a
    direct identifier for those categories.
    """
    return any(obs.identifiers.get(key) for key in ("email", "phone", "email_hash", "name"))


def _state_from_observation(obs: Observation) -> str:
    raw = (obs.raw_state or "").upper()
    if obs.present is False:
        return "ABSENT"
    category = obs.record_type
    if raw in {"ANONYMIZED", "REDACTED", "DISABLED", "BLOCKED", "ACTIVE"}:
        return raw
    if raw == "IDENTIFIABLE":
        return "IDENTIFIABLE"
    if category == "ANALYTICS_PROFILE":
        return "IDENTIFIABLE" if _has_direct_identifiers(obs) else "ANONYMIZED"
    if category == "PRODUCT_TELEMETRY":
        return "IDENTIFIABLE" if _has_direct_identifiers(obs) else "ANONYMIZED"
    if category == "SUPPORT_MESSAGE":
        return "IDENTIFIABLE" if _has_redaction_identifiers(obs) else "REDACTED"
    if category == "ACCOUNT_TOMBSTONE":
        direct = any(
            obs.identifiers.get(key) for key in ("email", "phone", "email_hash", "name")
        )
        return "IDENTIFIABLE" if direct else "REDACTED"
    if category == "DATA_FLOW":
        enabled = str(obs.attrs.get("enabled", "")).lower()
        if enabled in {"false", "0"}:
            return "DISABLED"
        if enabled in {"true", "1"}:
            return "ACTIVE"
        return "ACTIVE"
    if category == "BACKUP_ARCHIVE":
        allowed = str(obs.attrs.get("restore_allowed", "")).lower()
        if allowed in {"false", "0"}:
            return "BLOCKED"
        if allowed in {"true", "1"}:
            return "ACTIVE"
        if str(obs.attrs.get("deletion_block", "")).lower() == "true":
            return "BLOCKED"
        return "ACTIVE"
    return "PRESENT"


def _eligible(obs: Observation, audit_at: str) -> bool:
    if obs.captured_at and obs.captured_at > audit_at:
        return False
    if obs.observed_at and obs.observed_at > audit_at:
        return False
    return True


def reconstruct_state(
    index: EvidenceIndex,
    case_trace: CaseTrace,
    audit_at: str,
) -> Dict[str, ResourceState]:
    states: Dict[str, ResourceState] = {}

    for resource_id, trace in case_trace.resources.items():
        observations = [obs for obs in trace.observations if _eligible(obs, audit_at)]
        if observations:
            observations.sort(key=lambda obs: obs.sort_key(), reverse=True)
            latest = observations[0]
            states[resource_id] = ResourceState(
                resource_id=resource_id,
                system_id=latest.system_id,
                category=latest.record_type,
                state=_state_from_observation(latest),
                evidence_id=latest.file_id,
                observed_at=latest.observed_at,
                attrs={k: str(v) for k, v in latest.attrs.items()},
                trace=trace,
                link_path=trace.best_path(),
                direct_identifiers=_has_direct_identifiers(latest),
            )
            continue

        # No observation survives the cutoff.  Absence may still be provable
        # from a snapshot that covered the resource's system: the case reached
        # the resource at ``known_at``, and a later snapshot (still at or before
        # ``audit_at``) does not contain it.  A snapshot taken before the link
        # cannot prove anything about a resource first seen afterwards.
        category = trace.category
        system_id = trace.system_id
        if not system_id:
            # Fall back to the resource prefix only for coverage lookup.
            from code.ghost.evidence_index import category_for, system_for

            system_id = system_for(resource_id)
            category = category or category_for(resource_id)
        coverage = [
            cov
            for cov in index.coverage
            if cov.system_id == system_id
            and cov.captured_at <= audit_at
            and cov.observed_at <= audit_at
        ]
        if trace.known_at:
            coverage = [
                cov
                for cov in coverage
                if cov.observed_at >= trace.known_at
            ]
        # A coverage-only absence also needs a grounded link that says the
        # resource existed by ``known_at``.
        if coverage and trace.known_at:
            coverage.sort(key=lambda cov: (cov.observed_at, cov.captured_at, natural_sort_key(cov.file_id)), reverse=True)
            best = coverage[0]
            states[resource_id] = ResourceState(
                resource_id=resource_id,
                system_id=system_id,
                category=category,
                state="ABSENT",
                evidence_id=best.file_id,
                observed_at=best.observed_at,
                trace=trace,
                link_path=trace.best_path(),
            )

    # A subject has one current account profile.  Older account ids observed
    # for the same identity are stale historical resources, not extra copies.
    # Prefer a profile that is still present over an absent one; if every
    # candidate is absent, prefer one proven by a direct observation over a
    # tombstone inferred only from snapshot coverage.
    profiles = [
        state
        for state in states.values()
        if state.category in {"USER_PROFILE", "ACCOUNT_TOMBSTONE"}
    ]
    if len(profiles) > 1:
        present = [state for state in profiles if state.state != "ABSENT"]
        if present:
            keep = present
        else:
            direct = [state for state in profiles if state.direct_identifiers]
            keep = direct or profiles
        if len(keep) > 1:
            newest = max(keep, key=lambda state: (state.observed_at or "", state.resource_id))
            keep = [newest]
        keep_ids = {state.resource_id for state in keep}
        for state in profiles:
            if state.resource_id not in keep_ids:
                states.pop(state.resource_id, None)

    return states
