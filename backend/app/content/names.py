"""Character name policy: NFKC, 3-16 chars, letters with single inner separators, reserved names blocked."""

import unicodedata

from app.content.loader import load_yaml
from app.core.errors import ValidationFailedError

MIN_LEN, MAX_LEN = 3, 16
SEPARATORS = {" ", "'", "-"}


def normalize_name(name: str) -> str:
    """Display form: NFKC + collapsed spaces."""
    return " ".join(unicodedata.normalize("NFKC", name).split())


def name_key(name: str) -> str:
    """Case-insensitive uniqueness key (casefold)."""
    return normalize_name(name).casefold()


def validate_name(raw: str) -> str:
    name = normalize_name(raw)
    if not MIN_LEN <= len(name) <= MAX_LEN:
        raise ValidationFailedError(f"Name must be {MIN_LEN}-{MAX_LEN} characters", code="invalid_name_length")
    if name[0] in SEPARATORS or name[-1] in SEPARATORS:
        raise ValidationFailedError("Name cannot start or end with a separator", code="invalid_name_chars")
    prev_sep = False
    for ch in name:
        if ch in SEPARATORS:
            if prev_sep:
                raise ValidationFailedError("Consecutive separators are not allowed", code="invalid_name_chars")
            prev_sep = True
            continue
        prev_sep = False
        if not unicodedata.category(ch).startswith("L"):
            raise ValidationFailedError("Name may only contain letters", code="invalid_name_chars")
    if sum(ch in SEPARATORS for ch in name) > 2:
        raise ValidationFailedError("Too many separators", code="invalid_name_chars")
    key = name_key(name)
    compact = "".join(ch for ch in key if ch not in SEPARATORS)
    reserved = load_yaml("system/reserved_names.yaml")
    if key in reserved["exact"] or compact in reserved["exact"] or any(s in compact for s in reserved["contains"]):
        raise ValidationFailedError("This name is reserved", code="reserved_name")
    return name
