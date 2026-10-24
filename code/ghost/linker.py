"""Case-to-resource linking.

A case reaches a resource only through grounded identifiers:

* the identity cluster resolved from ``user_identities`` + ``user_audit_log``
  (current and historical emails, phones, email hashes, stable ``user_id``);
* identifier-bearing evidence observations (SQL rows, JSON records, lookup
  keys carried by log traces, handover lines, documents);
* ``LINK_RESOURCE_IDENTITY`` activity events; and
* resource-id propagation when an activity row explicitly names a downstream
  resource that was repopulated from the linked resource.

Nothing here uses numeric naming conventions such as ``user_7 -> account_7``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from code.ghost.evidence_index import (
    EvidenceIndex,
    Observation,
    RESOURCE_RE,
    USER_RE,
    prefixed_identifiers,
)
from code.ghost.identity import resolve_identity
from code.ghost.loaders import natural_sort_key


@dataclass
class LinkPath:
    resource_id: str
    reason: str
    identifier: str = ""
    evidence_id: str = ""

    def describe(self) -> str:
        bits = [self.reason]
        if self.identifier:
            bits.append(self.identifier)
        if self.evidence_id:
            bits.append(self.evidence_id)
        return ":".join(bits)


@dataclass
class ResourceTrace:
    resource_id: str
    observations: List[Observation] = field(default_factory=list)
    link_paths: List[LinkPath] = field(default_factory=list)
    activity_ids: List[str] = field(default_factory=list)
    # Latest time at or before the audit cutoff at which the case is known to
    # have reached this resource.  A snapshot can only prove absence if it was
    # taken after this moment.
    known_at: str = ""

    def note_known_at(self, value: str) -> None:
        if value and value > self.known_at:
            self.known_at = value

    @property
    def system_id(self) -> str:
        if self.observations:
            return self.observations[-1].system_id
        return ""

    @property
    def category(self) -> str:
        if self.observations:
            return self.observations[-1].record_type
        return ""

    def add(self, obs: Observation, path: LinkPath) -> None:
        if obs not in self.observations:
            self.observations.append(obs)
        self.link_paths.append(path)

    def best_path(self) -> str:
        if not self.link_paths:
            return ""
        return self.link_paths[0].describe()


@dataclass
class CaseTrace:
    case_id: str
    user_id: str
    resources: Dict[str, ResourceTrace] = field(default_factory=dict)
    cluster: Dict[str, Any] = field(default_factory=dict)

    def add_observation(self, obs: Observation, path: LinkPath) -> None:
        trace = self.resources.setdefault(obs.resource_id, ResourceTrace(obs.resource_id))
        trace.add(obs, path)

    def link_resource(self, resource_id: str, path: LinkPath) -> None:
        trace = self.resources.setdefault(resource_id, ResourceTrace(resource_id))
        trace.link_paths.append(path)

    def link_summary(self) -> List[str]:
        return [
            f"{rid}={trace.best_path()}"
            for rid, trace in sorted(self.resources.items(), key=lambda kv: natural_sort_key(kv[0]))
            if trace.link_paths
        ]


def _parse_resource_ids(text: str) -> Set[str]:
    return {m.group(1) for m in RESOURCE_RE.finditer(text or "")}


#: Families whose resources can disappear without leaving an identifier
#: behind, plus the dispatch event that names them.  Restricted to families
#: where the study in ``notes/LINK_RULE_STUDY.md`` showed no false positives.
WORKFLOW_FAMILIES: Dict[str, Tuple[str, Set[str]]] = {
    "account": ("account_service", {"DELETE_RECORD"}),
    "analytics": ("analytics_platform", {"ANONYMIZE_RECORD"}),
}

#: Minutes around ``reported_at`` searched for a unique dispatch.
#:
#: Swept 10-90 minutes and a widening 15->30->60->90 fallback against the
#: sample answers (``notes/LINK_RULE_STUDY.md``).  A single tight window is
#: the only setting with no wrong links: 15 minutes adds 6 correct account
#: links and 0 wrong ones, versus 15 correct and 11 wrong for the widening
#: fallback.  Wider windows pick up neighbouring requests in the same batch.
WORKFLOW_WINDOW_MINUTES = 15

#: A resource family that the case already reaches does not get a second one.
FAMILY_CATEGORIES = {
    "account": {"USER_PROFILE", "ACCOUNT_TOMBSTONE"},
    "analytics": {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"},
}


def resource_family(resource_id: str) -> str:
    for family in sorted(WORKFLOW_FAMILIES, key=len, reverse=True):
        if resource_id.startswith(family + "_"):
            return family
    return ""


def _seconds_between(left: str, right: str) -> float:
    from datetime import datetime

    def parse(value: str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    try:
        return (parse(left) - parse(right)).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


class CaseLinker:
    def __init__(
        self,
        index: EvidenceIndex,
        activity_rows: List[Dict[str, str]],
        user_identities: List[Dict[str, str]],
        user_audit_log: List[Dict[str, str]],
    ) -> None:
        self.index = index
        self.activity_rows = activity_rows
        self.user_identities = user_identities
        self.user_audit_log = user_audit_log
        self._activity_by_resource: Dict[str, List[Dict[str, str]]] = {}
        for row in activity_rows:
            rid = (row.get("resource_id") or "").strip()
            if rid:
                self._activity_by_resource.setdefault(rid, []).append(row)
        # Activity rows that explicitly link an identity to a resource.
        self._identity_links: List[Tuple[str, str, str, str]] = []
        for row in activity_rows:
            if row.get("event_type") != "LINK_RESOURCE_IDENTITY":
                continue
            details = row.get("details") or ""
            rid = (row.get("resource_id") or "").strip()
            if not rid:
                continue
            linked_at = row.get("event_time", "")
            for key, values in prefixed_identifiers(details).items():
                for value in values:
                    self._identity_links.append((key, value, rid, linked_at))

        # Workflow dispatches, indexed by resource family.  These are the
        # only rows that name a resource which leaves no identifier residue
        # behind (a deleted account, an anonymized analytics profile), so a
        # unique dispatch in the case's own workflow window is the workflow's
        # statement about that resource.
        self._dispatches: Dict[str, List[Dict[str, str]]] = {}
        for row in activity_rows:
            if row.get("source_system") != "deletion_worker":
                continue
            rid = (row.get("resource_id") or "").strip()
            family = resource_family(rid)
            if not family:
                continue
            target, types = WORKFLOW_FAMILIES[family]
            if row.get("target_system") != target or row.get("event_type") not in types:
                continue
            self._dispatches.setdefault(family, []).append(row)
        for rows in self._dispatches.values():
            rows.sort(key=lambda row: (row.get("event_time", ""), row.get("activity_id", "")))

    # -- cluster -----------------------------------------------------------

    def cluster_for(self, email: str) -> Dict[str, Any]:
        identity = resolve_identity(email, self.user_identities, self.user_audit_log)
        emails = {e.lower() for e in identity.get("all_emails", []) if e}
        phones = set()
        for phone in identity.get("all_phones", []):
            digits = re.sub(r"\D", "", phone or "")
            if len(digits) >= 7:
                phones.add(digits)
        hashes = {h.lower() for h in identity.get("all_email_hashes", []) if h}
        return {
            "user_id": identity.get("user_id", ""),
            "emails": emails,
            "phones": phones,
            "hashes": hashes,
            "names": {n.strip().lower() for n in identity.get("all_names", []) if n},
            "raw": identity,
        }

    def _identifier_match(self, obs: Observation, cluster: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        for key, value in obs.ident_values():
            if key == "email" and value in cluster["emails"]:
                return ("email", value)
            if key == "phone" and value in cluster["phones"]:
                return ("phone", value)
            if key == "email_hash" and value in cluster["hashes"]:
                return ("email_hash", value)
            if key == "user_id" and value == cluster["user_id"]:
                return ("user_id", value)
        return None

    # -- linking -----------------------------------------------------------

    def _eligible(self, obs: Observation, audit_at: str) -> bool:
        if obs.captured_at and obs.captured_at > audit_at:
            return False
        if obs.observed_at and obs.observed_at > audit_at:
            return False
        return True

    def _pre_request_screenshot(self, obs: Observation, case: Dict[str, str]) -> bool:
        """A screenshot taken before the deletion request is historical only.

        It can ground identity, but it cannot prove that a record survived the
        deletion workflow that the request started.  Screenshots captured
        during the request window remain fully admissible.
        """
        if obs.source_kind != "png":
            return False
        requested_at = case.get("requested_at", "")
        return bool(requested_at and obs.captured_at and obs.captured_at < requested_at)

    def _conflicts_with_subject(self, obs: Observation, cluster: Dict[str, Any]) -> bool:
        """True when a screenshot's own strong identifiers exclude the subject.

        Resource-scoped attachment is safe for identifier-free rows, but a
        screenshot that names a different person must not become state for
        this case merely because a catalog row points at the same resource.
        """
        if obs.source_kind != "png":
            return False
        strong = []
        for key in ("email", "phone", "email_hash", "user_id"):
            for value in obs.identifiers.get(key, set()):
                strong.append((key, value))
        if not strong:
            return False
        for key, value in strong:
            if key == "email" and value in cluster["emails"]:
                return False
            if key == "phone" and value in cluster["phones"]:
                return False
            if key == "email_hash" and value in cluster["hashes"]:
                return False
            if key == "user_id" and value == cluster["user_id"]:
                return False
        return True

    def _family_linked(self, trace: CaseTrace, family: str) -> bool:
        categories = FAMILY_CATEGORIES.get(family, set())
        for rid, resource_trace in trace.resources.items():
            if resource_family(rid) == family:
                return True
            if categories and any(obs.record_type in categories for obs in resource_trace.observations):
                return True
        return False

    def _link_workflow_dispatches(
        self, trace: CaseTrace, case: Dict[str, str], audit_at: str
    ) -> None:
        """Link a resource only when the workflow names exactly one candidate.

        Identity resolution cannot reach a resource that was deleted (account)
        or anonymized (analytics) before it was captured: no identifier
        survives on the record, and the evidence that proves the final state
        contains only the bare resource id.  The deletion workflow's own
        dispatch is then the only grounded statement that the resource belongs
        to this request.  Ambiguous windows (several cases dispatched into the
        same batch) are rejected rather than guessed.
        """
        reported_at = case.get("reported_at", "")
        if not reported_at:
            return
        for family in WORKFLOW_FAMILIES:
            if self._family_linked(trace, family):
                continue
            candidates = []
            for row in self._dispatches.get(family, []):
                event_time = row.get("event_time", "")
                if not event_time or event_time > audit_at:
                    continue
                delta = _seconds_between(event_time, reported_at)
                if delta == float("inf") or abs(delta) > WORKFLOW_WINDOW_MINUTES * 60:
                    continue
                if row["resource_id"] in trace.resources:
                    continue
                candidates.append(row)
            if len(candidates) != 1:
                continue
            row = candidates[0]
            rid = row["resource_id"]
            trace.link_resource(
                rid,
                LinkPath(
                    resource_id=rid,
                    reason="workflow_dispatch",
                    identifier=row.get("activity_id", ""),
                    evidence_id=row.get("activity_id", ""),
                ),
            )
            trace.resources[rid].note_known_at(row.get("event_time", ""))
            trace.resources[rid].activity_ids.append(row.get("activity_id", ""))

    def link_case(self, case: Dict[str, str], audit_at: str) -> CaseTrace:
        cluster = self.cluster_for(case.get("email", ""))
        trace = CaseTrace(case_id=case["case_id"], user_id=cluster["user_id"], cluster=cluster)

        # 1. Direct evidence observations whose own identifiers match.
        #    Identity discovery is not itself time-bounded: the current
        #    identity snapshot and post-cutoff artifacts may reveal which
        #    resource id belongs to the subject.  What the artifact says about
        #    the record's *state* is still gated on ``audit_at`` by
        #    :mod:`code.ghost.state`.
        for key in ("email", "phone", "email_hash", "user_id"):
            values = cluster["emails"] if key == "email" else (
                cluster["phones"] if key == "phone" else cluster["hashes"] if key == "email_hash" else {cluster["user_id"]}
            )
            for value in values:
                if not value:
                    continue
                matched = [
                    (self._eligible(obs, audit_at), obs)
                    for obs in self.index.lookup(key, value)
                ]
                # Prefer observations that are admissible as state proof so the
                # reported link reason/evidence names the strongest source.
                matched.sort(key=lambda item: (not item[0], item[1].sort_key()))
                for eligible, obs in matched:
                    if self._pre_request_screenshot(obs, case):
                        continue
                    trace.add_observation(
                        obs,
                        LinkPath(
                            resource_id=obs.resource_id,
                            reason=f"identifier:{key}" if eligible else f"identifier_late:{key}",
                            identifier=f"{key}={value}",
                            evidence_id=obs.file_id,
                        ),
                    )
                    if eligible:
                        known = obs.observed_at or obs.captured_at
                        trace.resources[obs.resource_id].note_known_at(known)

        # 2. Explicit data-catalog links.
        for key, value, rid, linked_at in self._identity_links:
            if linked_at and linked_at > audit_at:
                continue
            matched = (
                (key == "email" and value in cluster["emails"])
                or (key == "phone" and value in cluster["phones"])
                or (key == "email_hash" and value in cluster["hashes"])
                or (key == "user_id" and value == cluster["user_id"])
            )
            if matched:
                activity_ids = [
                    row["activity_id"]
                    for row in self._activity_by_resource.get(rid, [])
                    if row.get("event_type") == "LINK_RESOURCE_IDENTITY"
                ]
                trace.link_resource(
                    rid,
                    LinkPath(
                        resource_id=rid,
                        reason="catalog_link",
                        identifier=f"{key}={value}",
                        evidence_id=activity_ids[0] if activity_ids else "",
                    ),
                )
                trace.resources[rid].note_known_at(linked_at)

        # 3. Resource-id propagation: workflow rows that name a downstream copy.
        for rid in list(trace.resources):
            for row in self._activity_by_resource.get(rid, []):
                event_time = row.get("event_time", "")
                if event_time and event_time > audit_at:
                    continue
                details = row.get("details") or ""
                if "downstream resource" not in details.lower():
                    continue
                for downstream in _parse_resource_ids(details) - {rid}:
                    trace.link_resource(
                        downstream,
                        LinkPath(
                            resource_id=downstream,
                            reason="activity_propagation",
                            identifier=row.get("activity_id", ""),
                            evidence_id=row.get("activity_id", ""),
                        ),
                    )
                    trace.resources[downstream].note_known_at(event_time)

        # 4. Unique workflow-dispatch discovery (deleted accounts, anonymized
        #    analytics profiles).  Ambiguity is rejected, never guessed.
        self._link_workflow_dispatches(trace, case, audit_at)

        # 5. Resource-scoped evidence attach: once a resource id is grounded by
        #    any link, every observation that names that resource belongs to
        #    the case as well.  This is how a 404/readback row (which by design
        #    carries no identifier) becomes admissible state evidence.
        for rid in list(trace.resources):
            for obs in self.index.by_resource.get(rid, []):
                if obs in trace.resources[rid].observations:
                    continue
                if self._conflicts_with_subject(obs, cluster):
                    continue
                if self._pre_request_screenshot(obs, case):
                    continue
                eligible = self._eligible(obs, audit_at)
                trace.add_observation(
                    obs,
                    LinkPath(
                        resource_id=rid,
                        reason="resource_observation" if eligible else "resource_observation_late",
                        identifier=rid,
                        evidence_id=obs.file_id,
                    ),
                )
                if eligible:
                    trace.resources[rid].note_known_at(obs.observed_at or obs.captured_at)
        return trace


def load_activity_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
