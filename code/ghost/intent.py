"""Request-intent classification.

Only a request that authorises deletion proceeds to the audit.  Access,
rectification, portability, marketing opt-out and questions about held data
are ``NOT_APPLICABLE`` even when the surrounding case metadata looks like a
deletion case.
"""

from __future__ import annotations

import re

NEGATIVE_PATTERNS = [
    r"\bleave\s+(?:the\s+|my\s+)?account\s+active\b",
    r"\bleave\s+(?:the\s+|my\s+)?(?:profile|purchase history|order history)\b[^.]*\bin place\b",
    r"\bkeep\s+(?:the\s+|my\s+)?account\b",
    r"\bnot\s+asking\s+for\s+deletion\b",
    r"\bnot\s+a\s+request\s+to\s+(?:erase|delete)\b",
    r"\bdo\s+not\s+close\s+the\s+account\b",
    r"\bwithout\s+removing\s+any\s+of\s+my\s+records\b",
    r"\bmarketing\s+lists\s+only\b",
    r"\bremove\s+me\s+from\s+marketing\b",
    r"\binformation\s+request\b",
    r"\bcontinue\s+using\s+the\s+service\b",
    r"\b(?:don'?t|do\s+not)\s+delete\b",
    r"\bplease\s+keep\s+(?:the\s+)?account\b",
    r"\bstill\s+(?:use|need)\s+(?:it|the\s+account)\b",
    r"\bchange\s+the\s+email\s+address\b",
    r"\breset(?:ting)?\s+the\s+login\b",
    r"\bcorrect\s+it\b",
    r"\bdownload\s+my\s+account\s+information\b",
    r"\bsend\s+me\s+a\s+copy\b",
    r"\bstop\s+the\s+promotional\s+emails\b",
    r"\breplace\s+it\s+with\s+the\s+new\s+one\b",
]

POSITIVE_PATTERNS = [
    r"\bdelet(?:e|ed|ing|ion)\b",
    r"\beras(?:e|ed|ing|ure)\b",
    r"\bthe\s+profile\s+is\s+gone\b",
    r"\bremov(?:e|ed|al)\b",
    r"\bclose\s+(?:my|this|the)\s+account\b",
    r"\bexclus[aã]o\b",
    r"\bexcluir\b",
    r"\beliminaci[oó]n\b",
    r"\beliminar\b",
    r"\bsuppression\b",
    r"\bsupprimer\b",
    r"\bl[oö]schen\b",
    r"\bcancell?azione\b",
    r"\bverwijder",
    r"삭제",
    r"削除",
    r"删除",
    r"刪除",
    r"削除",
    r"удал",
    r"삭제",
]

NEGATIVE_RE = re.compile("|".join(NEGATIVE_PATTERNS), re.IGNORECASE | re.UNICODE)
POSITIVE_RE = re.compile("|".join(POSITIVE_PATTERNS), re.IGNORECASE | re.UNICODE)


def authorizes_deletion(text: str) -> bool:
    text = text or ""
    if NEGATIVE_RE.search(text):
        return False
    return bool(POSITIVE_RE.search(text))
