"""
Nifty Options Dashboard — Configuration Settings
All configurable parameters for the dashboard.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List


class DashboardSettings(BaseSettings):
    # Nifty lot size (changed from 75 to 65 effective Jan 2026)
    lot_size: int = 65

    # Strike suggestion parameters
    strike_offset: int = 200  # Points away from VIX range
    max_delta: float = 0.20  # Maximum acceptable delta for suggested strikes
    min_premium_gte7: float = 12.0  # Min premium when DTE >= 7
    max_premium_gte7: float = 60.0  # Max premium when DTE >= 7

    # Risk thresholds
    risk_warning_threshold: int = 30
    risk_danger_threshold: int = 60
    risk_critical_threshold: int = 80

    # Risk weights
    risk_weight_delta: float = 0.30
    risk_weight_iv: float = 0.20
    risk_weight_premium: float = 0.20
    risk_weight_proximity: float = 0.25
    risk_weight_theta: float = 0.05

    # Risk indicator thresholds
    delta_warning: float = 0.15
    delta_danger: float = 0.25
    delta_critical: float = 0.35

    iv_warning_pct: float = 20.0  # IV increase % from entry
    iv_danger_pct: float = 40.0
    iv_critical_pct: float = 60.0

    premium_warning_mult: float = 2.0  # Premium multiplier from entry
    premium_danger_mult: float = 3.0
    premium_critical_mult: float = 5.0

    proximity_warning_pct: float = 60.0  # % of distance consumed
    proximity_danger_pct: float = 80.0
    proximity_critical_pts: int = 50  # Points from strike

    # Auto-refresh interval in minutes
    auto_refresh_interval: int = 3

    # Risk-free rate for Black-Scholes (India 91-day T-bill rate)
    risk_free_rate: float = 0.065

    # Key support/resistance levels (user-editable)
    support_resistance_levels: List[int] = Field(
        default=[22000, 22500, 23000, 23500, 24000, 24500, 25000, 25500, 26000]
    )

    # Market hours (IST)
    market_open_hour: int = 9
    market_open_minute: int = 15
    market_close_hour: int = 15
    market_close_minute: int = 30

    # NSE API settings
    nse_base_url: str = "https://www.nseindia.com"
    nse_option_chain_url: str = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    nse_all_indices_url: str = "https://www.nseindia.com/api/allIndices"

    # Google Sheets settings
    google_sheets_id: str = ""
    google_credentials_file: str = "credentials.json"

    # Sheet names
    sheet_dashboard: str = "Dashboard"
    sheet_open_positions: str = "Open Positions"
    sheet_risk_monitor: str = "Risk Monitor"
    sheet_trade_history: str = "Trade History"
    sheet_option_chain: str = "Option Chain Data"
    sheet_settings: str = "Settings & Config"

    class Config:
        env_file = ".env"
        env_prefix = "NIFTY_"


settings = DashboardSettings()
