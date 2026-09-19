"""The daily briefing: one command that tells you what to do today.

Running a store generates far more things you *could* do than things that
matter. This module collapses every signal in the system - orders at risk,
tests that have reached a verdict, cash headroom, KPI breaches, the research
queue - into a single ordered list, then truncates it to what a person can
actually finish today.

The ordering is not cosmetic. It follows what costs the most money if ignored:

    1. Money leaving now      (chargebacks, undelivered paid orders)
    2. Decisions already due  (tests that have bought their answer)
    3. Cash constraints       (are you about to overspend)
    4. Trend breaches         (KPI alerts)
    5. Growth                 (next product, next creative)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import cashflow, kpis, ops, research, testing
from .economics import for_product
from .models import Config
from .store import Store


@dataclass
class BriefItem:
    priority: int
    area: str           # ops / decision / cash / metrics / growth
    title: str
    detail: str
    action: str
    command: str = ""


@dataclass
class Briefing:
    date: str
    headline: str = ""
    items: list[BriefItem] = field(default_factory=list)
    focus: list[BriefItem] = field(default_factory=list)
    scoreboard: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build(store: Store, today: date | None = None, focus_count: int = 3) -> Briefing:
    today = today or date.today()
    config = store.config
    brief = Briefing(date=today.isoformat())
    items: list[BriefItem] = []

    # -- 1. Money leaving right now ------------------------------------------
    queue = ops.action_queue(store.orders, config, today)
    critical = [a for a in queue if a.severity == "critical"]
    high = [a for a in queue if a.severity == "high"]

    for a in critical[:5]:
        items.append(BriefItem(
            priority=1, area="ops",
            title=f"{a.external_id}: {a.issue}",
            detail=a.why_it_matters,
            action=a.do_this,
            command=f"dropship cs {a.macro}" if a.macro else "",
        ))
    if len(critical) > 5:
        items.append(BriefItem(
            1, "ops", f"...and {len(critical) - 5} more critical orders",
            "The queue is longer than one sitting.",
            "Work it top-down; do not open the ad manager until it is clear.",
            "dropship today --all"))
    if high:
        items.append(BriefItem(
            2, "ops", f"{len(high)} orders drifting toward a dispute",
            "Still inside the window where a proactive email prevents a chargeback.",
            "Contact each customer before they contact their bank.",
            "dropship orders sla"))

    # -- 2. Decisions already bought and not yet made ------------------------
    for product in store.products:
        test = store.active_test(product.id)
        if not test or test.spend <= 0:
            continue
        ue = for_product(product, config)
        d = testing.decide(test, ue, config)

        if d.action == testing.KILL:
            items.append(BriefItem(
                1, "decision", f"KILL: {product.name}",
                f"{d.headline} Spent {test.spend:,.2f} for "
                f"{test.purchases} sale(s); breakeven CPA is {ue.breakeven_cpa:,.2f}.",
                "Turn the campaign off today. Every further day is a known loss.",
                f"dropship test decide {test.id}"))
        elif d.action == testing.SCALE:
            safe = cashflow.max_safe_daily_spend(
                ue, config, d.observed_cpa or ue.target_cpa(), 30)
            items.append(BriefItem(
                2, "decision", f"SCALE: {product.name}",
                f"{d.headline} Cash allows up to {safe:,.0f}/day at this CPA.",
                f"Raise daily budget {config.scale_step * 100:.0f}%, hold 48h, "
                f"re-check. Confirm supplier stock first.",
                f"dropship test ladder {test.id}"))
        elif d.action == testing.ITERATE:
            items.append(BriefItem(
                2, "decision", f"FIX: {product.name}",
                f"{d.headline}",
                (d.next_steps[0] if d.next_steps else "Rebuild the weak stage."),
                f"dropship test decide {test.id}"))
        elif d.action == testing.KEEP_TESTING and d.spend_to_verdict > 0:
            items.append(BriefItem(
                4, "decision", f"Still running: {product.name}",
                f"{d.spend_to_verdict:,.0f} more spend buys a real verdict.",
                "Change nothing. Mid-test edits destroy the data you are paying for.",
                ""))

    # -- 3. Cash ------------------------------------------------------------
    live = [p for p in store.products if p.status in ("testing", "scaling", "winner")]
    daily_spend = sum(t.daily_budget for p in live
                      for t in store.tests_for(p.id) if not t.ended)
    if live and daily_spend > 0:
        ue = for_product(live[0], config)
        cpa = ue.target_cpa() or ue.breakeven_cpa
        cash = config.starting_cash + sum(e.amount for e in store.ledger)
        safe = cashflow.max_safe_daily_spend(ue, config, cpa, 45, cash)
        if daily_spend > safe:
            items.append(BriefItem(
                1, "cash", "Daily ad spend exceeds what cash can cover",
                f"Spending {daily_spend:,.0f}/day against a safe maximum of "
                f"{safe:,.0f}/day at a {config.payout_delay_days}-day payout "
                f"delay. Profitable stores die here.",
                f"Cut daily budgets to {safe:,.0f} until payouts catch up.",
                "dropship cash max-spend"))
        elif daily_spend < safe * 0.4:
            items.append(BriefItem(
                4, "cash", "Cash headroom is going unused",
                f"Spending {daily_spend:,.0f}/day with room for {safe:,.0f}/day.",
                "If a product is under target CPA, step budgets up.",
                "dropship cash scenarios"))

    # -- 4. Trend breaches ---------------------------------------------------
    report = kpis.build(store.products, store.orders, store.tests, store.ledger,
                        config, 30, today)
    for alert in report.alerts:
        if alert.severity == "critical":
            items.append(BriefItem(1, "metrics", alert.metric.replace("_", " ").title(),
                                   alert.message, alert.fix, "dropship kpi"))
        elif alert.severity == "warning":
            items.append(BriefItem(3, "metrics", alert.metric.replace("_", " ").title(),
                                   alert.message, alert.fix, "dropship kpi"))

    # -- 5. Growth -----------------------------------------------------------
    testing_now = [p for p in store.products if p.status == "testing"]
    approved = [p for p in store.products if p.status == "approved"]
    candidates = [p for p in store.products if p.status == "candidate"]

    if len(testing_now) < 2 and approved:
        nxt = max(approved, key=lambda p: p.score)
        items.append(BriefItem(
            3, "growth", f"Open test slot - launch {nxt.name}",
            f"Scored {nxt.score:.0f} ({nxt.tier}-tier) and waiting. "
            f"Idle test slots are the real cost of a slow week.",
            f"Launch at {nxt.test_budget:,.0f} total budget.",
            f"dropship test plan {nxt.id}"))
    if candidates:
        items.append(BriefItem(
            4, "growth", f"{len(candidates)} products sourced but never scored",
            "Unscored products are a decision you are avoiding, not an option "
            "you are keeping open.",
            "Score them and either approve or delete.",
            "dropship product score --all"))
    if not store.products:
        items.append(BriefItem(
            1, "growth", "No products in the system",
            "Nothing to decide about yet.",
            "Add your first candidate and score it.",
            "dropship product add --name '...' --price 49.99 --cogs 8.50"))

    winners = [p for p in store.products if p.status in ("scaling", "winner")]
    if winners and len(store.suppliers) < 2:
        items.append(BriefItem(
            3, "growth", "Winners running on a single supplier",
            "One stockout, price rise or suspension takes the product offline "
            "with nothing to fall back on.",
            "Qualify a second supplier and order a sample this week.",
            "dropship supplier add --name '...'"))

    # Within a priority, order by what costs most if ignored - not
    # alphabetically, which would put "cash" ahead of a dying order.
    area_rank = {"ops": 0, "decision": 1, "cash": 2, "metrics": 3, "growth": 4}
    items.sort(key=lambda i: (i.priority, area_rank.get(i.area, 9)))
    brief.items = items
    brief.focus = items[:focus_count]

    brief.scoreboard = {
        "revenue_30d": report.revenue,
        "net_profit_30d": report.net_profit,
        "blended_roas": report.blended_roas,
        "breakeven_roas": report.breakeven_roas,
        "orders_30d": report.orders,
        "cash": report.cash_position,
        "products_testing": len(testing_now),
        "products_scaling": len(winners),
        "critical_actions": len(critical),
        "open_actions": len(queue),
    }

    if critical:
        brief.headline = (f"{len(critical)} order(s) need rescuing before anything "
                          f"else. Fulfilment failures cost more than any ad decision.")
    elif any(i.area == "decision" and i.title.startswith("KILL") for i in items):
        brief.headline = "A test has reached its verdict and it is a kill. Act today."
    elif any(i.area == "decision" and i.title.startswith("SCALE") for i in items):
        brief.headline = "You have a winner. Scale it in steps and watch the cash."
    elif report.net_profit > 0:
        brief.headline = (f"Profitable over 30 days ({report.net_profit:,.0f}). "
                          f"Keep testing creative - it is the only uncapped input.")
    else:
        brief.headline = "No fires. Use the time on research and creative."

    return brief


def portfolio(store: Store) -> list[dict]:
    """Every product, its economics and its live verdict, in one table."""
    rows = []
    for p in store.products:
        ue = for_product(p, store.config)
        test = store.active_test(p.id)
        verdict = ""
        if test and test.spend > 0:
            verdict = testing.decide(test, ue, store.config).action
        orders = store.orders_for(p.id)
        spend = sum(t.spend for t in store.tests_for(p.id))
        revenue = sum(o.revenue for o in orders)
        rows.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "score": p.score,
            "tier": p.tier,
            "price": p.price,
            "landed_cost": p.landed_cost,
            "margin_multiple": p.margin_multiple,
            "cm": ue.contribution_margin,
            "be_roas": ue.breakeven_roas,
            "be_cpa": ue.breakeven_cpa,
            "orders": len(orders),
            "spend": spend,
            "revenue": revenue,
            "roas": revenue / spend if spend else 0.0,
            "cpa": spend / len(orders) if orders else 0.0,
            "profit": len(orders) * ue.contribution_margin - spend,
            "verdict": verdict,
        })
    rows.sort(key=lambda r: -r["profit"])
    return rows
