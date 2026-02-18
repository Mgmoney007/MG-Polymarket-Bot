"""
Paper trading engine.

State is persisted to a JSON file (default: trades.json) so it survives
between cron runs.  No real money is ever touched.

JSON schema
-----------
{
  "open_positions": {
    "<market_id>": {
      "market_id":    str,
      "asset":        "BTC" | "ETH" | "SOL",
      "question":     str,
      "entry_price":  float,
      "size_usd":     float,
      "shares":       float,      # size_usd / entry_price
      "opened_at":    ISO-8601 str,
      "last_low":     float | null
    }
  },
  "closed_trades": [
    {
      "market_id":    str,
      "asset":        str,
      "question":     str,
      "entry_price":  float,
      "exit_price":   float,
      "size_usd":     float,
      "shares":       float,
      "pnl_usd":      float,
      "pnl_pct":      float,
      "outcome":      "WIN" | "LOSS",
      "opened_at":    ISO-8601 str,
      "closed_at":    ISO-8601 str
    }
  ],
  "circuit_breaker": {
    "consecutive_losses": int,
    "tripped":            bool,
    "tripped_at":         ISO-8601 str | null
  },
  "price_history": {
    "<market_id>": [float, ...]   # rolling window of last N yes_prices
  }
}
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from strategy import Signal, StrategyResult, evaluate

log = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "trades.json"
CIRCUIT_BREAKER_THRESHOLD = 3   # trip after this many consecutive losses
PRICE_HISTORY_WINDOW = 20       # keep this many price observations per market


# ------------------------------------------------------------------
# State I/O
# ------------------------------------------------------------------

def _empty_state() -> dict:
    return {
        "open_positions": {},
        "closed_trades": [],
        "circuit_breaker": {
            "consecutive_losses": 0,
            "tripped": False,
            "tripped_at": None,
        },
        "price_history": {},
    }


def load_state(path: str = DEFAULT_STATE_FILE) -> dict:
    if not os.path.exists(path):
        log.info("No state file found at %s — starting fresh.", path)
        return _empty_state()
    with open(path) as fh:
        raw = fh.read().strip()
    if not raw:
        log.info("State file %s is empty — starting fresh.", path)
        return _empty_state()
    state = json.loads(raw)
    # Ensure all keys exist in older state files
    state.setdefault("open_positions", {})
    state.setdefault("closed_trades", [])
    state.setdefault("circuit_breaker", {
        "consecutive_losses": 0,
        "tripped": False,
        "tripped_at": None,
    })
    state.setdefault("price_history", {})
    return state


def save_state(state: dict, path: str = DEFAULT_STATE_FILE) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)   # atomic write
    log.debug("State saved to %s", path)


# ------------------------------------------------------------------
# Circuit breaker
# ------------------------------------------------------------------

def is_circuit_tripped(state: dict) -> bool:
    return state["circuit_breaker"]["tripped"]


def _record_win(state: dict) -> None:
    state["circuit_breaker"]["consecutive_losses"] = 0


def _record_loss(state: dict) -> None:
    cb = state["circuit_breaker"]
    cb["consecutive_losses"] += 1
    log.info("Consecutive losses: %d / %d",
             cb["consecutive_losses"], CIRCUIT_BREAKER_THRESHOLD)
    if cb["consecutive_losses"] >= CIRCUIT_BREAKER_THRESHOLD:
        cb["tripped"] = True
        cb["tripped_at"] = _now()
        log.warning(
            "CIRCUIT BREAKER TRIPPED after %d consecutive losses at %s",
            cb["consecutive_losses"], cb["tripped_at"],
        )


def reset_circuit_breaker(state: dict) -> None:
    """Call manually after investigating losses."""
    state["circuit_breaker"] = {
        "consecutive_losses": 0,
        "tripped": False,
        "tripped_at": None,
    }
    log.info("Circuit breaker reset.")


# ------------------------------------------------------------------
# Price history helpers
# ------------------------------------------------------------------

def _update_price_history(state: dict, market_id: str, price: float) -> None:
    history = state["price_history"].setdefault(market_id, [])
    history.append(price)
    if len(history) > PRICE_HISTORY_WINDOW:
        history.pop(0)


def _get_last_low(state: dict, market_id: str) -> Optional[float]:
    history = state["price_history"].get(market_id, [])
    return min(history) if history else None


# ------------------------------------------------------------------
# Core trading actions
# ------------------------------------------------------------------

def open_position(state: dict, market: dict, result: StrategyResult) -> None:
    market_id = market["id"]
    shares = result.position_size_usd / result.yes_price
    position = {
        "market_id": market_id,
        "asset": market["asset"],
        "question": market.get("question", ""),
        "entry_price": result.yes_price,
        "size_usd": result.position_size_usd,
        "shares": shares,
        "opened_at": _now(),
        "last_low": _get_last_low(state, market_id),
    }
    state["open_positions"][market_id] = position
    log.info(
        "OPENED  %s | %s @ %.3f | $%.2f → %.4f shares",
        market["asset"], market_id, result.yes_price,
        result.position_size_usd, shares,
    )


def close_position(state: dict, market_id: str, exit_price: float) -> Optional[dict]:
    position = state["open_positions"].pop(market_id, None)
    if position is None:
        log.warning("Tried to close non-existent position %s", market_id)
        return None

    pnl_usd = (exit_price - position["entry_price"]) * position["shares"]
    pnl_pct = (exit_price / position["entry_price"] - 1) * 100
    outcome = "WIN" if pnl_usd > 0 else "LOSS"

    trade = {
        **position,
        "exit_price": exit_price,
        "pnl_usd": round(pnl_usd, 4),
        "pnl_pct": round(pnl_pct, 4),
        "outcome": outcome,
        "closed_at": _now(),
    }
    state["closed_trades"].append(trade)

    if outcome == "WIN":
        _record_win(state)
    else:
        _record_loss(state)

    log.info(
        "CLOSED  %s | %s @ %.3f → %.3f | P/L $%.4f (%.2f%%) [%s]",
        position["asset"], market_id,
        position["entry_price"], exit_price,
        pnl_usd, pnl_pct, outcome,
    )
    return trade


# ------------------------------------------------------------------
# Main per-market evaluation loop (called by run_bot.py)
# ------------------------------------------------------------------

def process_market(state: dict, market: dict) -> None:
    """
    Evaluate a single market and open/close positions as appropriate.
    Updates state in-place; caller is responsible for saving state.
    """
    market_id = market["id"]
    yes_price: float = market["yes_price"]
    has_position = market_id in state["open_positions"]

    # Read last_low from *existing* history before appending current price,
    # so the first-ever observation doesn't immediately become its own floor.
    last_low = _get_last_low(state, market_id)
    _update_price_history(state, market_id, yes_price)

    result: StrategyResult = evaluate(
        yes_price=yes_price,
        has_open_position=has_position,
        last_low=last_low,
    )

    log.debug("Market %s (%s) | YES=%.3f | Signal=%s | %s",
              market_id, market.get("asset"), yes_price,
              result.signal.value, result.reason)

    if result.signal == Signal.BUY:
        if is_circuit_tripped(state):
            log.warning("Circuit breaker is TRIPPED — skipping BUY for %s", market_id)
            return
        open_position(state, market, result)

    elif result.signal == Signal.SELL:
        close_position(state, market_id, exit_price=yes_price)


# ------------------------------------------------------------------
# Summary statistics (used by dashboard.py)
# ------------------------------------------------------------------

def compute_stats(state: dict) -> dict:
    trades = state["closed_trades"]
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl_usd": 0.0,
            "avg_pnl_usd": 0.0,
            "best_trade_usd": 0.0,
            "worst_trade_usd": 0.0,
            "open_positions": len(state["open_positions"]),
            "circuit_breaker": state["circuit_breaker"],
        }

    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    pnls = [t["pnl_usd"] for t in trades]

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl_usd": round(sum(pnls), 4),
        "avg_pnl_usd": round(sum(pnls) / len(pnls), 4),
        "best_trade_usd": round(max(pnls), 4),
        "worst_trade_usd": round(min(pnls), 4),
        "open_positions": len(state["open_positions"]),
        "circuit_breaker": state["circuit_breaker"],
    }


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
