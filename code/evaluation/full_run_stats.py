#!/usr/bin/env python3
"""Run the audit on the full request set and write coverage statistics.

The output file is the deliverable ``output.csv``.  This script also records
operational facts that are useful for the evaluation report: status mix, step
counts, which cases have no evidence-linked resource, how resources were
linked, invariant violations, and wall-clock runtime.
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code.ghost.intent import authorizes_deletion
from code.ghost.invariants import check_rows
from code.ghost.loaders import load_deletion_requests
from code.ghost.state import reconstruct_state
from code.main import build_engine, run_pipeline


def _share(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "0.0%"


def _stats(values):
    if not values:
        return {"count": 0, "total": 0, "mean": 0.0, "median": 0.0, "max": 0}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    return {
        "count": len(values),
        "total": sum(values),
        "mean": sum(values) / len(values),
        "median": median,
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Full-dataset run statistics")
    parser.add_argument(
        "--requests", default=os.path.join(REPO_ROOT, "dataset", "deletion_requests.csv")
    )
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "output.csv"))
    parser.add_argument(
        "--report", default=os.path.join(REPO_ROOT, "code", "evaluation", "full_run_stats.md")
    )
    args = parser.parse_args()

    requests = load_deletion_requests(args.requests)
    started = time.perf_counter()
    run_pipeline(args.requests, args.out)
    runtime = time.perf_counter() - started

    with open(args.out, "r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    index, linker, rules = build_engine()

    status_counts = Counter()
    steps_by_status = defaultdict(list)
    zero_step_complete = []
    status_by_case = {}
    steps_by_case = {}
    for row in rows:
        status = row["deletion_status"]
        count = len(json.loads(row["steps_json"]))
        status_counts[status] += 1
        steps_by_status[status].append(count)
        status_by_case[row["case_id"]] = status
        steps_by_case[row["case_id"]] = count
        if status == "COMPLETE" and count == 0:
            zero_step_complete.append(row["case_id"])

    zero_link = []
    linked_without_state = []
    low_evidence = []
    linked_without_observation = 0
    reason_cases = Counter()
    reason_resources = Counter()
    for request in requests:
        case_id = request["case_id"]
        if not authorizes_deletion(request.get("request_text", "")):
            continue
        trace = linker.link_case(request, request.get("audit_at", ""))
        linked = [
            resource_id
            for resource_id, resource_trace in trace.resources.items()
            if resource_trace.link_paths
        ]
        states = reconstruct_state(index, trace, request.get("audit_at", "")) if linked else {}
        if not linked:
            zero_link.append(case_id)
        elif not states:
            linked_without_state.append(case_id)
        if not linked or not states:
            low_evidence.append(
                {
                    "case_id": case_id,
                    "status": status_by_case.get(case_id, ""),
                    "steps": steps_by_case.get(case_id, 0),
                    "linked": len(linked),
                    "cause": "no link" if not linked else "no state at audit_at",
                    "reasons": sorted(
                        {
                            trace.resources[resource_id].best_path().split(":", 1)[0]
                            for resource_id in linked
                        }
                    ),
                }
            )
        linked_without_observation += sum(
            1 for resource_trace in trace.resources.values() if not resource_trace.observations
        )
        if not linked:
            continue
        seen_reasons = set()
        for resource_id in linked:
            reason = trace.resources[resource_id].best_path().split(":", 1)[0]
            reason_resources[reason] += 1
            seen_reasons.add(reason)
        for reason in seen_reasons:
            reason_cases[reason] += 1

    expected = [request["case_id"] for request in requests]
    evidence_dates = {file_id: meta["captured_at"] for file_id, meta in index.files.items()}
    audit_dates = {request["case_id"]: request["audit_at"] for request in requests}
    violations = check_rows(rows, expected, evidence_dates, audit_dates)

    total = len(rows)
    all_steps = [count for counts in steps_by_status.values() for count in counts]
    overall = _stats(all_steps)

    lines = []
    lines.append("# Full-Dataset Run Statistics")
    lines.append("")
    lines.append("Generated by `python3 code/evaluation/full_run_stats.py`.")
    lines.append("")
    lines.append(f"- Requests processed: **{total}**")
    lines.append(f"- Output file: `{os.path.relpath(args.out, REPO_ROOT)}`")
    lines.append(f"- Invariant violations: **{len(violations)}**")
    lines.append(f"- Pipeline wall time: **{runtime:.2f} s**")
    lines.append("")
    lines.append("## Status distribution")
    lines.append("")
    lines.append("| Status | Cases | Share |")
    lines.append("|---|---:|---:|")
    for status in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
        lines.append(
            f"| {status} | {status_counts.get(status, 0)} | "
            f"{_share(status_counts.get(status, 0), total)} |"
        )
    lines.append("")
    lines.append("## Steps per case")
    lines.append("")
    lines.append("| Status | Cases | Steps | Mean | Median | Max | Zero-step |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for status in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
        values = steps_by_status.get(status, [])
        stats = _stats(values)
        lines.append(
            f"| {status} | {stats['count']} | {stats['total']} | "
            f"{stats['mean']:.2f} | {stats['median']:.1f} | {stats['max']} | "
            f"{sum(1 for value in values if value == 0)} |"
        )
    lines.append(
        f"| **All** | **{overall['count']}** | **{overall['total']}** | "
        f"**{overall['mean']:.2f}** | **{overall['median']:.1f}** | "
        f"**{overall['max']}** | **{sum(1 for value in all_steps if value == 0)}** |"
    )
    lines.append("")
    lines.append("## Evidence coverage")
    lines.append("")
    lines.append(
        f"- Cases with no linked resource at all: **{len(zero_link)}** "
        f"({_share(len(zero_link), total)})"
    )
    lines.append(
        f"- Cases with a catalog link but no reconstructed state: **{len(linked_without_state)}**"
    )
    lines.append(
        f"- Linked resources with no observation at all: **{linked_without_observation}**"
    )
    lines.append(
        f"- COMPLETE cases with zero verification steps: **{len(zero_step_complete)}**"
    )
    lines.append(
        f"- `low_evidence` cases (no link, or links but no state at `audit_at`): "
        f"**{len(low_evidence)}** ({_share(len(low_evidence), total)})"
    )
    lines.append("")
    if zero_link:
        lines.append(
            "No-link cases: "
            + ", ".join(f"`{case_id}`" for case_id in sorted(zero_link))
        )
        lines.append("")
    if linked_without_state:
        lines.append(
            "Linked but stateless: "
            + ", ".join(f"`{case_id}`" for case_id in sorted(linked_without_state))
        )
        lines.append("")
    if zero_step_complete:
        lines.append(
            "Zero-step COMPLETE cases: "
            + ", ".join(f"`{case_id}`" for case_id in sorted(zero_step_complete))
        )
        lines.append("")
    lines.append("## Low-evidence cases")
    lines.append("")
    lines.append(
        "`low_evidence` is set when a case has no linked resource at all, or has links but no "
        "admissible state observation at `audit_at`. These answers are deterministic, but they "
        "rest on the absence of evidence rather than on positive evidence of the required state."
    )
    lines.append("")
    if low_evidence:
        lines.append("| Case | Status | Steps | Links | Cause | Link reasons |")
        lines.append("|---|---|---:|---:|---|---|")
        for item in sorted(low_evidence, key=lambda entry: entry["case_id"]):
            reasons = ", ".join(f"`{reason}`" for reason in item["reasons"]) or "-"
            lines.append(
                f"| `{item['case_id']}` | {item['status']} | {item['steps']} | "
                f"{item['linked']} | {item['cause']} | {reasons} |"
            )
    else:
        lines.append("No low-evidence cases.")
    lines.append("")
    lines.append("## Link-path usage")
    lines.append("")
    lines.append("| Link reason | Cases | Resources |")
    lines.append("|---|---:|---:|")
    for reason, count in sorted(reason_cases.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{reason}` | {count} | {reason_resources.get(reason, 0)} |")
    lines.append("")
    lines.append(
        "Reason keys are `identifier:<field>` for direct identifier matches, "
        "`identifier_late:<field>` for identity discovered only in post-cutoff artifacts, "
        "`catalog_link` for `LINK_RESOURCE_IDENTITY` activity, "
        "`activity_propagation` for named downstream copies, "
        "`resource_observation` for evidence attached once a resource id is grounded, and "
        "`workflow_dispatch` for the tight-window account/analytics discovery rule."
    )
    lines.append("")
    lines.append("## Invariants")
    lines.append("")
    if violations:
        lines.append(f"{len(violations)} violation(s):")
        lines.append("")
        for violation in violations[:50]:
            lines.append(f"- {violation}")
    else:
        lines.append("All label-free invariant checks passed.")
    lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    print(f"Wrote {args.report}")
    print(
        f"cases={total} statuses={dict(status_counts)} steps={overall['total']} "
        f"zero_link={len(zero_link)} linked_no_state={len(linked_without_state)} "
        f"no_obs_resources={linked_without_observation} "
        f"zero_step_complete={len(zero_step_complete)} "
        f"low_evidence={len(low_evidence)} "
        f"violations={len(violations)} runtime={runtime:.2f}s"
    )


if __name__ == "__main__":
    main()
