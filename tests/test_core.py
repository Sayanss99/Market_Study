"""
Core tests for the Nifty Options Dashboard modules.
"""

import math
import sys
import os
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_expected_move_calculation():
    """Test the VIX-based expected move formula."""
    from backend.modules.market_utils import calculate_expected_move

    # Example from spec: Nifty 24200, VIX 14.5, 5 days
    move = calculate_expected_move(24200, 14.5, 5)
    # Expected: ~494
    assert 480 <= move <= 510, f"Expected ~494, got {move}"


def test_round_to_100():
    """Test rounding to nearest 100."""
    from backend.modules.market_utils import round_to_100

    assert round_to_100(24694, "up") == 24700
    assert round_to_100(23706, "down") == 23700
    assert round_to_100(24500, "up") == 24500
    assert round_to_100(24550, "up") == 24600
    assert round_to_100(24550, "down") == 24500


def test_ensure_ends_in_00():
    """Test strike ending validation."""
    from backend.modules.market_utils import ensure_ends_in_00

    assert ensure_ends_in_00(24900) == 24900  # Already 00
    assert ensure_ends_in_00(24950, "further") == 25000  # 50 -> round up
    assert ensure_ends_in_00(23500) == 23500  # Already 00
    assert ensure_ends_in_00(23550, "further") == 23600


def test_greeks_calculator_call():
    """Test Black-Scholes call option Greeks."""
    from backend.modules.greeks_calculator import calculate_greeks

    # ATM call: spot=24000, strike=24000, 5 days, IV=15%
    greeks = calculate_greeks(
        spot=24000, strike=24000,
        time_to_expiry_years=5 / 365, iv=0.15, option_type="CE"
    )

    # Delta of ATM call should be around 0.5
    assert 0.45 < greeks.delta < 0.55, f"ATM call delta should be ~0.5, got {greeks.delta}"
    # Gamma should be positive
    assert greeks.gamma > 0
    # Theta should be negative
    assert greeks.theta < 0
    # Vega should be positive
    assert greeks.vega > 0


def test_greeks_calculator_put():
    """Test Black-Scholes put option Greeks."""
    from backend.modules.greeks_calculator import calculate_greeks

    # ATM put: spot=24000, strike=24000, 5 days, IV=15%
    greeks = calculate_greeks(
        spot=24000, strike=24000,
        time_to_expiry_years=5 / 365, iv=0.15, option_type="PE"
    )

    # Delta of ATM put should be around -0.5
    assert -0.55 < greeks.delta < -0.45, f"ATM put delta should be ~-0.5, got {greeks.delta}"


def test_greeks_far_otm():
    """Test Greeks for far OTM options."""
    from backend.modules.greeks_calculator import calculate_greeks

    # Far OTM CE: spot=24000, strike=25000, 5 days, IV=18%
    greeks = calculate_greeks(
        spot=24000, strike=25000,
        time_to_expiry_years=5 / 365, iv=0.18, option_type="CE"
    )

    # Delta should be small (far OTM)
    assert abs(greeks.delta) < 0.15, f"Far OTM delta should be small, got {greeks.delta}"


def test_risk_scoring():
    """Test risk engine scoring functions."""
    from backend.modules.risk_engine import _score_delta, _score_iv_change, _score_premium

    # Delta scores
    score, status = _score_delta(0.05)
    assert status == "OK"
    assert score < 30

    score, status = _score_delta(0.20)
    assert status == "WARNING"
    assert 30 <= score < 50

    score, status = _score_delta(0.30)
    assert status == "DANGER"
    assert 50 <= score < 70

    score, status = _score_delta(0.40)
    assert status == "CRITICAL"
    assert score >= 70

    # IV scores
    score, status = _score_iv_change(10)
    assert status == "OK"

    score, status = _score_iv_change(50)
    assert status == "DANGER"

    # Premium scores
    score, status = _score_premium(1.5)
    assert status == "OK"

    score, status = _score_premium(3.5)
    assert status == "DANGER"


def test_weekly_expiry():
    """Test weekly expiry calculation."""
    from backend.modules.market_utils import get_next_weekly_expiry

    # Test with a known Monday
    monday = date(2026, 3, 16)
    expiry = get_next_weekly_expiry(monday)
    # Should be Tuesday March 17
    assert expiry.weekday() <= 1, f"Expiry should be Mon or Tue, got weekday {expiry.weekday()}"
    assert expiry >= monday, "Expiry should be on or after the from_date"


def test_strike_suggestion_structure():
    """Test that StrikeSuggestion has all required fields."""
    from backend.modules.strike_suggestion import StrikeSuggestion

    s = StrikeSuggestion()
    assert s.ce_strike == 0
    assert s.pe_strike == 0
    assert isinstance(s.validation_notes, list)


def test_position_creation():
    """Test trade manager position creation."""
    from backend.modules.trade_manager import TradeManager
    from backend.modules.strike_suggestion import StrikeSuggestion

    tm = TradeManager()
    suggestion = StrikeSuggestion(
        ce_strike=25000,
        pe_strike=23000,
        ce_ltp=30.0,
        pe_ltp=25.0,
        ce_iv=18.0,
        pe_iv=19.0,
        ce_delta=0.07,
        pe_delta=-0.06,
        ce_theta=-28.0,
        pe_theta=-25.0,
        nifty_cmp=24000,
        india_vix=14.0,
        expected_move=450,
        upper_range=24450,
        lower_range=23550,
        days_to_expiry=5,
        expiry_date="17-Mar-2026",
    )

    pos = tm.create_position(
        suggestion=suggestion,
        ce_lots=10,
        ce_premium=30.0,
        pe_lots=10,
        pe_premium=25.0,
        lot_size=65,
    )

    assert pos.ce_strike == 25000
    assert pos.pe_strike == 23000
    assert pos.ce_qty == 650
    assert pos.pe_qty == 650
    assert pos.total_premium_collected == (30.0 * 650) + (25.0 * 650)
    assert pos.status == "ACTIVE"


def test_hedge_calculation_no_threat():
    """Test hedge calculator when no side is threatened."""
    from backend.modules.hedge_calculator import calculate_hedge
    from backend.modules.risk_engine import PositionRisk, RiskBreakdown

    risk = PositionRisk(
        ce_risk=RiskBreakdown(composite_score=20, severity="SAFE"),
        pe_risk=RiskBreakdown(composite_score=25, severity="SAFE"),
        overall_risk=25,
        threatened_side=None,
    )

    hedge = calculate_hedge(
        position_risk=risk,
        ce_strike=25000,
        pe_strike=23000,
        ce_entry_premium=30.0,
        pe_entry_premium=25.0,
        ce_lots=10,
        pe_lots=10,
        current_spot=24000,
        entry_spot=24000,
        chain={},
    )

    assert not hedge.is_needed


if __name__ == "__main__":
    tests = [
        test_expected_move_calculation,
        test_round_to_100,
        test_ensure_ends_in_00,
        test_greeks_calculator_call,
        test_greeks_calculator_put,
        test_greeks_far_otm,
        test_risk_scoring,
        test_weekly_expiry,
        test_strike_suggestion_structure,
        test_position_creation,
        test_hedge_calculation_no_threat,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__} — {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    sys.exit(1 if failed > 0 else 0)
