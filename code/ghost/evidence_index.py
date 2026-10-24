"""Normalized index of every participant-visible evidence artifact.

Each file listed in ``dataset/evidence_files.csv`` is parsed into flat
``Observation`` records.  An observation is one factual statement about one
``resource_id`` at one point in time: it exists (with attributes), it is
explicitly proven absent, or it exists in a treated state (redacted,
anonymized, disabled, blocked).

Nothing in this module knows about cases or users.  Linking is the job of
:mod:`code.ghost.linker`; policy is :mod:`code.ghost.rules`.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from code.ghost.loaders import natural_sort_key

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_RE = re.compile(r"(?<![A-Za-z0-9_.+\-])user_\d+(?![A-Za-z0-9_])")
HASH_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])")

RESOURCE_PREFIXES = (
    "account",
    "analytics",
    "audit_record",
    "backup",
    "cache",
    "data_flow",
    "email_delivery",
    "export",
    "legal_hold",
    "marketing",
    "object",
    "search",
    "support",
    "tombstone",
)

RESOURCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.])((?:%s)_\d+)(?![A-Za-z0-9_])"
    % "|".join(sorted(RESOURCE_PREFIXES, key=len, reverse=True))
)

PHONE_RE = re.compile(r"\+\d[\d\s().\-]{6,}\d")

CATEGORY_BY_PREFIX = {
    "account": "USER_PROFILE",
    "analytics": "ANALYTICS_PROFILE",
    "audit_record": "SECURITY_AUDIT_LOG",
    "backup": "BACKUP_ARCHIVE",
    "cache": "CACHE_ENTRY",
    "data_flow": "DATA_FLOW",
    "email_delivery": "EMAIL_DELIVERY_LOG",
    "export": "USER_EXPORT",
    "legal_hold": "LEGAL_HOLD_RECORD",
    "marketing": "MARKETING_PROFILE",
    "object": "SUPPORT_ATTACHMENT",
    "search": "SEARCH_INDEX_ENTRY",
    "support": "SUPPORT_MESSAGE",
    "tombstone": "ACCOUNT_TOMBSTONE",
}

SYSTEM_BY_PREFIX = {
    "account": "account_service",
    "analytics": "analytics_platform",
    "audit_record": "security_service",
    "backup": "backup_service",
    "cache": "cache_service",
    "data_flow": "integration_service",
    "email_delivery": "email_delivery_service",
    "export": "export_service",
    "legal_hold": "legal_service",
    "marketing": "marketing_platform",
    "object": "object_storage",
    "search": "search_service",
    "support": "support_platform",
    "tombstone": "identity_service",
}

SYSTEM_ALIASES = {
    "backup_restore_service": "backup_service",
    "customer_account_service": "account_service",
    "identity_service": "identity_service",
    "support_storage_service": "support_platform",
    "object_store": "object_storage",
    "archive_service": "backup_service",
}

IDENTIFIER_KEYS = {
    "user_id",
    "customer_reference",
    "subject_reference",
    "email",
    "owner_email",
    "customer_email",
    "requester_email",
    "uploaded_by",
    "email_hash",
    "phone",
    "owner_phone",
    "requester_phone",
    "full_name",
    "requester_name",
    "display_name",
    "lookup_key",
    "match_key",
    "scan_key",
    "subject_selector",
    "lookup_value",
    "correlation_key",
    "subject_ref",
    "subject_key",
    "owner_key",
}

IDENTIFIER_ALIASES = {
    "user": "user_id",
    "userid": "user_id",
    "subject": "subject_reference",
    "requester": "requester_email",
    "owner": "owner_email",
    "emailaddress": "email",
    "subject_ref": "subject_reference",
    "subject_key": "subject_reference",
    "owner_key": "owner_email",
    "correlation_key": "lookup_key",
}

STATE_TOKENS = {
    "FOUND",
    "NOT_FOUND",
    "PRESENT",
    "ABSENT",
    "IDENTIFIABLE",
    "ANONYMIZED",
    "REDACTED",
    "ACTIVE",
    "DISABLED",
    "BLOCKED",
    "DELETED",
}

TREATED_STATES = {"ANONYMIZED", "REDACTED", "DISABLED", "BLOCKED"}


def norm_system(value: Optional[str]) -> str:
    value = (value or "").strip().strip('"')
    return SYSTEM_ALIASES.get(value, value)


def norm_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip().strip('"').lower()
    if not EMAIL_RE.fullmatch(value):
        return None
    return value


def norm_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 7:
        return None
    return digits


def norm_user(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip().strip('"')
    m = USER_RE.fullmatch(value)
    return m.group(0) if m else None


def norm_hash(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip().strip('"').lower()
    return value if HASH_RE.fullmatch(value) else None


def norm_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip().lower()
    if not value or value in {"null", "none", "n/a", "no direct identifier"}:
        return None
    if len(value) < 3:
        return None
    return value


def classify_identifier(key: str, value: Any) -> Optional[tuple]:
    """Return ``(canonical_key, normalized_value)`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "no direct identifier", "-"}:
        return None
    key = IDENTIFIER_ALIASES.get(key.lower(), key.lower())

    if key in {"email", "owner_email", "customer_email", "requester_email"} or "@" in text:
        email = norm_email(text)
        return ("email", email) if email else None
    if key in {"phone", "owner_phone", "requester_phone"}:
        phone = norm_phone(text)
        return ("phone", phone) if phone else None
    if key in {"email_hash"}:
        h = norm_hash(text)
        return ("email_hash", h) if h else None
    if key in {"user_id", "customer_reference", "subject_reference", "subject_selector"}:
        user = norm_user(text)
        if user:
            return ("user_id", user)
        email = norm_email(text)
        if email:
            return ("email", email)
        h = norm_hash(text)
        return ("email_hash", h) if h else None
    if key in {"full_name", "requester_name", "display_name", "uploaded_by"}:
        email = norm_email(text)
        if email:
            return ("email", email)
        name = norm_name(text)
        return ("name", name) if name else None
    if key in {"lookup_key", "match_key", "scan_key", "lookup_value", "correlation_key"}:
        user = norm_user(text)
        if user:
            return ("user_id", user)
        email = norm_email(text)
        if email:
            return ("email", email)
        h = norm_hash(text)
        if h:
            return ("email_hash", h)
        phone = norm_phone(text)
        if phone and text.startswith("+"):
            return ("phone", phone)
        return None
    return None


def prefixed_identifiers(text: str) -> Dict[str, set]:
    """Extract identifiers from free text using token boundaries."""
    out: Dict[str, set] = {"email": set(), "user_id": set(), "email_hash": set(), "phone": set()}
    for m in EMAIL_RE.finditer(text or ""):
        email = norm_email(m.group(0))
        if email:
            out["email"].add(email)
    for m in USER_RE.finditer(text or ""):
        out["user_id"].add(m.group(0))
    for m in HASH_RE.finditer(text or ""):
        out["email_hash"].add(m.group(0).lower())
    for m in PHONE_RE.finditer(text or ""):
        phone = norm_phone(m.group(0))
        if phone:
            out["phone"].add(phone)
    return {k: v for k, v in out.items() if v}


def prefix_of(resource_id: str) -> str:
    for prefix in sorted(RESOURCE_PREFIXES, key=len, reverse=True):
        if resource_id.startswith(prefix + "_"):
            return prefix
    return ""


def category_for(resource_id: str, fallback: str = "") -> str:
    return CATEGORY_BY_PREFIX.get(prefix_of(resource_id), fallback)


def system_for(resource_id: str, fallback: str = "") -> str:
    return SYSTEM_BY_PREFIX.get(prefix_of(resource_id), fallback)


# ---------------------------------------------------------------------------
# Observation model
# ---------------------------------------------------------------------------


@dataclass
class Observation:
    file_id: str
    captured_at: str
    observed_at: str
    system_id: str
    store: str
    collection: str
    record_type: str
    resource_id: str
    identifiers: Dict[str, set] = field(default_factory=dict)
    attrs: Dict[str, Any] = field(default_factory=dict)
    present: Optional[bool] = None
    raw_state: str = ""
    source_kind: str = ""
    line_no: int = 0

    def ident_values(self) -> Iterable[tuple]:
        for key, values in self.identifiers.items():
            for value in values:
                yield key, value

    def sort_key(self):
        return (
            self.observed_at or "",
            self.captured_at or "",
            natural_sort_key(self.file_id),
        )


@dataclass
class Coverage:
    """A file asserts that it inspected a system/store at a point in time."""

    file_id: str
    captured_at: str
    system_id: str
    store: str
    observed_at: str


class EvidenceIndex:
    def __init__(self) -> None:
        self.observations: List[Observation] = []
        self.coverage: List[Coverage] = []
        self.files: Dict[str, Dict[str, str]] = {}
        self.by_identifier: Dict[tuple, List[Observation]] = {}
        self.by_resource: Dict[str, List[Observation]] = {}
        self._indexed = False

    def add(self, obs: Observation) -> None:
        if not obs.resource_id:
            return
        self.observations.append(obs)

    def add_coverage(self, cov: Coverage) -> None:
        self.coverage.append(cov)

    def build(self) -> "EvidenceIndex":
        self.by_identifier = {}
        self.by_resource = {}
        for obs in self.observations:
            self.by_resource.setdefault(obs.resource_id, []).append(obs)
            for key, value in obs.ident_values():
                self.by_identifier.setdefault((key, value), []).append(obs)
        for values in self.by_resource.values():
            values.sort(key=lambda o: o.sort_key())
        self._indexed = True
        return self

    def lookup(self, key: str, value: str) -> List[Observation]:
        return list(self.by_identifier.get((key, value), []))


# ---------------------------------------------------------------------------
# SQL snapshots
# ---------------------------------------------------------------------------

TABLE_CATEGORY_RULES = [
    ("customer_profiles", "USER_PROFILE"),
    ("deleted_customer", "ACCOUNT_TOMBSTONE"),
    ("tombstone", "ACCOUNT_TOMBSTONE"),
    ("search", "SEARCH_INDEX_ENTRY"),
    ("analytics", "ANALYTICS_PROFILE"),
    ("support_record", "SUPPORT_MESSAGE"),
    ("ticket_attachment", "SUPPORT_ATTACHMENT"),
    ("support_conversation", "SUPPORT_MESSAGE"),
    ("customer_exports", "USER_EXPORT"),
    ("export_job", "USER_EXPORT"),
    ("connector", "DATA_FLOW"),
    ("backup", "BACKUP_ARCHIVE"),
    ("security_audit", "SECURITY_AUDIT_LOG"),
    ("legal", "LEGAL_HOLD_RECORD"),
    ("marketing", "MARKETING_PROFILE"),
    ("cache", "CACHE_ENTRY"),
]

TABLE_SYSTEM_RULES = [
    ("customer_profiles", "account_service"),
    ("deleted_customer", "identity_service"),
    ("tombstone", "identity_service"),
    ("search", "search_service"),
    ("analytics", "analytics_platform"),
    ("support", "support_platform"),
    ("ticket", "support_platform"),
    ("export", "export_service"),
    ("connector", "integration_service"),
    ("backup", "backup_service"),
    ("security_audit", "security_service"),
    ("legal", "legal_service"),
    ("marketing", "marketing_platform"),
    ("cache", "cache_service"),
]


def _table_category(table: str, row: Dict[str, Any]) -> str:
    lower = table.lower()
    for token, category in TABLE_CATEGORY_RULES:
        if token in lower:
            if token == "customer_profiles" and str(row.get("account_status", "")).upper() in {
                "DELETED",
                "TOMBSTONED",
                "TOMBSTONE",
            }:
                return "ACCOUNT_TOMBSTONE"
            return category
    origin = row.get("origin_system") or ""
    collection = row.get("collection_name") or ""
    hint = f"{origin} {collection}".lower()
    for token, category in TABLE_CATEGORY_RULES:
        if token in hint:
            return category
    prefix = prefix_of(str(row.get("resource_id", "")))
    return CATEGORY_BY_PREFIX.get(prefix, "")


def _table_system(table: str, row: Dict[str, Any], fallback: str) -> str:
    lower = table.lower()
    for token, system in TABLE_SYSTEM_RULES:
        if token in lower:
            return system
    if row.get("origin_system"):
        return norm_system(str(row["origin_system"]))
    return system_for(str(row.get("resource_id", "")), fallback)


def _flatten_record(record: Any, prefix: str = "") -> Iterable[tuple]:
    """Yield ``(leaf_key, value)`` pairs from nested JSON structures."""
    if isinstance(record, dict):
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                yield from _flatten_record(value, key)
            else:
                yield key, value
    elif isinstance(record, list):
        for item in record:
            yield from _flatten_record(item, prefix)
    else:
        yield prefix, record


def _collect_identifiers(record: Any, extra_text: str = "") -> Dict[str, set]:
    found: Dict[str, set] = {}

    def put(key: str, value: str) -> None:
        found.setdefault(key, set()).add(value)

    for key, value in _flatten_record(record):
        if key is None:
            continue
        classified = classify_identifier(str(key), value)
        if classified:
            put(*classified)
    if extra_text:
        for key, values in prefixed_identifiers(extra_text).items():
            for value in values:
                put(key, value)
    return found


def _parse_sql(path: str, file_id: str, captured_at: str, root: str) -> tuple:
    observations: List[Observation] = []
    coverage: List[Coverage] = []
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(text)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
            )
        ]
        snapshot_at = captured_at
        if "snapshot_scope" in tables:
            try:
                row = conn.execute("SELECT captured_at FROM snapshot_scope LIMIT 1").fetchone()
                if row and row[0]:
                    snapshot_at = row[0]
            except sqlite3.Error:
                pass
        for table in tables:
            if table == "snapshot_scope":
                continue
            try:
                cursor = conn.execute(f'SELECT * FROM "{table}"')
            except sqlite3.Error:
                continue
            columns = [d[0] for d in cursor.description or []]
            systems = set()
            row_count = 0
            for raw in cursor.fetchall():
                row = dict(zip(columns, raw))
                resource_id = str(row.get("resource_id") or "")
                if not resource_id:
                    continue
                row_count += 1
                record_json = row.get("record_json")
                embedded: Dict[str, Any] = {}
                if isinstance(record_json, str) and record_json.strip().startswith("{"):
                    try:
                        parsed = json.loads(record_json)
                        if isinstance(parsed, dict):
                            embedded = parsed
                    except json.JSONDecodeError:
                        embedded = {}
                if embedded:
                    merged_row = dict(embedded)
                    merged_row.update({k: v for k, v in row.items() if k not in {"record_json"}})
                    row = merged_row
                system = _table_system(table, row, "")
                systems.add(system)
                category = _table_category(table, row)
                text_fields = " ".join(
                    str(row.get(k) or "")
                    for k in (
                        "message_excerpt",
                        "message_text",
                        "file_name",
                        "object_key",
                        "archive_key",
                        "document",
                    )
                )
                identifiers = _collect_identifiers(row, text_fields)
                observed_at = (
                    row.get("updated_at")
                    or row.get("captured_at")
                    or row.get("recorded_at")
                    or row.get("created_at")
                    or snapshot_at
                )
                attrs = {
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "resource_id",
                        "user_id",
                        "customer_reference",
                        "subject_reference",
                        "email",
                        "phone",
                        "email_hash",
                        "full_name",
                        "requester_name",
                        "requester_email",
                        "requester_phone",
                        "owner_email",
                        "owner_phone",
                        "customer_email",
                        "display_name",
                    }
                }
                observations.append(
                    Observation(
                        file_id=file_id,
                        captured_at=captured_at,
                        observed_at=str(observed_at),
                        system_id=system,
                        store=table,
                        collection=table,
                        record_type=category or _table_category(table, row),
                        resource_id=resource_id,
                        identifiers=identifiers,
                        attrs=attrs,
                        present=True,
                        raw_state="FOUND",
                        source_kind="sql",
                    )
                )
            for system in systems:
                coverage.append(
                    Coverage(
                        file_id=file_id,
                        captured_at=captured_at,
                        system_id=system,
                        store=table,
                        observed_at=str(snapshot_at),
                    )
                )
            if row_count == 0:
                # An empty table still proves the store was inspected and held
                # no row at snapshot time, which is valid absence evidence.
                system = _table_system(table, {}, "")
                if system:
                    coverage.append(
                        Coverage(
                            file_id=file_id,
                            captured_at=captured_at,
                            system_id=system,
                            store=table,
                            observed_at=str(snapshot_at),
                        )
                    )
    finally:
        conn.close()
    return observations, coverage


# ---------------------------------------------------------------------------
# JSON artifacts
# ---------------------------------------------------------------------------

SERVICE_COLLECTION_CATEGORY = {
    "profile_lookups": "USER_PROFILE",
    "profiles": "ANALYTICS_PROFILE",
    "restore_entries": "BACKUP_ARCHIVE",
    "exports": "USER_EXPORT",
    "connectors": "DATA_FLOW",
    "index_queries": "SEARCH_INDEX_ENTRY",
    "audit_records": "SECURITY_AUDIT_LOG",
    "tickets": "SUPPORT_MESSAGE",
    "jobs": "USER_EXPORT",
    "attachments": "SUPPORT_ATTACHMENT",
}

SNAPSHOT_COLLECTION_CATEGORY = {
    "customer_profiles": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "backup_catalog": "BACKUP_ARCHIVE",
    "customer_export_jobs": "USER_EXPORT",
    "connector_configurations": "DATA_FLOW",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "support_conversations": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "retained_order_records": "LEGAL_HOLD_RECORD",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
}

SNAPSHOT_COLLECTION_SYSTEM = {
    "backup_restore_service": "backup_service",
}


def _state_from_token(token: str) -> Optional[bool]:
    token = (token or "").upper()
    if token in {"NOT_FOUND", "ABSENT", "DELETED", "MISSING"}:
        return False
    if token in STATE_TOKENS:
        return True
    return None


def _parse_json(path: str, file_id: str, captured_at: str, root: str) -> tuple:
    observations: List[Observation] = []
    coverage: List[Coverage] = []
    try:
        data = json.load(open(path, "r", encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return observations, coverage

    def add_record(
        record: Dict[str, Any],
        system: str,
        collection: str,
        category: str,
        observed_at: str,
        present: Optional[bool] = None,
        raw_state: str = "",
    ) -> None:
        resource_id = str(record.get("resource_id") or "")
        if not resource_id:
            return
        identifiers = _collect_identifiers(record)
        attrs = {}
        for key, value in _flatten_record(record):
            if key in {
                "resource_id",
                "user_id",
                "customer_reference",
                "subject_reference",
                "email",
                "phone",
                "email_hash",
                "full_name",
                "requester_name",
                "requester_email",
                "requester_phone",
                "owner_email",
                "owner_phone",
                "customer_email",
                "display_name",
                "lookup_value",
            }:
                continue
            if isinstance(value, (str, int, float, bool)) and key:
                attrs[str(key)] = value
        if present is None:
            present = True
        observations.append(
            Observation(
                file_id=file_id,
                captured_at=captured_at,
                observed_at=str(observed_at or captured_at),
                system_id=norm_system(system) or system_for(resource_id),
                store=collection,
                collection=collection,
                record_type=category or category_for(resource_id),
                resource_id=resource_id,
                identifiers=identifiers,
                attrs=attrs,
                present=present,
                raw_state=raw_state or ("FOUND" if present else "NOT_FOUND"),
                source_kind="json",
            )
        )

    if isinstance(data, dict) and "snapshots" in data and isinstance(data["snapshots"], list):
        for snapshot in data["snapshots"]:
            if not isinstance(snapshot, dict):
                continue
            system = norm_system(snapshot.get("data_store"))
            collection = str(snapshot.get("collection") or "")
            snap_at = str(snapshot.get("captured_at") or captured_at)
            records = snapshot.get("records") or []
            if collection == "operational_record_history":
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    state = str(record.get("result") or "")
                    present = _state_from_token(state)
                    resource_id = str(record.get("resource_id") or "")
                    row_system = norm_system(record.get("system")) or system_for(resource_id)
                    record_type = str(record.get("record_type") or category_for(resource_id))
                    add_record(
                        record,
                        row_system,
                        collection,
                        record_type,
                        str(record.get("recorded_at") or snap_at),
                        present=present,
                        raw_state=state,
                    )
                coverage.append(
                    Coverage(
                        file_id=file_id,
                        captured_at=captured_at,
                        system_id=system,
                        store=collection,
                        observed_at=snap_at,
                    )
                )
                continue
            coverage.append(
                Coverage(
                    file_id=file_id,
                    captured_at=captured_at,
                    system_id=system,
                    store=collection,
                    observed_at=snap_at,
                )
            )
            for record in records:
                if not isinstance(record, dict):
                    continue
                add_record(
                    record,
                    system,
                    collection,
                    SNAPSHOT_COLLECTION_CATEGORY.get(collection, ""),
                    snap_at,
                )
        return observations, coverage

    if isinstance(data, dict) and "service_exports" in data and isinstance(data["service_exports"], dict):
        for service, payload in data["service_exports"].items():
            if not isinstance(payload, dict):
                continue
            for key, block in payload.items():
                if not isinstance(block, list):
                    continue
                category = SERVICE_COLLECTION_CATEGORY.get(key, "")
                for record in block:
                    if not isinstance(record, dict):
                        continue
                    resource_id = str(record.get("resource_id") or "")
                    present = True
                    raw_state = "FOUND"
                    if key == "profile_lookups":
                        status = record.get("status_code")
                        present = status in (200, "200")
                        raw_state = "FOUND" if present else "NOT_FOUND"
                        profile = record.get("profile")
                        if isinstance(profile, dict):
                            merged = dict(record)
                            merged.update(profile)
                            record = merged
                    elif key == "index_queries":
                        hits = record.get("hits") or {}
                        total = hits.get("total") if isinstance(hits, dict) else None
                        docs = hits.get("documents") if isinstance(hits, dict) else None
                        present = bool(total) or bool(docs)
                        raw_state = "FOUND" if present else "NOT_FOUND"
                        if isinstance(docs, list):
                            merged = dict(record)
                            for doc in docs:
                                if isinstance(doc, dict):
                                    merged.update(doc)
                            record = merged
                    add_record(
                        record,
                        service,
                        key,
                        category or category_for(resource_id),
                        str(record.get("observed_at") or captured_at),
                        present=present,
                        raw_state=raw_state,
                    )
                coverage.append(
                    Coverage(
                        file_id=file_id,
                        captured_at=captured_at,
                        system_id=norm_system(service),
                        store=key,
                        observed_at=captured_at,
                    )
                )
        return observations, coverage

    # Dedicated record dumps: walk for resource-bearing dicts.
    seen: set = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            resource_id = node.get("resource_id")
            if isinstance(resource_id, str) and RESOURCE_RE.fullmatch(resource_id):
                observed_at = (
                    node.get("observed_at")
                    or node.get("recorded_at")
                    or node.get("updated_at")
                    or node.get("created_at")
                    or captured_at
                )
                key = (resource_id, str(observed_at))
                if key not in seen:
                    seen.add(key)
                    present = True
                    raw_state = "FOUND"
                    for token_key in ("result", "state", "status"):
                        if token_key in node:
                            parsed = _state_from_token(str(node[token_key]))
                            if parsed is not None:
                                present = parsed
                                raw_state = str(node[token_key])
                    add_record(
                        node,
                        system_for(resource_id),
                        os.path.basename(path),
                        category_for(resource_id),
                        str(observed_at),
                        present=present,
                        raw_state=raw_state,
                    )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return observations, coverage


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

KV_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"]*)"|\'([^\']*)\'|([^\s]+))'
)
BRACKET_RE = re.compile(
    r"^\S+\s+\[(?P<level>[A-Z]+)\]\s+\[(?P<service>[a-z_]+)\]\s+"
    r"(?:\[(?P<trace>[^\]]+)\]\s+)?(?P<event>[a-z_]+):\s*(?P<rest>.*)$"
)
SYSLOG_RE = re.compile(
    r"^\S+\s+<\d+>\d\s+\S+\s+(?P<service>[a-z_]+)\s+(?P<trace>tr-\S+)\s+-\s+-\s+(?P<rest>.*)$"
)
PIPE_RE = re.compile(
    r"^\S+\s+\|\s*(?P<level>[A-Z]+)\s*\|\s*(?P<service>[a-z_]+)\s*\|\s*"
    r"(?P<trace>[^|]*?)\s*\|\s*(?P<event>[a-z_]+)\s*\|(?P<rest>.*)$"
)


def _kv_fields(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for m in KV_RE.finditer(text):
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else m.group(4)
        fields[key] = value
    return fields


def _json_log_fields(text: str) -> Dict[str, str]:
    """Parse a JSON-object log line into flat string fields."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(value, (str, int, float))
    }


def _unwrap_message(fields: Dict[str, str]) -> Dict[str, str]:
    """Promote key/value pairs packed inside a ``message`` envelope.

    Some collectors wrap the real payload as ``message="instance=..."`` with
    escaped quotes.  Re-parse that payload so its ``event`` and
    ``resource_id`` become first-class fields.
    """
    body = fields.get("message") or fields.get("msg") or ""
    if "=" not in body:
        return fields
    inner = _kv_fields(body)
    if not inner:
        return fields
    merged = dict(fields)
    for key, value in inner.items():
        merged.setdefault(key, value)
    return merged


EVENT_CATEGORY = {
    "profile_lookup_completed": "USER_PROFILE",
    "profile_lookup_started": "USER_PROFILE",
    "index_query_completed": "SEARCH_INDEX_ENTRY",
    "analytics_profile_read_completed": "ANALYTICS_PROFILE",
    "connector_config_read_completed": "DATA_FLOW",
    "connector_heartbeat": "DATA_FLOW",
    "restore_policy_read_completed": "BACKUP_ARCHIVE",
    "restore_candidate_evaluated": "BACKUP_ARCHIVE",
    "audit_record_read_completed": "SECURITY_AUDIT_LOG",
    "support_ticket_read_completed": "SUPPORT_MESSAGE",
    "message_pii_scan": "SUPPORT_MESSAGE",
    "attachment_pii_scan": "SUPPORT_ATTACHMENT",
    "analytics_identity_scan": "ANALYTICS_PROFILE",
    "contact_lookup_completed": "ANALYTICS_PROFILE",
    "contact_query_completed": "MARKETING_PROFILE",
    "export_download_check_completed": "USER_EXPORT",
    "export_metadata_read_completed": "USER_EXPORT",
    "deletion_marker_check": "ACCOUNT_TOMBSTONE",
    "cache_refresh": "CACHE_ENTRY",
}

READBACK_EVENTS = {
    "profile_lookup_completed",
    "index_query_completed",
    "analytics_profile_read_completed",
    "connector_config_read_completed",
    "connector_heartbeat",
    "restore_policy_read_completed",
    "restore_candidate_evaluated",
    "audit_record_read_completed",
    "support_ticket_read_completed",
    "message_pii_scan",
    "attachment_pii_scan",
    "analytics_identity_scan",
    "contact_lookup_completed",
    "contact_query_completed",
    "export_download_check_completed",
    "export_metadata_read_completed",
    "cache_refresh",
}


def _event_state(event: str, fields: Dict[str, str]) -> tuple:
    """Return ``(present, raw_state)`` for a completed event."""
    def val(*names):
        for name in names:
            if name in fields and fields[name] not in ("", "null", "None"):
                return fields[name]
        return None

    if event in {"profile_lookup_completed", "support_ticket_read_completed"}:
        status = val("http_status", "status_code")
        rows = val("rows")
        if status is not None:
            present = status in {"200", "201", "204"}
        elif rows is not None:
            try:
                present = int(rows) > 0
            except ValueError:
                present = False
        else:
            present = True
        return present, "FOUND" if present else "NOT_FOUND"
    if event == "index_query_completed":
        result = (val("result") or "").lower()
        total = val("total_hits", "hits")
        present = result in {"hit", "found"} or (total is not None and total.isdigit() and int(total) > 0)
        return present, "FOUND" if present else "NOT_FOUND"
    if event == "analytics_profile_read_completed":
        return True, "ANONYMIZED" if not any(
            val(k) for k in ("customer_reference", "email", "phone", "email_hash")
        ) else "IDENTIFIABLE"
    if event in {"connector_config_read_completed", "connector_heartbeat"}:
        enabled = (val("enabled") or "").lower()
        return True, "ACTIVE" if enabled == "true" else "DISABLED"
    if event == "restore_policy_read_completed":
        allowed = (val("restore_allowed") or "").lower()
        return True, "ACTIVE" if allowed == "true" else "BLOCKED"
    if event == "restore_candidate_evaluated":
        eligible = (val("eligible") or "").lower()
        blocked = (val("deletion_block") or "").lower()
        risky = eligible == "true" and blocked != "true"
        return True, "ACTIVE" if risky else "BLOCKED"
    if event == "audit_record_read_completed":
        rows = val("rows")
        try:
            present = int(rows) > 0 if rows is not None else True
        except ValueError:
            present = True
        return present, "FOUND" if present else "NOT_FOUND"
    if event in {"message_pii_scan", "attachment_pii_scan", "analytics_identity_scan"}:
        matched = val("matched_value", "match_key", "scan_key")
        return True, "IDENTIFIABLE" if matched else "ANONYMIZED"
    if event in {"contact_lookup_completed", "contact_query_completed"}:
        rows = val("rows", "total_hits")
        try:
            present = int(rows) > 0 if rows is not None else True
        except ValueError:
            present = True
        return present, "IDENTIFIABLE" if present else "NOT_FOUND"
    if event in {"export_download_check_completed", "export_metadata_read_completed"}:
        available = (val("available", "download_available") or "").lower()
        return True, "FOUND" if available in {"", "true", "yes"} else "ABSENT"
    if event == "deletion_marker_check":
        marker = (val("marker_found") or "").lower()
        return True, "FOUND" if marker == "true" else "NOT_FOUND"
    if event == "cache_refresh":
        return True, "FOUND"
    return True, "FOUND"


def _parse_logs(path: str, file_id: str, captured_at: str, root: str) -> tuple:
    observations: List[Observation] = []
    traces: Dict[str, Dict[str, str]] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            line = line.replace('\\"', '"')
            ts_match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+", line)
            observed_at = ts_match.group(1) if ts_match else captured_at
            rest = line[ts_match.end():] if ts_match else line

            service = ""
            event = ""
            body = rest
            bracket = BRACKET_RE.match(line)
            pipe = PIPE_RE.match(line)
            if bracket:
                service = bracket.group("service")
                event = bracket.group("event")
                body = bracket.group("rest")
                if bracket.group("trace"):
                    body = f'trace_id="{bracket.group("trace")}" ' + body
            elif pipe:
                service = pipe.group("service")
                event = pipe.group("event")
                body = pipe.group("rest")
                if pipe.group("trace") and pipe.group("trace") != "-":
                    body = f'trace_id="{pipe.group("trace")}" ' + body
            else:
                syslog = SYSLOG_RE.match(line)
                if syslog:
                    service = syslog.group("service")
                    body = syslog.group("rest")
                    if syslog.group("trace") and syslog.group("trace") != "-":
                        body = f'trace_id="{syslog.group("trace")}" ' + body
                fields_probe = _json_log_fields(rest)
                if fields_probe:
                    service = fields_probe.get("service", service) or fields_probe.get("logger", service)
                    event = fields_probe.get("event", "")
                    body = rest
                else:
                    fields_probe = _kv_fields(body)
                    service = fields_probe.get("service", service)
                    event = fields_probe.get("event", "")

            if rest.lstrip().startswith("{"):
                fields = _json_log_fields(rest)
                fields = _unwrap_message(fields)
            else:
                fields = _kv_fields(body)
                fields = _unwrap_message(fields)
            if service:
                fields.setdefault("service", service)
            if event:
                fields.setdefault("event", event)
            event = fields.get("event", "")
            if not event:
                continue
            trace_id = fields.get("trace_id") or fields.get("trace") or fields.get("requestId")
            if trace_id:
                stored = traces.setdefault(trace_id, {})
                for key in (
                    "lookup_key",
                    "match_key",
                    "scan_key",
                    "subject_reference",
                    "subject_ref",
                    "subject_key",
                    "customer_reference",
                    "correlation_key",
                ):
                    if fields.get(key) and fields[key] not in ("null", "None"):
                        stored[key] = fields[key]

            if event == "record_lookup":
                resource_id = fields.get("resource_id", "")
                if not resource_id:
                    continue
                system = norm_system(fields.get("system") or system_for(resource_id))
                state = fields.get("result", "")
                present = _state_from_token(state)
                identifiers = _collect_identifiers(fields, fields.get("subject_reference", ""))
                observations.append(
                    Observation(
                        file_id=file_id,
                        captured_at=captured_at,
                        observed_at=observed_at,
                        system_id=system,
                        store=os.path.basename(path),
                        collection="record_lookup",
                        record_type=fields.get("record_type") or category_for(resource_id),
                        resource_id=resource_id,
                        identifiers=identifiers,
                        attrs={k: v for k, v in fields.items() if k not in {"resource_id", "system", "result"}},
                        present=present,
                        raw_state=state,
                        source_kind="log",
                        line_no=line_no,
                    )
                )
                continue

            if event not in READBACK_EVENTS:
                continue
            resource_id = fields.get("resource_id", "")
            if not resource_id:
                continue
            merged = dict(fields)
            if trace_id:
                for key, value in traces.get(trace_id, {}).items():
                    merged.setdefault(key, value)
            for key in ("lookup_key", "match_key", "scan_key"):
                if merged.get(key) and merged[key] not in ("null", "None"):
                    # classify_identifier handles the value below.
                    pass
            present, raw_state = _event_state(event, merged)
            category = EVENT_CATEGORY.get(event, "") or category_for(resource_id)
            if event == "support_ticket_read_completed":
                category = "SUPPORT_MESSAGE"
            system = system_for(resource_id) or norm_system(merged.get("service"))
            if event in {"message_pii_scan"}:
                system = "support_platform"
            if event in {"attachment_pii_scan"}:
                system = "support_platform"
                category = "SUPPORT_ATTACHMENT"
            if event in {"analytics_identity_scan"}:
                system = "analytics_platform"
            if event in {"contact_lookup_completed"}:
                system = "analytics_platform"
                category = "MARKETING_PROFILE"
            if event in {"contact_query_completed"}:
                system = system_for(resource_id) or "marketing_platform"
                category = "SUPPORT_ATTACHMENT"
            if event == "deletion_marker_check":
                category = category_for(resource_id)
            identifiers = _collect_identifiers(merged, " ".join(str(v) for v in merged.values()))
            attrs = {
                k: v
                for k, v in merged.items()
                if k
                not in {
                    "resource_id",
                    "event",
                    "service",
                    "trace_id",
                    "trace",
                    "lookup_key",
                    "match_key",
                    "scan_key",
                    "email",
                    "phone",
                    "email_hash",
                    "customer_reference",
                    "subject_reference",
                }
            }
            observations.append(
                Observation(
                    file_id=file_id,
                    captured_at=captured_at,
                    observed_at=observed_at,
                    system_id=system or system_for(resource_id),
                    store=os.path.basename(path),
                    collection=event,
                    record_type=category,
                    resource_id=resource_id,
                    identifiers=identifiers,
                    attrs=attrs,
                    present=present,
                    raw_state=raw_state,
                    source_kind="log",
                    line_no=line_no,
                )
            )
    return observations, []


# ---------------------------------------------------------------------------
# Handover text and PDFs
# ---------------------------------------------------------------------------

HANDOVER_RE = re.compile(
    r"^-\s+(?P<ts>\S+)\s*\|\s*(?P<system>[a-z_]+)\s*\|\s*(?P<resource>[a-z_]+_\d+)\s*\|\s*"
    r"(?P<category>[A-Z_]+)\s*\|\s*(?P<state>[A-Z_]+)\s*\|\s*(?P<identifier>.*)$"
)


def _parse_txt(path: str, file_id: str, captured_at: str, root: str) -> tuple:
    observations: List[Observation] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            match = HANDOVER_RE.match(line.strip())
            if not match:
                continue
            state = match.group("state")
            present = _state_from_token(state)
            identifiers = _collect_identifiers({}, match.group("identifier"))
            if not identifiers and match.group("identifier").strip().lower() not in {
                "no direct identifier",
                "",
            }:
                name = norm_name(match.group("identifier"))
                if name:
                    identifiers["name"] = {name}
            observations.append(
                Observation(
                    file_id=file_id,
                    captured_at=captured_at,
                    observed_at=match.group("ts"),
                    system_id=norm_system(match.group("system")),
                    store=os.path.basename(path),
                    collection="handover",
                    record_type=match.group("category"),
                    resource_id=match.group("resource"),
                    identifiers=identifiers,
                    attrs={"state": state},
                    present=present,
                    raw_state=state,
                    source_kind="txt",
                    line_no=line_no,
                )
            )
    return observations, []


def _parse_pdf(path: str, file_id: str, captured_at: str, root: str) -> tuple:
    observations: List[Observation] = []
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - optional dependency
        return observations, []
    try:
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:  # pragma: no cover - malformed PDFs
        return observations, []

    resources = sorted(set(m.group(1) for m in RESOURCE_RE.finditer(text)))
    identifiers = _collect_identifiers({}, text)
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?", text)
    observed_at = dates[-1] if dates else captured_at
    category_hint = ""
    lower = text.lower()
    if "attachment" in lower or "uploaded file" in lower:
        category_hint = "SUPPORT_ATTACHMENT"
    if "legal" in lower or "retention" in lower:
        category_hint = "LEGAL_HOLD_RECORD"
    for resource_id in resources:
        category = category_for(resource_id) or category_hint or "SUPPORT_MESSAGE"
        if category_hint == "SUPPORT_ATTACHMENT" and category == "SUPPORT_MESSAGE":
            category = "SUPPORT_ATTACHMENT"
        attrs: Dict[str, Any] = {}
        if "retain" in lower or "retention" in lower:
            attrs["retention"] = True
        observations.append(
            Observation(
                file_id=file_id,
                captured_at=captured_at,
                observed_at=captured_at,
                system_id=system_for(resource_id),
                store=os.path.basename(path),
                collection="document",
                record_type=category,
                resource_id=resource_id,
                identifiers={k: set(v) for k, v in identifiers.items()},
                attrs=attrs,
                present=True,
                raw_state="FOUND",
                source_kind="pdf",
            )
        )
    return observations, []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_evidence_index(manifest_path: str, evidence_root: str) -> EvidenceIndex:
    index = EvidenceIndex()
    manifest = list(csv.DictReader(open(manifest_path, "r", encoding="utf-8")))
    for row in manifest:
        file_id = row["file_id"]
        rel_path = row["file_path"]
        captured_at = row["captured_at"]
        path = os.path.join(evidence_root, rel_path)
        index.files[file_id] = dict(row)
        if not os.path.exists(path):
            continue
        lower = path.lower()
        if lower.endswith(".sql"):
            observations, coverage = _parse_sql(path, file_id, captured_at, evidence_root)
        elif lower.endswith(".json"):
            observations, coverage = _parse_json(path, file_id, captured_at, evidence_root)
        elif lower.endswith(".log"):
            observations, coverage = _parse_logs(path, file_id, captured_at, evidence_root)
        elif lower.endswith(".txt"):
            observations, coverage = _parse_txt(path, file_id, captured_at, evidence_root)
        elif lower.endswith(".pdf"):
            observations, coverage = _parse_pdf(path, file_id, captured_at, evidence_root)
        else:
            continue
        for obs in observations:
            index.add(obs)
        for cov in coverage:
            index.add_coverage(cov)
    return index.build()
