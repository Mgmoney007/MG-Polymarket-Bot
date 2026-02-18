#!/usr/bin/env python3
"""
Manually reset the circuit breaker after reviewing consecutive losses.

Usage:
  python reset_circuit_breaker.py
"""
import os
from paper_trader import load_state, save_state, reset_circuit_breaker, DEFAULT_STATE_FILE

STATE_FILE = os.environ.get("STATE_FILE", DEFAULT_STATE_FILE)

state = load_state(STATE_FILE)
cb = state["circuit_breaker"]
if not cb["tripped"]:
    print(f"Circuit breaker is not tripped (consecutive losses: {cb['consecutive_losses']}).")
else:
    reset_circuit_breaker(state)
    save_state(state, STATE_FILE)
    print("Circuit breaker has been reset. Bot will resume trading on next run.")
