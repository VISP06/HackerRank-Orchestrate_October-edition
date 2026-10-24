#!/usr/bin/env python3
"""Evaluation harness for Ghost Data Still Exists deletion audit agent."""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code.main import run_pipeline


def step_to_tuple(step: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    """Convert step dict to canonical tuple for exact comparison."""
    return (
        step.get("phase", ""),
        step.get("system_id", ""),
        step.get("resource_id", ""),
        step.get("operation", ""),
        step.get("state", ""),
        step.get("evidence_id", ""),
    )


def load_output_dict(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Load an output CSV into a mapping: case_id -> {deletion_status, steps}."""
    results = {}
    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row["case_id"].strip()
            status = row["deletion_status"].strip()
            try:
                steps = json.loads(row["steps_json"])
            except Exception:
                steps = []
            results[cid] = {
                "status": status,
                "steps": steps,
                "step_tuples": [step_to_tuple(s) for s in steps],
            }
    return results


def evaluate(
    predictions_path: str,
    ground_truth_path: str,
    verbose_diff: bool = True,
) -> Dict[str, Any]:
    """Compare prediction output CSV against ground truth CSV."""
    preds = load_output_dict(predictions_path)
    truth = load_output_dict(ground_truth_path)

    cases = sorted(truth.keys())
    total_cases = len(cases)

    # 1. Status metrics
    correct_status_count = 0
    status_counts = Counter()
    status_tp = Counter()
    status_pred = Counter()
    status_truth = Counter()

    # 2. Step metrics
    total_tp_steps = 0
    total_pred_steps = 0
    total_truth_steps = 0

    # 3. Sequence accuracy
    exact_sequence_matches = 0

    diffs = []

    for cid in cases:
        t_data = truth[cid]
        p_data = preds.get(cid, {"status": "MISSING", "steps": [], "step_tuples": []})

        t_stat = t_data["status"]
        p_stat = p_data["status"]

        status_truth[t_stat] += 1
        status_pred[p_stat] += 1

        status_match = (p_stat == t_stat)
        if status_match:
            correct_status_count += 1
            status_tp[t_stat] += 1

        t_steps = t_data["step_tuples"]
        p_steps = p_data["step_tuples"]

        total_truth_steps += len(t_steps)
        total_pred_steps += len(p_steps)

        # Multiset step matching
        t_counter = Counter(t_steps)
        p_counter = Counter(p_steps)
        matched_steps = sum((t_counter & p_counter).values())
        total_tp_steps += matched_steps

        # Sequence match check (status and ordered step sequence must be identical)
        seq_match = status_match and (t_steps == p_steps)
        if seq_match:
            exact_sequence_matches += 1
        else:
            # Build compact failure diff
            missing_steps = list((t_counter - p_counter).elements())
            extra_steps = list((p_counter - t_counter).elements())

            diff_entry = {
                "case_id": cid,
                "status_pred": p_stat,
                "status_truth": t_stat,
                "missing_steps": missing_steps,
                "extra_steps": extra_steps,
            }
            diffs.append(diff_entry)

    # Calculations
    status_accuracy = correct_status_count / total_cases if total_cases > 0 else 0.0
    sequence_accuracy = exact_sequence_matches / total_cases if total_cases > 0 else 0.0

    step_precision = total_tp_steps / total_pred_steps if total_pred_steps > 0 else 0.0
    step_recall = total_tp_steps / total_truth_steps if total_truth_steps > 0 else 0.0
    step_f1 = (
        (2 * step_precision * step_recall) / (step_precision + step_recall)
        if (step_precision + step_recall) > 0
        else 0.0
    )

    # Per-status breakdown
    all_statuses = ["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]
    per_status = {}
    for st in all_statuses:
        tp = status_tp[st]
        pred_c = status_pred[st]
        truth_c = status_truth[st]
        prec = tp / pred_c if pred_c > 0 else 0.0
        rec = tp / truth_c if truth_c > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        per_status[st] = {
            "truth": truth_c,
            "pred": pred_c,
            "tp": tp,
            "precision": prec,
            "recall": rec,
            "f1": f1,
        }

    results = {
        "total_cases": total_cases,
        "status_accuracy": status_accuracy,
        "per_status": per_status,
        "total_truth_steps": total_truth_steps,
        "total_pred_steps": total_pred_steps,
        "step_precision": step_precision,
        "step_recall": step_recall,
        "step_f1": step_f1,
        "exact_sequence_matches": exact_sequence_matches,
        "sequence_accuracy": sequence_accuracy,
        "diffs": diffs,
    }

    # Print Report
    print("=" * 65)
    print("           GHOST DATA DELETION AUDIT EVALUATION REPORT          ")
    print("=" * 65)
    print(f"Total Evaluation Cases: {total_cases}")
    print(f"Status Accuracy:        {status_accuracy * 100:.2f}% ({correct_status_count}/{total_cases})")
    print(f"Sequence Accuracy:      {sequence_accuracy * 100:.2f}% ({exact_sequence_matches}/{total_cases})")
    print("-" * 65)
    print("Per-Status Breakdown:")
    for st in all_statuses:
        s = per_status[st]
        print(f"  {st:<15} Truth={s['truth']:<3} Pred={s['pred']:<3} P={s['precision']:.3f} R={s['recall']:.3f} F1={s['f1']:.3f}")
    print("-" * 65)
    print(f"Step-Level Evaluation (Exact 6-tuples):")
    print(f"  Truth Steps:   {total_truth_steps}")
    print(f"  Pred Steps:    {total_pred_steps}")
    print(f"  True Positives:{total_tp_steps}")
    print(f"  Precision:     {step_precision:.4f}")
    print(f"  Recall:        {step_recall:.4f}")
    print(f"  F1 Score:      {step_f1:.4f}")
    print("-" * 65)

    if diffs and verbose_diff:
        print(f"Compact Failure Diffs ({len(diffs)} cases):")
        for d in diffs[:10]:
            cid = d["case_id"]
            stat_info = f"Status: {d['status_pred']} (expected: {d['status_truth']})"
            steps_info = f"-{len(d['missing_steps'])} steps, +{len(d['extra_steps'])} steps"
            print(f"  [{cid}] {stat_info} | {steps_info}")
            if d["missing_steps"]:
                first_missing = d["missing_steps"][0]
                print(f"       Missing ex: {first_missing[0]}:{first_missing[1]}:{first_missing[2]}:{first_missing[3]}")
        if len(diffs) > 10:
            print(f"  ... and {len(diffs) - 10} more failures.")
    print("=" * 65)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Deletion Audit Pipeline on Samples")
    parser.add_argument(
        "--requests",
        type=str,
        default="dataset/sample_deletion_requests.csv",
        help="Path to sample deletion requests CSV (default: dataset/sample_deletion_requests.csv)",
    )
    parser.add_argument(
        "--ground_truth",
        type=str,
        default="dataset/sample_output.csv",
        help="Path to sample ground truth CSV (default: dataset/sample_output.csv)",
    )
    parser.add_argument(
        "--pred",
        type=str,
        default=None,
        help="Path to existing predictions CSV. If omitted, pipeline will run on --requests.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="/tmp/sample_predictions.csv",
        help="Path to save pipeline predictions if running (default: /tmp/sample_predictions.csv)",
    )
    args = parser.parse_args()

    pred_file = args.pred
    if not pred_file:
        run_pipeline(args.requests, args.out)
        pred_file = args.out

    evaluate(pred_file, args.ground_truth)


if __name__ == "__main__":
    main()
