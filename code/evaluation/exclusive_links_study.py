#!/usr/bin/env python3
"""Generate the exclusive-link validation study without hand-typed metrics."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from code.ghost.evidence_index import load_evidence_index
from code.ghost.exclusive_links import _family_linked
from code.ghost.intent import authorizes_deletion
from code.ghost.linker import (
    WORKFLOW_FAMILIES,
    WORKFLOW_WINDOW_MINUTES,
    CaseLinker,
    _seconds_between,
    load_activity_rows,
    resource_family,
)
from code.ghost.loaders import (
    load_deletion_requests,
    load_user_audit_log,
    load_user_identities,
)
from code.main import run_pipeline
from code.evaluation.run_eval import evaluate, load_output_dict


def make_linker():
    dataset = os.path.join(ROOT, "dataset")
    index = load_evidence_index(os.path.join(dataset, "evidence_files.csv"), dataset)
    return CaseLinker(
        index,
        load_activity_rows(os.path.join(dataset, "system_activity.csv")),
        load_user_identities(os.path.join(dataset, "user_identities.csv")),
        load_user_audit_log(os.path.join(dataset, "user_audit_log.csv")),
    )


def candidate_rows(case, family, linker):
    event_types = WORKFLOW_FAMILIES[family][1]
    result = []
    for row in linker._dispatches.get(family, []):
        event_time = row.get("event_time", "")
        if not event_time or event_time > case.get("audit_at", ""):
            continue
        if abs(_seconds_between(event_time, case.get("reported_at", ""))) > WORKFLOW_WINDOW_MINUTES * 60:
            continue
        if row.get("event_type") in event_types:
            result.append(row)
    return result


def self_supervised(requests, linker, base_traces):
    targets = []
    for case in requests:
        trace = base_traces[case["case_id"]]
        for rid, resource in trace.resources.items():
            family = next((f for f in WORKFLOW_FAMILIES if rid.startswith(f + "_")), "")
            if family and any(path.reason.startswith("identifier") for path in resource.link_paths):
                targets.append((case["case_id"], rid, family))

    cases_by_id = {case["case_id"]: case for case in requests}
    taken = {
        rid for trace in base_traces.values() for rid in trace.resources
        if any(path.reason.startswith(("identifier", "catalog_link", "activity_propagation")) for resource in trace.resources.values() for path in resource.link_paths if resource.resource_id == rid)
    }
    all_candidates = {
        (case["case_id"], family): candidate_rows(case, family, linker)
        for case in requests for family in WORKFLOW_FAMILIES
    }

    def unique_assignment(edges):
        by_case = defaultdict(list)
        by_event = defaultdict(list)
        for edge in edges:
            by_case[(edge[0], edge[1])].append(edge)
            by_event[(edge[1], edge[2])].append(edge)
        selected = []
        for edge in edges:
            if len(by_case[(edge[0], edge[1])]) == 1 and len(by_event[(edge[1], edge[2])]) == 1:
                selected.append(edge)
        return selected

    result = {}
    for mode in ("old", "exclusive"):
        totals = Counter()
        by_type = defaultdict(Counter)
        for case_id, rid, family in targets:
            case = next(c for c in requests if c["case_id"] == case_id)
            if mode == "exclusive":
                hidden_taken = taken - {rid}
                edges = []
                for key, rows in all_candidates.items():
                    cid, candidate_family = key
                    trace = base_traces[cid]
                    family_linked = _family_linked(trace, candidate_family)
                    if cid == case_id and candidate_family == family:
                        family_linked = any(other != rid and resource_family(other) == candidate_family for other in trace.resources)
                    if family_linked:
                        continue
                    for row in rows:
                        if row.get("resource_id") not in hidden_taken:
                            edges.append((cid, candidate_family, row.get("resource_id", ""), row))
                selected = [edge[3] for edge in unique_assignment(edges) if edge[0] == case_id and edge[1] == family]
            else:
                selected = []
                if not any(other != rid and resource_family(other) == family for other in base_traces[case_id].resources):
                    candidates = candidate_rows(case, family, linker)
                    if len(candidates) == 1:
                        selected = candidates
            assigned = selected[0].get("resource_id") if len(selected) == 1 else ""
            if assigned == rid:
                label = "correct"
            elif assigned:
                label = "wrong"
            else:
                label = "left_unlinked"
            totals[label] += 1
            by_type[family][label] += 1
        totals["precision"] = totals["correct"] / (totals["correct"] + totals["wrong"]) if totals["correct"] + totals["wrong"] else 0.0
        result[mode] = {"overall": dict(totals), "by_resource_type": {k: dict(v) for k, v in sorted(by_type.items())}}
    return result


def sample_metrics(path, label):
    truth = os.path.join(ROOT, "dataset", "sample_output.csv")
    return evaluate(path, truth, verbose_diff=False, label=label, summary_only=True)


def full_diff(path):
    baseline = load_output_dict(os.path.join(ROOT, "output.csv"))
    candidate = load_output_dict(path)
    changed = []
    failures = []
    for case_id in sorted(baseline, key=lambda x: int(x.split("_")[1])):
        old, new = baseline[case_id], candidate[case_id]
        if old == new:
            continue
        fields = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
        old_steps = {tuple(step.get(field, "") for field in fields) for step in old["steps"]}
        new_steps = {tuple(step.get(field, "") for field in fields) for step in new["steps"]}
        added = new_steps - old_steps
        removed = old_steps - new_steps
        allowed = not removed and old["status"] == new["status"] or (
            not removed and old["status"] == "COMPLETE" and new["status"] == "INCOMPLETE"
        )
        if not allowed:
            failures.append(case_id)
        changed.append({"case_id": case_id, "old_status": old["status"], "new_status": new["status"], "added_steps": len(added), "removed_steps": len(removed)})
    return changed, failures


def main():
    dataset = os.path.join(ROOT, "dataset")
    requests = [r for r in load_deletion_requests(os.path.join(dataset, "deletion_requests.csv")) if authorizes_deletion(r.get("request_text", ""))]
    linker = make_linker()
    base_traces = {c["case_id"]: linker.link_case_without_workflow(c, c["audit_at"]) for c in requests}
    self_test = self_supervised(requests, linker, base_traces)

    with tempfile.TemporaryDirectory() as temp:
        sample_before_out = os.path.join(temp, "sample_before.csv")
        sample_after_out = os.path.join(temp, "sample_after.csv")
        full_out = os.path.join(temp, "full.csv")
        with contextlib.redirect_stdout(io.StringIO()):
            run_pipeline(os.path.join(dataset, "sample_deletion_requests.csv"), sample_before_out, exclusive_links=False, offline=True)
            before = sample_metrics(sample_before_out, "before")
            run_pipeline(os.path.join(dataset, "sample_deletion_requests.csv"), sample_after_out, exclusive_links=True, offline=True)
            after = sample_metrics(sample_after_out, "after")
            run_pipeline(os.path.join(dataset, "deletion_requests.csv"), full_out, exclusive_links=True, offline=True)
        sample_ids = [r["case_id"] for r in load_deletion_requests(os.path.join(dataset, "sample_deletion_requests.csv"))]
        dev_ids = {cid for cid in sample_ids if int(cid.split("_")[1]) % 4 != 0}
        heldout_ids = set(sample_ids) - dev_ids
        split_metrics = {}
        for label, path in (("before", sample_before_out), ("after", sample_after_out)):
            split_metrics[label] = {
                "dev": evaluate(path, os.path.join(dataset, "sample_output.csv"), verbose_diff=False, case_filter=dev_ids, summary_only=True),
                "heldout": evaluate(path, os.path.join(dataset, "sample_output.csv"), verbose_diff=False, case_filter=heldout_ids, summary_only=True),
            }
        changed, failures = full_diff(full_out)

    report = [
        "# Exclusive Link Study",
        "",
        "Generated by `code/evaluation/exclusive_links_study.py`; all figures below are computed from participant-facing data.",
        "",
        "## A. Self-supervised precision",
        "",
        "| Rule | Correct | Wrong | Left unlinked | Precision |",
        "|---|---:|---:|---:|---:|",
    ]
    for mode, label in (("old", "Old +/-15-minute rule"), ("exclusive", "Exclusive rule")):
        values = self_test[mode]["overall"]
        report.append(f"| {label} | {values.get('correct', 0)} | {values.get('wrong', 0)} | {values.get('left_unlinked', 0)} | {values.get('precision', 0.0):.4f} |")
    report += ["", "| Type | Rule | Correct | Wrong | Left unlinked | Precision |", "|---|---|---:|---:|---:|---:|"]
    for family in sorted(self_test["exclusive"]["by_resource_type"]):
        for mode, label in (("old", "old"), ("exclusive", "exclusive")):
            values = self_test[mode]["by_resource_type"].get(family, {})
            denominator = values.get("correct", 0) + values.get("wrong", 0)
            precision = values.get("correct", 0) / denominator if denominator else 0.0
            report.append(f"| {family} | {label} | {values.get('correct', 0)} | {values.get('wrong', 0)} | {values.get('left_unlinked', 0)} | {precision:.4f} |")
    report += ["", "## B. Sample evaluation", "", "| Metric | Before | After |", "|---|---:|---:|"]
    for key, label in (("status_accuracy", "Status accuracy"), ("step_precision", "Precision"), ("step_recall", "Recall"), ("step_f1", "F1"), ("sequence_accuracy", "Sequence accuracy")):
        report.append(f"| {label} | {before[key]:.4f} | {after[key]:.4f} |")
    missing_before = {tuple(step) for diff in before["diffs"] for step in diff["missing_steps"]}
    missing_after = {tuple(step) for diff in after["diffs"] for step in diff["missing_steps"]}
    recovered = sorted(missing_before - missing_after)
    report += ["", "Recovered expected steps:"] + [f"- `{step}`" for step in recovered] if recovered else ["", "Recovered expected steps: none"]
    report += ["", "| Split | Before status / P / R / F1 | After status / P / R / F1 |", "|---|---|---|"]
    for split, label in (("dev", "Dev"), ("heldout", "Held-out")):
        old = split_metrics["before"][split]
        new = split_metrics["after"][split]
        report.append(f"| {label} | {old['status_accuracy']:.4f} / {old['step_precision']:.4f} / {old['step_recall']:.4f} / {old['step_f1']:.4f} | {new['status_accuracy']:.4f} / {new['step_precision']:.4f} / {new['step_recall']:.4f} / {new['step_f1']:.4f} |")
    report += ["", "## C. Full-run diff", "", f"Changed cases: {len(changed)}", f"Allowed-change violations: {len(failures)}"]
    report.append("Changed cases (all):")
    for item in changed:
        report.append(f"- `{item['case_id']}`: {item['old_status']} -> {item['new_status']}; +{item['added_steps']} steps, -{item['removed_steps']} steps")
    report.append("Examples (up to 10):")
    for item in changed[:10]:
        report.append(f"- `{item['case_id']}`: {item['old_status']} -> {item['new_status']}; +{item['added_steps']} steps, -{item['removed_steps']} steps")
    report += ["", "## Decision", "", "The study is evidence for the adoption gates; production remains default-OFF until all gates pass."]
    out = os.path.join(ROOT, "notes", "EXCLUSIVE_LINKS_STUDY.md")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(report) + "\n")
    print(json.dumps({"study": out, "old": self_test["old"]["overall"], "exclusive": self_test["exclusive"]["overall"], "sample_before": {k: before[k] for k in ("status_accuracy", "step_precision", "step_recall", "step_f1", "sequence_accuracy")}, "sample_after": {k: after[k] for k in ("status_accuracy", "step_precision", "step_recall", "step_f1", "sequence_accuracy")}, "changed_cases": len(changed), "diff_failures": len(failures)}, sort_keys=True))


if __name__ == "__main__":
    main()
