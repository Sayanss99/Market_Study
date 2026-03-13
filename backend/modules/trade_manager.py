"""
Trade Manager
Manages open positions, calculates live P&L, handles trade confirmation,
and archives expired/closed trades to history.
"""

import logging
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from enum import Enum

import pytz

from config.settings import settings
from backend.modules.data_fetcher import OptionChainRow, MarketSnapshot
from backend.modules.greeks_calculator import calculate_greeks
from backend.modules.strike_suggestion import StrikeSuggestion
from backend.modules.market_utils import days_to_expiry, get_next_weekly_expiry, IST, days_to_years
from backend.modules.risk_engine import assess_position_risk, PositionRisk
from backend.modules.hedge_calculator import calculate_hedge, HedgeSuggestion

logger = logging.getLogger(__name__)


class TradeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    HEDGED = "HEDGED"


@dataclass
class HedgeLeg:
    """A hedge (buy) leg attached to a position."""
    action: str = "BUY"
    side: str = ""  # "CE" or "PE"
    strike: int = 0
    premium: float = 0.0
    lots: int = 0
    qty: int = 0
    total_cost: float = 0.0
    current_ltp: float = 0.0
    pnl: float = 0.0
    timestamp: str = ""


@dataclass
class Position:
    """A complete options selling position with both CE and PE legs."""
    position_id: str = ""
    trade_date: str = ""
    expiry_date: str = ""
    entry_spot: float = 0.0
    status: str = TradeStatus.ACTIVE

    # CE Sell Leg
    ce_strike: int = 0
    ce_premium: float = 0.0
    ce_lots: int = 0
    ce_qty: int = 0
    ce_iv_at_entry: float = 0.0
    ce_delta_at_entry: float = 0.0
    ce_theta_at_entry: float = 0.0

    # PE Sell Leg
    pe_strike: int = 0
    pe_premium: float = 0.0
    pe_lots: int = 0
    pe_qty: int = 0
    pe_iv_at_entry: float = 0.0
    pe_delta_at_entry: float = 0.0
    pe_theta_at_entry: float = 0.0

    # Totals
    total_premium_collected: float = 0.0

    # Live Data
    ce_current_ltp: float = 0.0
    pe_current_ltp: float = 0.0
    ce_current_iv: float = 0.0
    pe_current_iv: float = 0.0
    ce_current_delta: float = 0.0
    pe_current_delta: float = 0.0

    # P&L
    ce_pnl: float = 0.0
    pe_pnl: float = 0.0
    total_pnl: float = 0.0

    # Risk
    ce_risk_score: float = 0.0
    pe_risk_score: float = 0.0
    overall_risk_score: float = 0.0

    # Hedge legs
    hedges: List[HedgeLeg] = field(default_factory=list)
    total_hedge_cost: float = 0.0
    total_hedge_pnl: float = 0.0
    net_pnl: float = 0.0  # total_pnl + total_hedge_pnl

    last_updated: str = ""


