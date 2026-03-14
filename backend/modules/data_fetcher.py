"""
NSE India Data Fetcher
Scrapes live option chain data, India VIX, Nifty spot price, and indices
from NSE India API endpoints with proper session/cookie handling.

NSE aggressively blocks non-browser requests. This module uses:
- Realistic Chrome 131 headers with sec-ch-ua, sec-fetch-* headers
- Two-step cookie acquisition: homepage → option-chain page → API
- Random delays between requests to avoid rate limiting
- Session rotation on repeated 403s
"""

import httpx
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_OPTION_CHAIN_PAGE = "https://www.nseindia.com/option-chain"
NSE_OPTION_CHAIN_API = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
NSE_ALL_INDICES = "https://www.nseindia.com/api/allIndices"

# Full browser-like headers that NSE expects (Chrome 131 on Windows 10)
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Headers for XHR/API calls (after cookies are set)
API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
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
    """Handles all data fetching from NSE India with cookie/session management.

    NSE requires a two-step flow:
    1. Visit the homepage with full browser headers → acquire session cookies
    2. Visit the option-chain page → warm the session for API access
    3. Hit the JSON API endpoints with XHR-style headers + cookies

    If 403 persists, the session is destroyed and recreated from scratch.
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies_valid = False
        self._session_init_count = 0
        self._last_fetch: Optional[datetime] = None
        self._cached_snapshot: Optional[MarketSnapshot] = None
        self._last_expiry_dates: List[str] = []
        self._last_selected_expiry: str = ""

    async def _create_client(self) -> httpx.AsyncClient:
        """Create a fresh HTTP client with browser-like settings."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

        self._client = httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            timeout=httpx.Timeout(30.0, connect=15.0),
            follow_redirects=True,
            verify=True,
            http2=False,
        )
        self._cookies_valid = False
        return self._client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            return await self._create_client()
        return self._client

    async def _init_session(self) -> bool:
        """Two-step session initialization: homepage → option-chain page.

        This mimics a real user opening Chrome, navigating to nseindia.com,
        and then clicking on the Option Chain page.
        """
        self._session_init_count += 1

        # After 3 failed inits, destroy and recreate the client entirely
        if self._session_init_count > 3:
            logger.warning("Multiple session init failures, creating fresh client...")
            await self._create_client()
            self._session_init_count = 1

        try:
            client = await self._get_client()

            # Step 1: Hit the homepage with full browser headers
            client.headers.update(BROWSER_HEADERS)
            resp = await client.get(NSE_BASE)
            if resp.status_code != 200:
                logger.warning(f"NSE homepage returned {resp.status_code}")
                return False

            logger.info("NSE homepage OK, cookies acquired.")

            # Small random delay to mimic human behavior
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Step 2: Visit the option-chain page (sets additional cookies)
            resp = await client.get(NSE_OPTION_CHAIN_PAGE)
            if resp.status_code != 200:
                logger.warning(f"NSE option-chain page returned {resp.status_code}")
                # Still try API — sometimes the page 403s but API works
            else:
                logger.info("NSE option-chain page OK, session warmed.")

            await asyncio.sleep(random.uniform(0.3, 0.8))

            self._cookies_valid = True
            self._session_init_count = 0
            return True

        except httpx.ConnectTimeout:
            logger.error("Connection timeout reaching NSE — check your internet")
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
                    wait = 2 ** attempt + random.uniform(0, 1)
                    logger.info(f"Session init failed, waiting {wait:.1f}s before retry...")
                    await asyncio.sleep(wait)
                    continue

            try:
                # Switch to API headers for XHR calls (keeps cookies from client)
                client.headers.update(API_HEADERS)
                resp = await client.get(url)

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (401, 403):
                    logger.warning(
                        f"NSE API returned {resp.status_code} on attempt {attempt + 1}, "
                        "re-initializing session..."
                    )
                    self._cookies_valid = False
                    await asyncio.sleep(1 + random.uniform(0, 1))
                    continue
                else:
                    logger.warning(f"NSE API {url} returned {resp.status_code}")
            except httpx.ReadTimeout:
                logger.warning(f"Timeout fetching {url}, attempt {attempt + 1}/{retries}")
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")

            await asyncio.sleep(2 ** attempt + random.uniform(0, 1))

        return None

    async def fetch_option_chain(self, expiry: Optional[str] = None) -> Dict[float, OptionChainRow]:
        """Fetch the full NIFTY option chain from NSE.

        Also populates self._last_expiry_dates and self._last_selected_expiry
        so fetch_full_snapshot doesn't need a second API call.
        """
        data = await self._fetch_json(NSE_OPTION_CHAIN_API)
        if not data:
            logger.error("Failed to fetch option chain data")
            return {}

        records = data.get("records", {})
        underlying_value = records.get("underlyingValue", 0.0)
        expiry_dates = records.get("expiryDates", [])
        all_data = records.get("data", [])

        # Use nearest expiry if none specified
        target_expiry = expiry or (expiry_dates[0] if expiry_dates else None)

        # Store for fetch_full_snapshot to use without a second API call
        self._last_expiry_dates = expiry_dates
        self._last_selected_expiry = target_expiry or ""

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
        """Fetch a complete market snapshot: option chain + all indices.

        Fetches sequentially (not concurrently) to avoid session/cookie
        conflicts — both calls share the same httpx client and cookies.
        """
        snapshot = MarketSnapshot()

        try:
            # Ensure session is initialized before any API calls
            if not self._cookies_valid:
                if not await self._init_session():
                    logger.error("Could not establish NSE session")
                    if self._cached_snapshot:
                        self._cached_snapshot.is_stale = True
                        return self._cached_snapshot
                    snapshot.error = "Could not establish NSE session"
                    return snapshot

            # Fetch option chain first (also extracts expiry dates)
            chain = await self.fetch_option_chain(expiry)
            snapshot.option_chain = chain
            snapshot.expiry_dates = self._last_expiry_dates
            snapshot.selected_expiry = self._last_selected_expiry

            # Small delay between API calls to avoid rate limiting
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # Fetch indices next
            indices = await self.fetch_indices()
            snapshot.indices = indices

            if indices:
                spot, change, change_pct = self._extract_nifty_spot(indices)
                snapshot.nifty_spot = spot
                snapshot.nifty_change = change
                snapshot.nifty_change_pct = change_pct

                vix, vix_change = self._extract_vix(indices)
                snapshot.india_vix = vix
                snapshot.india_vix_change_pct = vix_change

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
