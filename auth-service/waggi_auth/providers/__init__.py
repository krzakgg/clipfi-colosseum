"""OAuth provider registry for SSO login.

Public surface used by the router:
- `get_provider_client(provider)` -> ProviderClient (404 unknown, 501 unconfigured)
- `provider_status()` -> [(name, enabled), ...] for the discovery endpoint

To add a provider:
1. create `<name>.py` next to this file: a `ProviderClient` subclass with the
   provider's endpoints/scope/quirks + a module-level `SPEC = ProviderSpec(...)`;
2. add its SPEC to `_REGISTRY` below (dict order = discovery listing order);
3. add the provider's settings fields to `waggi_auth/config.py`.

No other changes are needed — discovery, authorize and callback routes are
fully provider-agnostic.
"""

from __future__ import annotations

from waggi_auth.config import settings
from waggi_auth.providers import apple, google
from waggi_auth.providers.base import ProviderClient, ProviderSpec, VerifiedIdentity
from waggi_shared.errors import APIError

_REGISTRY: dict[str, ProviderSpec] = {spec.name: spec for spec in (google.SPEC, apple.SPEC)}


def get_provider_client(provider: str) -> ProviderClient:
    """Build the configured client for `provider` (fresh per call; stateless)."""
    spec = _REGISTRY.get(provider)
    if spec is None:
        raise APIError("Unknown SSO provider", code="sso_provider_unknown", status_code=404, title="Not Found")
    if not spec.is_configured(settings):
        raise APIError(
            f"{provider.capitalize()} login is not configured",
            code="sso_provider_not_configured",
            status_code=501,
            title="Not Implemented",
        )
    return spec.build(settings)


def provider_status() -> list[tuple[str, bool]]:
    """Every registered provider + whether its credentials are configured."""
    return [(spec.name, spec.is_configured(settings)) for spec in _REGISTRY.values()]


__all__ = [
    "ProviderClient",
    "VerifiedIdentity",
    "get_provider_client",
    "provider_status",
]
