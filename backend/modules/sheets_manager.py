"""
Google Sheets Integration Layer
Reads/writes data to Google Sheets via the gspread library.
Manages all 6 sheets: Dashboard, Open Positions, Risk Monitor,
Trade History, Option Chain Data, Settings & Config.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

import gspread
from google.oauth2.service_account import Credentials

from config.settings import settings
from backend.modules.data_fetcher import MarketSnapshot, OptionChainRow
from backend.modules.strike_suggestion import StrikeSuggestion
from backend.modules.risk_engine import PositionRisk, RiskBreakdown
from backend.modules.hedge_calculator import HedgeSuggestion
from backend.modules.trade_manager import Position, TradeManager

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsManager:
    """Manages all Google Sheets read/write operations."""

    def __init__(self, credentials_file: str = None, sheet_id: str = None):
        self._creds_file = credentials_file or settings.google_credentials_file
        self._sheet_id = sheet_id or settings.google_sheets_id
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None

    def connect(self):
        """Authenticate and connect to Google Sheets."""
        try:
            creds = Credentials.from_service_account_file(
                self._creds_file, scopes=SCOPES
            )
            self._client = gspread.authorize(creds)
            self._spreadsheet = self._client.open_by_key(self._sheet_id)
            logger.info(f"Connected to Google Sheet: {self._spreadsheet.title}")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            raise

    def _get_or_create_sheet(self, title: str, rows: int = 200, cols: int = 30) -> gspread.Worksheet:
        """Get a worksheet by title, creating it if it doesn't exist."""
        try:
            return self._spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
            logger.info(f"Created new sheet: {title}")
            return ws

    # ──────────────────────────────────────────────
    # Dashboard Sheet
    # ──────────────────────────────────────────────

    def update_dashboard(
        self,
        snapshot: MarketSnapshot,
        suggestion: Optional[StrikeSuggestion],
        positions: List[Dict],
        position_risk: Optional[PositionRisk] = None,
        hedge: Optional[HedgeSuggestion] = None,
    ):
        """Write all dashboard data to the Dashboard sheet."""
        ws = self._get_or_create_sheet(settings.sheet_dashboard, rows=100, cols=20)

        cells = []

        # Row 1: Title
        cells.append(gspread.Cell(1, 1, "NIFTY OPTIONS SELLING DASHBOARD"))
        cells.append(gspread.Cell(1, 10, f"Last Updated: {snapshot.timestamp.strftime('%d-%b-%Y %H:%M:%S IST')}"))

        # Row 3-4: Market Overview
        cells.append(gspread.Cell(3, 1, "MARKET OVERVIEW"))
        nifty = snapshot.nifty_spot
        nifty_chg = snapshot.nifty_change_pct
        vix = snapshot.india_vix
        vix_chg = snapshot.india_vix_change_pct

        cells.append(gspread.Cell(4, 1, "Nifty 50"))
        cells.append(gspread.Cell(4, 2, nifty))
        cells.append(gspread.Cell(4, 3, f"{nifty_chg:+.2f}%"))
        cells.append(gspread.Cell(4, 4, "India VIX"))
        cells.append(gspread.Cell(4, 5, vix))
        cells.append(gspread.Cell(4, 6, f"{vix_chg:+.2f}%"))

        # Sectoral indices
        sectoral_names = [
            "NIFTY BANK", "NIFTY IT", "NIFTY PHARMA", "NIFTY FMCG",
            "NIFTY METAL", "NIFTY AUTO",
        ]
        cells.append(gspread.Cell(6, 1, "SECTORAL INDICES"))
        row = 7
        col = 1
        for name in sectoral_names:
            idx = snapshot.indices.get(name, {})
            cells.append(gspread.Cell(row, col, name))
            cells.append(gspread.Cell(row, col + 1, idx.get("last", "")))
            cells.append(gspread.Cell(row, col + 2, f"{idx.get('change', 0):+.2f}%"))
            col += 3
            if col > 13:
                col = 1
                row += 1

        # Row 10+: Global Markets
        global_names = ["DOW JONES", "S&P 500", "NASDAQ", "FTSE 100", "NIKKEI 225", "HANG SENG"]
        cells.append(gspread.Cell(row + 1, 1, "GLOBAL MARKETS"))
        row += 2
        col = 1
        for name in global_names:
            idx = snapshot.indices.get(name, {})
            cells.append(gspread.Cell(row, col, name))
            cells.append(gspread.Cell(row, col + 1, idx.get("last", "N/A")))
            cells.append(gspread.Cell(row, col + 2, f"{idx.get('change', 0):+.2f}%"))
            col += 3
            if col > 13:
                col = 1
                row += 1

        # Strike Suggestion Section
        row += 2
        cells.append(gspread.Cell(row, 1, "TRADE SUGGESTION"))
        if suggestion and suggestion.ce_strike > 0:
            row += 1
            cells.append(gspread.Cell(row, 1, f"Expiry: {suggestion.expiry_date}"))
            cells.append(gspread.Cell(row, 4, f"Days Left: {suggestion.days_to_expiry}"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"Nifty CMP: {suggestion.nifty_cmp:,.0f}"))
            cells.append(gspread.Cell(row, 4, f"India VIX: {suggestion.india_vix:.1f}"))
            cells.append(gspread.Cell(row, 7, f"Expected Move: ±{suggestion.expected_move}"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"Range: [{suggestion.lower_range:,.0f} — {suggestion.upper_range:,.0f}]"))
            row += 1

            # CE side
            cells.append(gspread.Cell(row, 1, "SELL"))
            cells.append(gspread.Cell(row, 2, f"{suggestion.ce_strike} CE"))
            cells.append(gspread.Cell(row, 3, f"LTP: ₹{suggestion.ce_ltp:.2f}"))
            cells.append(gspread.Cell(row, 4, f"IV: {suggestion.ce_iv:.1f}"))
            cells.append(gspread.Cell(row, 5, f"Delta: {suggestion.ce_delta:.4f}"))
            cells.append(gspread.Cell(row, 6, f"Theta: {suggestion.ce_theta:.2f}"))

            # PE side
            cells.append(gspread.Cell(row, 7, "SELL"))
            cells.append(gspread.Cell(row, 8, f"{suggestion.pe_strike} PE"))
            cells.append(gspread.Cell(row, 9, f"LTP: ₹{suggestion.pe_ltp:.2f}"))
            cells.append(gspread.Cell(row, 10, f"IV: {suggestion.pe_iv:.1f}"))
            cells.append(gspread.Cell(row, 11, f"Delta: {suggestion.pe_delta:.4f}"))
            cells.append(gspread.Cell(row, 12, f"Theta: {suggestion.pe_theta:.2f}"))

            row += 1
            cells.append(gspread.Cell(row, 1, "CONFIRM TRADE"))
            cells.append(gspread.Cell(row, 2, "FALSE"))  # Checkbox placeholder

        # Open Position Summary
        row += 2
        cells.append(gspread.Cell(row, 1, "OPEN POSITIONS SUMMARY"))
        row += 1
        headers = ["ID", "CE Strike", "PE Strike", "Total P&L", "Net P&L", "Risk", "Status"]
        for i, h in enumerate(headers):
            cells.append(gspread.Cell(row, i + 1, h))
        row += 1
        for pos in positions:
            cells.append(gspread.Cell(row, 1, pos.get("position_id", "")))
            cells.append(gspread.Cell(row, 2, pos.get("ce_strike", "")))
            cells.append(gspread.Cell(row, 3, pos.get("pe_strike", "")))
            cells.append(gspread.Cell(row, 4, f"₹{pos.get('total_pnl', 0):,.0f}"))
            cells.append(gspread.Cell(row, 5, f"₹{pos.get('net_pnl', 0):,.0f}"))
            cells.append(gspread.Cell(row, 6, f"{pos.get('overall_risk', 0):.0f}/100"))
            cells.append(gspread.Cell(row, 7, pos.get("status", "")))
            row += 1

        # Risk Meter Section
        row += 1
        cells.append(gspread.Cell(row, 1, "RISK METERS"))
        if position_risk:
            row += 1
            ce_score = position_risk.ce_risk.composite_score
            pe_score = position_risk.pe_risk.composite_score
            ce_bar = _risk_bar(ce_score)
            pe_bar = _risk_bar(pe_score)

            cells.append(gspread.Cell(row, 1, "CE SIDE RISK"))
            cells.append(gspread.Cell(row, 2, f"{ce_bar} {ce_score:.0f}/100"))
            cells.append(gspread.Cell(row, 3, position_risk.ce_risk.severity))
            cells.append(gspread.Cell(row, 6, "PE SIDE RISK"))
            cells.append(gspread.Cell(row, 7, f"{pe_bar} {pe_score:.0f}/100"))
            cells.append(gspread.Cell(row, 8, position_risk.pe_risk.severity))

            row += 1
            cells.append(gspread.Cell(row, 1, f"Delta: {position_risk.ce_risk.delta_current:.4f} ({position_risk.ce_risk.delta_status})"))
            cells.append(gspread.Cell(row, 6, f"Delta: {position_risk.pe_risk.delta_current:.4f} ({position_risk.pe_risk.delta_status})"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"IV: {position_risk.ce_risk.iv_change_pct:+.1f}% ({position_risk.ce_risk.iv_status})"))
            cells.append(gspread.Cell(row, 6, f"IV: {position_risk.pe_risk.iv_change_pct:+.1f}% ({position_risk.pe_risk.iv_status})"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"Premium: {position_risk.ce_risk.premium_multiple:.1f}x ({position_risk.ce_risk.premium_status})"))
            cells.append(gspread.Cell(row, 6, f"Premium: {position_risk.pe_risk.premium_multiple:.1f}x ({position_risk.pe_risk.premium_status})"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"Spot Distance: {position_risk.ce_risk.spot_distance_pts:.0f} pts ({position_risk.ce_risk.proximity_status})"))
            cells.append(gspread.Cell(row, 6, f"Spot Distance: {position_risk.pe_risk.spot_distance_pts:.0f} pts ({position_risk.pe_risk.proximity_status})"))

        # Hedge Alert Section
        if hedge and hedge.is_needed:
            row += 2
            cells.append(gspread.Cell(row, 1, f"HEDGE ALERT — {hedge.threatened_side} SIDE UNDER THREAT"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"Sold Position: {hedge.sold_strike} {hedge.threatened_side} x {hedge.sold_qty} qty @ ₹{hedge.sold_premium}"))
            cells.append(gspread.Cell(row, 6, f"Risk Score: {hedge.risk_score:.0f}/100"))
            row += 1
            cells.append(gspread.Cell(row, 1, "SUGGESTED HEDGE:"))
            row += 1
            cells.append(gspread.Cell(row, 1, f"BUY {hedge.hedge_strike} {hedge.threatened_side} x {hedge.hedge_lots} lots ({hedge.hedge_qty} qty) @ ₹{hedge.hedge_premium:.2f}"))
            cells.append(gspread.Cell(row, 6, f"Cost: ₹{hedge.hedge_cost:,.0f}"))
            cells.append(gspread.Cell(row, 9, f"Protection: Nifty {hedge.protection_level:,.0f}"))

            row += 1
            cells.append(gspread.Cell(row, 1, "SCENARIO ANALYSIS:"))
            for scenario in hedge.scenarios:
                row += 1
                cells.append(gspread.Cell(row, 1, scenario.scenario_name))
                cells.append(gspread.Cell(row, 4, f"Nifty @ {scenario.nifty_level:,.0f}"))
                cells.append(gspread.Cell(row, 7, f"Net P&L: ₹{scenario.net_pnl:,.0f}"))
                cells.append(gspread.Cell(row, 10, scenario.description))

            row += 1
            cells.append(gspread.Cell(row, 1, "EXECUTE HEDGE"))
            cells.append(gspread.Cell(row, 2, "FALSE"))  # Checkbox placeholder

        # Disclaimer
        row += 2
        cells.append(gspread.Cell(row, 1, "DISCLAIMER: For educational/personal use only. Not financial advice. All values in INR."))

        # Batch update
        try:
            ws.update_cells(cells, value_input_option="USER_ENTERED")
            logger.info("Dashboard sheet updated successfully.")
        except Exception as e:
            logger.error(f"Error updating dashboard: {e}")

    # ──────────────────────────────────────────────
    # Open Positions Sheet
    # ──────────────────────────────────────────────

    def update_open_positions(self, positions: List[Dict]):
        """Write all active positions to the Open Positions sheet."""
        ws = self._get_or_create_sheet(settings.sheet_open_positions)

        headers = [
            "Position ID", "Trade Date", "Expiry", "Status", "Entry Spot",
            "CE Strike", "CE Premium", "CE Lots", "CE Qty", "CE IV@Entry", "CE Delta@Entry",
            "CE Current LTP", "CE P&L", "CE Risk",
            "PE Strike", "PE Premium", "PE Lots", "PE Qty", "PE IV@Entry", "PE Delta@Entry",
            "PE Current LTP", "PE P&L", "PE Risk",
            "Total Premium", "Total P&L", "Hedge Cost", "Hedge P&L", "Net P&L",
            "Overall Risk", "Last Updated",
        ]

        data = [headers]
        for pos in positions:
            data.append([
                pos.get("position_id", ""),
                pos.get("trade_date", ""),
                pos.get("expiry_date", ""),
                pos.get("status", ""),
                pos.get("entry_spot", ""),
                pos.get("ce_strike", ""),
                pos.get("ce_premium", ""),
                pos.get("ce_lots", ""),
                pos.get("ce_qty", ""),
                pos.get("ce_iv_at_entry", ""),
                pos.get("ce_delta_at_entry", ""),
                pos.get("ce_current_ltp", ""),
                pos.get("ce_pnl", ""),
                pos.get("ce_risk", ""),
                pos.get("pe_strike", ""),
                pos.get("pe_premium", ""),
                pos.get("pe_lots", ""),
                pos.get("pe_qty", ""),
                pos.get("pe_iv_at_entry", ""),
                pos.get("pe_delta_at_entry", ""),
                pos.get("pe_current_ltp", ""),
                pos.get("pe_pnl", ""),
                pos.get("pe_risk", ""),
                pos.get("total_premium", ""),
                pos.get("total_pnl", ""),
                pos.get("hedge_cost", ""),
                pos.get("hedge_pnl", ""),
                pos.get("net_pnl", ""),
                pos.get("overall_risk", ""),
                pos.get("last_updated", ""),
            ])

        try:
            ws.clear()
            ws.update(range_name="A1", values=data, value_input_option="USER_ENTERED")
            logger.info(f"Open Positions sheet updated with {len(positions)} positions.")
        except Exception as e:
            logger.error(f"Error updating open positions: {e}")

    # ──────────────────────────────────────────────
    # Risk Monitor Sheet
    # ──────────────────────────────────────────────

    def update_risk_monitor(self, positions_with_risk: List[Dict]):
        """Write detailed risk breakdowns to the Risk Monitor sheet."""
        ws = self._get_or_create_sheet(settings.sheet_risk_monitor)

        headers = [
            "Position ID", "Side", "Strike", "Risk Score", "Severity",
            "Delta Current", "Delta Status", "Delta Score",
            "IV Change%", "IV Status", "IV Score",
            "Premium Multiple", "Premium Status", "Premium Score",
            "Spot Distance (pts)", "Proximity Status", "Proximity Score",
            "Theta Status", "Theta Score",
        ]

        data = [headers]
        for pos in positions_with_risk:
            # CE row
            data.append([
                pos.get("position_id", ""),
                "CE",
                pos.get("ce_strike", ""),
                f"{pos.get('ce_risk_score', 0):.0f}",
                pos.get("ce_severity", ""),
                pos.get("ce_delta_current", ""),
                pos.get("ce_delta_status", ""),
                pos.get("ce_delta_score", ""),
                pos.get("ce_iv_change_pct", ""),
                pos.get("ce_iv_status", ""),
                pos.get("ce_iv_score", ""),
                pos.get("ce_premium_multiple", ""),
                pos.get("ce_premium_status", ""),
                pos.get("ce_premium_score", ""),
                pos.get("ce_spot_distance", ""),
                pos.get("ce_proximity_status", ""),
                pos.get("ce_proximity_score", ""),
                pos.get("ce_theta_status", ""),
                pos.get("ce_theta_score", ""),
            ])
            # PE row
            data.append([
                pos.get("position_id", ""),
                "PE",
                pos.get("pe_strike", ""),
                f"{pos.get('pe_risk_score', 0):.0f}",
                pos.get("pe_severity", ""),
                pos.get("pe_delta_current", ""),
                pos.get("pe_delta_status", ""),
                pos.get("pe_delta_score", ""),
                pos.get("pe_iv_change_pct", ""),
                pos.get("pe_iv_status", ""),
                pos.get("pe_iv_score", ""),
                pos.get("pe_premium_multiple", ""),
                pos.get("pe_premium_status", ""),
                pos.get("pe_premium_score", ""),
                pos.get("pe_spot_distance", ""),
                pos.get("pe_proximity_status", ""),
                pos.get("pe_proximity_score", ""),
                pos.get("pe_theta_status", ""),
                pos.get("pe_theta_score", ""),
            ])

        try:
            ws.clear()
            ws.update(range_name="A1", values=data, value_input_option="USER_ENTERED")
            logger.info("Risk Monitor sheet updated.")
        except Exception as e:
            logger.error(f"Error updating risk monitor: {e}")

    # ──────────────────────────────────────────────
    # Trade History Sheet
    # ──────────────────────────────────────────────

    def update_trade_history(self, history: List[Dict]):
        """Append closed/expired trades to Trade History sheet."""
        ws = self._get_or_create_sheet(settings.sheet_trade_history)

        # Check if headers exist
        existing = ws.get_all_values()
        if not existing:
            headers = [
                "Position ID", "Trade Date", "Expiry", "Status",
                "CE Strike", "CE Premium", "CE Lots",
                "PE Strike", "PE Premium", "PE Lots",
                "Total Premium", "Final P&L", "Net P&L (with hedge)",
                "Hedge Cost",
            ]
            ws.append_row(headers, value_input_option="USER_ENTERED")

        for trade in history:
            row = [
                trade.get("position_id", ""),
                trade.get("trade_date", ""),
                trade.get("expiry_date", ""),
                trade.get("status", ""),
                trade.get("ce_strike", ""),
                trade.get("ce_premium", ""),
                trade.get("ce_lots", ""),
                trade.get("pe_strike", ""),
                trade.get("pe_premium", ""),
                trade.get("pe_lots", ""),
                trade.get("total_premium", ""),
                trade.get("total_pnl", ""),
                trade.get("net_pnl", ""),
                trade.get("hedge_cost", ""),
            ]
            ws.append_row(row, value_input_option="USER_ENTERED")

        logger.info(f"Trade History updated with {len(history)} entries.")

    # ──────────────────────────────────────────────
    # Option Chain Data Sheet
    # ──────────────────────────────────────────────

    def update_option_chain_data(self, chain: Dict[float, OptionChainRow]):
        """Write raw option chain data to the hidden data sheet."""
        ws = self._get_or_create_sheet(settings.sheet_option_chain, rows=500, cols=20)

        headers = [
            "Strike", "CE LTP", "CE IV", "CE OI", "CE Change OI", "CE Volume",
            "CE Bid", "CE Ask",
            "PE LTP", "PE IV", "PE OI", "PE Change OI", "PE Volume",
            "PE Bid", "PE Ask",
        ]

        data = [headers]
        for strike in sorted(chain.keys()):
            row_data = chain[strike]
            ce = row_data.ce
            pe = row_data.pe
            data.append([
                strike,
                ce.ltp if ce else "",
                ce.iv if ce else "",
                ce.oi if ce else "",
                ce.change_in_oi if ce else "",
                ce.volume if ce else "",
                ce.bid_price if ce else "",
                ce.ask_price if ce else "",
                pe.ltp if pe else "",
                pe.iv if pe else "",
                pe.oi if pe else "",
                pe.change_in_oi if pe else "",
                pe.volume if pe else "",
                pe.bid_price if pe else "",
                pe.ask_price if pe else "",
            ])

        try:
            ws.clear()
            ws.update(range_name="A1", values=data, value_input_option="USER_ENTERED")
            logger.info(f"Option Chain Data sheet updated with {len(chain)} strikes.")
        except Exception as e:
            logger.error(f"Error updating option chain data: {e}")

    # ──────────────────────────────────────────────
    # Settings & Config Sheet
    # ──────────────────────────────────────────────

    def update_settings_sheet(self):
        """Write current settings to the Settings & Config sheet."""
        ws = self._get_or_create_sheet(settings.sheet_settings, rows=30, cols=4)

        data = [
            ["Parameter", "Value", "Description"],
            ["Lot Size", settings.lot_size, "Nifty lot size (changed from 75 to 65 effective Jan 2026)"],
            ["Strike Offset", settings.strike_offset, "Points away from VIX range to suggest strikes"],
            ["Max Delta", settings.max_delta, "Maximum acceptable delta for suggested strikes"],
            ["Min Premium (DTE>=7)", settings.min_premium_gte7, "Minimum premium when days to expiry >= 7"],
            ["Max Premium (DTE>=7)", settings.max_premium_gte7, "Maximum premium when days to expiry >= 7"],
            ["Risk Warning Threshold", settings.risk_warning_threshold, "Risk score to trigger yellow warning"],
            ["Risk Danger Threshold", settings.risk_danger_threshold, "Risk score to trigger red/hedge suggestion"],
            ["Risk Critical Threshold", settings.risk_critical_threshold, "Risk score for critical alert"],
            ["Auto-Refresh Interval (min)", settings.auto_refresh_interval, "Minutes between data refreshes"],
            ["Risk-Free Rate", f"{settings.risk_free_rate*100:.1f}%", "For Black-Scholes calculations"],
            ["Support/Resistance Levels", ", ".join(str(x) for x in settings.support_resistance_levels), "Key levels for hedge calculations"],
            ["", "", ""],
            ["Market Hours", "9:15 AM - 3:30 PM IST", "Mon-Fri (excluding holidays)"],
            ["Weekly Expiry", "Every Tuesday", "Shifted to Monday if Tuesday is a holiday"],
            ["Strike Intervals", "50 points", "Only '00' ending strikes are suggested for selling"],
        ]

        try:
            ws.clear()
            ws.update(range_name="A1", values=data, value_input_option="USER_ENTERED")
            logger.info("Settings sheet updated.")
        except Exception as e:
            logger.error(f"Error updating settings sheet: {e}")

    def read_settings_from_sheet(self) -> Dict[str, Any]:
        """Read user-modified settings from the Settings sheet."""
        try:
            ws = self._spreadsheet.worksheet(settings.sheet_settings)
            data = ws.get_all_values()

            user_settings = {}
            for row in data[1:]:  # Skip header
                if len(row) >= 2 and row[0] and row[1]:
                    user_settings[row[0]] = row[1]
            return user_settings
        except Exception as e:
            logger.warning(f"Could not read settings from sheet: {e}")
            return {}


def _risk_bar(score: float) -> str:
    """Generate a text-based risk bar for display."""
    filled = int(score / 5)  # 20 char bar, each = 5 points
    empty = 20 - filled
    return "[" + "#" * filled + "-" * empty + "]"


# Singleton
_sheets_mgr: Optional[SheetsManager] = None


def get_sheets_manager() -> SheetsManager:
    global _sheets_mgr
    if _sheets_mgr is None:
        _sheets_mgr = SheetsManager()
    return _sheets_mgr
