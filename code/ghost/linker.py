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

    def link_case(self, case: Dict[str, str], audit_at: str) -> CaseTrace:
        cluster = self.cluster_for(case.get("email", ""))
        trace = CaseTrace(case_id=case["case_id"], user_id=cluster["user_id"], cluster=cluster)

        # 1. Direct evidence observations whose own identifiers match.
        for key in ("email", "phone", "email_hash", "user_id"):
            values = cluster["emails"] if key == "email" else (
                cluster["phones"] if key == "phone" else cluster["hashes"] if key == "email_hash" else {cluster["user_id"]}
            )
            for value in values:
                if not value:
                    continue
                for obs in self.index.lookup(key, value):
                    if obs.captured_at > audit_at:
                        continue
                    if obs.observed_at and obs.observed_at > audit_at:
                        continue
                    trace.add_observation(
                        obs,
                        LinkPath(
                            resource_id=obs.resource_id,
                            reason=f"identifier:{key}",
                            identifier=f"{key}={value}",
                            evidence_id=obs.file_id,
                        ),
                    )
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

        # 4. Workflow-window discovery for the subject's account profile.
        #    The account id itself is not an identifier, but a single
        #    unambiguous deletion dispatch within half an hour of the reported
        #    completion is the workflow's own statement about this case.  It
        #    is used only to locate the resource; state still comes from
        #    evidence captured at or before audit_at.
        if not any(
            trace.resources[rid].category in {"USER_PROFILE", "ACCOUNT_TOMBSTONE"}
            for rid in trace.resources
        ):
            reported_at = case.get("reported_at", "")
            if reported_at:
                window = 30 * 60
                candidates = set()
                for row in self.activity_rows:
                    if row.get("event_type") != "DELETE_RECORD":
                        continue
                    if row.get("source_system") != "deletion_worker":
                        continue
                    rid = (row.get("resource_id") or "").strip()
                    if not rid.startswith("account_"):
                        continue
                    event_time = row.get("event_time", "")
                    if not event_time or event_time > audit_at:
                        continue
                    if abs(_seconds_between(event_time, reported_at)) <= window:
                        candidates.add((rid, event_time))
                if len(candidates) == 1:
                    rid, deleted_at = candidates.pop()
                    trace.link_resource(
                        rid,
                        LinkPath(
                            resource_id=rid,
                            reason="workflow_window",
                            identifier=reported_at,
                            evidence_id="",
                        ),
                    )
                    trace.resources[rid].note_known_at(deleted_at)
        return trace


def load_activity_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
