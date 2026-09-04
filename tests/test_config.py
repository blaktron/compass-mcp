from pathlib import Path

import pytest

from compass_mcp.config import Config
from compass_mcp.errors import ConfigError


def test_from_env_defaults(tmp_path):
    cfg = Config.from_env({"COMPASS_TOKEN_DIR": str(tmp_path)})
    assert cfg.env == "sandbox-app"
    assert cfg.grant_type == "client_credentials"
    assert cfg.allow_writes is False
    assert cfg.base_url == "https://sandbox-app.bespokemetrics.io"
    assert cfg.web_url == "https://sandbox.compass-app.com"
    assert cfg.token_path == Path(tmp_path) / "sandbox-app.json"


def test_from_env_production_web_url(tmp_path):
    cfg = Config.from_env({"COMPASS_ENV": "compass2", "COMPASS_TOKEN_DIR": str(tmp_path)})
    assert cfg.base_url == "https://compass2.bespokemetrics.io"
    assert cfg.web_url == "https://compass-app.com"


def test_allow_writes_parsing(tmp_path):
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        assert Config.from_env(
            {"COMPASS_ALLOW_WRITES": truthy, "COMPASS_TOKEN_DIR": str(tmp_path)}
        ).allow_writes
    for falsy in ("0", "false", "no", "", "off"):
        assert not Config.from_env(
            {"COMPASS_ALLOW_WRITES": falsy, "COMPASS_TOKEN_DIR": str(tmp_path)}
        ).allow_writes


def test_overrides(tmp_path):
    cfg = Config.from_env(
        {
            "COMPASS_BASE_URL": "http://localhost:9999/",
            "COMPASS_WEB_URL": "https://example.test/",
            "COMPASS_TOKEN_DIR": str(tmp_path),
        }
    )
    assert cfg.base_url == "http://localhost:9999"
    assert cfg.web_url == "https://example.test"


def test_bad_grant_type_rejected(tmp_path):
    with pytest.raises(ConfigError):
        Config.from_env({"COMPASS_GRANT_TYPE": "password", "COMPASS_TOKEN_DIR": str(tmp_path)})


def test_bad_redirect_uri_rejected(tmp_path):
    with pytest.raises(ConfigError):
        Config.from_env({"COMPASS_REDIRECT_URI": "not a url", "COMPASS_TOKEN_DIR": str(tmp_path)})


def test_require_client_credentials():
    cfg = Config(client_id=None, client_secret=None)
    with pytest.raises(ConfigError):
        cfg.require_client_credentials()
    Config(client_id="a", client_secret="b").require_client_credentials()