class TradeManager:
    """Manages all trading operations: creation, tracking, risk, hedging."""

    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Position] = []

    def create_position(
        self,
        suggestion: StrikeSuggestion,
        ce_lots: int,
        ce_premium: float,
        pe_lots: int,
        pe_premium: float,
        lot_size: int = None,
    ) -> Position:
        """Create a new position from a confirmed trade suggestion."""
        if lot_size is None:
            lot_size = settings.lot_size

        now = datetime.now(IST)
        pos_id = f"POS_{now.strftime('%Y%m%d_%H%M%S')}"

        ce_qty = ce_lots * lot_size
        pe_qty = pe_lots * lot_size
        total_premium = (ce_premium * ce_qty) + (pe_premium * pe_qty)

        position = Position(
            position_id=pos_id,
            trade_date=now.strftime("%Y-%m-%d %H:%M:%S"),
            expiry_date=suggestion.expiry_date,
            entry_spot=suggestion.nifty_cmp,
            status=TradeStatus.ACTIVE,
            ce_strike=suggestion.ce_strike,
            ce_premium=ce_premium,
            ce_lots=ce_lots,
            ce_qty=ce_qty,
            ce_iv_at_entry=suggestion.ce_iv,
            ce_delta_at_entry=suggestion.ce_delta,
            ce_theta_at_entry=suggestion.ce_theta,
            pe_strike=suggestion.pe_strike,
            pe_premium=pe_premium,
            pe_lots=pe_lots,
            pe_qty=pe_qty,
            pe_iv_at_entry=suggestion.pe_iv,
            pe_delta_at_entry=suggestion.pe_delta,
            pe_theta_at_entry=suggestion.pe_theta,
            total_premium_collected=total_premium,
            last_updated=now.strftime("%Y-%m-%d %H:%M:%S"),
        )

        self.positions[pos_id] = position
        logger.info(
            f"Position {pos_id} created: SELL {suggestion.ce_strike} CE x{ce_lots} @ ₹{ce_premium} "
            f"+ SELL {suggestion.pe_strike} PE x{pe_lots} @ ₹{pe_premium} "
            f"= ₹{total_premium:,.0f} total premium"
        )
        return position

    def update_live_data(
        self,
        position_id: str,
        snapshot: MarketSnapshot,
    ) -> Optional[Position]:
        """Update a position with live market data and recalculate P&L and risk."""
        pos = self.positions.get(position_id)
        if pos is None or pos.status != TradeStatus.ACTIVE:
            return None

        chain = snapshot.option_chain
        spot = snapshot.nifty_spot
        now = datetime.now(IST)

        # Update CE live data
        ce_row = chain.get(float(pos.ce_strike))
        if ce_row and ce_row.ce:
            pos.ce_current_ltp = ce_row.ce.ltp
            pos.ce_current_iv = ce_row.ce.iv

        # Update PE live data
        pe_row = chain.get(float(pos.pe_strike))
        if pe_row and pe_row.pe:
            pos.pe_current_ltp = pe_row.pe.ltp
            pos.pe_current_iv = pe_row.pe.iv

        # Calculate current Greeks
        expiry = get_next_weekly_expiry()
        dte = days_to_expiry(expiry)
        T = days_to_years(dte)

        if pos.ce_current_iv > 0:
            ce_iv_dec = pos.ce_current_iv / 100.0 if pos.ce_current_iv > 1 else pos.ce_current_iv
            ce_greeks = calculate_greeks(spot, pos.ce_strike, T, ce_iv_dec, "CE")
            pos.ce_current_delta = ce_greeks.delta
        if pos.pe_current_iv > 0:
            pe_iv_dec = pos.pe_current_iv / 100.0 if pos.pe_current_iv > 1 else pos.pe_current_iv
            pe_greeks = calculate_greeks(spot, pos.pe_strike, T, pe_iv_dec, "PE")
            pos.pe_current_delta = pe_greeks.delta

        # Calculate P&L (Sell P&L: entry_premium - current_ltp)
        pos.ce_pnl = (pos.ce_premium - pos.ce_current_ltp) * pos.ce_qty
        pos.pe_pnl = (pos.pe_premium - pos.pe_current_ltp) * pos.pe_qty
        pos.total_pnl = pos.ce_pnl + pos.pe_pnl

        # Update hedge P&L
        pos.total_hedge_pnl = 0.0
        for hedge in pos.hedges:
            h_row = chain.get(float(hedge.strike))
            if h_row:
                h_opt = h_row.pe if hedge.side == "PE" else h_row.ce
                if h_opt:
                    hedge.current_ltp = h_opt.ltp
                    hedge.pnl = (hedge.current_ltp - hedge.premium) * hedge.qty
                    pos.total_hedge_pnl += hedge.pnl

        pos.net_pnl = pos.total_pnl + pos.total_hedge_pnl

        # Calculate risk
        trade_date = datetime.strptime(pos.trade_date, "%Y-%m-%d %H:%M:%S")
        days_held = max(1, (now - trade_date).days)

        risk = assess_position_risk(
            ce_strike=pos.ce_strike,
            pe_strike=pos.pe_strike,
            ce_entry_premium=pos.ce_premium,
            pe_entry_premium=pos.pe_premium,
            ce_current_premium=pos.ce_current_ltp,
            pe_current_premium=pos.pe_current_ltp,
            ce_entry_iv=pos.ce_iv_at_entry,
            pe_entry_iv=pos.pe_iv_at_entry,
            ce_current_iv=pos.ce_current_iv,
            pe_current_iv=pos.pe_current_iv,
            ce_entry_delta=pos.ce_delta_at_entry,
            pe_entry_delta=pos.pe_delta_at_entry,
            ce_current_delta=pos.ce_current_delta,
            pe_current_delta=pos.pe_current_delta,
            entry_spot=pos.entry_spot,
            current_spot=spot,
            ce_entry_theta=pos.ce_theta_at_entry,
            pe_entry_theta=pos.pe_theta_at_entry,
            days_held=days_held,
        )

        pos.ce_risk_score = risk.ce_risk.composite_score
        pos.pe_risk_score = risk.pe_risk.composite_score
        pos.overall_risk_score = risk.overall_risk
        pos.last_updated = now.strftime("%Y-%m-%d %H:%M:%S")

        return pos

    def check_hedge_needed(
        self,
        position_id: str,
        snapshot: MarketSnapshot,
    ) -> Optional[HedgeSuggestion]:
        """Check if a hedge is needed for a position and generate suggestion."""
        pos = self.positions.get(position_id)
        if pos is None or pos.status != TradeStatus.ACTIVE:
            return None

        # Only suggest hedge if risk > danger threshold
        max_risk = max(pos.ce_risk_score, pos.pe_risk_score)
        if max_risk < settings.risk_danger_threshold:
            return None

        # Build PositionRisk from current data
        trade_date = datetime.strptime(pos.trade_date, "%Y-%m-%d %H:%M:%S")
        days_held = max(1, (datetime.now(IST) - trade_date).days)

        risk = assess_position_risk(
            ce_strike=pos.ce_strike,
            pe_strike=pos.pe_strike,
            ce_entry_premium=pos.ce_premium,
            pe_entry_premium=pos.pe_premium,
            ce_current_premium=pos.ce_current_ltp,
            pe_current_premium=pos.pe_current_ltp,
            ce_entry_iv=pos.ce_iv_at_entry,
            pe_entry_iv=pos.pe_iv_at_entry,
            ce_current_iv=pos.ce_current_iv,
            pe_current_iv=pos.pe_current_iv,
            ce_entry_delta=pos.ce_delta_at_entry,
            pe_entry_delta=pos.pe_delta_at_entry,
            ce_current_delta=pos.ce_current_delta,
            pe_current_delta=pos.pe_current_delta,
            entry_spot=pos.entry_spot,
            current_spot=snapshot.nifty_spot,
            ce_entry_theta=pos.ce_theta_at_entry,
            pe_entry_theta=pos.pe_theta_at_entry,
            days_held=days_held,
        )

        hedge = calculate_hedge(
            position_risk=risk,
            ce_strike=pos.ce_strike,
            pe_strike=pos.pe_strike,
            ce_entry_premium=pos.ce_premium,
            pe_entry_premium=pos.pe_premium,
            ce_lots=pos.ce_lots,
            pe_lots=pos.pe_lots,
            current_spot=snapshot.nifty_spot,
            entry_spot=pos.entry_spot,
            chain=snapshot.option_chain,
        )

        return hedge

    def execute_hedge(
        self,
        position_id: str,
        hedge: HedgeSuggestion,
    ) -> bool:
        """Record a hedge execution against a position."""
        pos = self.positions.get(position_id)
        if pos is None:
            return False

        now = datetime.now(IST)
        hedge_leg = HedgeLeg(
            action="BUY",
            side=hedge.threatened_side,
            strike=hedge.hedge_strike,
            premium=hedge.hedge_premium,
            lots=hedge.hedge_lots,
            qty=hedge.hedge_qty,
            total_cost=hedge.hedge_cost,
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
        )

        pos.hedges.append(hedge_leg)
        pos.total_hedge_cost += hedge.hedge_cost
        pos.status = TradeStatus.HEDGED

        logger.info(
            f"Hedge executed for {position_id}: BUY {hedge.hedge_strike} "
            f"{hedge.threatened_side} x{hedge.hedge_lots} lots @ ₹{hedge.hedge_premium}"
        )
        return True

    def close_position(self, position_id: str, reason: str = "EXPIRED") -> bool:
        """Close/archive a position."""
        pos = self.positions.get(position_id)
        if pos is None:
            return False

        pos.status = TradeStatus.EXPIRED if reason == "EXPIRED" else TradeStatus.CLOSED
        self.trade_history.append(pos)
        del self.positions[position_id]

        logger.info(f"Position {position_id} closed ({reason}). Net P&L: ₹{pos.net_pnl:,.0f}")
        return True

    def get_active_positions(self) -> List[Position]:
        """Get all active positions."""
        return [
            p for p in self.positions.values()
            if p.status in (TradeStatus.ACTIVE, TradeStatus.HEDGED)
        ]

    def get_position_summary(self, position_id: str) -> Optional[Dict]:
        """Get a summary dict for a position (for sheet display)."""
        pos = self.positions.get(position_id)
        if pos is None:
            return None

        return {
            "position_id": pos.position_id,
            "trade_date": pos.trade_date,
            "expiry_date": pos.expiry_date,
            "status": pos.status,
            "ce_strike": pos.ce_strike,
            "ce_premium": pos.ce_premium,
            "ce_lots": pos.ce_lots,
            "ce_current_ltp": pos.ce_current_ltp,
            "ce_pnl": pos.ce_pnl,
            "ce_risk": pos.ce_risk_score,
            "pe_strike": pos.pe_strike,
            "pe_premium": pos.pe_premium,
            "pe_lots": pos.pe_lots,
            "pe_current_ltp": pos.pe_current_ltp,
            "pe_pnl": pos.pe_pnl,
            "pe_risk": pos.pe_risk_score,
            "total_premium": pos.total_premium_collected,
            "total_pnl": pos.total_pnl,
            "hedge_cost": pos.total_hedge_cost,
            "hedge_pnl": pos.total_hedge_pnl,
            "net_pnl": pos.net_pnl,
            "overall_risk": pos.overall_risk_score,
            "last_updated": pos.last_updated,
        }

    def to_dict(self) -> Dict:
        """Serialize all positions for persistence."""
        return {
            "positions": {pid: asdict(p) for pid, p in self.positions.items()},
            "history": [asdict(p) for p in self.trade_history],
        }


# Singleton
_manager: Optional[TradeManager] = None


def get_trade_manager() -> TradeManager:
    global _manager
    if _manager is None:
        _manager = TradeManager()
    return _manager
