#!/usr/bin/env python3
"""Main entry point for Ghost Data Still Exists deletion audit agent."""

import argparse
import csv
import os
import re
import sys

# Ensure repository root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code.ghost.loaders import load_deletion_requests
from code.ghost.validate import validate_output_file

NON_DELETION_PATTERNS = [
    r"\bleave\s+(?:the\s+)?account\s+active\b",
    r"\bnot\s+asking\s+for\s+deletion\b",
    r"\bnot\s+a\s+request\s+to\s+erase\b",
    r"\bkeep\s+(?:the\s+)?account\b",
    r"\bdo\s+not\s+close\s+the\s+account\b",
    r"\bwithout\s+removing\s+any\s+of\s+my\s+records\b",
    r"\bmarketing\s+lists\s+only\b",
    r"\binformation\s+request\b",
    r"\bleave\s+my\s+profile\b",
    r"\bcontinue\s+using\s+the\s+service\b",
    r"\bdon't\s+delete\s+or\s+change\s+anything\b",
    r"\bdo\s+not\s+delete\b",
]

NON_DELETION_REGEX = re.compile("|".join(NON_DELETION_PATTERNS), re.IGNORECASE)


def is_deletion_request(text: str) -> bool:
    """Check if request authorizes personal data deletion."""
    if NON_DELETION_REGEX.search(text):
        return False
    return True


def run_pipeline(requests_path: str, output_path: str) -> None:
    """Run baseline audit pipeline and write validated output.csv."""
    requests = load_deletion_requests(requests_path)
    output_rows = []

    for req in requests:
        case_id = req["case_id"]
        req_text = req.get("request_text", "")

        if not is_deletion_request(req_text):
            status = "NOT_APPLICABLE"
        else:
            status = "INCOMPLETE"

        output_rows.append({
            "case_id": case_id,
            "deletion_status": status,
            "steps_json": "[]",
        })

    # Write output CSV
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for r in output_rows:
            writer.writerow([r["case_id"], r["deletion_status"], r["steps_json"]])

    # Validate output
    expected_case_ids = [r["case_id"] for r in requests]
    is_valid, errors = validate_output_file(output_path, expected_cases=expected_case_ids, allow_empty_steps=True)
    if not is_valid:
        print(f"Validation failed for {output_path}:", file=sys.stderr)
        for err in errors[:10]:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print(f"Successfully generated baseline {output_path} ({len(output_rows)} cases, valid schema).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists Deletion Audit Agent")
    parser.add_argument(
        "--requests",
        type=str,
        default="dataset/deletion_requests.csv",
        help="Path to deletion requests CSV (default: dataset/deletion_requests.csv)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="output.csv",
        help="Path to output CSV (default: output.csv)",
    )
    args = parser.parse_args()

    run_pipeline(args.requests, args.out)


if __name__ == "__main__":
    main()
