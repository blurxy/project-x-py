"""BOT-400: trade-side classification must not trust a crossed or locked book.

The classifier tests `price >= best ask` first. When a stale ask level sits below the best
bid (a crossed book: an ask level the feed never deleted), every print at or above that stale
ask reads "buy", including prints at the bid, so cumulative delta can only rise. These tests
drive a REAL OrderBook through the depth-batch entry point; only the client and bus are mocked.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from project_x_py.orderbook import OrderBook
from project_x_py.types import DomType


@pytest.fixture
def orderbook():
    bus = MagicMock()
    bus.emit = AsyncMock()
    bus.subscribe = AsyncMock()
    return OrderBook(instrument="MNQ", event_bus=bus, project_x=MagicMock())


def _e(kind: DomType, price: float, volume: int) -> dict:
    return {"type": kind.value, "price": price, "volume": volume}


async def _batch(ob: OrderBook, *entries: dict) -> None:
    await ob.realtime_handler._process_market_depth({"data": list(entries)})


def _sides(ob: OrderBook) -> list[str]:
    return ob.recent_trades["side"].to_list()


@pytest.mark.asyncio
async def test_print_at_the_bid_on_a_crossed_book_is_not_a_buy(orderbook):
    ob = orderbook
    # Normal book 100.00 / 100.25, one print lifting the ask.
    await _batch(ob, _e(DomType.BID, 100.00, 5), _e(DomType.ASK, 100.25, 5))
    await _batch(ob, _e(DomType.TRADE, 100.25, 1))
    # Price moves up a level; the 100.25 ask is never deleted, so the book is now
    # bid 100.50 / ask 100.25: crossed.
    await _batch(
        ob, _e(DomType.NEW_BEST_BID, 100.50, 4), _e(DomType.NEW_BEST_ASK, 100.75, 3)
    )
    best = ob._get_best_bid_ask_unlocked()
    assert best["ask"] < best["bid"], "precondition: the test book must be crossed"

    await _batch(ob, _e(DomType.TRADE, 100.75, 2))  # uptick: a buyer lifting 100.75
    await _batch(ob, _e(DomType.TRADE, 100.50, 3))  # downtick: a seller hitting 100.50

    assert _sides(ob) == ["buy", "buy", "sell"]
    assert ob.cumulative_delta == 1 + 2 - 3
    assert ob.trade_flow_stats["crossed_book_trades"] == 2


@pytest.mark.asyncio
async def test_locked_book_falls_back_to_the_tick_rule(orderbook):
    ob = orderbook
    await _batch(ob, _e(DomType.BID, 100.00, 5), _e(DomType.ASK, 100.25, 5))
    await _batch(ob, _e(DomType.TRADE, 100.00, 1))  # at the bid
    await _batch(ob, _e(DomType.TRADE, 100.25, 2))  # at the ask, an uptick
    await _batch(ob, _e(DomType.NEW_BEST_ASK, 100.00, 3))  # ask == bid: locked
    best = ob._get_best_bid_ask_unlocked()
    assert best["ask"] == best["bid"], "precondition: the test book must be locked"

    # A downtick. The quote test reads it as a buy (price >= ask); the tick rule says sell.
    await _batch(ob, _e(DomType.TRADE, 100.00, 4))

    assert _sides(ob) == ["sell", "buy", "sell"]
    assert ob.cumulative_delta == -1 + 2 - 4
    assert ob.trade_flow_stats["crossed_book_trades"] == 1


@pytest.mark.asyncio
async def test_zero_tick_repeats_the_last_tick_side_and_first_print_is_unknown(
    orderbook,
):
    ob = orderbook
    # Crossed from the start.
    await _batch(ob, _e(DomType.BID, 100.50, 5), _e(DomType.ASK, 100.25, 5))
    await _batch(ob, _e(DomType.TRADE, 100.50, 1))  # no prior print: unknown
    await _batch(ob, _e(DomType.TRADE, 100.25, 2))  # downtick
    await _batch(ob, _e(DomType.TRADE, 100.25, 3))  # zero tick: repeats the last side

    assert _sides(ob) == ["unknown", "sell", "sell"]
    assert ob.cumulative_delta == -5


@pytest.mark.asyncio
async def test_a_normal_book_classifies_by_quote_as_before(orderbook):
    ob = orderbook
    await _batch(ob, _e(DomType.BID, 100.00, 5), _e(DomType.ASK, 100.25, 5))
    await _batch(ob, _e(DomType.TRADE, 100.25, 1))  # at the ask
    await _batch(ob, _e(DomType.TRADE, 100.00, 2))  # at the bid
    # Spread widens to 100.00 / 100.50.
    await _batch(ob, _e(DomType.ASK, 100.50, 5), _e(DomType.ASK, 100.25, 0))
    await _batch(ob, _e(DomType.TRADE, 100.25, 7))  # inside the spread

    assert _sides(ob) == ["buy", "sell", "neutral"]
    assert ob.cumulative_delta == 1 - 2
    assert ob.trade_flow_stats["crossed_book_trades"] == 0
    assert ob.trade_flow_stats["aggressive_buy_volume"] == 1
    assert ob.trade_flow_stats["aggressive_sell_volume"] == 2
