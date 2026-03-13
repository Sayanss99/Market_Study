"""
NSE India Data Fetcher
Scrapes live option chain data, India VIX, Nifty spot price, and indices
from NSE India API endpoints with proper session/cookie handling.
"""

import httpx
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_OPTION_CHAIN = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
NSE_ALL_INDICES = "https://www.nseindia.com/api/allIndices"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}


@dataclass
class OptionData:
    """Represents data for a single option strike (one side: CE or PE)."""
    strike_price: float
    option_type: str  # "CE" or "PE"
    ltp: float = 0.0
    iv: float = 0.0
    oi: int = 0
    change_in_oi: int = 0
    volume: int = 0
    bid_price: float = 0.0
    bid_qty: int = 0
    ask_price: float = 0.0
    ask_qty: int = 0
    underlying_value: float = 0.0
    expiry_date: str = ""


@dataclass
class OptionChainRow:
    """One row of the option chain — a CE and PE pair at the same strike."""
    strike_price: float
    ce: Optional[OptionData] = None
    pe: Optional[OptionData] = None


@dataclass
class MarketSnapshot:
    """Complete market snapshot from NSE."""
    timestamp: datetime = field(default_factory=datetime.now)
    nifty_spot: float = 0.0
    nifty_change: float = 0.0
    nifty_change_pct: float = 0.0
    india_vix: float = 0.0
    india_vix_change_pct: float = 0.0
    nifty_futures: float = 0.0
    option_chain: Dict[float, OptionChainRow] = field(default_factory=dict)
    expiry_dates: List[str] = field(default_factory=list)
    selected_expiry: str = ""
    indices: Dict[str, Dict[str, float]] = field(default_factory=dict)
    is_stale: bool = False
    error: Optional[str] = None


