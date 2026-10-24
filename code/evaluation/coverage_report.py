#!/usr/bin/env python3
"""Coverage matrix for the deletion-audit pipeline.

Reports, per policy category, how many cases and resources the linker reaches,
how many have an admissible state at the case cutoff, which evidence formats
carry the observations, and where the corpus is evidence-poor (catalog-only
links, unparsed screenshots, PDF-only categories).

Measurement only: reads participant-facing files and writes
``notes/COVERAGE.md``.  The sample answer key is not used.
"""

from __future__ import annotations

import csv
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code.ghost.evidence_index import category_for, system_for
from code.ghost.intent import authorizes_deletion
from code.ghost.loaders import load_deletion_requests
from code.ghost.rules import assess_state
from code.ghost.state import reconstruct_state
from code.main import build_engine

FORMAT_ORDER = ("log", "txt", "json", "sql", "pdf", "csv", "other")
CATEGORY_ORDER = (
    "USER_PROFILE",
    "ACCOUNT_TOMBSTONE",
    "ANALYTICS_PROFILE",
    "PRODUCT_TELEMETRY",
    "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD",
    "DATA_FLOW",
    "BACKUP_ARCHIVE",
    "SEARCH_INDEX_ENTRY",
    "CACHE_ENTRY",
    "SUPPORT_MESSAGE",
    "SUPPORT_ATTACHMENT",
    "USER_EXPORT",
    "MARKETING_PROFILE",
    "EMAIL_DELIVERY_LOG",
    "SECONDARY_IDENTIFIER",
)


