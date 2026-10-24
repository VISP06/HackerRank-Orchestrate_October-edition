#!/usr/bin/env python3
"""Ghost Data Still Exists - deterministic deletion audit pipeline."""

import argparse
import csv
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code.ghost.evidence_index import load_evidence_index
from code.ghost.intent import authorizes_deletion
from code.ghost.invariants import check_rows
from code.ghost.linker import CaseLinker, load_activity_rows
from code.ghost.loaders import load_deletion_requests, load_user_identities, load_user_audit_log
from code.ghost.rules import load_rules
from code.ghost.state import reconstruct_state
from code.ghost.steps import build_case_result, serialize_steps
from code.ghost.validate import validate_output_file


def _dataset_path(name: str) -> str:
    return os.path.join(REPO_ROOT, "dataset", name)


def build_engine(dataset_dir: str = ""):
    dataset_dir = dataset_dir or os.path.join(REPO_ROOT, "dataset")
    index = load_evidence_index(
        os.path.join(dataset_dir, "evidence_files.csv"), dataset_dir
    )
    linker = CaseLinker(
        index,
        load_activity_rows(os.path.join(dataset_dir, "system_activity.csv")),
        load_user_identities(os.path.join(dataset_dir, "user_identities.csv")),
        load_user_audit_log(os.path.join(dataset_dir, "user_audit_log.csv")),
    )
    rules = load_rules(os.path.join(dataset_dir, "deletion_rules.csv"))
    return index, linker, rules


def audit_case(case, linker, index, rules):
    audit_at = case.get("audit_at", "")
    trace = linker.link_case(case, audit_at)
    states = reconstruct_state(index, trace, audit_at)
    status, steps = build_case_result(states, rules, audit_at, trace)
    return status, steps, trace, states


def run_pipeline(requests_path: str, output_path: str, explain: str = "") -> None:
    requests = load_deletion_requests(requests_path)
    index, linker, rules = build_engine()

    output_rows = []
    for req in requests:
        case_id = req["case_id"]
        if not authorizes_deletion(req.get("request_text", "")):
            status, steps = "NOT_APPLICABLE", []
        else:
            status, steps, trace, states = audit_case(req, linker, index, rules)
            if explain and case_id == explain:
                print(f"[explain] {case_id} status={status}")
                for resource_id in sorted(states):
                    state = states[resource_id]
                    print(
                        f"  {resource_id:22s} {state.category:20s} state={state.state:12s} "
                        f"evidence={state.evidence_id} link={state.link_path}"
                    )
                for resource_id in sorted(trace.resources):
                    if resource_id not in states:
                        paths = trace.resources[resource_id].link_paths
                        if paths:
                            print(f"  {resource_id:22s} (linked, no observation) {paths[0].describe()}")
        output_rows.append(
            {
                "case_id": case_id,
                "deletion_status": status,
                "steps_json": serialize_steps(steps),
            }
        )

    output_rows.sort(key=lambda row: int(row["case_id"].split("_")[1]))
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for row in output_rows:
            writer.writerow([row["case_id"], row["deletion_status"], row["steps_json"]])

    expected = [row["case_id"] for row in requests]
    is_valid, errors = validate_output_file(output_path, expected_cases=expected, allow_empty_steps=True)
    if not is_valid:
        print(f"Validation failed for {output_path}:", file=sys.stderr)
        for error in errors[:10]:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    evidence_dates = {fid: meta["captured_at"] for fid, meta in index.files.items()}
    audit_dates = {row["case_id"]: row["audit_at"] for row in requests}
    violations = check_rows(output_rows, expected, evidence_dates, audit_dates)
    if violations:
        print(f"Invariant violations: {len(violations)}", file=sys.stderr)
        for violation in violations[:10]:
            print(f"  - {violation}", file=sys.stderr)
    print(f"Wrote {output_path}: {len(output_rows)} cases, validation=ok, invariants={len(violations)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists deletion audit agent")
    parser.add_argument("--requests", default=os.path.join(REPO_ROOT, "dataset", "deletion_requests.csv"))
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "output.csv"))
    parser.add_argument("--explain", default="", help="Print per-resource state for one case id")
    args = parser.parse_args()
    run_pipeline(args.requests, args.out, explain=args.explain)


if __name__ == "__main__":
    main()
