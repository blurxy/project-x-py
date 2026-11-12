"""TradingSuite.switch_account: client, realtime, then per-instrument state (account_switch)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from project_x_py import TradingSuite, TradingSuiteConfig
from project_x_py.event_bus import EventBus
from project_x_py.exceptions import ProjectXError
from project_x_py.models import Account
from project_x_py.order_manager.core import OrderManager
from project_x_py.position_manager.core import PositionManager
from project_x_py.trading_suite import InstrumentContext

NEW = Account(
    id=2, name="NEW-ACCT", balance=1.0, canTrade=True, isVisible=True, simulated=True
)


def _context(symbol):
    bus = EventBus()
    om = OrderManager(MagicMock(), bus)
    pm = PositionManager(MagicMock(), bus)
    om.tracked_orders["11"] = {"id": 11}
    om.order_status_cache["11"] = 1
    om.order_to_position[11] = "CON"
    om.position_orders["CON"] = {"stop_orders": [11]}
    om.oco_groups[11] = 12
    om.oco_pairs["11"] = "12"
    pm.tracked_positions["CON"] = MagicMock()
    pm.position_history["CON"].append({"size": 1})
    return InstrumentContext(
        symbol=symbol,
        instrument_info=MagicMock(),
        data=MagicMock(),
        orders=om,
        positions=pm,
        event_bus=bus,
    )


def _suite():
    client = MagicMock()
    client.switch_account = AsyncMock(return_value=NEW)
    realtime = MagicMock()
    realtime.switch_account = AsyncMock()
    contexts = {"MNQ": _context("MNQ"), "ES": _context("ES")}
    config = TradingSuiteConfig(instrument="MNQ", timezone="America/Chicago")
    return TradingSuite(client, realtime, config, contexts), contexts


@pytest.mark.asyncio
async def test_suite_switch_clears_every_instruments_order_and_position_state():
    suite, contexts = _suite()

    acct = await suite.switch_account(2)

    assert acct is NEW
    suite.client.switch_account.assert_awaited_once_with(2)
    suite.realtime.switch_account.assert_awaited_once_with(2)
    for ctx in contexts.values():
        om, pm = ctx.orders, ctx.positions
        assert len(om.tracked_orders) == 0
        assert len(om.order_status_cache) == 0
        assert om.order_to_position == {}
        assert len(om.position_orders) == 0
        assert om.oco_groups == {}
        assert om.oco_pairs == {}
        assert pm.tracked_positions == {}
        assert len(pm.position_history) == 0


@pytest.mark.asyncio
async def test_suite_switch_raises_when_realtime_step_fails():
    suite, contexts = _suite()
    suite.realtime.switch_account = AsyncMock(side_effect=ProjectXError("hub refused"))

    with pytest.raises(ProjectXError, match="hub refused"):
        await suite.switch_account(2)
