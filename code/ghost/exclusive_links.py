"""Conservative, opt-in exclusive matching for workflow dispatch events."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Tuple

from code.ghost.linker import (
    FAMILY_CATEGORIES,
    WORKFLOW_FAMILIES,
    WORKFLOW_WINDOW_MINUTES,
    CaseTrace,
    _seconds_between,
    resource_family,
)


def _family_linked(trace: CaseTrace, family: str) -> bool:
    categories = FAMILY_CATEGORIES.get(family, set())
    return any(
        resource_family(rid) == family
        or (categories and any(obs.record_type in categories for obs in rtrace.observations))
        for rid, rtrace in trace.resources.items()
    )


def _grounded_resource(trace: CaseTrace, resource_id: str) -> bool:
    resource = trace.resources.get(resource_id)
    return bool(resource and any(
        path.reason.startswith(("identifier", "catalog_link", "activity_propagation"))
        for path in resource.link_paths
    ))


def build_exclusive_assignments(
    requests: Iterable[Dict[str, str]],
    linker,
    base_traces: Mapping[str, CaseTrace] | None = None,
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, object], Dict[str, CaseTrace]]:
    """Build one-to-one assignments after excluding already-taken resources."""
    requests = list(requests)
    traces = dict(base_traces or {
        case["case_id"]: linker.link_case_without_workflow(case, case.get("audit_at", ""))
        for case in requests
    })
    taken = {
        rid
        for trace in traces.values()
        for rid in trace.resources
        if _grounded_resource(trace, rid)
    }
    edges = []
    excluded_taken = 0
    for case in requests:
        case_id = case["case_id"]
        audit_at = case.get("audit_at", "")
        for family, (_, event_types) in WORKFLOW_FAMILIES.items():
            if _family_linked(traces[case_id], family):
                continue
            for row in linker._dispatches.get(family, []):
                rid = row.get("resource_id", "")
                event_time = row.get("event_time", "")
                if rid in taken:
                    excluded_taken += 1
                    continue
                if not event_time or event_time > audit_at:
                    continue
                if abs(_seconds_between(event_time, case.get("reported_at", ""))) > WORKFLOW_WINDOW_MINUTES * 60:
                    continue
                if row.get("event_type") not in event_types:
                    continue
                edges.append((case_id, family, rid, row))

    by_case = defaultdict(list)
    by_event = defaultdict(list)
    for edge in edges:
        by_case[(edge[0], edge[1])].append(edge)
        by_event[(edge[1], edge[2])].append(edge)
    selected: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for case_id, family, rid, row in edges:
        if len(by_case[(case_id, family)]) == 1 and len(by_event[(family, rid)]) == 1:
            selected[case_id].append(row)
    diagnostics = {
        "candidate_edges": len(edges),
        "excluded_taken_events": excluded_taken,
        "forced_matches": sum(len(rows) for rows in selected.values()),
        "rejected_case_ambiguities": sum(1 for rows in by_case.values() if len(rows) > 1),
        "rejected_event_ambiguities": sum(1 for rows in by_event.values() if len(rows) > 1),
    }
    return dict(selected), diagnostics, traces


def link_cases_exclusive(requests: Iterable[Dict[str, str]], linker):
    """Produce final traces using only globally forced exclusive links."""
    requests = list(requests)
    assignments, diagnostics, base_traces = build_exclusive_assignments(requests, linker)
    traces = {
        case["case_id"]: linker.link_case_selected(
            case, case.get("audit_at", ""), assignments.get(case["case_id"], [])
        )
        for case in requests
    }
    return traces, assignments, diagnostics, base_traces
