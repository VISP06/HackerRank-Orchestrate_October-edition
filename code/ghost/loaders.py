"""Data loaders for Ghost Data Still Exists challenge dataset."""

import csv
import os
import re
from typing import Any, Dict, List, Optional


def natural_sort_key(key: str) -> int:
    """Extract integer from case ID for natural numerical ordering.
    
    Examples:
        'case_01' -> 1
        'case_33' -> 33
        'case_100' -> 100
    """
    match = re.search(r'\d+', key)
    return int(match.group()) if match else 0


def _load_csv(path: str) -> List[Dict[str, str]]:
    """Read a CSV file into a list of dictionaries with stripped keys/values."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset file not found: {path}")
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [{k.strip(): (v.strip() if v is not None else "") for k, v in row.items()} for row in reader]


def load_deletion_requests(path: str = "dataset/deletion_requests.csv") -> List[Dict[str, str]]:
    """Load deletion requests and ensure sorted in natural numeric order by case_id."""
    rows = _load_csv(path)
    rows.sort(key=lambda r: natural_sort_key(r.get("case_id", "")))
    return rows


def load_user_identities(path: str = "dataset/user_identities.csv") -> List[Dict[str, str]]:
    """Load user identity snapshots."""
    return _load_csv(path)


def load_user_audit_log(path: str = "dataset/user_audit_log.csv") -> List[Dict[str, str]]:
    """Load historical identity changes from the audit log."""
    return _load_csv(path)


def load_system_activity(path: str = "dataset/system_activity.csv") -> List[Dict[str, str]]:
    """Load global system activity events."""
    return _load_csv(path)


def load_deletion_rules(path: str = "dataset/deletion_rules.csv") -> List[Dict[str, str]]:
    """Load retention and deletion policy rules."""
    return _load_csv(path)


def load_evidence_files(path: str = "dataset/evidence_files.csv") -> List[Dict[str, str]]:
    """Load evidence files manifest."""
    return _load_csv(path)
