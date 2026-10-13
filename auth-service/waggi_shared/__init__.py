"""waggi shared library.

Cross-cutting concerns used by the auth service (and future consumers).
"""

from waggi_shared import database, email, errors, security, validation

__all__ = [
    "database",
    "email",
    "errors",
    "security",
    "validation",
]

__version__ = "0.1.0"
