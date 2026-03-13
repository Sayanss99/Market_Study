"""
Strike Suggestion Engine
VIX-based range calculation, delta-balanced strike selection,
and premium validation for weekly Nifty options selling.
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from config.settings import settings
from backend.modules.market_utils import (
    calculate_expected_move,
    days_to_expiry,
    days_to_years,
    get_next_weekly_expiry,
    round_to_100,
)
from backend.modules.greeks_calculator import calculate_greeks, Greeks
from backend.modules.data_fetcher import OptionChainRow, MarketSnapshot

logger = logging.getLogger(__name__)


@dataclass
class StrikeSuggestion:
    """Complete strike suggestion with all relevant data."""
    ce_strike: int = 0
    pe_strike: int = 0
    ce_ltp: float = 0.0
    pe_ltp: float = 0.0
    ce_iv: float = 0.0
    pe_iv: float = 0.0
    ce_delta: float = 0.0
    pe_delta: float = 0.0
    ce_theta: float = 0.0
    pe_theta: float = 0.0
    ce_gamma: float = 0.0
    pe_gamma: float = 0.0
    nifty_cmp: float = 0.0
    india_vix: float = 0.0
    expected_move: int = 0
    upper_range: float = 0.0
    lower_range: float = 0.0
    days_to_expiry: int = 0
    expiry_date: str = ""
    validation_notes: list = None

    def __post_init__(self):
        if self.validation_notes is None:
            self.validation_notes = []


def _get_option_data_at_strike(
    chain: Dict[float, OptionChainRow],
    strike: int,
    side: str,
) -> Tuple[float, float]:
    """Get LTP and IV for a specific strike and side from the option chain."""
    row = chain.get(float(strike))
    if row is None:
        return 0.0, 0.0

    opt = row.ce if side == "CE" else row.pe
    if opt is None:
        return 0.0, 0.0

    return opt.ltp, opt.iv


def _compute_greeks_for_strike(
    spot: float, strike: int, iv_pct: float, dte: int, side: str
) -> Greeks:
    """Compute Black-Scholes Greeks for a given strike."""
    iv_decimal = iv_pct / 100.0 if iv_pct > 1 else iv_pct
    T = days_to_years(dte)
    return calculate_greeks(spot, strike, T, iv_decimal, side)


def _find_delta_matched_strike(
    chain: Dict[float, OptionChainRow],
    spot: float,
    target_delta: float,
    dte: int,
    side: str,
    start_strike: int,
) -> Tuple[int, float, float, Greeks]:
    """
    Scan strikes to find one whose |delta| matches target_delta.
    Returns (strike, ltp, iv, greeks).
    """
    best_strike = start_strike
    best_diff = float("inf")
    best_ltp = 0.0
    best_iv = 0.0
    best_greeks = Greeks(0, 0, 0, 0, 0)

    # Determine scan direction and range
    if side == "PE":
        # Scan downward for PE (further OTM = lower strikes)
        strikes_to_check = sorted(
            [s for s in chain.keys() if s <= start_strike and s % 100 == 0],
            reverse=True,
        )
    else:
        # Scan upward for CE (further OTM = higher strikes)
        strikes_to_check = sorted(
            [s for s in chain.keys() if s >= start_strike and s % 100 == 0]
        )

    for strike_f in strikes_to_check:
        strike = int(strike_f)
        ltp, iv = _get_option_data_at_strike(chain, strike, side)

        if iv <= 0:
            continue

        greeks = _compute_greeks_for_strike(spot, strike, iv, dte, side)
        abs_delta = abs(greeks.delta)

        diff = abs(abs_delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike
            best_ltp = ltp
            best_iv = iv
            best_greeks = greeks

        # If we've passed the target and diff is increasing, stop
        if diff > best_diff and best_diff < 0.02:
            break

    return best_strike, best_ltp, best_iv, best_greeks


def generate_suggestion(snapshot: MarketSnapshot) -> StrikeSuggestion:
    """
    Generate a complete strike suggestion based on current market data.
    Implements the full 5-step validation process.
    """
    suggestion = StrikeSuggestion()
    chain = snapshot.option_chain

    if not chain or snapshot.nifty_spot <= 0 or snapshot.india_vix <= 0:
        suggestion.validation_notes.append("Insufficient market data for suggestion")
        return suggestion

    spot = snapshot.nifty_spot
    vix = snapshot.india_vix
    expiry = get_next_weekly_expiry()
    dte = days_to_expiry(expiry)

    suggestion.nifty_cmp = spot
    suggestion.india_vix = vix
    suggestion.days_to_expiry = dte
    suggestion.expiry_date = expiry.strftime("%d-%b-%Y")

    # ── Step 1: Calculate Expected Move ──
    expected_move = calculate_expected_move(spot, vix, dte)
    upper_range = spot + expected_move
    lower_range = spot - expected_move

    suggestion.expected_move = expected_move
    suggestion.upper_range = upper_range
    suggestion.lower_range = lower_range

    # ── Step 2: Initial Strike Selection (150-200 pts away from range) ──
    offset = settings.strike_offset

    raw_ce = round_to_100(upper_range, "up") + offset
    raw_pe = round_to_100(lower_range, "down") - offset

    # Ensure strikes end in '00'
    if raw_ce % 100 != 0:
        raw_ce = round_to_100(raw_ce, "up")
    if raw_pe % 100 != 0:
        raw_pe = round_to_100(raw_pe, "down")

    ce_strike = int(raw_ce)
    pe_strike = int(raw_pe)

    suggestion.validation_notes.append(
        f"Initial: CE={ce_strike}, PE={pe_strike} "
        f"(Range: {lower_range:.0f}-{upper_range:.0f}, Offset: {offset})"
    )

    # ── Step 3: Delta Balancing via IV Comparison ──
    ce_ltp, ce_iv = _get_option_data_at_strike(chain, ce_strike, "CE")
    pe_ltp, pe_iv = _get_option_data_at_strike(chain, pe_strike, "PE")

    ce_greeks = _compute_greeks_for_strike(spot, ce_strike, ce_iv, dte, "CE")
    pe_greeks = _compute_greeks_for_strike(spot, pe_strike, pe_iv, dte, "PE")

    # Determine anchor side (lower IV = anchor)
    if ce_iv > 0 and pe_iv > 0:
        if ce_iv <= pe_iv:
            # CE is anchor — match PE delta to CE delta
            anchor_side = "CE"
            anchor_delta = abs(ce_greeks.delta)

            pe_strike, pe_ltp, pe_iv, pe_greeks = _find_delta_matched_strike(
                chain, spot, anchor_delta, dte, "PE", pe_strike
            )
            suggestion.validation_notes.append(
                f"Delta balance: CE anchor (IV={ce_iv:.1f}), "
                f"PE adjusted to {pe_strike} (delta={pe_greeks.delta:.4f})"
            )
        else:
            # PE is anchor — match CE delta to PE delta
            anchor_side = "PE"
            anchor_delta = abs(pe_greeks.delta)

            ce_strike, ce_ltp, ce_iv, ce_greeks = _find_delta_matched_strike(
                chain, spot, anchor_delta, dte, "CE", ce_strike
            )
            suggestion.validation_notes.append(
                f"Delta balance: PE anchor (IV={pe_iv:.1f}), "
                f"CE adjusted to {ce_strike} (delta={ce_greeks.delta:.4f})"
            )
    else:
        suggestion.validation_notes.append("IV data missing, skipping delta balance")

    # Validate max delta constraint
    if abs(ce_greeks.delta) > settings.max_delta:
        suggestion.validation_notes.append(
            f"WARNING: CE delta {ce_greeks.delta:.4f} exceeds max {settings.max_delta}"
        )
    if abs(pe_greeks.delta) > settings.max_delta:
        suggestion.validation_notes.append(
            f"WARNING: PE delta {pe_greeks.delta:.4f} exceeds max {settings.max_delta}"
        )

    # ── Step 4: Premium Range Validation (only if DTE >= 7) ──
    if dte >= 7:
        min_p = settings.min_premium_gte7
        max_p = settings.max_premium_gte7

        # Adjust CE if premium out of range
        ce_strike, ce_ltp, ce_iv, ce_greeks = _adjust_for_premium(
            chain, spot, ce_strike, ce_ltp, ce_iv, dte, "CE", min_p, max_p
        )

        # Adjust PE if premium out of range
        pe_strike, pe_ltp, pe_iv, pe_greeks = _adjust_for_premium(
            chain, spot, pe_strike, pe_ltp, pe_iv, dte, "PE", min_p, max_p
        )

        suggestion.validation_notes.append(
            f"Premium check (DTE={dte}): CE LTP=₹{ce_ltp:.2f}, PE LTP=₹{pe_ltp:.2f}"
        )

    # ── Step 5: Final Suggestion ──
    suggestion.ce_strike = ce_strike
    suggestion.pe_strike = pe_strike
    suggestion.ce_ltp = ce_ltp
    suggestion.pe_ltp = pe_ltp
    suggestion.ce_iv = ce_iv
    suggestion.pe_iv = pe_iv
    suggestion.ce_delta = ce_greeks.delta
    suggestion.pe_delta = pe_greeks.delta
    suggestion.ce_theta = ce_greeks.theta
    suggestion.pe_theta = pe_greeks.theta
    suggestion.ce_gamma = ce_greeks.gamma
    suggestion.pe_gamma = pe_greeks.gamma

    return suggestion


def _adjust_for_premium(
    chain: Dict[float, OptionChainRow],
    spot: float,
    strike: int,
    ltp: float,
    iv: float,
    dte: int,
    side: str,
    min_premium: float,
    max_premium: float,
) -> Tuple[int, float, float, Greeks]:
    """
    Adjust strike to bring premium within the acceptable range.
    Moves further OTM if premium > max, closer if premium < min.
    Always maintains '00' ending.
    """
    original_strike = strike
    step = 100  # Move in increments of 100

    for _ in range(20):  # Max 20 adjustments
        if min_premium <= ltp <= max_premium:
            break

        if ltp > max_premium:
            # Move further OTM
            if side == "CE":
                strike += step
            else:
                strike -= step
        elif ltp < min_premium and ltp > 0:
            # Move closer to spot
            if side == "CE":
                strike -= step
            else:
                strike += step

        # Ensure ends in 00
        if strike % 100 != 0:
            if side == "CE":
                strike = round_to_100(strike, "up")
            else:
                strike = round_to_100(strike, "down")

        ltp, iv = _get_option_data_at_strike(chain, strike, side)
        if ltp <= 0:
            # No data at this strike, revert
            strike = original_strike
            ltp, iv = _get_option_data_at_strike(chain, strike, side)
            break

    greeks = _compute_greeks_for_strike(spot, strike, iv, dte, side)
    return strike, ltp, iv, greeks


