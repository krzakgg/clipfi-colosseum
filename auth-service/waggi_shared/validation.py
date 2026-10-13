"""Reusable field validation shared across services.

Phone numbers are stored in international (E.164) format — "+" followed by
6-15 digits, e.g. +48600100200. Input may contain formatting separators
(spaces, dashes, dots, parentheses, slashes) which are stripped before
validation, so "+48 600 100 200" is accepted and stored as "+48600100200".
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

#: International (E.164): "+" then 6-15 digits; the first digit is 1-9.
PHONE_E164_PATTERN = re.compile(r"^\+[1-9]\d{5,14}$")

#: Separators users commonly type; stripped before validation.
_PHONE_SEPARATORS = re.compile(r"[\s\-()./]")

PHONE_INVALID_MESSAGE = "phone must be in international format, e.g. +48600100200"


def normalize_phone(value: str) -> str:
    """Strip formatting separators: "+48 600 100-200" -> "+48600100200"."""
    return _PHONE_SEPARATORS.sub("", value.strip())


def validate_phone(value: str | None) -> str | None:
    """Normalize + validate a phone number as international (E.164).

    Empty input maps to None. Raises ValueError (a 422 in Pydantic-powered
    APIs) when the number is not a valid international format.
    """
    if value is None:
        return None
    normalized = normalize_phone(value)
    if not normalized:
        return None
    if PHONE_E164_PATTERN.fullmatch(normalized) is None:
        raise ValueError(PHONE_INVALID_MESSAGE)
    return normalized


#: Drop-in Pydantic field type: canonicalizes input to E.164 on the way in.
#: Use as `phone: PhoneNumber | None = None`.
PhoneNumber = Annotated[str, AfterValidator(validate_phone)]
