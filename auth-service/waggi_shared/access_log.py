"""Access-log hygiene: keep liveness/readiness probes out of uvicorn's log.

Docker healthchecks (docker-compose.yml) probe ``/health`` every 15s per
service, and deploy.sh curls ``/ready`` — without a filter each probe appends
a ``uvicorn.access`` line to the container logs. All three services install
:func:`install_health_probe_filter` in ``create_app()``.
"""

from __future__ import annotations

import logging

_PROBE_PATHS = frozenset({"/health", "/ready"})
_ACCESS_LOGGER = "uvicorn.access"


class HealthProbeFilter(logging.Filter):
    """Drop uvicorn access-log records whose request path is a health probe.

    uvicorn logs each access line as a single %-format record whose ``args``
    are ``(client_addr, method, full_path, http_version, status_code)`` —
    ``full_path`` includes the query string. Records that don't match that
    shape are passed through untouched (never eat an unexpected record).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        full_path = args[2]
        if not isinstance(full_path, str):
            return True
        return full_path.split("?", 1)[0] not in _PROBE_PATHS


def install_health_probe_filter() -> None:
    """Attach :class:`HealthProbeFilter` to uvicorn's access logger.

    Idempotent: safe for repeated ``create_app()`` calls (tests). The filter
    lives on the logger object itself, and uvicorn's dictConfig only resets
    *handlers* — never filters — so installing at app-import time survives
    uvicorn's logging setup.
    """
    logger = logging.getLogger(_ACCESS_LOGGER)
    if any(isinstance(existing, HealthProbeFilter) for existing in logger.filters):
        return
    logger.addFilter(HealthProbeFilter())
