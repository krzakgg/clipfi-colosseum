"""Password policy shared across services (character classes + personal-data check).

Beyond the length bounds already enforced by request schemas (min 8, max 64),
every path that SETS a password validates the chosen value against this
policy:

1. **Length** — at least min_length (default 8; env-configurable per
   service) and at most PASSWORD_MAX_LENGTH (fixed 64 — the NIST 800-63B
   "allow at least 64" floor so passphrases fit; NOT configurable,
   hard-enforced by the request schemas and re-checked here).
2. **Character classes** — minimum counts for uppercase, lowercase, digits
   and symbols (defaults 0 = not required; env-configurable per service).
   Counting is Unicode-aware: `isupper`/`islower` letters, `isdigit`, and
   anything not alphanumeric (incl. spaces) counts as a symbol.
3. **Personal data** — the password must not contain the user's email local
   part or any name token (case-insensitive, diacritics-stripped, tokens of
   3+ characters). Names are the obvious guess ("Kowalska2026!").

The function is pure and returns a stable violation code (see the error
taxonomy in the repo docs); callers map it to their error type (auth raises
`ValidationError` 422 with the code, admin raises a Pydantic `ValueError`).

Consumers: auth (setup-password, change-password, password-reset/confirm,
and GET /password-policy which publishes the configured minimums to the
frontend), admin (WorkerCreate.temp_password — an admin-supplied temp
password is a real credential until first login, so it must meet the same
bar). Both services pass their env-configured minimums in.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Length bounds, mirrored by the request-schema Field constraints in every
#: service (schema and policy share the same numbers). The max is NOT
#: configurable — 64 is the NIST 800-63B floor ("allow at least 64"),
#: hard-enforced so client and server validation can never disagree about
#: it. The min is the library baseline; services configure their own via env.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64

#: Library-baseline character-class minimums — 0 means "no requirement" when
#: a caller doesn't specify one. The PRODUCT defaults live in the services'
#: Settings (auth + admin: uppercase/lowercase/digit 1, symbol 0); set a
#: minimum to 0 there via env to disable that rule.
PASSWORD_MIN_UPPERCASE = 0
PASSWORD_MIN_LOWERCASE = 0
PASSWORD_MIN_DIGIT = 0
PASSWORD_MIN_SYMBOL = 0

#: Personal tokens shorter than this are ignored ("jo" matches too much).
_PERSONAL_TOKEN_MIN_LENGTH = 3

#: Runs of non-alphanumerics split emails/names into tokens.
_TOKEN_SEPARATOR = re.compile(r"[^a-z0-9]+")

#: Polish ł is the one letter of the alphabet that does NOT decompose under
#: NFD (it is not "l" + stroke) — translate it explicitly so "Łukasz" and
#: "Lukasz" fold to the same token. Every other diacritic (ą ć ę ń ó ś ź ż)
#: decomposes via NFD below.
_LOT_TRANSLATION = str.maketrans("ł", "l")


def _fold(value: str) -> str:
    """Lowercase and strip diacritics: "Łukasz" -> "lukasz", "Müller" -> "muller"."""
    lowered = value.lower().translate(_LOT_TRANSLATION)
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def personal_tokens(email: str | None, full_name: str | None) -> list[str]:
    """Deduplicated personal tokens (email local part + name words), folded.

    "jan.kowalski@example.com" + "Jan Kowalski Jr" -> ["jan", "kowalski"].
    Tokens shorter than 3 characters are dropped.
    """
    tokens: set[str] = set()
    for source in (email.split("@", 1)[0] if email else None, full_name):
        if not source:
            continue
        for part in _TOKEN_SEPARATOR.split(_fold(source)):
            if len(part) >= _PERSONAL_TOKEN_MIN_LENGTH:
                tokens.add(part)
    return sorted(tokens)


def _count_character_classes(password: str) -> tuple[int, int, int, int]:
    """(uppercase, lowercase, digit, symbol) counts — one class per char.

    Unicode-aware: "Ź" is uppercase, "ą" lowercase; digits via isdigit;
    everything else (punctuation, spaces, uncased scripts) is a symbol.
    """
    upper = lower = digit = symbol = 0
    for ch in password:
        if ch.isupper():
            upper += 1
        elif ch.islower():
            lower += 1
        elif ch.isdigit():
            digit += 1
        else:
            symbol += 1
    return upper, lower, digit, symbol


def password_policy_violation(
    password: str,
    *,
    email: str | None = None,
    full_name: str | None = None,
    min_length: int = PASSWORD_MIN_LENGTH,
    min_uppercase: int = PASSWORD_MIN_UPPERCASE,
    min_lowercase: int = PASSWORD_MIN_LOWERCASE,
    min_digit: int = PASSWORD_MIN_DIGIT,
    min_symbol: int = PASSWORD_MIN_SYMBOL,
) -> str | None:
    """Validate a candidate password; return a violation code or None if OK.

    The minimums are parameterized so services can drive them from their
    env config (auth also publishes them via GET /password-policy). The
    maximum is fixed: PASSWORD_MAX_LENGTH, mirrored by the request schemas.

    Codes (stable, part of the API error taxonomy):
    - ``password_too_short`` — under min_length (defensive; request schemas
      normally reject this first);
    - ``password_too_long`` — over PASSWORD_MAX_LENGTH (defensive; request
      schemas reject this first too);
    - ``password_character_requirements`` — a configured character-class
      minimum (uppercase/lowercase/digit/symbol) is not met;
    - ``password_contains_personal`` — contains an email/name token.
    """
    if len(password) < min_length:
        return "password_too_short"

    if len(password) > PASSWORD_MAX_LENGTH:
        return "password_too_long"

    upper, lower, digit, symbol = _count_character_classes(password)
    if upper < min_uppercase or lower < min_lowercase or digit < min_digit or symbol < min_symbol:
        return "password_character_requirements"

    tokens = personal_tokens(email, full_name)
    folded_password = _fold(password)
    for token in tokens:
        if token in folded_password:
            return "password_contains_personal"

    return None


@dataclass(frozen=True)
class PasswordPolicyConfig:
    """A complete, validated password policy (what services configure).

    Constructing raises ValueError on impossible combinations (min beyond
    the fixed max, negative class minimums, or class minimums summing
    above min_length) so a bad env var fails loudly in BOTH services
    instead of silently weakening the policy.
    """

    min_length: int = PASSWORD_MIN_LENGTH
    min_uppercase: int = PASSWORD_MIN_UPPERCASE
    min_lowercase: int = PASSWORD_MIN_LOWERCASE
    min_digit: int = PASSWORD_MIN_DIGIT
    min_symbol: int = PASSWORD_MIN_SYMBOL

    def __post_init__(self) -> None:
        if not PASSWORD_MIN_LENGTH <= self.min_length <= PASSWORD_MAX_LENGTH:
            raise ValueError(
                f"need {PASSWORD_MIN_LENGTH} <= min_length <= {PASSWORD_MAX_LENGTH} (got min_length={self.min_length})"
            )
        minimums = (self.min_uppercase, self.min_lowercase, self.min_digit, self.min_symbol)
        if any(m < 0 for m in minimums):
            raise ValueError(f"character-class minimums must be >= 0 (got {minimums})")
        if sum(minimums) > self.min_length:
            raise ValueError(
                f"character-class minimums sum to {sum(minimums)}, above min_length={self.min_length} "
                "— no password could satisfy the policy"
            )

    def check(self, password: str, *, email: str | None = None, full_name: str | None = None) -> str | None:
        """password_policy_violation with this config's bounds filled in."""
        return password_policy_violation(
            password,
            email=email,
            full_name=full_name,
            min_length=self.min_length,
            min_uppercase=self.min_uppercase,
            min_lowercase=self.min_lowercase,
            min_digit=self.min_digit,
            min_symbol=self.min_symbol,
        )


__all__ = [
    "PASSWORD_MAX_LENGTH",
    "PASSWORD_MIN_DIGIT",
    "PASSWORD_MIN_LENGTH",
    "PASSWORD_MIN_LOWERCASE",
    "PASSWORD_MIN_SYMBOL",
    "PASSWORD_MIN_UPPERCASE",
    "PasswordPolicyConfig",
    "password_policy_violation",
    "personal_tokens",
]
