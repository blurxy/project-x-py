"""place_order's account-id check follows an in-place account switch (account_switch)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytz

from project_x_py.exceptions import ProjectXOrderError

_ACCTS = {
    "success": True,
    "accounts": [
        {
            "id": 12345,
            "name": "Test Account",
            "balance": 1.0,
            "canTrade": True,
            "isVisible": True,
            "simulated": True,
        },
        {
            "id": 67890,
            "name": "Replacement",
            "balance": 1.0,
            "canTrade": True,
            "isVisible": True,
            "simulated": True,
        },
    ],
}


@pytest.mark.asyncio
async def test_place_order_after_switch_accepts_new_id_rejects_old(
    order_manager, make_order_response
):
    client = order_manager.project_x
    client._authenticated = True
    client.token_expiry = datetime.now(pytz.UTC) + timedelta(hours=1)
    client._make_request = AsyncMock(return_value=_ACCTS)
    await client.switch_account(67890)

    client._make_request = AsyncMock(return_value=make_order_response(7))
    resp = await order_manager.place_order("MGC", 2, 0, 1, account_id=67890)
    assert resp.orderId == 7
    assert client._make_request.call_args[1]["data"]["accountId"] == 67890

    with pytest.raises(ProjectXOrderError, match="Invalid account ID 12345"):
        await order_manager.place_order("MGC", 2, 0, 1, account_id=12345)
