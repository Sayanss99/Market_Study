"""
Black-Scholes Greeks Calculator
Calculates Delta, Gamma, Theta, Vega for European options.
Used as fallback when Sensibull Greeks data is unavailable.
"""

import math
from typing import NamedTuple
from scipy.stats import norm

from config.settings import settings


class Greeks(NamedTuple):
    delta: float
    gamma: float
    theta: float
    vega: float
    theoretical_price: float


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate d1 in the Black-Scholes formula."""
    if T <= 0 or sigma <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate d2 in the Black-Scholes formula."""
    if T <= 0 or sigma <= 0:
        return 0.0
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float,
    option_type: str = "CE",
    risk_free_rate: float = None,
) -> Greeks:
    """
    Calculate Black-Scholes Greeks for a European option.

    Args:
        spot: Current underlying price (Nifty spot)
        strike: Option strike price
        time_to_expiry_years: Time to expiry in years (e.g., 5/365 for 5 days)
        iv: Implied volatility as decimal (e.g., 0.145 for 14.5%)
        option_type: "CE" for call, "PE" for put
        risk_free_rate: Risk-free rate (defaults to settings value)

    Returns:
        Greeks namedtuple with delta, gamma, theta, vega, theoretical_price
    """
    if risk_free_rate is None:
        risk_free_rate = settings.risk_free_rate

    S = spot
    K = strike
    T = max(time_to_expiry_years, 1e-10)  # Avoid division by zero
    r = risk_free_rate
    sigma = iv

    if sigma <= 0 or S <= 0 or K <= 0:
        return Greeks(0.0, 0.0, 0.0, 0.0, 0.0)

    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)

    sqrt_T = math.sqrt(T)
    n_d1 = norm.cdf(d1)
    n_d2 = norm.cdf(d2)
    n_neg_d1 = norm.cdf(-d1)
    n_neg_d2 = norm.cdf(-d2)
    pdf_d1 = norm.pdf(d1)

    exp_neg_rT = math.exp(-r * T)

    if option_type.upper() == "CE":
        # Call option
        price = S * n_d1 - K * exp_neg_rT * n_d2
        delta = n_d1
        theta = (
            (-S * pdf_d1 * sigma / (2 * sqrt_T))
            - (r * K * exp_neg_rT * n_d2)
        ) / 365  # Per day
    else:
        # Put option
        price = K * exp_neg_rT * n_neg_d2 - S * n_neg_d1
        delta = n_d1 - 1  # Negative for puts
        theta = (
            (-S * pdf_d1 * sigma / (2 * sqrt_T))
            + (r * K * exp_neg_rT * n_neg_d2)
        ) / 365  # Per day

    gamma = pdf_d1 / (S * sigma * sqrt_T)
    vega = S * pdf_d1 * sqrt_T / 100  # Per 1% change in IV

    return Greeks(
        delta=round(delta, 6),
        gamma=round(gamma, 6),
        theta=round(theta, 4),
        vega=round(vega, 4),
        theoretical_price=round(price, 2),
    )


def days_to_years(days: int) -> float:
    """Convert calendar days to fraction of year."""
    return days / 365.0


def calculate_iv_from_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    market_price: float,
    option_type: str = "CE",
    risk_free_rate: float = None,
    precision: float = 1e-5,
    max_iterations: int = 100,
) -> float:
    """
    Calculate implied volatility from market price using Newton-Raphson method.
    Returns IV as decimal (e.g., 0.145 for 14.5%).
    """
    if risk_free_rate is None:
        risk_free_rate = settings.risk_free_rate

    S = spot
    K = strike
    T = max(time_to_expiry_years, 1e-10)
    r = risk_free_rate

    # Initial guess
    sigma = 0.20

    for _ in range(max_iterations):
        greeks = calculate_greeks(S, K, T, sigma, option_type, r)
        price_diff = greeks.theoretical_price - market_price

        if abs(price_diff) < precision:
            return sigma

        vega = greeks.vega * 100  # Convert back from per-1% to per-1.0
        if abs(vega) < 1e-10:
            break

        sigma -= price_diff / vega
        sigma = max(sigma, 0.001)  # Keep IV positive

    return sigma
