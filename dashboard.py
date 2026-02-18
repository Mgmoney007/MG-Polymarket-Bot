"""
HTML dashboard generator.

Reads trades.json and writes dashboard.html.
Open dashboard.html in any browser to see the current state.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from paper_trader import compute_stats, load_state, DEFAULT_STATE_FILE

OUTPUT_FILE = "dashboard.html"


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def generate(state_path: str = DEFAULT_STATE_FILE, output_path: str = OUTPUT_FILE) -> None:
    state = load_state(state_path)
    stats = compute_stats(state)
    html = _render(state, stats)
    with open(output_path, "w") as fh:
        fh.write(html)
    print(f"Dashboard written to {output_path}")


# ------------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------------

def _pnl_colour(value: float) -> str:
    if value > 0:
        return "#27ae60"   # green
    if value < 0:
        return "#e74c3c"   # red
    return "#7f8c8d"       # grey


def _fmt_usd(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}${value:.4f}"


def _fmt_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _circuit_badge(cb: dict) -> str:
    if cb["tripped"]:
        tripped_at = cb.get("tripped_at", "unknown")
        return (
            f'<span class="badge badge-danger">TRIPPED — {cb["consecutive_losses"]} '
            f'consecutive losses (since {tripped_at})</span>'
        )
    losses = cb["consecutive_losses"]
    colour = "badge-warning" if losses >= 2 else "badge-ok"
    return (
        f'<span class="badge {colour}">Active — {losses} / 3 consecutive losses</span>'
    )


def _open_positions_table(state: dict) -> str:
    positions = list(state["open_positions"].values())
    if not positions:
        return '<p class="muted">No open positions.</p>'

    rows = ""
    for p in positions:
        rows += (
            f"<tr>"
            f"<td>{p['asset']}</td>"
            f"<td class='question'>{p['question']}</td>"
            f"<td>{p['entry_price']:.3f}</td>"
            f"<td>{p['size_usd']:.2f}</td>"
            f"<td>{p['shares']:.4f}</td>"
            f"<td>{p['opened_at']}</td>"
            f"</tr>"
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>Asset</th><th>Question</th><th>Entry</th>
          <th>Size ($)</th><th>Shares</th><th>Opened At</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def _closed_trades_table(state: dict) -> str:
    trades = list(reversed(state["closed_trades"]))  # newest first
    if not trades:
        return '<p class="muted">No closed trades yet.</p>'

    rows = ""
    for t in trades:
        pnl_color = _pnl_colour(t["pnl_usd"])
        outcome_class = "win" if t["outcome"] == "WIN" else "loss"
        rows += (
            f"<tr>"
            f"<td>{t['asset']}</td>"
            f"<td class='question'>{t['question']}</td>"
            f"<td>{t['entry_price']:.3f}</td>"
            f"<td>{t['exit_price']:.3f}</td>"
            f"<td style='color:{pnl_color};font-weight:bold'>{_fmt_usd(t['pnl_usd'])}</td>"
            f"<td style='color:{pnl_color}'>{_fmt_pct(t['pnl_pct'])}</td>"
            f"<td class='{outcome_class}'>{t['outcome']}</td>"
            f"<td>{t['opened_at']}</td>"
            f"<td>{t['closed_at']}</td>"
            f"</tr>"
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>Asset</th><th>Question</th><th>Entry</th><th>Exit</th>
          <th>P/L ($)</th><th>P/L (%)</th><th>Outcome</th>
          <th>Opened At</th><th>Closed At</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render(state: dict, stats: dict) -> str:
    total_pnl = stats["total_pnl_usd"]
    pnl_color = _pnl_colour(total_pnl)
    win_rate = stats["win_rate"]
    win_rate_color = "#27ae60" if win_rate >= 50 else "#e74c3c"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="900">
  <title>MG Polymarket Paper Trading Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f1117;
      color: #e0e0e0;
      padding: 24px;
    }}
    h1 {{ font-size: 1.6rem; margin-bottom: 4px; color: #fff; }}
    h2 {{ font-size: 1.1rem; margin: 28px 0 12px; color: #aaa; text-transform: uppercase;
          letter-spacing: 0.05em; border-bottom: 1px solid #2a2a3a; padding-bottom: 6px; }}
    .subtitle {{ color: #666; font-size: 0.85rem; margin-bottom: 24px; }}

    /* KPI cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
      margin-bottom: 10px;
    }}
    .kpi {{
      background: #1a1d27;
      border: 1px solid #2a2d3a;
      border-radius: 10px;
      padding: 16px 20px;
    }}
    .kpi .label {{ font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
    .kpi .value {{ font-size: 1.6rem; font-weight: 700; margin-top: 6px; }}

    /* Badge */
    .badge {{
      display: inline-block;
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 0.82rem;
      font-weight: 600;
    }}
    .badge-ok      {{ background: #1a3a28; color: #27ae60; border: 1px solid #27ae60; }}
    .badge-warning {{ background: #3a2e10; color: #f39c12; border: 1px solid #f39c12; }}
    .badge-danger  {{ background: #3a1515; color: #e74c3c; border: 1px solid #e74c3c; }}

    /* Tables */
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.83rem;
    }}
    th {{
      text-align: left;
      padding: 8px 12px;
      color: #777;
      font-weight: 500;
      border-bottom: 1px solid #2a2d3a;
      white-space: nowrap;
    }}
    td {{
      padding: 9px 12px;
      border-bottom: 1px solid #1e2130;
      vertical-align: top;
    }}
    tr:hover td {{ background: #1c1f2e; }}
    .question {{ max-width: 320px; font-size: 0.78rem; color: #aaa; }}
    .win  {{ color: #27ae60; font-weight: 600; }}
    .loss {{ color: #e74c3c; font-weight: 600; }}
    .muted {{ color: #555; font-style: italic; padding: 8px 0; }}
  </style>
</head>
<body>
  <h1>MG Polymarket &mdash; Paper Trading Dashboard</h1>
  <p class="subtitle">Auto-refreshes every 15 min &nbsp;|&nbsp; Last generated: {_now_utc()}</p>

  <h2>Performance Summary</h2>
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">Total P/L</div>
      <div class="value" style="color:{pnl_color}">{_fmt_usd(total_pnl)}</div>
    </div>
    <div class="kpi">
      <div class="label">Win Rate</div>
      <div class="value" style="color:{win_rate_color}">{win_rate:.1f}%</div>
    </div>
    <div class="kpi">
      <div class="label">Total Trades</div>
      <div class="value">{stats['total_trades']}</div>
    </div>
    <div class="kpi">
      <div class="label">Wins / Losses</div>
      <div class="value">{stats['wins']} / {stats['losses']}</div>
    </div>
    <div class="kpi">
      <div class="label">Avg P/L / Trade</div>
      <div class="value" style="color:{_pnl_colour(stats['avg_pnl_usd'])}">{_fmt_usd(stats['avg_pnl_usd'])}</div>
    </div>
    <div class="kpi">
      <div class="label">Best Trade</div>
      <div class="value" style="color:#27ae60">{_fmt_usd(stats['best_trade_usd'])}</div>
    </div>
    <div class="kpi">
      <div class="label">Worst Trade</div>
      <div class="value" style="color:#e74c3c">{_fmt_usd(stats['worst_trade_usd'])}</div>
    </div>
    <div class="kpi">
      <div class="label">Open Positions</div>
      <div class="value">{stats['open_positions']}</div>
    </div>
  </div>

  <h2>Circuit Breaker</h2>
  {_circuit_badge(stats['circuit_breaker'])}

  <h2>Open Positions ({stats['open_positions']})</h2>
  <div class="table-wrap">
    {_open_positions_table(state)}
  </div>

  <h2>Closed Trades ({stats['total_trades']})</h2>
  <div class="table-wrap">
    {_closed_trades_table(state)}
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    generate()
