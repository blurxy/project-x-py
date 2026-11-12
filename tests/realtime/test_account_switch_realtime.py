"""Realtime user-hub re-subscription on an in-place account switch (account_switch)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from project_x_py.exceptions import ProjectXError
from project_x_py.realtime.connection_management import ConnectionManagementMixin
from project_x_py.realtime.subscriptions import SubscriptionsMixin


class Client(SubscriptionsMixin, ConnectionManagementMixin):
    def __init__(self):
        super().__init__()
        self.account_id = "123456"
        self.jwt_token = "tok"
        self.setup_complete = True
        self.user_connected = True
        self.market_connected = True
        self.user_hub_ready = asyncio.Event()
        self.market_hub_ready = asyncio.Event()
        self.user_hub_ready.set()
        self.market_hub_ready.set()
        self.user_connection = MagicMock()
        self.market_connection = MagicMock()
        self._subscribed_contracts = []
        self._connection_lock = asyncio.Lock()
        self.logger = MagicMock()


def _user_sends(client):
    return list(client.user_connection.send.call_args_list)


@pytest.mark.asyncio
async def test_switch_unsubscribes_old_subscribes_new_and_reconnect_uses_new():
    client = Client()

    await client.switch_account(67890)

    sends = _user_sends(client)
    assert call("UnsubscribeOrders", [123456]) in sends
    assert call("SubscribeOrders", [67890]) in sends
    assert sends.index(call("UnsubscribeOrders", [123456])) < sends.index(
        call("SubscribeOrders", [67890])
    )
    assert client.account_id == "67890"

    # Simulated reconnect (token refresh path re-subscribes the user hub).
    client.user_connection.send.reset_mock()
    with (
        patch.object(client, "disconnect", new_callable=AsyncMock),
        patch.object(client, "connect", new_callable=AsyncMock, return_value=True),
    ):
        assert await client.update_jwt_token("tok2") is True
    sends = _user_sends(client)
    assert call("SubscribeOrders", [67890]) in sends
    assert call("SubscribeOrders", [123456]) not in sends


@pytest.mark.asyncio
async def test_switch_when_not_connected_only_sets_id():
    client = Client()
    client.user_connected = False

    await client.switch_account(67890)

    assert client.account_id == "67890"
    client.user_connection.send.assert_not_called()


@pytest.mark.asyncio
async def test_switch_continues_when_server_rejects_unsubscribe_of_deleted_account():
    client = Client()

    def _send(method, args):
        if method.startswith("Unsubscribe"):
            raise RuntimeError("account not found")

    client.user_connection.send.side_effect = _send

    await client.switch_account(67890)

    assert client.account_id == "67890"
    assert call("SubscribeOrders", [67890]) in _user_sends(client)


@pytest.mark.asyncio
async def test_switch_raises_when_new_subscribe_fails_while_connected():
    client = Client()

    def _send(method, args):
        if method.startswith("Subscribe"):
            raise RuntimeError("hub refused")

    client.user_connection.send.side_effect = _send

    with pytest.raises(ProjectXError):
        await client.switch_account(67890)


@pytest.mark.asyncio
async def test_real_realtime_client_exposes_switch_account():
    from project_x_py.realtime import ProjectXRealtimeClient

    client = ProjectXRealtimeClient(jwt_token="tok", account_id="1")
    assert client.user_connected is False

    await client.switch_account(2)

    assert client.account_id == "2"
