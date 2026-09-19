"""Small statistics toolkit, stdlib only.

Everything here exists to answer one question honestly: given the money I have
spent and the sales I have seen, how sure can I be about the true CPA?

No scipy, no numpy - this has to run on any machine with Python 3.10+.
"""

from __future__ import annotations

import math

_TINY = 1e-300
_EPS = 1e-14


def _gser(a: float, x: float) -> float:
    """Lower regularized incomplete gamma P(a, x) by series expansion."""
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(1000):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Upper regularized incomplete gamma Q(a, x) by continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _TINY:
            d = _TINY
        c = b + an / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gamma_cdf_reg(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) = CDF of Gamma(a, 1)."""
    if a <= 0:
        raise ValueError("a must be positive")
    if x <= 0:
        return 0.0
    if x < a + 1.0:
        return _gser(a, x)
    return 1.0 - _gcf(a, x)


def gamma_ppf_reg(p: float, a: float) -> float:
    """Inverse of gamma_cdf_reg: find x with P(a, x) = p. Bisection."""
    if not 0.0 < p < 1.0:
        if p <= 0.0:
            return 0.0
        return math.inf
    lo, hi = 0.0, max(a + 10.0 * math.sqrt(a) + 10.0, 1.0)
    while gamma_cdf_reg(a, hi) < p:
        hi *= 2.0
        if hi > 1e12:
            return hi
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if gamma_cdf_reg(a, mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12 * max(1.0, hi):
            break
    return 0.5 * (lo + hi)


def chi2_ppf(p: float, dof: float) -> float:
    """Inverse chi-square CDF. Chi2(k) == Gamma(shape=k/2, scale=2)."""
    if dof <= 0:
        return 0.0
    return 2.0 * gamma_ppf_reg(p, dof / 2.0)


def poisson_rate_ci(events: int, exposure: float, confidence: float = 0.90
                    ) -> tuple[float, float]:
    """Exact (Garwood) confidence interval for a Poisson rate.

    ``events`` sales observed over ``exposure`` units of ad spend. Returns the
    (low, high) bounds on sales-per-unit-spend. Exact rather than normal
    approximation because dropshipping tests routinely run on 0-10 sales, where
    the normal approximation is simply wrong.
    """
    if exposure <= 0:
        return (0.0, math.inf)
    alpha = 1.0 - confidence
    lo = chi2_ppf(alpha / 2.0, 2 * events) / 2.0 if events > 0 else 0.0
    hi = chi2_ppf(1.0 - alpha / 2.0, 2 * events + 2) / 2.0
    return (lo / exposure, hi / exposure)


def poisson_pmf_zero(lam: float) -> float:
    """P(observing zero events) when the true mean is lam."""
    return math.exp(-lam) if lam < 700 else 0.0


def wilson_interval(successes: int, trials: int, confidence: float = 0.90
                    ) -> tuple[float, float]:
    """Wilson score interval for a proportion. Well-behaved at small n and p=0."""
    if trials <= 0:
        return (0.0, 1.0)
    z = z_score(confidence)
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = p + z * z / (2 * trials)
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def z_score(confidence: float) -> float:
    """Two-sided z for a confidence level, via the inverse normal CDF."""
    return _norm_ppf(0.5 + confidence / 2.0)


def _norm_ppf(p: float) -> float:
    """Acklam's inverse normal CDF approximation. Accurate to ~1e-9."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def bisect(fn, lo: float, hi: float, target: float = 0.0, iterations: int = 100
           ) -> float:
    """Find x in [lo, hi] where fn(x) == target, assuming fn is monotonic."""
    f_lo = fn(lo) - target
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        f_mid = fn(mid) - target
        if (f_mid < 0) == (f_lo < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
