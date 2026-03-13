"""
FastAPI Backend Server for Nifty Options Dashboard
Provides REST API endpoints and scheduled data refresh.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

import pytz
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.settings import settings
from backend.modules.data_fetcher import get_fetcher, MarketSnapshot
from backend.modules.strike_suggestion import generate_suggestion, StrikeSuggestion
from backend.modules.market_utils import (
    is_market_open,
    is_pre_market,
    get_next_weekly_expiry,
    days_to_expiry,
    IST,
)
from backend.modules.trade_manager import get_trade_manager, TradeManager
from backend.modules.risk_engine import assess_position_risk, PositionRisk
from backend.modules.hedge_calculator import HedgeSuggestion

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── Global state ──
latest_snapshot: Optional[MarketSnapshot] = None
latest_suggestion: Optional[StrikeSuggestion] = None
latest_risks: Dict[str, PositionRisk] = {}
latest_hedges: Dict[str, HedgeSuggestion] = {}
scheduler: Optional[AsyncIOScheduler] = None


async def refresh_data():
    """Core data refresh routine — called by scheduler and manual trigger."""
    global latest_snapshot, latest_suggestion

    fetcher = get_fetcher()
    snapshot = await fetcher.fetch_full_snapshot()
    latest_snapshot = snapshot

    if snapshot.nifty_spot > 0 and snapshot.india_vix > 0:
        suggestion = generate_suggestion(snapshot)
        latest_suggestion = suggestion
        logger.info(
            f"Data refreshed: Nifty={snapshot.nifty_spot:.0f}, VIX={snapshot.india_vix:.1f}, "
            f"Suggestion: {suggestion.ce_strike} CE / {suggestion.pe_strike} PE"
        )
    else:
        logger.warning("Incomplete data, suggestion not updated.")

    # Update live data for all active positions
    tm = get_trade_manager()
    for pos in tm.get_active_positions():
        tm.update_live_data(pos.position_id, snapshot)
        hedge = tm.check_hedge_needed(pos.position_id, snapshot)
        if hedge and hedge.is_needed:
            latest_hedges[pos.position_id] = hedge

    # Try to update Google Sheets (non-blocking)
    try:
        await _update_sheets()
    except Exception as e:
        logger.warning(f"Sheets update failed (non-critical): {e}")


async def _update_sheets():
    """Update Google Sheets with latest data."""
    from backend.modules.sheets_manager import get_sheets_manager

    try:
        mgr = get_sheets_manager()
        if not mgr._spreadsheet:
            mgr.connect()

        tm = get_trade_manager()
        positions = [tm.get_position_summary(p.position_id) for p in tm.get_active_positions()]
        positions = [p for p in positions if p is not None]

        # Get risk for first active position (if any)
        position_risk = None
        hedge = None
        active = tm.get_active_positions()
        if active:
            first = active[0]
            if first.position_id in latest_hedges:
                hedge = latest_hedges[first.position_id]

        mgr.update_dashboard(
            snapshot=latest_snapshot,
            suggestion=latest_suggestion,
            positions=positions,
            position_risk=position_risk,
            hedge=hedge,
        )
        mgr.update_open_positions(positions)

        if latest_snapshot and latest_snapshot.option_chain:
            mgr.update_option_chain_data(latest_snapshot.option_chain)

    except Exception as e:
        logger.error(f"Error updating sheets: {e}")


async def scheduled_refresh():
    """Scheduled refresh that respects market hours."""
    if is_market_open():
        logger.info("Market is open — running scheduled refresh...")
        await refresh_data()
    elif is_pre_market():
        logger.info("Pre-market — running refresh at reduced frequency...")
        await refresh_data()
    else:
        logger.debug("Market closed — skipping refresh.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup and shutdown."""
    global scheduler

    # Start scheduler
    scheduler = AsyncIOScheduler(timezone=IST)
    scheduler.add_job(
        scheduled_refresh,
        "interval",
        minutes=settings.auto_refresh_interval,
        id="data_refresh",
        name="NSE Data Refresh",
    )
    scheduler.start()
    logger.info(f"Scheduler started: refresh every {settings.auto_refresh_interval} minutes")

    # Initial data fetch
    await refresh_data()

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown()
    fetcher = get_fetcher()
    await fetcher.close()
    logger.info("Shutdown complete.")


