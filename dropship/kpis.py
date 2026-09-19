"""KPI rollups and health checks.

Dashboards are easy to build and easy to ignore. The rule here is that every
number comes with a threshold and a consequence, so the output is a list of
things that are wrong rather than a wall of figures that are fine.

Only blended numbers can be trusted. Ad platforms attribute generously and
will happily report a 3x ROAS on a month you lost money; blended ROAS
(all revenue / all ad spend) cannot be flattered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .economics import for_product
from .models import AdTest, Config, LedgerEntry, Order, Product
from .ops import fulfilment_health


@dataclass
class Alert:
    severity: str    # critical / warning / info
    metric: str
    message: str
    fix: str


@dataclass
class KPIReport:
    period_days: int
    start: str
    end: str

    orders: int = 0
    revenue: float = 0.0
    refunds: float = 0.0
    net_revenue: float = 0.0
    aov: float = 0.0
    cogs: float = 0.0
    ad_spend: float = 0.0
    fees: float = 0.0
    fixed_costs: float = 0.0
    contribution_margin: float = 0.0
    net_profit: float = 0.0
    net_margin: float = 0.0

    blended_roas: float = 0.0
    blended_cac: float = 0.0
    breakeven_roas: float = 0.0

    refund_rate: float = 0.0
    chargeback_rate: float = 0.0
    on_time_rate: float = 0.0
    sla_breaches: int = 0

    cash_position: float = 0.0
    alerts: list[Alert] = field(default_factory=list)
    by_product: list[dict] = field(default_factory=list)


def _in_window(iso: str, start: date, end: date) -> bool:
    if not iso:
        return False
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return False
    return start <= d <= end


def build(products: list[Product], orders: list[Order], tests: list[AdTest],
          ledger: list[LedgerEntry], config: Config, days: int = 30,
          today: date | None = None) -> KPIReport:
    end = today or date.today()
    start = end - timedelta(days=days - 1)
    report = KPIReport(period_days=days, start=start.isoformat(), end=end.isoformat())

    window = [o for o in orders if _in_window(o.ordered_date, start, end)]
    paid = [o for o in window if o.status not in ("cancelled",)]
    refunded = [o for o in window if o.status in ("refunded", "chargeback")]

    report.orders = len(paid)
    report.revenue = sum(o.revenue for o in paid)
    report.refunds = sum(o.revenue for o in refunded)
    report.net_revenue = report.revenue - report.refunds
    report.aov = report.revenue / report.orders if report.orders else 0.0
    report.cogs = sum(o.cogs for o in paid)

    # Ad spend: prefer the ledger (what actually left the bank), fall back to
    # the ad platform figures on live tests.
    ledger_ads = sum(-e.amount for e in ledger
                     if e.category == "ads" and _in_window(e.date, start, end)
                     and e.amount < 0)
    report.ad_spend = ledger_ads or sum(
        t.spend for t in tests if _in_window(t.started, start, end) or not t.ended)

    report.fees = sum(o.revenue * config.payment_rate + config.payment_fixed
                      for o in paid)
    report.fees += len([o for o in window if o.status == "chargeback"]) * config.chargeback_fee
    report.fixed_costs = config.fixed_monthly_costs * (days / 30.0)

    report.contribution_margin = (report.net_revenue - report.cogs - report.fees
                                  - config.cs_cost_per_order * report.orders)
    report.net_profit = report.contribution_margin - report.ad_spend - report.fixed_costs
    report.net_margin = report.net_profit / report.revenue if report.revenue else 0.0

    report.blended_roas = report.revenue / report.ad_spend if report.ad_spend else 0.0
    report.blended_cac = report.ad_spend / report.orders if report.orders else 0.0

    # Portfolio-weighted breakeven ROAS, so the comparison is like-for-like.
    weighted, weight = 0.0, 0.0
    for p in products:
        n = len([o for o in paid if o.product_id == p.id])
        if n:
            ue = for_product(p, config)
            if ue.breakeven_roas != float("inf"):
                weighted += ue.breakeven_roas * n
                weight += n
    report.breakeven_roas = weighted / weight if weight else 0.0

    total = len(window) or 1
    report.refund_rate = len([o for o in window if o.status == "refunded"]) / total
    report.chargeback_rate = len([o for o in window if o.status == "chargeback"]) / total

    health = fulfilment_health(window, config, end)
    report.on_time_rate = health["on_time_rate"]
    report.sla_breaches = health["sla_breaches"]

    report.cash_position = config.starting_cash + sum(e.amount for e in ledger)
    report.by_product = _per_product(products, paid, tests, config)
    report.alerts = check_health(report, config)
    return report


def _per_product(products: list[Product], orders: list[Order],
                 tests: list[AdTest], config: Config) -> list[dict]:
    rows = []
    for p in products:
        p_orders = [o for o in orders if o.product_id == p.id]
        p_tests = [t for t in tests if t.product_id == p.id]
        ue = for_product(p, config)
        spend = sum(t.spend for t in p_tests)
        revenue = sum(o.revenue for o in p_orders)
        n = len(p_orders)
        rows.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "score": p.score,
            "tier": p.tier,
            "orders": n,
            "revenue": revenue,
            "ad_spend": spend,
            "roas": revenue / spend if spend else 0.0,
            "breakeven_roas": ue.breakeven_roas,
            "cpa": spend / n if n else 0.0,
            "breakeven_cpa": ue.breakeven_cpa,
            "contribution_margin": ue.contribution_margin,
            "profit": n * ue.contribution_margin - spend,
        })
    rows.sort(key=lambda r: -r["profit"])
    return rows


def check_health(r: KPIReport, config: Config) -> list[Alert]:
    """Turn numbers into a to-do list. Order matters: the first alert is the
    one costing the most money right now."""
    alerts: list[Alert] = []

    if r.ad_spend > 0 and r.breakeven_roas > 0 and r.blended_roas < r.breakeven_roas:
        alerts.append(Alert(
            "critical", "blended_roas",
            f"Blended ROAS {r.blended_roas:.2f}x is below breakeven "
            f"{r.breakeven_roas:.2f}x. Every extra dollar of ad spend loses money.",
            "Pause the worst product by profit today. Do not raise budgets "
            "anywhere until blended ROAS clears breakeven."))

    if r.net_profit < 0 and r.revenue > 0:
        alerts.append(Alert(
            "critical", "net_profit",
            f"Net loss of {abs(r.net_profit):,.2f} over {r.period_days} days.",
            "Rank products by profit and cut the bottom one. Losses concentrate "
            "in one or two SKUs far more often than they spread evenly."))

    if r.chargeback_rate > 0.01:
        alerts.append(Alert(
            "critical", "chargeback_rate",
            f"Chargeback rate {r.chargeback_rate * 100:.2f}% is above the 1% "
            f"threshold where processors start holding funds - and above 2% "
            f"they close accounts.",
            "Fix fulfilment speed and answer support inside 24h. Refund "
            "proactively on anything late: a refund costs a third of a dispute."))
    elif r.chargeback_rate > 0.005:
        alerts.append(Alert(
            "warning", "chargeback_rate",
            f"Chargeback rate {r.chargeback_rate * 100:.2f}% is climbing toward "
            f"the 1% danger line.",
            "Audit the late orders now, before the next monitoring review."))

    if r.refund_rate > config.refund_rate * 1.5 and r.orders >= 20:
        alerts.append(Alert(
            "warning", "refund_rate",
            f"Refund rate {r.refund_rate * 100:.1f}% is well above the "
            f"{config.refund_rate * 100:.1f}% your economics assume, so your real "
            f"breakeven is worse than the one every decision is using.",
            f"Update config refund_rate to {r.refund_rate:.3f} and re-run the "
            f"numbers. Then fix the cause - usually delivery time or a "
            f"listing that oversells."))

    if r.sla_breaches > 0:
        alerts.append(Alert(
            "warning", "fulfilment",
            f"{r.sla_breaches} orders are past their fulfilment SLA.",
            "Run `dropship today` and clear the critical queue before touching ads."))

    if r.on_time_rate and r.on_time_rate < 0.85:
        alerts.append(Alert(
            "warning", "on_time_rate",
            f"Only {r.on_time_rate * 100:.0f}% of orders arrived within the "
            f"promised window.",
            "Either speed up the supplier or lengthen the promise. Quoting a "
            "date you miss is worse than quoting a longer one you hit."))

    if r.cash_position < config.fixed_monthly_costs * 2:
        alerts.append(Alert(
            "critical", "cash",
            f"Cash position {r.cash_position:,.2f} is under two months of fixed "
            f"costs.",
            "Cut daily ad spend to the level `dropship cash max-spend` returns "
            "and hold there until payouts catch up."))

    if r.net_margin > 0 and r.net_margin < 0.05 and r.revenue > 1000:
        alerts.append(Alert(
            "info", "net_margin",
            f"Net margin {r.net_margin * 100:.1f}% leaves no room for a bad week.",
            "Raise AOV with a bundle or post-purchase upsell. It moves margin "
            "faster than any bid adjustment."))

    if not alerts:
        alerts.append(Alert("info", "all_clear",
                            "No threshold breached this period.",
                            "Spend the time on creative testing - it is the "
                            "only input with uncapped upside."))
    return alerts
