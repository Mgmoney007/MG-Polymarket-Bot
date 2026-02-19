"""
Mean-reversion strategy for Polymarket crypto Up/Down markets.

Logic
-----
We watch the YES price on an "Up" market (e.g. "Will BTC be higher?").

  BUY signal  -> YES price < BUY_THRESHOLD  (market oversold given uptrend)
  SELL signal -> YES price > SELL_THRESHOLD (market overbought, take profit)
  HOLD        -> price in the neutral zone

Uptrend filter
--------------
Because mean-reversion on a "down" market is dangerous, we only BUY when
a simple uptrend check passes: the current price recovered above the
recent low by at least TREND_BUFFER, *or* we have no previous price data.
The check is deliberately lightweight - a more sophisticated implementation
could use a moving average from a time-series store.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ------------------------------------------------------------------
# Tuneable parameters
# ------------------------------------------------------------------

BUY_THRESHOLD = 0.40    # enter when YES price drops here or below
SELL_THRESHOLD = 0.60   # exit when YES price rises here or above
TREND_BUFFER = 0.02     # price must be >= last_low + TREND_BUFFER to confirm uptrend
MAX_POSITION_USD = 10.0  # max dollars allocated per open position


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal: Signal
    yes_price: float
    reason: str
    position_size_usd: float = 0.0   # only set when signal == BUY


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def evaluate(
    yes_price: float,
    has_open_position: bool,
    last_low: Optional[float] = None,
) -> StrategyResult:
    """
    Decide what to do given the current YES price.

    Parameters
    ----------
    yes_price          Current probability for the YES outcome (0-1).
    has_open_position  Whether we already hold a position in this market.
    last_low           Lowest YES price observed in the recent window (optional).
                       Used for the lightweight uptrend filter.

    Returns
    -------
    StrategyResult with the recommended signal and reasoning.
    """

    # --- SELL check (must come first so we can exit existing positions) ---
    if has_open_position and yes_price >= SELL_THRESHOLD:
        return StrategyResult(
            signal=Signal.SELL,
            yes_price=yes_price,
            reason=f"YES price {yes_price:.3f} >= SELL threshold {SELL_THRESHOLD}",
        )

    # --- BUY check ---
    if not has_open_position and yes_price <= BUY_THRESHOLD:
        if not _uptrend_confirmed(yes_price, last_low):
            return StrategyResult(
                signal=Signal.HOLD,
                yes_price=yes_price,
                reason=(
                    f"YES price {yes_price:.3f} <= BUY threshold but uptrend "
                    f"not confirmed (last_low={last_low})"
                ),
            )
        size = _position_size(yes_price)
        return StrategyResult(
            signal=Signal.BUY,
            yes_price=yes_price,
            reason=f"YES price {yes_price:.3f} <= BUY threshold {BUY_THRESHOLD}, uptrend confirmed",
            position_size_usd=size,
        )

    # --- HOLD ---
    status = "in position" if has_open_position else "no position"
    return StrategyResult(
        signal=Signal.HOLD,
        yes_price=yes_price,
        reason=f"YES price {yes_price:.3f} in neutral zone [{BUY_THRESHOLD}, {SELL_THRESHOLD}] ({status})",
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _uptrend_confirmed(yes_price: float, last_low: Optional[float]) -> bool:
    """
    Return True when price looks like it has bottomed and is recovering.

    If we have no historical low, we give the benefit of the doubt and
    treat it as an uptrend (first observation for this market).
    """
    if last_low is None:
        return True
    # Price must be at least TREND_BUFFER above the recent low
    return yes_price >= last_low + TREND_BUFFER


def _position_size(yes_price: float) -> float:
    """
    Fixed-dollar position sizing capped at MAX_POSITION_USD.
    We always use the full cap; the price determines implied share count,
    which the paper trader tracks separately.
    """
    return min(MAX_POSITION_USD, MAX_POSITION_USD)  # extensible hook for Kelly etc.