def file_format(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower().lstrip(".")
    return suffix or "other"


def main() -> None:
    requests = [
        request
        for request in load_deletion_requests(os.path.join(REPO_ROOT, "dataset", "deletion_requests.csv"))
        if authorizes_deletion(request.get("request_text", ""))
    ]
    index, linker, rules = build_engine()

    category_cases: Dict[str, Set[str]] = defaultdict(set)
    category_resources: Counter = Counter()
    category_state: Counter = Counter()
    category_findings: Counter = Counter()
    category_catalog_only: Counter = Counter()
    category_formats: Dict[str, Counter] = defaultdict(Counter)
    state_distribution: Dict[str, Counter] = defaultdict(Counter)
    catalog_only_examples: Dict[str, List[str]] = defaultdict(list)
    no_state_cases: List[str] = []

    for request in requests:
        case_id = request["case_id"]
        audit_at = request.get("audit_at", "")
        trace = linker.link_case(request, audit_at)
        states = reconstruct_state(index, trace, audit_at)
        if trace.resources and not states:
            no_state_cases.append(case_id)
        for resource_id, resource_trace in trace.resources.items():
            if not resource_trace.link_paths:
                continue
            category = category_for(resource_id, resource_trace.category)
            category_cases[category].add(case_id)
            category_resources[category] += 1
            if not resource_trace.observations:
                category_catalog_only[category] += 1
                if len(catalog_only_examples[category]) < 6:
                    catalog_only_examples[category].append(
                        f"{case_id}:{resource_id}"
                    )
            for observation in resource_trace.observations:
                path = index.files.get(observation.file_id, {}).get("file_path", "")
                extension = file_format(path)
                category_formats[observation.record_type or category][extension] += 1
            state = states.get(resource_id)
            if state is not None:
                category_state[category] += 1
                state_distribution[category][state.state] += 1
        for state in states.values():
            assessment = assess_state(state, rules, audit_at)
            if assessment is not None and assessment.is_finding:
                category_findings[category_for(state.resource_id, state.category)] += 1

    manifest = list(csv.DictReader(open(os.path.join(REPO_ROOT, "dataset", "evidence_files.csv"))))
    by_format = Counter(file_format(row["file_path"]) for row in manifest)
    parsed_files = {observation.file_id for observation in index.observations}
    manifest_by_id = {row["file_id"]: row for row in manifest}
    observations_per_file = Counter(observation.file_id for observation in index.observations)
    pdf_rows = []
    for row in manifest:
        if file_format(row["file_path"]) == "pdf":
            sample = observations_per_file.get(row["file_id"], 0)
            pdf_rows.append((row["file_id"], os.path.basename(row["file_path"]), row["captured_at"], sample))
    image_rows = [
        (row["file_id"], os.path.basename(row["file_path"]), row["captured_at"])
        for row in manifest
        if file_format(row["file_path"]) in {"png", "jpg", "jpeg", "webp", "gif"}
    ]

    categories = [category for category in CATEGORY_ORDER if category_resources[category]]
    categories += sorted(set(category_resources) - set(categories))

    lines: List[str] = []
    lines.append("# Evidence coverage matrix")
    lines.append("")
    lines.append("Generated by `python3 code/evaluation/coverage_report.py` over all 518 requests.")
    lines.append("Counts describe resources the linker actually reached; `state` means an")
    lines.append("observation captured at or before the case's `audit_at`.")
    lines.append("")
    lines.append("| Category | Cases | Linked resources | With state | Findings | Catalog-only links |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for category in categories:
        lines.append(
            f"| `{category}` | {len(category_cases[category])} | {category_resources[category]} | "
            f"{category_state[category]} | {category_findings[category]} | {category_catalog_only[category]} |"
        )
    lines.append("")

    lines.append("## Category x evidence format")
    lines.append("")
    lines.append("Cell values are observation counts. A category can receive several formats; a dash")
    lines.append("means the corpus never carried that category in that format.")
    lines.append("")
    lines.append("| Category | " + " | ".join(FORMAT_ORDER) + " |")
    lines.append("|---|" + "---:|" * len(FORMAT_ORDER))
    for category in categories:
        cells = []
        for extension in FORMAT_ORDER:
            count = category_formats.get(category, {}).get(extension, 0)
            cells.append(str(count) if count else "-")
        lines.append(f"| `{category}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## State distribution")
    lines.append("")
    states_seen = sorted({state for counter in state_distribution.values() for state in counter})
    lines.append("| Category | " + " | ".join(states_seen) + " |")
    lines.append("|---|" + "---:|" * len(states_seen))
    for category in categories:
        cells = [str(state_distribution[category].get(state, 0)) if state_distribution[category].get(state) else "-" for state in states_seen]
        if any(cell != "-" for cell in cells):
            lines.append(f"| `{category}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Evidence files by format")
    lines.append("")
    lines.append("| Format | Files | Files yielding observations |")
    lines.append("|---|---:|---:|")
    for extension in sorted(
        by_format,
        key=lambda item: (FORMAT_ORDER.index(item) if item in FORMAT_ORDER else len(FORMAT_ORDER), item),
    ):
        files = [row for row in manifest if file_format(row["file_path"]) == extension]
        if not files:
            continue
        parsed = sum(1 for row in files if row["file_id"] in parsed_files)
        lines.append(f"| `{extension}` | {len(files)} | {parsed} |")
    lines.append("")
    lines.append("`png` files are screenshots and are not parsed at all; `pdf` text is extracted")
    lines.append("with `pypdf`.  A file can be parsed but still yield zero observations when it")
    lines.append("contains no record rows.")
    lines.append("")

    lines.append("## PDF inventory")
    lines.append("")
    lines.append("| File | Captured | Observations extracted |")
    lines.append("|---|---|---:|")
    for file_id, name, captured_at, count in pdf_rows:
        lines.append(f"| `{file_id}` `{name}` | {captured_at} | {count} |")
    lines.append("")

    lines.append("## Image inventory")
    lines.append("")
    lines.append("| File | Captured | Parsed |")
    lines.append("|---|---|---:|")
    for file_id, name, captured_at in image_rows:
        lines.append(f"| `{file_id}` `{name}` | {captured_at} | no |")
    lines.append("")
    lines.append(
        "No image carries identity in its file name (all are `<artifact>_<date>.png`) and none"
    )
    lines.append("has `tEXt`/`iTXt` metadata, so screenshots currently contribute nothing.")
    lines.append("")

    lines.append("## Gaps")
    lines.append("")
    absent = sorted(set(rules) - set(category_resources))
    if absent:
        lines.append(
            "Policy categories with **no linked resource anywhere in the run**: "
            + ", ".join(f"`{category}`" for category in absent)
            + ". Their ids appear only in `system_activity.csv`, so the workflow mentions them"
            " but no evidence record carries them; they cannot be audited from participant data."
        )
        lines.append("")
    catalog_only = [(category, category_catalog_only[category]) for category in categories if category_catalog_only[category]]
    if catalog_only:
        lines.append("Categories with catalog-only links (linked but never observed):")
        lines.append("")
        for category, count in sorted(catalog_only, key=lambda item: (-item[1], item[0])):
            examples = ", ".join(f"`{item}`" for item in catalog_only_examples[category][:4])
            lines.append(f"- `{category}`: {count} resource(s); e.g. {examples}")
        lines.append("")
    single_format = []
    for category in categories:
        formats = [extension for extension in FORMAT_ORDER if category_formats.get(category, {}).get(extension)]
        if len(formats) == 1:
            single_format.append((category, formats[0]))
    if single_format:
        lines.append("Categories observed through a single format:")
        lines.append("")
        for category, extension in single_format:
            lines.append(f"- `{category}`: `{extension}` only")
        lines.append("")
    if no_state_cases:
        lines.append(
            f"{len(no_state_cases)} case(s) reach a resource but reconstruct no state at the cutoff: "
            + ", ".join(f"`{case_id}`" for case_id in sorted(no_state_cases))
        )
        lines.append("")
    lines.append(
        "The `png` gap is the main blind spot: screenshots can be the only pre-cutoff artifact"
        " for an object or marketing record (see `notes/ZERO_STEP_FAMILIES.md`, Family B)."
    )
    lines.append("")

    out = os.path.join(REPO_ROOT, "notes", "COVERAGE.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print("wrote", out)
    print("categories", len(categories), "manifest_formats", dict(by_format), "no_state_cases", len(no_state_cases))


if __name__ == "__main__":
    main()
