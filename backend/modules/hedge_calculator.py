"""
Hedge (Preventive Buy) Calculator
When a position side is under threat (risk score > 60),
calculates the optimal hedge trade: instrument, quantity, and scenario analysis.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config.settings import settings
from backend.modules.market_utils import (
    round_to_100,
    get_nearest_support_resistance,
)
from backend.modules.data_fetcher import OptionChainRow
from backend.modules.risk_engine import PositionRisk

logger = logging.getLogger(__name__)


@dataclass
class ScenarioAnalysis:
    """P&L scenario for the hedge."""
    scenario_name: str = ""
    nifty_level: float = 0.0
    sell_leg_pnl: float = 0.0
    hedge_leg_pnl: float = 0.0
    net_pnl: float = 0.0
    description: str = ""


@dataclass
class HedgeSuggestion:
    """Complete hedge suggestion with scenario analysis."""
    is_needed: bool = False
    threatened_side: str = ""  # "CE" or "PE"
    risk_score: float = 0.0

    # Sold position details
    sold_strike: int = 0
    sold_premium: float = 0.0
    sold_lots: int = 0
    sold_qty: int = 0

    # Hedge details
    hedge_action: str = "BUY"
    hedge_strike: int = 0
    hedge_premium: float = 0.0
    hedge_lots: int = 0
    hedge_qty: int = 0
    hedge_cost: float = 0.0
    protection_level: float = 0.0

    # Scenario analysis
    scenarios: List[ScenarioAnalysis] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def calculate_hedge(
    position_risk: PositionRisk,
    ce_strike: int,
    pe_strike: int,
    ce_entry_premium: float,
    pe_entry_premium: float,
    ce_lots: int,
    pe_lots: int,
    current_spot: float,
    entry_spot: float,
    chain: Dict[float, OptionChainRow],
    lot_size: int = None,
) -> HedgeSuggestion:
    """
    Calculate hedge suggestion when a position side is threatened.
    """
    if lot_size is None:
        lot_size = settings.lot_size

    suggestion = HedgeSuggestion()

    threatened = position_risk.threatened_side
    if threatened is None:
        suggestion.is_needed = False
        suggestion.notes.append("No side is under significant threat.")
        return suggestion

    suggestion.is_needed = True
    suggestion.threatened_side = threatened

    if threatened == "PE":
        suggestion.risk_score = position_risk.pe_risk.composite_score
        suggestion.sold_strike = pe_strike
        suggestion.sold_premium = pe_entry_premium
        suggestion.sold_lots = pe_lots
        suggestion.sold_qty = pe_lots * lot_size
    else:
        suggestion.risk_score = position_risk.ce_risk.composite_score
        suggestion.sold_strike = ce_strike
        suggestion.sold_premium = ce_entry_premium
        suggestion.sold_lots = ce_lots
        suggestion.sold_qty = ce_lots * lot_size

    # Step 2: Determine expected max adverse move
    worst_case_level = get_nearest_support_resistance(
        current_spot,
        suggestion.sold_strike,
        settings.support_resistance_levels,
        side=threatened,
    )
    suggestion.protection_level = worst_case_level

    # Calculate max loss if market reaches worst case
    if threatened == "PE":
        max_loss_per_qty = max(0, suggestion.sold_strike - worst_case_level)
    else:
        max_loss_per_qty = max(0, worst_case_level - suggestion.sold_strike)

    total_max_loss = max_loss_per_qty * suggestion.sold_qty

    if total_max_loss <= 0:
        suggestion.is_needed = False
        suggestion.notes.append(
            "Max loss calculation indicates no significant directional risk."
        )
        return suggestion

    # Step 3: Select hedge instrument (ATM option on threatened side)
    hedge_strike = round_to_100(current_spot, "nearest")
    if hedge_strike % 100 != 0:
        hedge_strike = round_to_100(current_spot, "up")

    suggestion.hedge_strike = hedge_strike

    # Get hedge premium from chain
    hedge_row = chain.get(float(hedge_strike))
    if hedge_row:
        opt = hedge_row.pe if threatened == "PE" else hedge_row.ce
        if opt:
            suggestion.hedge_premium = opt.ltp
        else:
            suggestion.notes.append(
                f"No {threatened} data at hedge strike {hedge_strike}. "
                "Using estimated premium."
            )
            suggestion.hedge_premium = abs(current_spot - hedge_strike) * 0.4 + 50
    else:
        suggestion.notes.append(f"Strike {hedge_strike} not in chain, estimating premium.")
        suggestion.hedge_premium = 150  # Conservative estimate

    if suggestion.hedge_premium <= 0:
        suggestion.hedge_premium = 50  # Safety fallback

    # Calculate profit per qty from hedge if worst case occurs
    if threatened == "PE":
        profit_per_qty = max(
            0, (hedge_strike - worst_case_level) - suggestion.hedge_premium
        )
    else:
        profit_per_qty = max(
            0, (worst_case_level - hedge_strike) - suggestion.hedge_premium
        )

    if profit_per_qty <= 0:
        suggestion.notes.append(
            "Hedge may not fully cover the loss. Consider a closer hedge strike."
        )
        profit_per_qty = max(1, abs(hedge_strike - worst_case_level) * 0.5)

    # Calculate required hedge quantity
    required_qty = math.ceil(total_max_loss / profit_per_qty)
    suggestion.hedge_lots = math.ceil(required_qty / lot_size)
    suggestion.hedge_qty = suggestion.hedge_lots * lot_size
    suggestion.hedge_cost = suggestion.hedge_premium * suggestion.hedge_qty

    # Step 4: Scenario Analysis
    total_sell_premium = (
        ce_entry_premium * ce_lots * lot_size
        + pe_entry_premium * pe_lots * lot_size
    )

    # Scenario 1: Market stays / reverses (best case)
    best_case = ScenarioAnalysis(
        scenario_name="Market Reverses (Best Case)",
        nifty_level=entry_spot,
    )
    # Sell legs: both expire worthless → keep full premium
    best_case.sell_leg_pnl = total_sell_premium
    # Hedge leg: ATM option loses most value
    hedge_decay_loss = suggestion.hedge_premium * 0.75  # ~75% premium lost
    best_case.hedge_leg_pnl = -hedge_decay_loss * suggestion.hedge_qty
    best_case.net_pnl = best_case.sell_leg_pnl + best_case.hedge_leg_pnl
    if best_case.net_pnl >= 0:
        best_case.description = f"Still profitable: +₹{best_case.net_pnl:,.0f}"
    else:
        best_case.description = f"Small loss from hedge cost: -₹{abs(best_case.net_pnl):,.0f}"
    suggestion.scenarios.append(best_case)

    # Scenario 2: Market reaches worst case level (break-even scenario)
    worst_scenario = ScenarioAnalysis(
        scenario_name="Market Reaches Protection Level",
        nifty_level=worst_case_level,
    )
    if threatened == "PE":
        sell_loss = max(0, suggestion.sold_strike - worst_case_level) * suggestion.sold_qty
        hedge_profit = max(0, hedge_strike - worst_case_level - suggestion.hedge_premium) * suggestion.hedge_qty
    else:
        sell_loss = max(0, worst_case_level - suggestion.sold_strike) * suggestion.sold_qty
        hedge_profit = max(0, worst_case_level - hedge_strike - suggestion.hedge_premium) * suggestion.hedge_qty

    worst_scenario.sell_leg_pnl = total_sell_premium - sell_loss
    worst_scenario.hedge_leg_pnl = hedge_profit
    worst_scenario.net_pnl = worst_scenario.sell_leg_pnl + worst_scenario.hedge_leg_pnl
    worst_scenario.description = f"Approximately break-even: ₹{worst_scenario.net_pnl:,.0f}"
    suggestion.scenarios.append(worst_scenario)

    # Scenario 3: Market goes beyond worst case
    beyond = ScenarioAnalysis(
        scenario_name="Market Goes Beyond Protection",
        nifty_level=worst_case_level - 200 if threatened == "PE" else worst_case_level + 200,
    )
    beyond_level = beyond.nifty_level
    if threatened == "PE":
        sell_loss_beyond = max(0, suggestion.sold_strike - beyond_level) * suggestion.sold_qty
        hedge_profit_beyond = max(0, hedge_strike - beyond_level - suggestion.hedge_premium) * suggestion.hedge_qty
    else:
        sell_loss_beyond = max(0, beyond_level - suggestion.sold_strike) * suggestion.sold_qty
        hedge_profit_beyond = max(0, beyond_level - hedge_strike - suggestion.hedge_premium) * suggestion.hedge_qty

    beyond.sell_leg_pnl = total_sell_premium - sell_loss_beyond
    beyond.hedge_leg_pnl = hedge_profit_beyond
    beyond.net_pnl = beyond.sell_leg_pnl + beyond.hedge_leg_pnl
    beyond.description = f"Partial protection, additional risk: ₹{beyond.net_pnl:,.0f}"
    suggestion.scenarios.append(beyond)

    return suggestion
