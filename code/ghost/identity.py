"""Identity resolution scaffolding for Ghost Data Still Exists challenge."""

import hashlib
from typing import Any, Dict, List, Optional, Set


def compute_email_hash(email: str) -> str:
    """Compute sha256(lowercase(email.strip()))."""
    clean_email = email.strip().lower()
    return hashlib.sha256(clean_email.encode("utf-8")).hexdigest()


def resolve_identity(
    email: str,
    user_identities: List[Dict[str, str]],
    user_audit_log: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Resolve a case email (current or historical) to all associated identifiers.
    
    Returns:
        Dict with canonical user_id, current & historical emails, phones, names,
        and computed email hashes.
    """
    clean_email = email.strip().lower()
    primary_hash = compute_email_hash(clean_email)

    # 1. Build lookup tables
    user_by_email = {r["email"].strip().lower(): r for r in user_identities if "email" in r}
    user_by_id = {r["user_id"].strip(): r for r in user_identities if "user_id" in r}

    # Index audit log by user_id and reverse lookup for historical emails
    audit_by_user: Dict[str, List[Dict[str, str]]] = {}
    audit_email_to_user: Dict[str, str] = {}

    for entry in user_audit_log:
        uid = entry.get("user_id", "").strip()
        if not uid:
            continue
        audit_by_user.setdefault(uid, []).append(entry)

        field = entry.get("field_name", "").strip().lower()
        if field == "email":
            old_val = entry.get("old_value", "").strip().lower()
            new_val = entry.get("new_value", "").strip().lower()
            if old_val:
                audit_email_to_user[old_val] = uid
            if new_val:
                audit_email_to_user[new_val] = uid

    # 2. Locate canonical user_id
    canonical_uid: Optional[str] = None
    if clean_email in user_by_email:
        canonical_uid = user_by_email[clean_email].get("user_id", "").strip()
    elif clean_email in audit_email_to_user:
        canonical_uid = audit_email_to_user[clean_email]

    if not canonical_uid:
        # Subject not in user database
        return {
            "user_id": "",
            "name": "",
            "email": clean_email,
            "phone": "",
            "email_hash": primary_hash,
            "all_emails": [clean_email],
            "historical_emails": [],
            "all_phones": [],
            "historical_phones": [],
            "all_names": [],
            "all_email_hashes": [primary_hash],
            "is_resolved": False,
        }

    # 3. Gather current attributes
    current_user = user_by_id.get(canonical_uid, {})
    curr_name = current_user.get("name", "").strip()
    curr_email = current_user.get("email", "").strip()
    curr_phone = current_user.get("phone", "").strip()
    curr_hash = current_user.get("email_hash", "").strip() or primary_hash

    all_emails: Set[str] = set()
    historical_emails: Set[str] = set()
    all_phones: Set[str] = set()
    historical_phones: Set[str] = set()
    all_names: Set[str] = set()

    if curr_email:
        all_emails.add(curr_email.lower())
    if clean_email:
        all_emails.add(clean_email)
    if curr_phone:
        all_phones.add(curr_phone)
    if curr_name:
        all_names.add(curr_name)

    # 4. Ingest audit log history
    for entry in audit_by_user.get(canonical_uid, []):
        field = entry.get("field_name", "").strip().lower()
        old_val = entry.get("old_value", "").strip()
        new_val = entry.get("new_value", "").strip()

        if field == "email":
            if old_val:
                all_emails.add(old_val.lower())
                historical_emails.add(old_val.lower())
            if new_val:
                all_emails.add(new_val.lower())
        elif field == "phone":
            if old_val:
                all_phones.add(old_val)
                historical_phones.add(old_val)
            if new_val:
                all_phones.add(new_val)
        elif field == "name":
            if old_val:
                all_names.add(old_val)
            if new_val:
                all_names.add(new_val)

    # Historical emails exclude the current email
    if curr_email.lower() in historical_emails:
        historical_emails.remove(curr_email.lower())

    # Compute hashes for all emails
    all_hashes = {compute_email_hash(em) for em in all_emails}
    if curr_hash:
        all_hashes.add(curr_hash)

    return {
        "user_id": canonical_uid,
        "name": curr_name,
        "email": curr_email or clean_email,
        "phone": curr_phone,
        "email_hash": curr_hash,
        "all_emails": sorted(list(all_emails)),
        "historical_emails": sorted(list(historical_emails)),
        "all_phones": sorted(list(all_phones)),
        "historical_phones": sorted(list(historical_phones)),
        "all_names": sorted(list(all_names)),
        "all_email_hashes": sorted(list(all_hashes)),
        "is_resolved": True,
    }
