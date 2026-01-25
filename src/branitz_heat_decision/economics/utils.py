from __future__ import annotations

import math
from typing import List


def crf(discount_rate: float, lifetime_years: int) -> float:
    """
    Capital Recovery Factor (CRF):

      CRF = r(1+r)^n / ((1+r)^n - 1)

    For r=0, CRF = 1/n.
    """
    r = float(discount_rate)
    n = int(lifetime_years)
    if n <= 0:
        raise ValueError("lifetime_years must be > 0")
    if abs(r) < 1e-12:
        return 1.0 / float(n)
    a = (1.0 + r) ** n
    return float(r * a / (a - 1.0))


def calculate_crf(discount_rate: float, lifetime_years: int) -> float:
    """
    Calculate Capital Recovery Factor (CRF).

    Formula: CRF = r*(1+r)^n / ((1+r)^n - 1)
    Special case: if r=0, CRF = 1/n
    """
    return crf(discount_rate, lifetime_years)


def calculate_pv_factor(discount_rate: float, lifetime_years: int) -> float:
    """
    Calculate present value factor for annuity.

    Formula: PV = Σ(1/(1+r)^t) for t=1..n
    Closed form: PV = (1 - (1+r)^(-n)) / r
    Special case: r=0 => PV = n
    """
    r = float(discount_rate)
    n = int(lifetime_years)
    if n <= 0:
        raise ValueError("lifetime_years must be > 0")
    if abs(r) < 1e-12:
        return float(n)
    return float((1.0 - (1.0 + r) ** (-n)) / r)


def calculate_npv(cash_flows: List[float], discount_rate: float) -> float:
    """
    Calculate Net Present Value (NPV) of cash flow series.

    Args:
        cash_flows: Annual cash flows (EUR), starting with year 0.
        discount_rate: Annual discount rate.
    """
    r = float(discount_rate)
    npv = 0.0
    for t, cf in enumerate(cash_flows):
        npv += float(cf) / ((1.0 + r) ** t)
    return float(npv)


def annualize_capex(capex_eur: float, discount_rate: float, lifetime_years: int) -> float:
    """Convert CAPEX (EUR) into equivalent annual cost (EUR/a) using CRF."""
    return float(capex_eur) * crf(discount_rate, lifetime_years)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(x)))


def safe_div(numer: float, denom: float, default: float = 0.0) -> float:
    d = float(denom)
    if abs(d) < 1e-18:
        return float(default)
    return float(numer) / d


def percentile(values: list[float], q: float) -> float:
    """Simple percentile helper without numpy dependency."""
    if not values:
        return float("nan")
    xs = sorted(float(v) for v in values)
    q = clamp(q, 0.0, 1.0)
    i = q * (len(xs) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    if lo == hi:
        return xs[lo]
    w = i - lo
    return xs[lo] * (1.0 - w) + xs[hi] * w