class NSEDataFetcher:
    """Handles all data fetching from NSE India with cookie/session management."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies_valid = False
        self._last_fetch: Optional[datetime] = None
        self._cached_snapshot: Optional[MarketSnapshot] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=HEADERS,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                verify=True,
            )
            self._cookies_valid = False
        return self._client

    async def _init_session(self) -> bool:
        """Hit NSE homepage to get cookies before API calls."""
        try:
            client = await self._get_client()
            resp = await client.get(NSE_BASE)
            if resp.status_code == 200:
                self._cookies_valid = True
                logger.info("NSE session initialized, cookies acquired.")
                return True
            else:
                logger.warning(f"NSE homepage returned {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize NSE session: {e}")
            return False

    async def _fetch_json(self, url: str, retries: int = 3) -> Optional[Dict]:
        """Fetch JSON from NSE API with retry logic and session refresh."""
        client = await self._get_client()

        for attempt in range(retries):
            if not self._cookies_valid:
                if not await self._init_session():
                    await asyncio.sleep(2 ** attempt)
                    continue

            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (401, 403):
                    logger.warning("NSE session expired, re-initializing...")
                    self._cookies_valid = False
                    continue
                else:
                    logger.warning(f"NSE API {url} returned {resp.status_code}")
            except httpx.ReadTimeout:
                logger.warning(f"Timeout fetching {url}, attempt {attempt + 1}")
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")

            await asyncio.sleep(2 ** attempt)

        return None

    async def fetch_option_chain(self, expiry: Optional[str] = None) -> Dict[float, OptionChainRow]:
        """Fetch the full NIFTY option chain from NSE."""
        data = await self._fetch_json(NSE_OPTION_CHAIN)
        if not data:
            logger.error("Failed to fetch option chain data")
            return {}

        records = data.get("records", {})
        underlying_value = records.get("underlyingValue", 0.0)
        expiry_dates = records.get("expiryDates", [])
        all_data = records.get("data", [])

        # Use nearest expiry if none specified
        target_expiry = expiry or (expiry_dates[0] if expiry_dates else None)

        chain: Dict[float, OptionChainRow] = {}

        for row in all_data:
            if row.get("expiryDate") != target_expiry:
                continue

            strike = float(row.get("strikePrice", 0))
            if strike not in chain:
                chain[strike] = OptionChainRow(strike_price=strike)

            if "CE" in row:
                ce = row["CE"]
                chain[strike].ce = OptionData(
                    strike_price=strike,
                    option_type="CE",
                    ltp=ce.get("lastPrice", 0.0),
                    iv=ce.get("impliedVolatility", 0.0),
                    oi=ce.get("openInterest", 0),
                    change_in_oi=ce.get("changeinOpenInterest", 0),
                    volume=ce.get("totalTradedVolume", 0),
                    bid_price=ce.get("bidprice", 0.0),
                    bid_qty=ce.get("bidQty", 0),
                    ask_price=ce.get("askprice", 0.0),
                    ask_qty=ce.get("askQty", 0),
                    underlying_value=ce.get("underlyingValue", underlying_value),
                    expiry_date=target_expiry or "",
                )

            if "PE" in row:
                pe = row["PE"]
                chain[strike].pe = OptionData(
                    strike_price=strike,
                    option_type="PE",
                    ltp=pe.get("lastPrice", 0.0),
                    iv=pe.get("impliedVolatility", 0.0),
                    oi=pe.get("openInterest", 0),
                    change_in_oi=pe.get("changeinOpenInterest", 0),
                    volume=pe.get("totalTradedVolume", 0),
                    bid_price=pe.get("bidprice", 0.0),
                    bid_qty=pe.get("bidQty", 0),
                    ask_price=pe.get("askprice", 0.0),
                    ask_qty=pe.get("askQty", 0),
                    underlying_value=pe.get("underlyingValue", underlying_value),
                    expiry_date=target_expiry or "",
                )

        return chain

    async def fetch_indices(self) -> Dict[str, Dict[str, Any]]:
        """Fetch all NSE indices including Nifty spot, VIX, and sectoral indices."""
        data = await self._fetch_json(NSE_ALL_INDICES)
        if not data:
            return {}

        indices = {}
        for item in data.get("data", []):
            name = item.get("index", "")
            indices[name] = {
                "last": item.get("last", 0.0),
                "change": item.get("percentChange", 0.0),
                "open": item.get("open", 0.0),
                "high": item.get("high", 0.0),
                "low": item.get("low", 0.0),
                "prev_close": item.get("previousClose", 0.0),
            }

        return indices

    def _extract_nifty_spot(self, indices: Dict) -> tuple:
        """Extract Nifty 50 spot price and change from indices data."""
        nifty = indices.get("NIFTY 50", {})
        spot = nifty.get("last", 0.0)
        prev = nifty.get("prev_close", 0.0)
        change = spot - prev if prev else 0.0
        change_pct = (change / prev * 100) if prev else 0.0
        return spot, change, change_pct

    def _extract_vix(self, indices: Dict) -> tuple:
        """Extract India VIX value and change from indices data."""
        vix = indices.get("INDIA VIX", {})
        value = vix.get("last", 0.0)
        change_pct = vix.get("change", 0.0)
        return value, change_pct

    async def fetch_full_snapshot(self, expiry: Optional[str] = None) -> MarketSnapshot:
        """Fetch a complete market snapshot: option chain + all indices."""
        snapshot = MarketSnapshot()

        try:
            # Fetch option chain and indices concurrently
            chain_task = self.fetch_option_chain(expiry)
            indices_task = self.fetch_indices()

            chain, indices = await asyncio.gather(chain_task, indices_task)

            snapshot.option_chain = chain
            snapshot.indices = indices

            if indices:
                spot, change, change_pct = self._extract_nifty_spot(indices)
                snapshot.nifty_spot = spot
                snapshot.nifty_change = change
                snapshot.nifty_change_pct = change_pct

                vix, vix_change = self._extract_vix(indices)
                snapshot.india_vix = vix
                snapshot.india_vix_change_pct = vix_change

            # Get expiry dates from option chain API
            oc_data = await self._fetch_json(NSE_OPTION_CHAIN)
            if oc_data:
                records = oc_data.get("records", {})
                snapshot.expiry_dates = records.get("expiryDates", [])
                snapshot.selected_expiry = expiry or (
                    snapshot.expiry_dates[0] if snapshot.expiry_dates else ""
                )

            snapshot.timestamp = datetime.now()
            self._last_fetch = snapshot.timestamp
            self._cached_snapshot = snapshot

        except Exception as e:
            logger.error(f"Error fetching full snapshot: {e}")
            snapshot.error = str(e)
            if self._cached_snapshot:
                snapshot = self._cached_snapshot
                snapshot.is_stale = True

        return snapshot

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton instance
_fetcher: Optional[NSEDataFetcher] = None


def get_fetcher() -> NSEDataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = NSEDataFetcher()
    return _fetcher
