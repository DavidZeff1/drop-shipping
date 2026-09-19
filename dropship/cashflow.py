"""Cash flow: the reason profitable stores still die.

A dropshipping store pays for ads today and for goods today, but gets paid by
its processor in three days - or twenty-one, if a rolling reserve is in place.
Scale fast enough and a *profitable* store runs out of cash before the money
it already earned arrives.

This module simulates that gap day by day so you can answer the only two
questions that matter when a product starts working:

    "How much can I safely spend per day?"
    "On which day do I run out?"
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .economics import UnitEconomics
from .models import Config
from .stats import bisect


@dataclass
class DayRow:
    day: int
    ad_spend: float = 0.0        # incurred today (may be paid later)
    orders: float = 0.0
    revenue_booked: float = 0.0  # what the customer paid today
    cash_in: float = 0.0         # what actually landed in the bank today
    cogs_out: float = 0.0
    ads_out: float = 0.0
    fixed_out: float = 0.0
    refunds_out: float = 0.0
    reserve_held: float = 0.0
    reserve_released: float = 0.0
    balance: float = 0.0

    @property
    def cash_out(self) -> float:
        return self.cogs_out + self.ads_out + self.fixed_out + self.refunds_out


@dataclass
class CashResult:
    rows: list[DayRow] = field(default_factory=list)
    starting_cash: float = 0.0
    ending_cash: float = 0.0
    min_balance: float = 0.0
    min_balance_day: int = 0
    insolvent_day: int | None = None
    peak_working_capital: float = 0.0
    total_revenue: float = 0.0
    total_ad_spend: float = 0.0
    total_profit: float = 0.0
    reserve_outstanding: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def solvent(self) -> bool:
        return self.insolvent_day is None


def simulate(ue: UnitEconomics, config: Config, daily_ad_spend: float,
             cpa: float, days: int = 90, starting_cash: float | None = None,
             growth_rate: float = 0.0) -> CashResult:
    """Run the business forward day by day.

    ``growth_rate`` compounds daily ad spend (0.03 = +3%/day, a realistic
    scaling ramp). That is where cash crunches are born: spend compounds
    immediately, revenue arrives on a delay.
    """
    cash = config.starting_cash if starting_cash is None else starting_cash
    result = CashResult(starting_cash=cash)

    if cpa <= 0:
        result.warnings.append("CPA must be positive to simulate.")
        return result

    payout_delay = max(0, int(config.payout_delay_days))
    reserve_rate = max(0.0, config.rolling_reserve_rate)
    reserve_days = max(0, int(config.reserve_release_days))
    ad_delay = max(0, int(config.ad_payment_delay_days))
    refund_lag = max(0, int(config.refund_lag_days))
    daily_fixed = config.fixed_monthly_costs / 30.0

    horizon = days + payout_delay + reserve_days + refund_lag + ad_delay + 2
    cash_in_sched = [0.0] * (horizon + 1)
    reserve_sched = [0.0] * (horizon + 1)
    ads_sched = [0.0] * (horizon + 1)
    refund_sched = [0.0] * (horizon + 1)

    spend = daily_ad_spend
    peak_deficit = 0.0
    cumulative_out = 0.0
    cumulative_in = 0.0

    for day in range(1, days + 1):
        row = DayRow(day=day)
        row.ad_spend = spend
        orders = spend / cpa
        row.orders = orders
        revenue = orders * ue.aov
        row.revenue_booked = revenue

        # Goods are paid for when the order is placed - same day, in practice.
        row.cogs_out = orders * ue.variable_cogs

        # Processor holds a reserve, releases the rest after the payout delay.
        held = revenue * reserve_rate
        net_now = revenue - held
        if day + payout_delay <= horizon:
            cash_in_sched[day + payout_delay] += net_now
        if held and day + payout_delay + reserve_days <= horizon:
            reserve_sched[day + payout_delay + reserve_days] += held
        row.reserve_held = held

        # Ads: prepaid card is same-day, net terms push it out.
        if day + ad_delay <= horizon:
            ads_sched[day + ad_delay] += spend

        # Refunds land weeks later, after the goods have already been paid for.
        refunded_orders = orders * config.refund_rate
        refund_cost = refunded_orders * ue.aov
        if day + refund_lag <= horizon:
            refund_sched[day + refund_lag] += refund_cost

        row.cash_in = cash_in_sched[day]
        row.reserve_released = reserve_sched[day]
        row.ads_out = ads_sched[day]
        row.refunds_out = refund_sched[day]
        row.fixed_out = daily_fixed

        cash += row.cash_in + row.reserve_released - row.cash_out
        row.balance = cash
        result.rows.append(row)

        cumulative_in += row.cash_in + row.reserve_released
        cumulative_out += row.cash_out
        peak_deficit = max(peak_deficit, cumulative_out - cumulative_in)

        result.total_revenue += revenue
        result.total_ad_spend += spend

        if cash < 0 and result.insolvent_day is None:
            result.insolvent_day = day

        spend *= (1.0 + growth_rate)

    result.ending_cash = cash
    balances = [(r.balance, r.day) for r in result.rows]
    result.min_balance, result.min_balance_day = min(balances) if balances else (cash, 0)
    result.peak_working_capital = peak_deficit
    result.reserve_outstanding = sum(reserve_sched[days + 1:])

    total_orders = sum(r.orders for r in result.rows)
    result.total_profit = total_orders * (ue.contribution_margin - cpa) \
        - daily_fixed * days

    _add_warnings(result, config, ue, cpa, days)
    return result


def _add_warnings(result: CashResult, config: Config, ue: UnitEconomics,
                  cpa: float, days: int) -> None:
    if result.insolvent_day is not None:
        result.warnings.append(
            f"INSOLVENT on day {result.insolvent_day}. The business is "
            f"{'profitable' if result.total_profit > 0 else 'unprofitable'} on "
            f"paper but runs out of cash first."
        )
    elif result.min_balance < result.starting_cash * 0.2:
        result.warnings.append(
            f"Cash dips to {result.min_balance:,.0f} on day "
            f"{result.min_balance_day} - under 20% of your starting balance. "
            f"One chargeback wave or a supplier price rise ends the run."
        )

    if config.rolling_reserve_rate > 0:
        result.warnings.append(
            f"{config.rolling_reserve_rate * 100:.0f}% rolling reserve means "
            f"{result.reserve_outstanding:,.0f} of your own money is still held "
            f"by the processor at day {days}."
        )
    if config.payout_delay_days >= 7:
        result.warnings.append(
            f"A {config.payout_delay_days}-day payout delay is the single "
            f"biggest constraint on how fast you can scale. Negotiate it down "
            f"before you negotiate anything else."
        )
    if cpa >= ue.contribution_margin:
        result.warnings.append(
            f"CPA {cpa:,.2f} is at or above contribution margin "
            f"{ue.contribution_margin:,.2f}: every order deepens the hole. "
            f"Cash flow cannot fix broken unit economics."
        )


def max_safe_daily_spend(ue: UnitEconomics, config: Config, cpa: float,
                         days: int = 60, starting_cash: float | None = None,
                         buffer: float = 0.25, growth_rate: float = 0.0
                         ) -> float:
    """Highest daily ad spend that never drops cash below a safety buffer.

    ``buffer`` is the fraction of starting cash you refuse to go below. Set it
    to zero only if you enjoy explaining declined supplier payments.

    Returns 0 when contribution margin is non-positive. Strictly as a cash
    question there is always *some* spend slow enough to survive the horizon -
    you simply lose money more slowly than you run out of it - but reporting
    that as "safe" would invite someone to spend it. No daily budget is safe on
    a product that loses money on every order; the fix is price or cost, not
    pacing.
    """
    if ue.contribution_margin <= 0:
        return 0.0
    cash = config.starting_cash if starting_cash is None else starting_cash
    floor = cash * buffer

    def min_balance_at(spend: float) -> float:
        res = simulate(ue, config, spend, cpa, days, cash, growth_rate)
        return res.min_balance - floor

    if min_balance_at(1.0) < 0:
        return 0.0

    hi = max(10.0, cash)
    while min_balance_at(hi) > 0 and hi < cash * 1000:
        hi *= 2.0
    return round(bisect(min_balance_at, 1.0, hi, 0.0), 2)


def runway_days(ue: UnitEconomics, config: Config, daily_ad_spend: float,
                cpa: float, starting_cash: float | None = None,
                growth_rate: float = 0.0, horizon: int = 365) -> int | None:
    """Days until cash hits zero, or None if it never does within the horizon."""
    res = simulate(ue, config, daily_ad_spend, cpa, horizon,
                   starting_cash, growth_rate)
    return res.insolvent_day


def scenarios(ue: UnitEconomics, config: Config, cpa: float, days: int = 60,
              starting_cash: float | None = None) -> list[dict]:
    """Same product, four futures. Shows what the delay actually costs you."""
    cash = config.starting_cash if starting_cash is None else starting_cash
    safe = max_safe_daily_spend(ue, config, cpa, days, cash)
    rows = []
    for label, spend, growth in (
        ("Conservative (50% of safe)", safe * 0.5, 0.0),
        ("Safe maximum", safe, 0.0),
        ("Aggressive (1.5x safe)", safe * 1.5, 0.0),
        ("Safe + 3%/day scaling", safe, 0.03),
    ):
        res = simulate(ue, config, spend, cpa, days, cash, growth)
        rows.append({
            "scenario": label,
            "daily_spend": round(spend, 2),
            "growth": growth,
            "ending_cash": round(res.ending_cash, 2),
            "min_balance": round(res.min_balance, 2),
            "min_day": res.min_balance_day,
            "profit": round(res.total_profit, 2),
            "insolvent_day": res.insolvent_day,
            "peak_working_capital": round(res.peak_working_capital, 2),
        })
    return rows
