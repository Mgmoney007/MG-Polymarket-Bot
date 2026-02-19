#!/usr/bin/env python3
"""
MG Polymarket Paper Trading Bot - main entry point.

Linux/macOS - run via cron every 15 minutes:
  */15 * * * * /path/to/venv/bin/python /path/to/run_bot.py >> /path/to/bot.log 2>&1

Windows - run via Task Scheduler every 15 minutes:
  Use setup_taskscheduler.ps1, or manually create a task that calls:
  C:\\path\\to\\venv\\Scripts\\python.exe C:\\path\\to\\run_bot.py >> C:\\path\\to\\bot.log 2>&1

What this script does on each run:
  1. Load persisted state (trades.json)
  2. Fetch active crypto Up/Down markets from Polymarket Gamma API
  3. For each market run the mean-reversion strategy
  4. Open / close paper positions as signalled
  5. Save updated state
  6. Regenerate the HTML dashboard
  7. Log a compact summary
"""

import logging
import os
import sys
from datetime import datetime, timezone

# Windows terminals default to cp1252; reconfigure stdout/stderr to UTF-8 so
# that log output doesn't raise UnicodeEncodeError at runtime.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # Python < 3.7 fallback: set PYTHONIOENCODING=utf-8 in env

from polymarket_client import PolymarketClient
from paper_trader import (
    load_state,
    save_state,
    process_market,
    compute_stats,
    is_circuit_tripped,
    DEFAULT_STATE_FILE,
)
from dashboard import generate as generate_dashboard

# ------------------------------------------------------------------
# Logging - structured single-line format, plays well with log files
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
log = logging.getLogger("run_bot")

# Config from environment (override via .env or export before cron)
STATE_FILE = os.environ.get("STATE_FILE", DEFAULT_STATE_FILE)
DASHBOARD_FILE = os.environ.get("DASHBOARD_FILE", "dashboard.html")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    run_start = datetime.now(timezone.utc)
    log.info("=== Bot run starting at %s ===", run_start.isoformat())

    # 1. Load state
    state = load_state(STATE_FILE)

    # 2. Check circuit breaker before making any API calls
    if is_circuit_tripped(state):
        log.warning(
            "Circuit breaker is TRIPPED - no new trades will be opened. "
            "Review losses and run: python reset_circuit_breaker.py"
        )
        # Still refresh dashboard so the user sees the tripped status
        _regenerate_dashboard(state)
        return

    # 3. Discover markets
    client = PolymarketClient()
    try:
        markets = client.get_crypto_updown_markets()
    except Exception as exc:
        log.error("Failed to fetch markets: %s - aborting run.", exc)
        sys.exit(1)

    if not markets:
        log.info("No active crypto Up/Down markets found - nothing to do.")
        _regenerate_dashboard(state)
        return

    log.info("Processing %d market(s)...", len(markets))

    # 4. Evaluate each market and act
    for market in markets:
        try:
            process_market(state, market)
        except Exception as exc:
            # Never let a single market error kill the whole run
            log.error("Error processing market %s: %s", market.get("id"), exc, exc_info=True)

    # 5. Also refresh prices for open positions whose markets weren't in the
    #    discovery batch (e.g. if market went quiet but position still open)
    open_ids = set(state["open_positions"].keys())
    seen_ids = {m["id"] for m in markets}
    stale_ids = open_ids - seen_ids
    if stale_ids:
        log.info("Refreshing %d open position(s) not in discovery batch...", len(stale_ids))
        for market_id in stale_ids:
            try:
                fresh = client.refresh_market_price(market_id)
                if fresh["yes_price"] is None:
                    log.warning("Could not refresh price for %s", market_id)
                    continue
                # Synthesise a minimal market dict for process_market
                pos = state["open_positions"][market_id]
                synthetic_market = {
                    "id": market_id,
                    "asset": pos["asset"],
                    "question": pos["question"],
                    "yes_price": fresh["yes_price"],
                    "no_price": fresh["no_price"],
                    "active": fresh["active"],
                    "closed": fresh["closed"],
                }
                process_market(state, synthetic_market)
            except Exception as exc:
                log.error("Error refreshing position %s: %s", market_id, exc, exc_info=True)

    # 6. Save state
    save_state(state, STATE_FILE)

    # 7. Dashboard
    _regenerate_dashboard(state)

    # 8. Summary log
    stats = compute_stats(state)
    cb = state["circuit_breaker"]
    run_end = datetime.now(timezone.utc)
    log.info(
        "=== Run complete in %.1fs | Trades: %d | W/L: %d/%d | "
        "Win rate: %.1f%% | Total P/L: $%.4f | Open: %d | "
        "Circuit: %s (%d consec. losses) ===",
        (run_end - run_start).total_seconds(),
        stats["total_trades"],
        stats["wins"],
        stats["losses"],
        stats["win_rate"],
        stats["total_pnl_usd"],
        stats["open_positions"],
        "TRIPPED" if cb["tripped"] else "OK",
        cb["consecutive_losses"],
    )


def _regenerate_dashboard(state) -> None:
    try:
        generate_dashboard(state_path=STATE_FILE, output_path=DASHBOARD_FILE)
    except Exception as exc:
        log.warning("Dashboard generation failed: %s", exc)


if __name__ == "__main__":
    main()
