"""
NSE India Data Fetcher
Scrapes live option chain data, India VIX, Nifty spot price, and indices
from NSE India API endpoints with proper session/cookie handling.

Uses curl_cffi which impersonates Chrome's exact TLS fingerprint at the
handshake level. NSE uses Akamai Bot Manager which does deep TLS
fingerprinting — both httpx and requests get blocked because their TLS
stacks are recognizably different from real browsers. curl_cffi solves
this by using curl-impersonate under the hood.

The async interface is preserved via asyncio.to_thread() wrappers.
"""

from curl_cffi import requests as curl_requests
import asyncio
import logging
import time
import random
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_OPTION_CHAIN_PAGE = "https://www.nseindia.com/option-chain"
NSE_OPTION_CHAIN_API = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
NSE_ALL_INDICES = "https://www.nseindia.com/api/allIndices"


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
    """Handles all data fetching from NSE India using curl_cffi.

    curl_cffi impersonates Chrome's TLS fingerprint at the handshake level,
    which bypasses Akamai Bot Manager's deep TLS fingerprinting that blocks
    both httpx and requests.

    Session flow:
    1. Create curl_cffi session with impersonate="chrome131"
    2. GET homepage → acquire cookies (nseappid, nsit, ak_bmsc, etc.)
    3. GET option-chain page → warm session
    4. GET API endpoints → get JSON data

    All public methods are async (via asyncio.to_thread).
    """

    def __init__(self):
        self._session: Optional[curl_requests.Session] = None
        self._cookies_valid = False
        self._session_init_count = 0
        self._last_fetch: Optional[datetime] = None
        self._cached_snapshot: Optional[MarketSnapshot] = None
        self._last_expiry_dates: List[str] = []
        self._last_selected_expiry: str = ""

    def _create_session(self) -> curl_requests.Session:
        """Create a fresh curl_cffi session impersonating Chrome 131."""
        if self._session:
            self._session.close()

        self._session = curl_requests.Session(impersonate="chrome131")
        self._cookies_valid = False
        return self._session

    def _get_session(self) -> curl_requests.Session:
        if self._session is None:
            return self._create_session()
        return self._session

    def _init_session_sync(self) -> bool:
        """Session initialization: homepage → option-chain page."""
        self._session_init_count += 1

        if self._session_init_count > 3:
            logger.warning("Multiple session init failures, creating fresh session...")
            self._create_session()
            self._session_init_count = 1

        try:
            session = self._get_session()

            # Step 1: Hit the homepage to get cookies
            resp = session.get(NSE_BASE, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"NSE homepage returned {resp.status_code}")
                return False

            cookie_names = [c.name for c in session.cookies]
            logger.info(f"NSE homepage OK, cookies: {cookie_names}")

            # Small delay to mimic human behavior
            time.sleep(random.uniform(0.5, 1.5))

            # Step 2: Visit the option-chain page
            resp = session.get(NSE_OPTION_CHAIN_PAGE, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"NSE option-chain page returned {resp.status_code}")
            else:
                logger.info("NSE option-chain page OK, session warmed.")

            time.sleep(random.uniform(0.3, 0.8))

            self._cookies_valid = True
            self._session_init_count = 0
            return True

        except Exception as e:
            logger.error(f"Failed to initialize NSE session: {e}")
            return False

    def _fetch_json_sync(self, url: str, retries: int = 3) -> Optional[Dict]:
        """Fetch JSON from NSE API with retry logic."""
        session = self._get_session()

        for attempt in range(retries):
            if not self._cookies_valid:
                if not self._init_session_sync():
                    wait = 2 ** attempt + random.uniform(0, 1)
                    logger.info(f"Session init failed, waiting {wait:.1f}s...")
                    time.sleep(wait)
                    continue

            try:
                resp = session.get(url, timeout=15)

                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" not in content_type and "javascript" not in content_type:
                        logger.warning(
                            f"NSE returned non-JSON Content-Type: {content_type} "
                            f"(first 200 chars: {resp.text[:200]})"
                        )

                    try:
                        data = resp.json()
                        if isinstance(data, dict) and data:
                            return data
                        else:
                            logger.warning(
                                f"NSE returned empty/invalid JSON from {url}: "
                                f"type={type(data).__name__}, "
                                f"keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}"
                            )
                    except ValueError as e:
                        logger.error(
                            f"JSON decode failed for {url}: {e} "
                            f"(first 300 chars: {resp.text[:300]})"
                        )

                    self._cookies_valid = False
                    time.sleep(1 + random.uniform(0, 1))
                    continue

                elif resp.status_code in (401, 403):
                    logger.warning(
                        f"NSE API returned {resp.status_code} on attempt {attempt + 1}, "
                        "re-initializing session..."
                    )
                    self._cookies_valid = False
                    time.sleep(1 + random.uniform(0, 1))
                    continue
                else:
                    logger.warning(f"NSE API {url} returned {resp.status_code}")

            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")

            time.sleep(2 ** attempt + random.uniform(0, 1))

        return None

    def _fetch_option_chain_sync(self, expiry: Optional[str] = None) -> Dict[float, OptionChainRow]:
        """Synchronous option chain fetch."""
        data = self._fetch_json_sync(NSE_OPTION_CHAIN_API)
        if not data:
            logger.error("Failed to fetch option chain data")
            return {}

        records = data.get("records", {})
        underlying_value = records.get("underlyingValue", 0.0)
        expiry_dates = records.get("expiryDates", [])
        all_data = records.get("data", [])

        target_expiry = expiry or (expiry_dates[0] if expiry_dates else None)

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

        logger.info(f"Option chain: {len(chain)} strikes loaded for expiry {target_expiry}")
        return chain

    def _fetch_indices_sync(self) -> Dict[str, Dict[str, Any]]:
        """Synchronous indices fetch."""
        data = self._fetch_json_sync(NSE_ALL_INDICES)
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

    def _fetch_full_snapshot_sync(self, expiry: Optional[str] = None) -> MarketSnapshot:
        """Synchronous full snapshot fetch."""
        snapshot = MarketSnapshot()

        try:
            if not self._cookies_valid:
                if not self._init_session_sync():
                    logger.error("Could not establish NSE session")
                    if self._cached_snapshot:
                        self._cached_snapshot.is_stale = True
                        return self._cached_snapshot
                    snapshot.error = "Could not establish NSE session"
                    return snapshot

            chain = self._fetch_option_chain_sync(expiry)
            snapshot.option_chain = chain
            snapshot.expiry_dates = self._last_expiry_dates
            snapshot.selected_expiry = self._last_selected_expiry

            time.sleep(random.uniform(0.5, 1.0))

            indices = self._fetch_indices_sync()
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

    # ── Async wrappers (called by FastAPI / app.py) ─────────────────────

    async def fetch_option_chain(self, expiry: Optional[str] = None) -> Dict[float, OptionChainRow]:
        return await asyncio.to_thread(self._fetch_option_chain_sync, expiry)

    async def fetch_indices(self) -> Dict[str, Dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_indices_sync)

    async def fetch_full_snapshot(self, expiry: Optional[str] = None) -> MarketSnapshot:
        return await asyncio.to_thread(self._fetch_full_snapshot_sync, expiry)

    async def close(self):
        """Close the HTTP session."""
        if self._session:
            self._session.close()


# Singleton instance
_fetcher: Optional[NSEDataFetcher] = None


def get_fetcher() -> NSEDataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = NSEDataFetcher()
    return _fetcher
