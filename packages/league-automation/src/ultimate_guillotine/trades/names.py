"""Name normalization shared between trade resolution and member alias storage.

Lives in its own module (rather than in ``trades.resolve``) so
``data.repositories.MemberAliasRepository`` can import it without depending on
the rest of the resolution module.
"""

import re
import unicodedata

_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalize a name for matching: NFKC, lower-case, strip punctuation, collapse whitespace."""
    normalized = unicodedata.normalize("NFKC", name)
    normalized = normalized.lower()
    normalized = _PUNCTUATION_RE.sub("", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized
