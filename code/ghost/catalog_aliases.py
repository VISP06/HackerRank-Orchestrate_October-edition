"""Grounded aliases from explicit data-catalog link rows.

``LINK_RESOURCE_IDENTITY`` activity rows sometimes name a resource together
with a stable reference or file name, for example ``object_19
(delivery_confirmation_19.pdf)`` or ``export_1842 (NST-2026-0718-1842)``.
Those parenthetical tokens are the only safe way to map a document that
prints a business reference (rather than an internal id) to the catalog
resource id.  Aliases are accepted only when the reference also appears in
the document text; nothing is inferred from a name or an order number.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Dict

from code.ghost.evidence_index import RESOURCE_RE


def load_resource_aliases(dataset_dir: str) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    path = os.path.join(dataset_dir, "system_activity.csv")
    if not os.path.exists(path):
        return aliases
    with open(path, "r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("event_type") != "LINK_RESOURCE_IDENTITY":
                continue
            rid = (row.get("resource_id") or "").strip()
            if not RESOURCE_RE.fullmatch(rid):
                continue
            match = re.search(r"\(([^)]+)\)", row.get("details") or "")
            if not match:
                continue
            token = match.group(1).strip()
            if token and token != rid and not RESOURCE_RE.fullmatch(token):
                aliases[token.lower()] = rid
    return aliases
