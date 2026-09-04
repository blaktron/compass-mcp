"""Error types for the Compass MCP server."""

from __future__ import annotations

from typing import Any


class CompassError(Exception):
    """Base class for all errors raised by this package."""


class ConfigError(CompassError):
    """Configuration is missing or invalid."""


class NotAuthenticatedError(CompassError):
    """No usable credentials for the configured grant type."""


class LoginError(CompassError):
    """The interactive OAuth login flow failed."""


class WritesDisabledError(CompassError):
    """A write tool was called while COMPASS_ALLOW_WRITES is not enabled."""

    def __init__(self) -> None:
        super().__init__(
            "Write operations are disabled. Set COMPASS_ALLOW_WRITES=true in the "
            "server environment to enable mutating tools."
        )


class CompassApiError(CompassError):
    """A non-2xx response from the Compass API.

    Compass documents no global error schema (only the CSV import has one),
    so the raw status and body are preserved verbatim rather than parsed.
    """

    def __init__(self, status_code: int, body: str, method: str, path: str) -> None:
        self.status_code = status_code
        self.body = body
        self.method = method
        self.path = path
        super().__init__(f"Compass API error {status_code} on {method} {path}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "status": self.status_code,
                "method": self.method,
                "path": self.path,
                "body": self.body[:4000],
            }
        }
