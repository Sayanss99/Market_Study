"""
Market Utilities
Handles Nifty expiry calculations, market hours detection,
and other Indian market-specific utility functions.
"""

import math
from datetime import datetime, date, timedelta
from typing import List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")

# Known NSE holidays for 2026 (update annually)
# Source: NSE circular on trading holidays
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 17),  # Mahashivratri (example)
    date(2026, 3, 10),  # Holi (example)
    date(2026, 3, 30),  # Id-ul-Fitr (example)
    date(2026, 4, 2),   # Ram Navami (example)
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 25),  # Buddha Purnima (example)
    date(2026, 6, 5),   # Id-ul-Adha (Bakrid) (example)
    date(2026, 7, 6),   # Muharram (example)
    date(2026, 8, 15),  # Independence Day
    date(2026, 9, 4),   # Milad-un-Nabi (example)
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra (example)
    date(2026, 11, 9),  # Diwali (Laxmi Pujan) (example)
    date(2026, 11, 10), # Diwali (Balipratipada) (example)
    date(2026, 11, 30), # Guru Nanak Jayanti (example)
    date(2026, 12, 25), # Christmas
}


def is_market_holiday(d: date) -> bool:
    """Check if a date is a market holiday or weekend."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return True
    return d in NSE_HOLIDAYS_2026


def is_trading_day(d: date) -> bool:
    """Check if a date is a valid trading day."""
    return not is_market_holiday(d)


def get_previous_trading_day(d: date) -> date:
    """Get the most recent trading day on or before the given date."""
    while is_market_holiday(d):
        d -= timedelta(days=1)
    return d


def get_next_weekly_expiry(from_date: Optional[date] = None) -> date:
    """
    Calculate the next Nifty weekly expiry date.
    Nifty weekly options expire every Tuesday.
    If Tuesday is a holiday, expiry shifts to the previous trading day.
    """
    if from_date is None:
        from_date = datetime.now(IST).date()

    # Find the next Tuesday (weekday=1)
    days_until_tuesday = (1 - from_date.weekday()) % 7
    if days_until_tuesday == 0:
        # Today is Tuesday — check if market is still open
        now = datetime.now(IST)
        if now.hour < 15 or (now.hour == 15 and now.minute < 30):
            # Market still open, this Tuesday is the expiry
            next_tuesday = from_date
        else:
            # Market closed, move to next Tuesday
            next_tuesday = from_date + timedelta(days=7)
    else:
        next_tuesday = from_date + timedelta(days=days_until_tuesday)

    # If Tuesday is a holiday, shift to previous trading day
    if is_market_holiday(next_tuesday):
        return get_previous_trading_day(next_tuesday)

    return next_tuesday


def days_to_expiry(expiry_date: Optional[date] = None) -> int:
    """Calculate calendar days from today to expiry."""
    if expiry_date is None:
        expiry_date = get_next_weekly_expiry()
    today = datetime.now(IST).date()
    delta = (expiry_date - today).days
    return max(delta, 1)  # At least 1 day


def calculate_expected_move(nifty_cmp: float, vix: float, days: int) -> int:
    """
    Calculate the VIX-based expected move for Nifty.
    Formula: Nifty_CMP * (VIX / sqrt(252 / days)) / 100
    """
    if days <= 0 or vix <= 0:
        return 0
    move = nifty_cmp * (vix / math.sqrt(252 / days)) / 100
    return round(move)


def round_to_100(value: float, direction: str = "nearest") -> int:
    """
    Round a value to the nearest strike ending in '00'.
    direction: 'up' for CEILING, 'down' for FLOOR, 'nearest' for rounding
    """
    if direction == "up":
        return int(math.ceil(value / 100) * 100)
    elif direction == "down":
        return int(math.floor(value / 100) * 100)
    else:
        return int(round(value / 100) * 100)


def ensure_ends_in_00(strike: int, direction_otm: str = "further") -> int:
    """
    Ensure strike ends in '00'. Nifty strikes come in intervals of 50.
    If it ends in '50', adjust based on direction.
    direction_otm: 'further' moves further OTM, 'closer' moves closer to spot
    For CE: 'further' means higher strike
    For PE: 'further' means lower strike
    """
    if strike % 100 == 0:
        return strike
    if direction_otm == "further":
        # For CE: round up; For PE: round down
        # Caller should handle CE vs PE distinction
        return round_to_100(strike, "up")
    else:
        return round_to_100(strike, "down")


def days_to_years(days: int) -> float:
    """Convert calendar days to fraction of year."""
    return days / 365.0


def is_market_open() -> bool:
    """Check if the Indian stock market is currently open."""
    now = datetime.now(IST)
    today = now.date()

    if is_market_holiday(today):
        return False

    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    return market_open <= now <= market_close


def is_pre_market() -> bool:
    """Check if we're in pre-market hours (9:00 - 9:15 IST)."""
    now = datetime.now(IST)
    today = now.date()

    if is_market_holiday(today):
        return False

    pre_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)

    return pre_open <= now < market_open


def get_nearest_support_resistance(
    current_price: float,
    sold_strike: float,
    levels: List[int],
    side: str = "PE",
) -> int:
    """
    Find the next significant support/resistance level beyond the sold strike.
    For PE threat (market falling): find support below the sold strike.
    For CE threat (market rising): find resistance above the sold strike.
    """
    if side == "PE":
        # Market is falling — find support below sold PE strike
        below = [lvl for lvl in levels if lvl < sold_strike]
        if below:
            return max(below)  # Nearest support below
        return int(sold_strike - 200)  # Default fallback
    else:
        # Market is rising — find resistance above sold CE strike
        above = [lvl for lvl in levels if lvl > sold_strike]
        if above:
            return min(above)  # Nearest resistance above
        return int(sold_strike + 200)  # Default fallback
