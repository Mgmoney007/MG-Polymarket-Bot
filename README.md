# MG Polymarket Paper Trading Bot

Automated paper trading system for Polymarket crypto "Up or Down" prediction markets
(Bitcoin, Ethereum, Solana). Uses a simple mean-reversion strategy. **No real money is
ever touched.**

---

## Architecture

```
polymarket_client.py   ← Gamma API wrapper + market discovery
strategy.py            ← Mean-reversion signal logic
paper_trader.py        ← Position management, circuit breaker, state I/O
dashboard.py           ← HTML report generator
run_bot.py             ← Entry point (called by cron every 15 min)
reset_circuit_breaker.py  ← Manual reset utility
setup_cron.sh          ← Cron installer helper
trades.json            ← Persisted state (created on first run)
dashboard.html         ← Generated dashboard (open in any browser)
```

---

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run once manually

```bash
python run_bot.py
```

This will:
- Fetch active crypto Up/Down markets from `gamma-api.polymarket.com`
- Evaluate buy/sell signals
- Write `trades.json` (state) and `dashboard.html`

### 3. Install the cron job (every 15 min)

```bash
bash setup_cron.sh
# or specify a custom Python:
bash setup_cron.sh /path/to/venv/bin/python
```

Verify: `crontab -l`
View logs: `tail -f bot.log`

### 4. View the dashboard

Open `dashboard.html` in any browser. It auto-refreshes every 15 minutes.

---

## Strategy

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `BUY_THRESHOLD` | 0.40 | Buy YES shares when price ≤ 0.40 |
| `SELL_THRESHOLD` | 0.60 | Sell when price ≥ 0.60 |
| `MAX_POSITION_USD` | $10.00 | Max dollars per open position |
| `CIRCUIT_BREAKER_THRESHOLD` | 3 | Stop after 3 consecutive losses |

**Uptrend filter**: a BUY is only triggered when the current price is at least
`TREND_BUFFER` (0.02) above the recent observed low, or if there is no price
history yet. This prevents buying into a confirmed downtrend.

---

## Circuit Breaker

After 3 consecutive losing trades the bot stops opening new positions.
To resume trading after reviewing the losses:

```bash
python reset_circuit_breaker.py
```

---

## State File (trades.json)

```json
{
  "open_positions": { "<market_id>": { ... } },
  "closed_trades":  [ { ... } ],
  "circuit_breaker": {
    "consecutive_losses": 0,
    "tripped": false,
    "tripped_at": null
  },
  "price_history": { "<market_id>": [0.42, 0.39, ...] }
}
```

---

## Configuration

| Env variable | Default | Purpose |
|---|---|---|
| `STATE_FILE` | `trades.json` | Path to state JSON |
| `DASHBOARD_FILE` | `dashboard.html` | Path to HTML output |

---

## Limitations & Next Steps

- Paper trading only — no CLOB order submission
- Mean-reversion is a basic strategy; real edge requires more research
- Price history is in-memory per run; add a time-series DB for richer signals
- No slippage or liquidity modelling
- Consider adding email/Telegram alerts on circuit-breaker trip
