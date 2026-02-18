"""
Polymarket Gamma API client.

Gamma API base: https://gamma-api.polymarket.com
Docs: https://docs.polymarket.com (see gamma-api section)

Key endpoints used:
  GET /markets           - paginated list of all markets
  GET /markets/{id}      - single market detail
  GET /events            - paginated list of events (groups of markets)
"""

import logging
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Crypto asset keywords we care about for the "Up or Down" strategy
CRYPTO_KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]

# Words that indicate a directional "up/down" market
DIRECTION_KEYWORDS = ["up or down", "higher or lower", "above or below", "up/down"]


class PolymarketClient:
    """Thin wrapper around the Gamma REST API."""

    def __init__(self, timeout: int = 15, retry_attempts: int = 3):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MG-Polymarket-Bot/1.0"})
        self.timeout = timeout
        self.retry_attempts = retry_attempts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> dict | list:
        url = f"{GAMMA_BASE}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning("GET %s attempt %d/%d failed: %s — retrying in %ds",
                            url, attempt, self.retry_attempts, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"All {self.retry_attempts} attempts failed for {url}") from last_exc

    def _paginate(self, path: str, params: dict, page_size: int = 100) -> list[dict]:
        """Collect all pages from a paginated endpoint."""
        results: list[dict] = []
        offset = 0
        while True:
            params = {**params, "limit": page_size, "offset": offset}
            page = self._get(path, params)
            if not page:
                break
            results.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_market(self, market_id: str) -> dict:
        """Fetch a single market by its Gamma market ID."""
        return self._get(f"/markets/{market_id}")

    def get_all_active_markets(self, page_size: int = 100) -> list[dict]:
        """
        Return all currently active (non-closed, non-archived) markets.

        Each market dict from the Gamma API includes at minimum:
          id, question, conditionId, startDate, endDate, active, closed,
          tokens (list of {token_id, outcome, price, winner}),
          outcomePrices (list of price strings indexed to tokens),
          volume, liquidity, spread, tags
        """
        params = {"active": "true", "closed": "false", "archived": "false"}
        return self._paginate("/markets", params, page_size=page_size)

    def get_crypto_updown_markets(self) -> list[dict]:
        """
        Filter active markets down to crypto 'Up or Down' markets for
        BTC, ETH, and SOL.

        Returns a list of normalised market dicts with extra keys:
          asset        - 'BTC' | 'ETH' | 'SOL'
          yes_price    - float, current YES outcome price (0–1)
          no_price     - float, current NO outcome price (0–1)
          yes_token_id - str, CLOB token id for YES leg
          no_token_id  - str, CLOB token id for NO leg
        """
        log.info("Fetching all active markets from Gamma API…")
        markets = self.get_all_active_markets()
        log.info("Total active markets fetched: %d", len(markets))

        matched: list[dict] = []
        for m in markets:
            question: str = m.get("question", "").lower()
            if not _is_direction_market(question):
                continue
            asset = _detect_crypto_asset(question)
            if asset is None:
                continue

            # Parse YES/NO prices from outcomePrices + tokens
            yes_price, no_price, yes_tok, no_tok = _parse_prices(m)
            if yes_price is None:
                continue

            matched.append({
                **m,
                "asset": asset,
                "yes_price": yes_price,
                "no_price": no_price,
                "yes_token_id": yes_tok,
                "no_token_id": no_tok,
            })

        log.info("Crypto Up/Down markets found: %d", len(matched))
        return matched

    def refresh_market_price(self, market_id: str) -> dict:
        """
        Re-fetch a single market and return updated price info.
        Returns dict with keys: yes_price, no_price, active, closed
        """
        m = self.get_market(market_id)
        yes_price, no_price, _, _ = _parse_prices(m)
        return {
            "yes_price": yes_price,
            "no_price": no_price,
            "active": m.get("active", False),
            "closed": m.get("closed", False),
        }


# ------------------------------------------------------------------
# Module-level helpers (pure functions, easy to unit-test)
# ------------------------------------------------------------------

def _is_direction_market(question_lower: str) -> bool:
    return any(kw in question_lower for kw in DIRECTION_KEYWORDS)


def _detect_crypto_asset(question_lower: str) -> Optional[str]:
    if "bitcoin" in question_lower or " btc" in question_lower or "btc " in question_lower:
        return "BTC"
    if "ethereum" in question_lower or " eth" in question_lower or "eth " in question_lower:
        return "ETH"
    if "solana" in question_lower or " sol" in question_lower or "sol " in question_lower:
        return "SOL"
    return None


def _parse_prices(market: dict) -> tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """
    Extract YES and NO prices from a Gamma market object.

    The Gamma API returns either:
      - outcomePrices: ["0.65", "0.35"]   (parallel to tokens list)
      - tokens[i].price: float            (alternative location)

    Returns (yes_price, no_price, yes_token_id, no_token_id).
    Returns (None, None, None, None) on any parse error.
    """
    tokens: list[dict] = market.get("tokens", [])
    outcome_prices: list[str] = market.get("outcomePrices", [])

    # Build a map outcome→(price, token_id)
    price_map: dict[str, tuple[float, str]] = {}

    for i, tok in enumerate(tokens):
        outcome: str = tok.get("outcome", "").upper()
        token_id: str = tok.get("token_id", tok.get("tokenId", ""))

        # Price priority: outcomePrices list first, then token.price
        price_raw = None
        if i < len(outcome_prices):
            price_raw = outcome_prices[i]
        elif "price" in tok:
            price_raw = tok["price"]

        if price_raw is None:
            continue
        try:
            price_map[outcome] = (float(price_raw), token_id)
        except (ValueError, TypeError):
            continue

    yes_data = price_map.get("YES")
    no_data = price_map.get("NO")

    if yes_data is None or no_data is None:
        return None, None, None, None

    return yes_data[0], no_data[0], yes_data[1], no_data[1]
