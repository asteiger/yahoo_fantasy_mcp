"""Tests for the interactive `auth` command."""

import json
import stat
from unittest.mock import patch

import pytest

from yahoo_fantasy_mcp import __main__ as cli


class FakeOAuth2:
    """Stands in for yahoo_oauth.OAuth2 after a successful authorization flow."""

    def __init__(self, consumer_key, consumer_secret, **kwargs):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.kwargs = kwargs
        self.access_token = "new-access"
        self.refresh_token = "new-refresh"
        self.token_type = "bearer"
        self.token_time = 1700000000.0


@pytest.fixture(autouse=True)
def no_league_listing():
    with patch.object(cli, "list_available_leagues") as listing:
        yield listing


@pytest.fixture(autouse=True)
def clear_credential_env(monkeypatch):
    monkeypatch.delenv("YAHOO_CLIENT_ID", raising=False)
    monkeypatch.delenv("YAHOO_CLIENT_SECRET", raising=False)


def test_auth_uses_env_credentials_and_writes_private_file(tmp_path, monkeypatch, no_league_listing):
    monkeypatch.setenv("YAHOO_CLIENT_ID", "env-key")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "env-secret")
    path = tmp_path / "oauth2.json"

    with patch.object(cli, "OAuth2", FakeOAuth2):
        assert cli.run_auth(path) == 0

    assert json.loads(path.read_text()) == {
        "consumer_key": "env-key",
        "consumer_secret": "env-secret",
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "token_type": "bearer",
        "token_time": 1700000000.0,
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    no_league_listing.assert_called_once()
    assert no_league_listing.call_args.kwargs["oauth2_file"] == str(path)


def test_auth_reuses_app_credentials_from_existing_file(tmp_path):
    path = tmp_path / "oauth2.json"
    path.write_text(json.dumps({
        "consumer_key": "file-key",
        "consumer_secret": "file-secret",
        "access_token": "old-access",
    }))

    with patch.object(cli, "OAuth2", FakeOAuth2), \
            patch("builtins.input", side_effect=AssertionError("should not prompt")):
        assert cli.run_auth(path) == 0

    data = json.loads(path.read_text())
    assert data["consumer_key"] == "file-key"
    assert data["access_token"] == "new-access"


def test_auth_prompts_for_app_credentials(tmp_path):
    path = tmp_path / "nested" / "oauth2.json"

    with patch.object(cli, "OAuth2", FakeOAuth2), \
            patch("builtins.input", return_value=" typed-key "), \
            patch.object(cli, "getpass", return_value="typed-secret"):
        assert cli.run_auth(path) == 0

    data = json.loads(path.read_text())
    assert (data["consumer_key"], data["consumer_secret"]) == ("typed-key", "typed-secret")


def test_auth_rejects_blank_credentials(tmp_path):
    path = tmp_path / "oauth2.json"

    with patch.object(cli, "OAuth2", FakeOAuth2), \
            patch("builtins.input", return_value=""), \
            patch.object(cli, "getpass", return_value=""):
        assert cli.run_auth(path) == 1

    assert not path.exists()


def test_rejected_authorization_explains_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("YAHOO_CLIENT_ID", "env-key")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "env-secret")
    path = tmp_path / "oauth2.json"

    with patch.object(cli, "OAuth2", side_effect=KeyError("access_token")):
        assert cli.run_auth(path) == 1

    assert "Yahoo rejected the authorization" in capsys.readouterr().err
    assert not path.exists()


def test_failed_authorization_keeps_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("YAHOO_CLIENT_ID", "env-key")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "env-secret")
    path = tmp_path / "oauth2.json"
    original = json.dumps({"consumer_key": "k", "consumer_secret": "s", "access_token": "keep"})
    path.write_text(original)

    with patch.object(cli, "OAuth2", side_effect=RuntimeError("invalid code")):
        assert cli.run_auth(path) == 1

    assert path.read_text() == original