# ── FastAPI App ──
app = FastAPI(
    title="Nifty Options Selling Dashboard",
    description="Backend API for the weekly Nifty options selling dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ──

class TradeConfirmRequest(BaseModel):
    ce_lots: int
    ce_premium: float
    pe_lots: int
    pe_premium: float


class HedgeConfirmRequest(BaseModel):
    position_id: str


class RefreshResponse(BaseModel):
    status: str
    nifty_spot: float = 0.0
    india_vix: float = 0.0
    timestamp: str = ""
    is_stale: bool = False


class SuggestionResponse(BaseModel):
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
    nifty_cmp: float = 0.0
    india_vix: float = 0.0
    expected_move: int = 0
    upper_range: float = 0.0
    lower_range: float = 0.0
    days_to_expiry: int = 0
    expiry_date: str = ""
    validation_notes: List[str] = []


# ── Endpoints ──

@app.get("/")
async def root():
    return {
        "name": "Nifty Options Selling Dashboard API",
        "version": "1.0.0",
        "market_open": is_market_open(),
        "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    }


@app.post("/api/refresh", response_model=RefreshResponse)
async def manual_refresh():
    """Manually trigger a data refresh."""
    await refresh_data()
    if latest_snapshot:
        return RefreshResponse(
            status="ok",
            nifty_spot=latest_snapshot.nifty_spot,
            india_vix=latest_snapshot.india_vix,
            timestamp=latest_snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            is_stale=latest_snapshot.is_stale,
        )
    return RefreshResponse(status="error")


@app.get("/api/market")
async def get_market_data():
    """Get current market snapshot."""
    if not latest_snapshot:
        raise HTTPException(status_code=503, detail="No data available yet")

    indices = {}
    for name, data in latest_snapshot.indices.items():
        indices[name] = {
            "last": data.get("last", 0),
            "change_pct": data.get("change", 0),
        }

    return {
        "nifty_spot": latest_snapshot.nifty_spot,
        "nifty_change": latest_snapshot.nifty_change,
        "nifty_change_pct": latest_snapshot.nifty_change_pct,
        "india_vix": latest_snapshot.india_vix,
        "india_vix_change_pct": latest_snapshot.india_vix_change_pct,
        "indices": indices,
        "timestamp": latest_snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "is_stale": latest_snapshot.is_stale,
        "market_open": is_market_open(),
        "next_expiry": get_next_weekly_expiry().strftime("%d-%b-%Y"),
        "days_to_expiry": days_to_expiry(),
    }


@app.get("/api/suggestion", response_model=SuggestionResponse)
async def get_suggestion():
    """Get the current strike suggestion."""
    if not latest_suggestion:
        raise HTTPException(status_code=503, detail="No suggestion available")

    return SuggestionResponse(
        ce_strike=latest_suggestion.ce_strike,
        pe_strike=latest_suggestion.pe_strike,
        ce_ltp=latest_suggestion.ce_ltp,
        pe_ltp=latest_suggestion.pe_ltp,
        ce_iv=latest_suggestion.ce_iv,
        pe_iv=latest_suggestion.pe_iv,
        ce_delta=latest_suggestion.ce_delta,
        pe_delta=latest_suggestion.pe_delta,
        ce_theta=latest_suggestion.ce_theta,
        pe_theta=latest_suggestion.pe_theta,
        nifty_cmp=latest_suggestion.nifty_cmp,
        india_vix=latest_suggestion.india_vix,
        expected_move=latest_suggestion.expected_move,
        upper_range=latest_suggestion.upper_range,
        lower_range=latest_suggestion.lower_range,
        days_to_expiry=latest_suggestion.days_to_expiry,
        expiry_date=latest_suggestion.expiry_date,
        validation_notes=latest_suggestion.validation_notes or [],
    )


@app.post("/api/trade/confirm")
async def confirm_trade(req: TradeConfirmRequest):
    """Confirm a trade suggestion and create a position."""
    if not latest_suggestion or latest_suggestion.ce_strike == 0:
        raise HTTPException(status_code=400, detail="No active suggestion to confirm")

    tm = get_trade_manager()
    position = tm.create_position(
        suggestion=latest_suggestion,
        ce_lots=req.ce_lots,
        ce_premium=req.ce_premium,
        pe_lots=req.pe_lots,
        pe_premium=req.pe_premium,
    )

    return {
        "status": "ok",
        "position_id": position.position_id,
        "total_premium": position.total_premium_collected,
        "message": (
            f"Position created: SELL {position.ce_strike} CE x{req.ce_lots} "
            f"+ SELL {position.pe_strike} PE x{req.pe_lots}"
        ),
    }


@app.get("/api/positions")
async def get_positions():
    """Get all active positions with live P&L."""
    tm = get_trade_manager()
    positions = []
    for pos in tm.get_active_positions():
        summary = tm.get_position_summary(pos.position_id)
        if summary:
            positions.append(summary)
    return {"positions": positions}


@app.get("/api/positions/{position_id}")
async def get_position(position_id: str):
    """Get details for a specific position."""
    tm = get_trade_manager()
    summary = tm.get_position_summary(position_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Position not found")
    return summary


@app.get("/api/positions/{position_id}/risk")
async def get_position_risk(position_id: str):
    """Get risk breakdown for a position."""
    tm = get_trade_manager()
    pos = tm.positions.get(position_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    return {
        "position_id": position_id,
        "ce_risk_score": pos.ce_risk_score,
        "pe_risk_score": pos.pe_risk_score,
        "overall_risk": pos.overall_risk_score,
    }


@app.get("/api/positions/{position_id}/hedge")
async def get_hedge_suggestion(position_id: str):
    """Get hedge suggestion for a threatened position."""
    if position_id in latest_hedges:
        hedge = latest_hedges[position_id]
        return {
            "is_needed": hedge.is_needed,
            "threatened_side": hedge.threatened_side,
            "risk_score": hedge.risk_score,
            "hedge_strike": hedge.hedge_strike,
            "hedge_premium": hedge.hedge_premium,
            "hedge_lots": hedge.hedge_lots,
            "hedge_qty": hedge.hedge_qty,
            "hedge_cost": hedge.hedge_cost,
            "protection_level": hedge.protection_level,
            "scenarios": [
                {
                    "name": s.scenario_name,
                    "nifty_level": s.nifty_level,
                    "net_pnl": s.net_pnl,
                    "description": s.description,
                }
                for s in hedge.scenarios
            ],
        }
    return {"is_needed": False, "message": "No hedge needed at this time."}


@app.post("/api/positions/{position_id}/hedge/execute")
async def execute_hedge(position_id: str):
    """Execute a hedge for a position."""
    if position_id not in latest_hedges:
        raise HTTPException(status_code=400, detail="No hedge suggestion available")

    hedge = latest_hedges[position_id]
    tm = get_trade_manager()
    success = tm.execute_hedge(position_id, hedge)

    if success:
        del latest_hedges[position_id]
        return {"status": "ok", "message": "Hedge executed successfully."}
    raise HTTPException(status_code=400, detail="Failed to execute hedge")


@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: str):
    """Close/archive a position."""
    tm = get_trade_manager()
    success = tm.close_position(position_id)
    if success:
        return {"status": "ok", "message": f"Position {position_id} closed."}
    raise HTTPException(status_code=404, detail="Position not found")


@app.get("/api/history")
async def get_trade_history():
    """Get trade history."""
    tm = get_trade_manager()
    from dataclasses import asdict
    return {"history": [asdict(t) for t in tm.trade_history]}


@app.get("/api/option-chain")
async def get_option_chain():
    """Get raw option chain data."""
    if not latest_snapshot or not latest_snapshot.option_chain:
        raise HTTPException(status_code=503, detail="No option chain data")

    chain_data = []
    for strike in sorted(latest_snapshot.option_chain.keys()):
        row = latest_snapshot.option_chain[strike]
        chain_data.append({
            "strike": strike,
            "ce_ltp": row.ce.ltp if row.ce else None,
            "ce_iv": row.ce.iv if row.ce else None,
            "ce_oi": row.ce.oi if row.ce else None,
            "pe_ltp": row.pe.ltp if row.pe else None,
            "pe_iv": row.pe.iv if row.pe else None,
            "pe_oi": row.pe.oi if row.pe else None,
        })

    return {
        "expiry": latest_snapshot.selected_expiry,
        "underlying": latest_snapshot.nifty_spot,
        "chain": chain_data,
    }


@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    return {
        "lot_size": settings.lot_size,
        "strike_offset": settings.strike_offset,
        "max_delta": settings.max_delta,
        "min_premium_gte7": settings.min_premium_gte7,
        "max_premium_gte7": settings.max_premium_gte7,
        "risk_warning_threshold": settings.risk_warning_threshold,
        "risk_danger_threshold": settings.risk_danger_threshold,
        "risk_critical_threshold": settings.risk_critical_threshold,
        "auto_refresh_interval": settings.auto_refresh_interval,
        "risk_free_rate": settings.risk_free_rate,
        "support_resistance_levels": settings.support_resistance_levels,
    }


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "market_open": is_market_open(),
        "last_refresh": (
            latest_snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if latest_snapshot
            else None
        ),
        "data_stale": latest_snapshot.is_stale if latest_snapshot else True,
        "active_positions": len(get_trade_manager().get_active_positions()),
    }
