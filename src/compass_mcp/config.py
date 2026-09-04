"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigError

KNOWN_ENVIRONMENTS = ("sandbox-app", "compass2")
GRANT_CLIENT_CREDENTIALS = "client_credentials"
GRANT_AUTHORIZATION_CODE = "authorization_code"

_TRUE = {"1", "true", "yes", "on"}


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUE


@dataclass
class Config:
    env: str = "sandbox-app"
    client_id: str | None = None
    client_secret: str | None = None
    grant_type: str = GRANT_CLIENT_CREDENTIALS
    allow_writes: bool = False
    redirect_uri: str = "http://localhost:8765/oauth2/callback"
    base_url_override: str | None = None
    web_url_override: str | None = None
    token_dir: Path = field(default_factory=lambda: Path.home() / ".compass-mcp")
    timeout: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Config":
        e = os.environ if environ is None else environ
        cfg = cls(
            env=e.get("COMPASS_ENV", "sandbox-app").strip(),
            client_id=e.get("COMPASS_CLIENT_ID") or None,
            client_secret=e.get("COMPASS_CLIENT_SECRET") or None,
            grant_type=e.get("COMPASS_GRANT_TYPE", GRANT_CLIENT_CREDENTIALS).strip(),
            allow_writes=_as_bool(e.get("COMPASS_ALLOW_WRITES"), default=False),
            redirect_uri=e.get("COMPASS_REDIRECT_URI", "http://localhost:8765/oauth2/callback").strip(),
            base_url_override=e.get("COMPASS_BASE_URL") or None,
            web_url_override=e.get("COMPASS_WEB_URL") or None,
            token_dir=Path(e.get("COMPASS_TOKEN_DIR", str(Path.home() / ".compass-mcp"))),
            timeout=float(e.get("COMPASS_TIMEOUT", "30")),
            max_retries=int(e.get("COMPASS_MAX_RETRIES", "3")),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.grant_type not in (GRANT_CLIENT_CREDENTIALS, GRANT_AUTHORIZATION_CODE):
            raise ConfigError(
                f"COMPASS_GRANT_TYPE must be '{GRANT_CLIENT_CREDENTIALS}' or "
                f"'{GRANT_AUTHORIZATION_CODE}', got {self.grant_type!r}"
            )
        parsed = urlparse(self.redirect_uri)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ConfigError(f"COMPASS_REDIRECT_URI is not a valid URL: {self.redirect_uri!r}")

    def require_client_credentials(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ConfigError(
                "COMPASS_CLIENT_ID and COMPASS_CLIENT_SECRET must be set "
                "(obtained by registering with Compass — product@bespokemetrics.com)."
            )

    @property
    def base_url(self) -> str:
        if self.base_url_override:
            return self.base_url_override.rstrip("/")
        return f"https://{self.env}.bespokemetrics.io"

    @property
    def web_url(self) -> str:
        """The web host used to build the OAuth consent URL.

        Override with COMPASS_WEB_URL.
        """
        if self.web_url_override:
            return self.web_url_override.rstrip("/")
        if self.env == "compass2":
            return "https://compass-app.com"
        return "https://sandbox.compass-app.com"

    @property
    def token_path(self) -> Path:
        return self.token_dir / f"{self.env}.json"

    @property
    def is_known_env(self) -> bool:
        return self.env in KNOWN_ENVIRONMENTS
