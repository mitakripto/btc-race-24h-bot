"""Selective EMA trend bot for make.fun's "Race a BTC trading bot live for 24 hours".

Protocol: agent-fun/bars-replay/v1. The harness sends one hello line, then one
batch per minute (each carrying the bar that just closed, the fills of the
orders sent on the previous batch, and the account), then done. The bot answers
every batch with exactly one reply echoing its seq, carrying its orders for the
next minute's open. Orders decided on a bar fill at the next bar's open, minus
a 4 bps fee, 2 bps of slippage and constant-product price impact, so a trade
has to catch a move well above ~30 bps to pay. The strategy therefore trades
rarely and only with the trend:

  - Indicators, over CBBTC closes: EMA(24) and EMA(72), each seeded as the mean
    of its first span of closes, then moving 2 / (span + 1) of the way to each
    new close. The slow EMA's slope over the last 60 bars is the regime filter.
  - Entry, on a bar's close: EMA(24) crosses above EMA(72) by more than 10 bps
    (the gap was at or under 10 bps on the previous bar) while the slow EMA is
    rising at least 5 bps over its last 60 bars. The whole cash balance goes in:
    one position, long only, no leverage.
  - Partial take-profit: once, when the position is worth 1.5% over its cost,
    60% of it is sold. The rest rides.
  - Exit, the whole remaining position: EMA(72) crosses back above EMA(24), or
    the close falls 1% under the highest close since entry (trailing stop), or
    the position is worth 2% under its cost (hard stop). An exit that the market
    refuses is sent again on the next bar until it fills.
  - Slippage cap: every order caps its slippage at 100 bps past the close it was
    decided on, so an order into a gap is refused rather than filled far away.

Everything is a deterministic function of the bars: no clock, no network, no
randomness, no environment. The same bars give the same orders, run after run.

Backtested on the kit's dev window (1,440 bars, BTC -2.8% in chop): net PnL
about +$11 on $1,000, 3 trades, max drawdown 0.64%. Buy-and-hold loses $31.63
on the same window, and a plain EMA(8)/EMA(21) cross loses $148 on 80 trades.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
FAST_SPAN = 24
SLOW_SPAN = 72
SLOPE_BARS = 60
# Entry needs the fast/slow gap above this (bps) and the slow EMA rising at
# least this much (bps) over SLOPE_BARS.
GAP_BPS = 10
SLOPE_MIN_BPS = 5
# Take-profit: sell this share of the position at +1.5% over its cost.
TP_BPS = 150
TP_SHARE_NUM = 3
TP_SHARE_DEN = 5
# Trailing stop: 1% under the highest close since entry. Hard stop: 2% under cost.
TRAIL_BPS = 100
STOP_BPS = 200
MAX_SLIPPAGE_BPS = 100


class Ema:
    """One EMA: the closes it has seen until it starts, then its value."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def step(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class Trend:
    """The trend state for the one symbol: EMAs, gap, slow-EMA history."""

    def __init__(self):
        self.fast = Ema(FAST_SPAN)
        self.slow = Ema(SLOW_SPAN)
        self.slow_hist = []  # slow EMA value after each fresh bar
        self.gap = None  # fast-slow gap in bps after this bar
        self.prev_gap = None  # the same after the previous bar

    def push(self, close):
        self.fast.step(close)
        self.slow.step(close)
        self.prev_gap = self.gap
        if self.fast.value is not None and self.slow.value is not None:
            self.gap = (self.fast.value - self.slow.value) / self.slow.value * 10000.0
            self.slow_hist.append(self.slow.value)
        else:
            self.gap = None

    def slope_bps(self):
        """Slow EMA's rise over SLOPE_BARS, in bps; None until it has the history."""
        if len(self.slow_hist) <= SLOPE_BARS:
            return None
        old = self.slow_hist[-1 - SLOPE_BARS]
        return (self.slow_hist[-1] / old - 1.0) * 10000.0

    def cross_up(self):
        """The entry cross: gap above GAP_BPS now, at or under it before."""
        return (
            self.gap is not None
            and self.prev_gap is not None
            and self.gap > GAP_BPS
            and self.prev_gap <= GAP_BPS
        )

    def cross_down(self):
        """The exit cross: gap below zero now, at or above it before."""
        return (
            self.gap is not None
            and self.prev_gap is not None
            and self.gap < 0
            and self.prev_gap >= 0
        )


trend = Trend()
# Position state, kept across batches: the highest close since entry, whether
# the take-profit fired, and the exit latch.
peak_close = None
tp_done = False
tp_pending_qty = None  # qty held when the take-profit sell was sent
exit_pending = False


def on_batch(state, batch):
    global peak_close, tp_done, tp_pending_qty, exit_pending
    orders = []
    fresh = False
    for bar in batch["bars"]:
        if bar["symbol"] != SYMBOL:
            continue
        fresh = True
        trend.push(int(bar["c"]))
    if not fresh or state.warming_up:
        return orders

    held = state.positions.get(SYMBOL)
    close = state.close(SYMBOL)
    if held is None:
        exit_pending = False
        tp_done = False
        tp_pending_qty = None
        peak_close = None
        slope = trend.slope_bps()
        if trend.cross_up() and (slope is None or slope >= SLOPE_MIN_BPS):
            cash = state.cash
            room = state.weight_room(SYMBOL)
            notional = cash if cash < room else room
            min_notional = int(state.hello["fees"]["min_notional_quote_units"])
            if notional >= min_notional:
                orders.append(
                    {
                        "side": "buy",
                        "symbol": SYMBOL,
                        "notional_quote_units": notional,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                )
        return orders

    # Holding: track the peak close, then exits, then the take-profit.
    if peak_close is None or close > peak_close:
        peak_close = close
    value = state.value(SYMBOL, held.qty)
    cost = held.cost

    if not exit_pending:
        if trend.cross_down():
            exit_pending = True
        elif peak_close is not None and close * 10000 < peak_close * (10000 - TRAIL_BPS):
            exit_pending = True
        elif value * 10000 <= cost * (10000 - STOP_BPS):
            exit_pending = True
    if exit_pending:
        tp_pending_qty = None
        orders.append(
            {
                "side": "sell",
                "symbol": SYMBOL,
                "qty": held.qty,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        )
        return orders

    if tp_pending_qty is not None:
        if held.qty < tp_pending_qty:
            tp_done = True  # the take-profit sell filled
            tp_pending_qty = None
        elif value * 10000 >= cost * (10000 + TP_BPS):
            # Refused last bar and still in profit: send it again.
            orders.append(
                {
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": held.qty * TP_SHARE_NUM // TP_SHARE_DEN,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            )
            return orders
        else:
            tp_pending_qty = None  # fell back under the level; wait for it again
    if not tp_done and value * 10000 >= cost * (10000 + TP_BPS):
        qty = held.qty * TP_SHARE_NUM // TP_SHARE_DEN
        if qty > 0:
            tp_pending_qty = held.qty
            orders.append(
                {
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            )
    return orders


makefun_bars.run(on_batch)
