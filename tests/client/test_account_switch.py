"""In-place account switch on the same authenticated session (account_switch)."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytz

from project_x_py.client.auth import AuthenticationMixin
from project_x_py.exceptions import ProjectXError
from project_x_py.models import Account

OLD = {
    "id": 1,
    "name": "OLD-ACCT",
    "balance": 50000.0,
    "canTrade": True,
    "isVisible": True,
    "simulated": True,
}
NEW = {
    "id": 2,
    "name": "NEW-ACCT",
    "balance": 50000.0,
    "canTrade": True,
    "isVisible": True,
    "simulated": True,
}


# A JWT with exp=9999999999: a non-JWT token leaves token_expiry untouched.
FRESH_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwiZXhwIjo5OTk5OTk5OTk5LCJuYW1lIjoiSm9obiBEb2UiLCJpYXQiOjE1MTYyMzkwMjJ9."
    "4Adcj3NFYzYLhBtYcAv7m8_GSDgYQvxDN3mPIFc47Hg"
)


class MockAuthClient(AuthenticationMixin):
    def __init__(self):
        super().__init__()
        self.username = "test_user"
        self.api_key = "test_api_key"  # pragma: allowlist secret
        self.account_name = "OLD-ACCT"
        self.headers = {}
        self._make_request = AsyncMock()
        self._auth_lock = asyncio.Lock()
        # Already logged in on OLD with a valid token.
        self.account_info = Account(**OLD)
        self._authenticated = True
        self.session_token = "tok"
        self.token_expiry = datetime.now(pytz.UTC) + timedelta(hours=1)


def _router(accounts):
    """_make_request stand-in: a login returns a token, a search returns `accounts`."""

    async def _req(method, endpoint, data=None, **_kw):
        if endpoint == "/Auth/loginKey":
            return {"token": FRESH_JWT}
        if endpoint == "/Account/search":
            return {"success": True, "accounts": list(accounts)}
        raise AssertionError(f"unexpected endpoint {endpoint}")

    return _req


@pytest.fixture
def client():
    return MockAuthClient()


@pytest.mark.asyncio
async def test_switch_to_listed_id_sets_account_info_and_name(client):
    client._make_request.side_effect = _router([OLD, NEW])

    acct = await client.switch_account(2)

    assert acct.id == 2
    assert client.account_info.id == 2
    assert client.account_name == "NEW-ACCT"


@pytest.mark.asyncio
async def test_switch_to_unknown_id_raises_and_changes_nothing(client):
    client._make_request.side_effect = _router([OLD, NEW])

    with pytest.raises(ProjectXError, match="not found"):
        await client.switch_account(99)

    assert client.account_info.id == 1
    assert client.account_name == "OLD-ACCT"


@pytest.mark.asyncio
async def test_reauth_after_switch_lands_on_new_account_when_old_is_gone(client):
    client._make_request.side_effect = _router([OLD, NEW])
    await client.switch_account(2)

    # The broker removes OLD; the token then expires and every re-auth path runs.
    client._make_request.side_effect = _router([NEW])
    for reauth in (
        client._ensure_authenticated,
        client._refresh_authentication,
        client.authenticate,
    ):
        client.token_expiry = None
        client.account_info = Account(**OLD)  # prove re-auth re-selects
        await reauth()
        assert client.account_info.id == 2, reauth.__name__
        assert client.account_name == "NEW-ACCT"


@pytest.mark.asyncio
async def test_switch_succeeds_when_old_account_gone_and_token_expired(client):
    # The incident shape: OLD already delisted and the token due for refresh. A
    # re-auth that re-selects by the OLD name inside the switch would raise here.
    client.token_expiry = datetime.now(pytz.UTC) - timedelta(minutes=1)
    client._make_request.side_effect = _router([NEW])

    acct = await client.switch_account(2)

    assert acct.id == 2
    assert client.account_info.id == 2
    assert client.account_name == "NEW-ACCT"
    assert client.session_token == FRESH_JWT


def test_vendored_fixes_advertises_account_switch():
    from project_x_py import VENDORED_FIXES

    assert "account_switch" in VENDORED_FIXES
