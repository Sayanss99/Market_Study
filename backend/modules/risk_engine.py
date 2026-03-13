"""
Risk Monitor & Severity Engine
Continuously monitors open positions for risk indicators:
Delta drift, IV surge, premium blowup, spot proximity, and theta decay.
Computes a composite risk score (0-100) for each side (CE and PE).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings
from backend.modules.greeks_calculator import calculate_greeks, Greeks
from backend.modules.market_utils import days_to_years

logger = logging.getLogger(__name__)


@dataclass
class RiskBreakdown:
    """Detailed breakdown of risk indicators for one side."""
    delta_current: float = 0.0
    delta_at_entry: float = 0.0
    delta_score: float = 0.0
    delta_status: str = "OK"

    iv_current: float = 0.0
    iv_at_entry: float = 0.0
    iv_change_pct: float = 0.0
    iv_score: float = 0.0
    iv_status: str = "OK"

    premium_current: float = 0.0
    premium_at_entry: float = 0.0
    premium_multiple: float = 0.0
    premium_score: float = 0.0
    premium_status: str = "OK"

    spot_current: float = 0.0
    spot_at_entry: float = 0.0
    strike: float = 0.0
    spot_distance_pts: float = 0.0
    proximity_pct: float = 0.0
    proximity_score: float = 0.0
    proximity_status: str = "OK"

    theta_expected: float = 0.0
    theta_actual_decay: float = 0.0
    theta_score: float = 0.0
    theta_status: str = "OK"

    composite_score: float = 0.0
    severity: str = "SAFE"  # SAFE, WARNING, DANGER, CRITICAL


@dataclass
class PositionRisk:
    """Risk assessment for a complete position (both CE and PE sides)."""
    ce_risk: RiskBreakdown = field(default_factory=RiskBreakdown)
    pe_risk: RiskBreakdown = field(default_factory=RiskBreakdown)
    overall_risk: float = 0.0
    threatened_side: Optional[str] = None  # "CE", "PE", or None


def _score_delta(abs_delta: float) -> tuple:
    """Score delta risk on 0-100 scale."""
    if abs_delta >= settings.delta_critical:
        return min(100, 70 + (abs_delta - settings.delta_critical) * 100), "CRITICAL"
    elif abs_delta >= settings.delta_danger:
        return 50 + (abs_delta - settings.delta_danger) / (settings.delta_critical - settings.delta_danger) * 20, "DANGER"
    elif abs_delta >= settings.delta_warning:
        return 30 + (abs_delta - settings.delta_warning) / (settings.delta_danger - settings.delta_warning) * 20, "WARNING"
    else:
        return abs_delta / settings.delta_warning * 30, "OK"


def _score_iv_change(iv_change_pct: float) -> tuple:
    """Score IV change risk on 0-100 scale."""
    if iv_change_pct >= settings.iv_critical_pct:
        return min(100, 70 + (iv_change_pct - settings.iv_critical_pct) / 40 * 30), "CRITICAL"
    elif iv_change_pct >= settings.iv_danger_pct:
        return 50 + (iv_change_pct - settings.iv_danger_pct) / (settings.iv_critical_pct - settings.iv_danger_pct) * 20, "DANGER"
    elif iv_change_pct >= settings.iv_warning_pct:
        return 30 + (iv_change_pct - settings.iv_warning_pct) / (settings.iv_danger_pct - settings.iv_warning_pct) * 20, "WARNING"
    else:
        return max(0, iv_change_pct / settings.iv_warning_pct * 30), "OK"


def _score_premium(multiple: float) -> tuple:
    """Score premium blowup risk on 0-100 scale."""
    if multiple >= settings.premium_critical_mult:
        return min(100, 70 + (multiple - settings.premium_critical_mult) * 10), "CRITICAL"
    elif multiple >= settings.premium_danger_mult:
        return 50 + (multiple - settings.premium_danger_mult) / (settings.premium_critical_mult - settings.premium_danger_mult) * 20, "DANGER"
    elif multiple >= settings.premium_warning_mult:
        return 30 + (multiple - settings.premium_warning_mult) / (settings.premium_danger_mult - settings.premium_warning_mult) * 20, "WARNING"
    else:
        return max(0, multiple / settings.premium_warning_mult * 30), "OK"


def _score_proximity(
    spot: float,
    strike: float,
    entry_spot: float,
    side: str,
) -> tuple:
    """Score spot proximity risk on 0-100 scale."""
    # Distance from entry spot to strike
    total_distance = abs(strike - entry_spot)
    if total_distance == 0:
        return 100, "CRITICAL"

    # How much of that distance has been consumed
    if side == "CE":
        consumed = max(0, spot - entry_spot)
    else:
        consumed = max(0, entry_spot - spot)

    proximity_pct = (consumed / total_distance) * 100
    remaining_pts = abs(strike - spot)

    if remaining_pts <= settings.proximity_critical_pts:
        return 100, "CRITICAL"
    elif proximity_pct >= settings.proximity_danger_pct:
        return 70 + (proximity_pct - settings.proximity_danger_pct) / (100 - settings.proximity_danger_pct) * 30, "DANGER"
    elif proximity_pct >= settings.proximity_warning_pct:
        return 40 + (proximity_pct - settings.proximity_warning_pct) / (settings.proximity_danger_pct - settings.proximity_warning_pct) * 30, "WARNING"
    else:
        return max(0, proximity_pct / settings.proximity_warning_pct * 40), "OK"


def _score_theta(theta_expected: float, actual_decay: float) -> tuple:
    """
    Score theta decay efficiency.
    If actual decay is slower than expected (premium not decaying as fast as theta predicts),
    it could indicate risk.
    """
    if theta_expected == 0:
        return 0, "OK"

    # actual_decay = entry_premium - current_premium (positive if decaying)
    # theta_expected = cumulative theta * days passed (should be positive)
    if theta_expected > 0:
        efficiency = actual_decay / theta_expected
    else:
        efficiency = 1.0  # Theta is tiny

    if efficiency < 0:
        # Premium increased instead of decaying
        return min(100, 80), "CRITICAL"
    elif efficiency < 0.3:
        return 60, "DANGER"
    elif efficiency < 0.6:
        return 40, "WARNING"
    else:
        return max(0, (1 - efficiency) * 30), "OK"


def calculate_risk(
    side: str,
    strike: float,
    entry_premium: float,
    current_premium: float,
    entry_iv: float,
    current_iv: float,
    entry_delta: float,
    current_delta: float,
    entry_spot: float,
    current_spot: float,
    entry_theta: float = 0.0,
    days_held: int = 1,
) -> RiskBreakdown:
    """
    Calculate comprehensive risk breakdown for one side of a position.
    """
    risk = RiskBreakdown()

    # 1. Delta Drift
    risk.delta_current = current_delta
    risk.delta_at_entry = entry_delta
    abs_delta = abs(current_delta)
    risk.delta_score, risk.delta_status = _score_delta(abs_delta)

    # 2. IV Surge
    risk.iv_current = current_iv
    risk.iv_at_entry = entry_iv
    if entry_iv > 0:
        risk.iv_change_pct = ((current_iv - entry_iv) / entry_iv) * 100
    else:
        risk.iv_change_pct = 0.0
    risk.iv_score, risk.iv_status = _score_iv_change(max(0, risk.iv_change_pct))

    # 3. Premium Blowup
    risk.premium_current = current_premium
    risk.premium_at_entry = entry_premium
    if entry_premium > 0:
        risk.premium_multiple = current_premium / entry_premium
    else:
        risk.premium_multiple = 0.0
    risk.premium_score, risk.premium_status = _score_premium(risk.premium_multiple)

    # 4. Spot Proximity
    risk.spot_current = current_spot
    risk.spot_at_entry = entry_spot
    risk.strike = strike
    risk.spot_distance_pts = abs(strike - current_spot)
    risk.proximity_score, risk.proximity_status = _score_proximity(
        current_spot, strike, entry_spot, side
    )

    # 5. Theta Decay
    risk.theta_expected = abs(entry_theta) * days_held if entry_theta else 0.0
    risk.theta_actual_decay = entry_premium - current_premium
    risk.theta_score, risk.theta_status = _score_theta(
        risk.theta_expected, risk.theta_actual_decay
    )

    # Composite Score
    risk.composite_score = (
        settings.risk_weight_delta * risk.delta_score
        + settings.risk_weight_iv * risk.iv_score
        + settings.risk_weight_premium * risk.premium_score
        + settings.risk_weight_proximity * risk.proximity_score
        + settings.risk_weight_theta * risk.theta_score
    )
    risk.composite_score = min(100, max(0, risk.composite_score))

    # Severity classification
    if risk.composite_score >= settings.risk_critical_threshold:
        risk.severity = "CRITICAL"
    elif risk.composite_score >= settings.risk_danger_threshold:
        risk.severity = "DANGER"
    elif risk.composite_score >= settings.risk_warning_threshold:
        risk.severity = "WARNING"
    else:
        risk.severity = "SAFE"

    return risk


def assess_position_risk(
    ce_strike: float,
    pe_strike: float,
    ce_entry_premium: float,
    pe_entry_premium: float,
    ce_current_premium: float,
    pe_current_premium: float,
    ce_entry_iv: float,
    pe_entry_iv: float,
    ce_current_iv: float,
    pe_current_iv: float,
    ce_entry_delta: float,
    pe_entry_delta: float,
    ce_current_delta: float,
    pe_current_delta: float,
    entry_spot: float,
    current_spot: float,
    ce_entry_theta: float = 0.0,
    pe_entry_theta: float = 0.0,
    days_held: int = 1,
) -> PositionRisk:
    """Assess risk for a complete straddle/strangle position."""
    pos_risk = PositionRisk()

    pos_risk.ce_risk = calculate_risk(
        side="CE",
        strike=ce_strike,
        entry_premium=ce_entry_premium,
        current_premium=ce_current_premium,
        entry_iv=ce_entry_iv,
        current_iv=ce_current_iv,
        entry_delta=ce_entry_delta,
        current_delta=ce_current_delta,
        entry_spot=entry_spot,
        current_spot=current_spot,
        entry_theta=ce_entry_theta,
        days_held=days_held,
    )

    pos_risk.pe_risk = calculate_risk(
        side="PE",
        strike=pe_strike,
        entry_premium=pe_entry_premium,
        current_premium=pe_current_premium,
        entry_iv=pe_entry_iv,
        current_iv=pe_current_iv,
        entry_delta=pe_entry_delta,
        current_delta=pe_current_delta,
        entry_spot=entry_spot,
        current_spot=current_spot,
        entry_theta=pe_entry_theta,
        days_held=days_held,
    )

    pos_risk.overall_risk = max(
        pos_risk.ce_risk.composite_score,
        pos_risk.pe_risk.composite_score,
    )

    # Determine threatened side
    if pos_risk.ce_risk.composite_score > pos_risk.pe_risk.composite_score:
        if pos_risk.ce_risk.composite_score >= settings.risk_danger_threshold:
            pos_risk.threatened_side = "CE"
    elif pos_risk.pe_risk.composite_score >= settings.risk_danger_threshold:
        pos_risk.threatened_side = "PE"

    return pos_risk
