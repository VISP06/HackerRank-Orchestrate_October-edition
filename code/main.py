#!/usr/bin/env python3
"""Ghost Data Still Exists - deletion audit pipeline.

The deterministic engine handles all decisions.  An optional LLM layer adds:
  (a) screenshot extraction (11 PNGs → Observations)
  (b) enhanced PDF extraction (4 PDFs → Observations)
  (c) intent cross-check (second opinion on deletion vs non-deletion)

LLM results are disk-cached so subsequent runs are offline-reproducible.
If no API key or network is available, the pipeline falls back to cache
or runs without LLM features.
"""

import argparse
import csv
import json
import os
import sys
import time

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
from code.ghost.explain import build_explanation, render_plain


def _dataset_path(name: str) -> str:
    return os.path.join(REPO_ROOT, "dataset", name)


def _load_dotenv() -> None:
    """Load .env from repo root if present (never print values)."""
    env_path = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def build_engine(dataset_dir: str = "", llm=None, llm_tasks: str = "screenshots,pdfs,intent"):
    """Build the evidence index, linker, and rules.

    If an LLM client is provided, screenshot and enhanced PDF observations
    are extracted and merged into the index.
    """
    dataset_dir = dataset_dir or os.path.join(REPO_ROOT, "dataset")
    enabled = {t.strip() for t in (llm_tasks or "").split(",") if t.strip()}

    # Load base evidence index (deterministic parsers)
    index = load_evidence_index(
        os.path.join(dataset_dir, "evidence_files.csv"), dataset_dir
    )

    # LLM-enhanced extraction
    screenshot_results = []
    pdf_results = []
    if llm is not None:
        manifest_path = os.path.join(dataset_dir, "evidence_files.csv")
        manifest = list(csv.DictReader(open(manifest_path, "r", encoding="utf-8")))

        # Screenshot extraction
        if "screenshots" in enabled:
            from code.ghost.llm_screenshots import extract_all_screenshots
            screenshot_obs, screenshot_results = extract_all_screenshots(
                llm, manifest, dataset_dir, dataset_dir
            )
            for obs in screenshot_obs:
                index.add(obs)

        # Enhanced PDF extraction
        if "pdfs" in enabled:
            from code.ghost.llm_pdfs import extract_all_pdfs
            pdf_obs, pdf_results = extract_all_pdfs(llm, manifest, dataset_dir)
            # Merge LLM PDF observations: for files that the deterministic parser
            # already handled, only add new resource IDs not already present.
            existing_pdf_resources = set()
            for obs in index.observations:
                if obs.source_kind == "pdf":
                    existing_pdf_resources.add((obs.file_id, obs.resource_id))
            for obs in pdf_obs:
                if (obs.file_id, obs.resource_id) not in existing_pdf_resources:
                    index.add(obs)

        # Rebuild index after adding new observations
        index.build()

    # Keep extraction reports available to callers without changing the
    # long-standing (index, linker, rules) return contract used by the
    # evaluation scripts.
    index.llm_extraction = {
        "screenshots": screenshot_results,
        "pdfs": pdf_results,
    }

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


