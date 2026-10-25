"""Post-hoc, deterministic explanations for an already computed audit.

This module deliberately does not participate in a decision.  It consumes the
trace, reconstructed states, assessments, and steps returned by the normal
pipeline and turns those objects into an audit-friendly record.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

from code.ghost.evidence_index import category_for, system_for
from code.ghost.loaders import natural_sort_key
from code.ghost.rules import assess_state, required_action
from code.ghost.intent import NEGATIVE_RE


def mask_email(value: str) -> str:
    if "@" not in value:
        return "***"
    local, domain = value.split("@", 1)
    return (local[:3] + "***" if len(local) > 3 else local + "***") + "@" + domain


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return ("*" * max(0, len(digits) - 2) + digits[-2:]) if digits else "***"


def mask_name(value: str) -> str:
    return "".join(part[:1].upper() + "." for part in re.findall(r"[\w]+", value or "", re.UNICODE))


def mask_text(value: str) -> str:
    value = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", lambda m: mask_email(m.group(0)), value or "")
    return re.sub(r"\+\d[\d\s().\-]{6,}\d", lambda m: mask_phone(m.group(0)), value)


def _safe_identity(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": raw.get("user_id", ""),
        "name": mask_name(raw.get("name", "")),
        "email": mask_email(raw.get("email", "")),
        "emails": [mask_email(v) for v in raw.get("all_emails", [])],
        "historical_emails": [mask_email(v) for v in raw.get("historical_emails", [])],
        "phones": [mask_phone(v) for v in raw.get("all_phones", [])],
        "historical_phones": [mask_phone(v) for v in raw.get("historical_phones", [])],
        "names": [mask_name(v) for v in raw.get("all_names", [])],
    }


def _captured(files: Dict[str, Dict[str, str]], evidence_id: str) -> str:
    return (files.get(evidence_id) or {}).get("captured_at", "")


def _eligible_observations(resource_trace: Any, audit_at: str) -> List[Any]:
    return sorted(
        [o for o in resource_trace.observations
         if not (o.captured_at and o.captured_at > audit_at)
         and not (o.observed_at and o.observed_at > audit_at)],
        key=lambda o: (o.observed_at, o.captured_at, o.file_id),
    )


def _safe_path(path: Any, index: Any, linker: Any, audit_at: str) -> str:
    evidence = path.evidence_id
    if evidence in index.files:
        if index.files[evidence].get("captured_at", "") > audit_at:
            evidence = ""
    elif evidence:
        activity = next((row for row in linker.activity_rows if row.get("activity_id") == evidence), None)
        if activity and activity.get("event_time", "") > audit_at:
            evidence = ""
    bits = [path.reason]
    if path.identifier:
        bits.append(mask_text(path.identifier))
    if evidence:
        bits.append(evidence)
    return ":".join(bits)


def _plain_step(step: Dict[str, Any]) -> str:
    operation = step["operation"].replace("_", " ").lower()
    evidence = f" (evidence {step['evidence_id']})" if step.get("evidence_id") else ""
    return f"{step['step_no']}. {step['phase'].title()}: {operation} for {step['resource_id']} in {step['system_id']} ({step['state']}){evidence}."


def build_explanation(case: Dict[str, str], trace: Any, states: Dict[str, Any], rules: Dict[str, Dict[str, str]], steps: List[Dict[str, Any]], status: str, index: Any, linker: Any) -> Dict[str, Any]:
    audit_at = case.get("audit_at", "")
    raw = trace.cluster.get("raw", {})
    resources: List[Dict[str, Any]] = []
    for rid in sorted(trace.resources, key=natural_sort_key):
        rtrace = trace.resources[rid]
        state = states.get(rid)
        category = state.category if state else (rtrace.category or category_for(rid))
        action = required_action(category, state, rules, audit_at) if state else (rules.get(category, {}).get("required_action", "") or "RETAIN")
        observations = []
        for obs in _eligible_observations(rtrace, audit_at):
            observations.append({
                "store": obs.store or obs.system_id,
                "replica": obs.attrs.get("replica", "") if hasattr(obs, "attrs") else "",
                "state": (state.state if state and obs.file_id == state.evidence_id else (obs.raw_state or ("PRESENT" if obs.present is not False else "ABSENT"))),
                "evidence_id": obs.file_id,
                "capture_time": _captured(index.files, obs.file_id),
            })
        verdict = "not observed at audit_at"
        assessment = assess_state(state, rules, audit_at) if state else None
        if assessment:
            verdict = "finding" if assessment.is_finding else "compliant"
        resources.append({
            "resource_id": rid,
            "system_id": state.system_id if state else (rtrace.system_id or system_for(rid)),
            "category": category,
            "policy_rule": rules.get(category, {}),
            "required_action": action,
            "link_reason": [_safe_path(path, index, linker, audit_at) for path in rtrace.link_paths],
            "known_at": rtrace.known_at,
            "observations": observations,
            "observed_state": state.state if state else "UNKNOWN",
            "evidence_id": state.evidence_id if state else "",
            "capture_time": _captured(index.files, state.evidence_id) if state else "",
            "verdict": verdict,
        })

    flows = [r["resource_id"] for r in resources if r["category"] == "DATA_FLOW" and r["observed_state"] == "ACTIVE"]
    restores = [r["resource_id"] for r in resources if r["category"] == "BACKUP_ARCHIVE" and r["observed_state"] == "ACTIVE"]
    authorized = bool(trace.user_id or raw.get("is_resolved"))
    if not authorized:
        authorized = False
    classification = "deletion intent matched" if status != "NOT_APPLICABLE" else ("intent classifier matched a non-deletion signal" if NEGATIVE_RE.search(case.get("request_text", "") or "") else "intent classifier found no deletion signal")
    resource_ids = set(trace.resources)
    classify_activity = [row.get("activity_id", "") for row in linker.activity_rows if row.get("event_type") == "CLASSIFY_REQUEST" and row.get("event_time", "") <= audit_at and (not row.get("resource_id") or row.get("resource_id") in resource_ids)]
    rejected = []
    for rid, rtrace in trace.resources.items():
        for obs in index.by_resource.get(rid, []):
            if obs in rtrace.observations or obs.captured_at > audit_at:
                continue
            if linker._conflicts_with_subject(obs, trace.cluster):
                rejected.append({"resource_id": rid, "reason": "evidence names a different subject", "evidence_id": obs.file_id, "capture_time": _captured(index.files, obs.file_id)})
    return {
        "case_id": case["case_id"],
        "identity": {"cluster": _safe_identity(raw), "link_user_id": trace.user_id, "resolved": bool(trace.user_id)},
        "timeline": {"requested_at": case.get("requested_at", ""), "reported_at": case.get("reported_at", ""), "audit_at": audit_at, "reported_status": case.get("reported_status", "")},
        "resources": resources,
        "risks": {"active_data_flows": flows, "restore_risks": restores},
        "rejected_candidates": rejected,
        "status": {"decision": status, "reason": ("request did not authorize deletion" if status == "NOT_APPLICABLE" else ("one or more policy findings remain" if status == "INCOMPLETE" else ("no admissible subject evidence; no finding invented" if not steps else "all observed resources satisfy policy"))), "intent_signal": classification, "classify_request_activity": classify_activity},
        "steps": steps,
        "steps_plain": [_plain_step(step) for step in steps],
    }


def render_plain(explanation: Dict[str, Any]) -> str:
    lines = [f"AUDIT TRAIL — {explanation['case_id']}", "IDENTITY"]
    identity = explanation["identity"]["cluster"]
    lines.append("  user_id: " + (identity.get("user_id") or "unresolved"))
    lines.append("  name: " + (identity.get("name") or "***"))
    lines.append("  email: " + (identity.get("email") or "***"))
    lines.append("  link cluster: " + json.dumps(identity, sort_keys=True))
    lines.append("TIMELINE")
    lines.extend(f"  {k}: {v}" for k, v in explanation["timeline"].items())
    lines.append("RESOURCES")
    for resource in explanation["resources"]:
        lines.append(f"  {resource['system_id']} / {resource['resource_id']} — {resource['category']}; policy={resource['required_action']}; link={'; '.join(resource['link_reason']) or 'none'}; state={resource['observed_state']}; verdict={resource['verdict']}")
        for obs in resource["observations"]:
            lines.append(f"    {obs['store']} {obs['replica']} {obs['state']} evidence={obs['evidence_id']} captured={obs['capture_time']}")
    if explanation["rejected_candidates"]:
        lines.append("  Rejected decoys: " + json.dumps(explanation["rejected_candidates"], sort_keys=True))
    lines.append("RISKS")
    lines.append("  active data flows: " + (", ".join(explanation["risks"]["active_data_flows"]) or "none"))
    lines.append("  restore risks: " + (", ".join(explanation["risks"]["restore_risks"]) or "none"))
    lines.append("STATUS")
    lines.append(f"  {explanation['status']['decision']}: {explanation['status']['reason']} ({explanation['status']['intent_signal']})")
    lines.append("STEPS")
    lines.extend("  " + text for text in explanation["steps_plain"] or ["none"])
    return "\n".join(lines)
