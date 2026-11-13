"""Integration error types — fail-closed semantics."""

from __future__ import annotations


class IntegrationError(Exception):
    """Base integration failure."""

    code = "integration_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class IntegrationUnauthorized(IntegrationError):
    """Missing or invalid session — no V2 call / no fabricated access."""

    code = "unauthorized"


class IntegrationForbidden(IntegrationError):
    """Caller lacks fixture-simulated permission or branch scope."""

    code = "forbidden"


class IntegrationNotFound(IntegrationError):
    """Requested entity not found in authorized fixture set."""

    code = "not_found"


class IntegrationUpstreamForbidden(IntegrationError):
    """Simulated upstream 403-style denial from ERP V2 visibility rules."""

    code = "upstream_forbidden"