def run_pipeline(
    requests_path: str,
    output_path: str,
    explain: str = "",
    fresh: bool = False,
    skip_llm: bool = False,
    llm_tasks: str = "screenshots,pdfs,intent",
) -> dict:
    """Run the full pipeline. Returns a summary dict."""
    _load_dotenv()

    requests = load_deletion_requests(requests_path)

    # Initialize LLM client (optional)
    llm = None
    intent_classifications = []
    intent_disagreements = []
    enabled_tasks = {t.strip() for t in (llm_tasks or "").split(",") if t.strip()}
    if not skip_llm:
        from code.ghost.llm import LLMClient
        llm = LLMClient(fresh=fresh)

    index, linker, rules = build_engine(llm=llm, llm_tasks=llm_tasks)
    extraction = getattr(index, "llm_extraction", {})
    screenshot_results = extraction.get("screenshots", [])
    pdf_results = extraction.get("pdfs", [])

    # Intent cross-check (Task 4)
    if llm is not None and "intent" in enabled_tasks:
        from code.ghost.llm_intent import classify_all_intents
        intent_classifications, intent_disagreements = classify_all_intents(
            llm, requests, authorizes_deletion
        )
        if intent_disagreements:
            print(
                f"[intent] {len(intent_disagreements)} disagreement(s) between "
                f"deterministic and LLM classifiers",
                file=sys.stderr,
            )
            for d in intent_disagreements:
                print(
                    f"  {d['case_ids']}: det={d['deterministic']} llm={d['llm']} "
                    f"reason={d['reason'][:60]}",
                    file=sys.stderr,
                )

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

    # Status distribution
    from collections import Counter
    status_dist = Counter(row["deletion_status"] for row in output_rows)
    step_count = sum(len(json.loads(row["steps_json"])) for row in output_rows)

    summary = {
        "cases": len(output_rows),
        "status_distribution": dict(status_dist),
        "total_steps": step_count,
        "invariant_violations": len(violations),
        "screenshot_results": screenshot_results,
        "pdf_results": pdf_results,
        "intent_disagreements": intent_disagreements,
        "intent_classifications_count": len(intent_classifications),
    }

    # Usage accounting
    if llm is not None:
        summary["llm_usage"] = llm.estimate_cost()

    print(
        f"Wrote {output_path}: {len(output_rows)} cases, "
        f"{status_dist.get('COMPLETE', 0)} COMPLETE / "
        f"{status_dist.get('INCOMPLETE', 0)} INCOMPLETE / "
        f"{status_dist.get('NOT_APPLICABLE', 0)} NOT_APPLICABLE, "
        f"{step_count} steps, validation=ok, invariants={len(violations)}"
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists deletion audit agent")
    parser.add_argument("--requests", default=os.path.join(REPO_ROOT, "dataset", "deletion_requests.csv"))
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "output.csv"))
    parser.add_argument("--explain", default="", help="Print per-resource state for one case id")
    parser.add_argument("--json", action="store_true", help="Emit --explain as JSON")
    parser.add_argument("--explain-all", default="", metavar="DIR", help="Write one explanation JSON file per case")
    parser.add_argument("--fresh", action="store_true", help="Bypass all LLM caches for a fresh run")
    parser.add_argument("--skip-llm", action="store_true", help="Skip all LLM features (deterministic only)")
    parser.add_argument(
        "--llm-tasks",
        default="screenshots,pdfs,intent",
        help="Comma-separated LLM tasks to enable (screenshots,pdfs,intent)",
    )
    args = parser.parse_args()
    if args.explain or args.explain_all:
        from code.ghost.llm import LLMClient
        # Empty credentials make this explicitly cache-only: explanation mode
        # can never create an API client or make a network request.
        os.environ.pop("GEMINI_API_KEY", None)
        offline_llm = LLMClient(api_key="", fresh=False)
        requests = load_deletion_requests(args.requests)
        index, linker, rules = build_engine(llm=offline_llm)
        wanted = {args.explain} if args.explain else {r["case_id"] for r in requests}
        explanations = {}
        for req in requests:
            if req["case_id"] not in wanted:
                continue
            if authorizes_deletion(req.get("request_text", "")):
                status, steps, trace, states = audit_case(req, linker, index, rules)
            else:
                trace = linker.link_case(req, req.get("audit_at", ""))
                status, steps, states = "NOT_APPLICABLE", [], {}
            explanations[req["case_id"]] = build_explanation(req, trace, states, rules, steps, status, index, linker)
        if args.explain_all:
            os.makedirs(args.explain_all, exist_ok=True)
            for case_id in sorted(explanations, key=lambda value: int(value.split("_")[1])):
                with open(os.path.join(args.explain_all, case_id + ".json"), "w", encoding="utf-8") as handle:
                    json.dump(explanations[case_id], handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        elif args.json:
            print(json.dumps(explanations[args.explain], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        else:
            print(render_plain(explanations[args.explain]))
        return
    summary = run_pipeline(
        args.requests, args.out,
        explain=args.explain,
        fresh=args.fresh,
        skip_llm=args.skip_llm,
        llm_tasks=args.llm_tasks,
    )

    # Print summary
    if summary.get("llm_usage"):
        usage = summary["llm_usage"]
        print(f"\nLLM Usage: model={usage['model']}, calls={usage['total_calls']}, "
              f"cache_hits={usage['cache_hits']}, "
              f"tokens={usage['total_input_tokens']}in/{usage['total_output_tokens']}out, "
              f"cost=${usage['total_cost_usd']:.4f}")
        for task, stats in usage.get("by_task", {}).items():
            print(f"  {task}: calls={stats['calls']}, cache_hits={stats.get('cache_hits', 0)}, "
                  f"tokens={stats['input_tokens']}in/{stats['output_tokens']}out")


if __name__ == "__main__":
    main()
