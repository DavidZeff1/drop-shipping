"""The decision engine: kill, iterate, hold, or scale.

Two mistakes destroy dropshipping accounts, and they are opposites:

  * killing a winner on day two because of one bad morning, and
  * feeding a loser for three weeks because "it just needs more data".

Both come from reading noise as signal. This module replaces the gut feel with
an exact Poisson confidence interval on the true cost per acquisition, then
compares that interval - not the point estimate - against breakeven.

The rule in one sentence: act only when the *whole plausible range* of your
true CPA sits on one side of breakeven.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .economics import UnitEconomics
from .models import AdTest, Config
from .stats import poisson_rate_ci, poisson_pmf_zero, wilson_interval

# Decisions, in the order they get more expensive to get wrong.
NOT_STARTED = "NOT_STARTED"
KEEP_TESTING = "KEEP_TESTING"
ITERATE = "ITERATE"
HOLD = "HOLD"
SCALE = "SCALE"
KILL = "KILL"

# Healthy bands for a paid-social ecommerce funnel. Deliberately generous at
# the low end: these are "something is broken" thresholds, not targets.
BENCHMARKS = {
    "ctr":            (0.008, 0.015),   # link clicks / impressions
    "lpv_rate":       (0.70, 0.85),     # landing page views / clicks
    "atc_rate":       (0.05, 0.09),     # add to cart / landing page views
    "checkout_rate":  (0.40, 0.60),     # checkouts / add to cart
    "purchase_rate":  (0.40, 0.60),     # purchases / checkouts
}

_STAGE_FIXES = {
    "ctr": (
        "Creative or audience. The ad is not earning the click.",
        ["Write 5 new hooks aimed at the first 3 seconds",
         "Lead with the problem, not the product",
         "Test a native/UGC cut against the polished one",
         "Broaden the audience - a narrow one burns out fast"],
    ),
    "lpv_rate": (
        "Page speed or link mismatch. People click, then leave before it loads.",
        ["Test the page on 4G, not office wifi - target under 2.5s",
         "Compress hero images and drop unused apps",
         "Make the landing page continue the ad's promise word-for-word"],
    ),
    "atc_rate": (
        "The product page is not converting interest into intent.",
        ["Put the demo video above the fold",
         "Add 20+ reviews with photos",
         "Lead the benefit copy with the outcome, not the specification",
         "Show the delivery estimate honestly and early - surprises refund later"],
    ),
    "checkout_rate": (
        "Carts are abandoned before checkout starts. Usually price shock.",
        ["Show shipping cost on the product page, not at checkout",
         "Add trust badges and a visible returns policy",
         "Offer free shipping over a threshold and raise AOV with it"],
    ),
    "purchase_rate": (
        "Checkout is leaking. This is the most expensive leak you have.",
        ["Enable express wallets (Shop Pay, Apple Pay, PayPal)",
         "Cut form fields; never force account creation",
         "Check the payment gateway is not declining foreign cards",
         "Add an abandoned-checkout email at 1h and 24h"],
    ),
}


@dataclass
class FunnelStage:
    name: str
    value: float
    numerator: int
    denominator: int
    low: float
    good: float

    @property
    def status(self) -> str:
        if self.denominator <= 0:
            return "no data"
        if self.value >= self.good:
            return "good"
        if self.value >= self.low:
            return "ok"
        return "weak"


@dataclass
class Decision:
    action: str
    confidence: float
    headline: str
    reasoning: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    observed_cpa: float = float("inf")
    cpa_best_case: float = 0.0
    cpa_worst_case: float = float("inf")
    breakeven_cpa: float = 0.0
    target_cpa: float = 0.0
    observed_roas: float = 0.0
    breakeven_roas: float = 0.0
    profit_so_far: float = 0.0
    spend_to_verdict: float = 0.0

    funnel: list[FunnelStage] = field(default_factory=list)
    weakest_stage: str = ""

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "funnel"}
        d["funnel"] = [s.__dict__ | {"status": s.status} for s in self.funnel]
        return d


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def analyse_funnel(test: AdTest) -> list[FunnelStage]:
    """Walk the funnel top to bottom and find the first step that leaks.

    Landing page views fall back to clicks when the pixel is not reporting
    them, which is common on a fresh setup.
    """
    lpv = test.landing_views or test.clicks
    pairs = [
        ("ctr", test.clicks, test.impressions),
        ("lpv_rate", lpv, test.clicks),
        ("atc_rate", test.add_to_carts, lpv),
        ("checkout_rate", test.checkouts, test.add_to_carts),
        ("purchase_rate", test.purchases, test.checkouts),
    ]
    stages = []
    for name, num, den in pairs:
        low, good = BENCHMARKS[name]
        stages.append(FunnelStage(name, _safe_div(num, den), int(num), int(den), low, good))
    return stages


def weakest_stage(stages: list[FunnelStage], min_denominator: int = 25) -> str:
    """First stage from the top that is below its floor, with enough traffic to trust."""
    for stage in stages:
        if stage.denominator >= min_denominator and stage.status == "weak":
            return stage.name
    return ""


def decide(test: AdTest, ue: UnitEconomics, config: Config) -> Decision:
    """The verdict on one test."""
    conf = config.confidence
    alpha = 1.0 - conf
    be_cpa = ue.breakeven_cpa
    tgt_cpa = ue.target_cpa()
    spend, purchases = test.spend, int(test.purchases)

    d = Decision(
        action=NOT_STARTED,
        confidence=conf,
        headline="",
        breakeven_cpa=be_cpa,
        target_cpa=tgt_cpa,
        breakeven_roas=ue.breakeven_roas,
    )
    d.funnel = analyse_funnel(test)
    d.weakest_stage = weakest_stage(d.funnel)
    d.observed_roas = _safe_div(test.revenue, spend)
    d.profit_so_far = purchases * ue.contribution_margin - spend

    # Spend needed before a zero-sale result means anything.
    kill_threshold = -math.log(alpha) * be_cpa if be_cpa > 0 else 0.0
    d.spend_to_verdict = max(0.0, kill_threshold - spend)

    if be_cpa <= 0:
        d.action = KILL
        d.headline = "Contribution margin is negative - this loses money on every sale."
        d.reasoning.append(
            "Before a cent of ad spend, each order costs more than it brings in. "
            "No campaign can fix this; only price or cost can."
        )
        d.next_steps = ["Raise price or find a cheaper supplier, then re-score"]
        return d

    if spend <= 0:
        d.headline = "Not started. No spend recorded yet."
        d.next_steps = [f"Fund the test with at least {kill_threshold:,.0f} "
                        f"({kill_threshold / be_cpa:.1f}x breakeven CPA)"]
        return d

    lo_rate, hi_rate = poisson_rate_ci(purchases, spend, conf)
    d.cpa_best_case = 1.0 / hi_rate if hi_rate > 0 else 0.0
    d.cpa_worst_case = 1.0 / lo_rate if lo_rate > 0 else float("inf")
    d.observed_cpa = spend / purchases if purchases else float("inf")

    planned = test.planned_budget or kill_threshold
    budget_spent = spend >= planned

    # ------------------------------------------------------ zero purchases --
    if purchases == 0:
        expected_if_breakeven = spend / be_cpa
        p_zero = poisson_pmf_zero(expected_if_breakeven)
        d.reasoning.append(
            f"Spent {spend:,.2f} with no sales. If the true CPA were exactly "
            f"breakeven ({be_cpa:,.2f}) you would expect "
            f"{expected_if_breakeven:.1f} sales by now; the chance of seeing "
            f"zero is {p_zero * 100:.1f}%."
        )
        if p_zero < alpha:
            # Strong upper funnel means the product works but the offer doesn't.
            if d.weakest_stage in ("checkout_rate", "purchase_rate", "atc_rate"):
                d.action = ITERATE
                d.headline = ("The ads work, the offer does not. Fix the funnel "
                              "before spending another cent on traffic.")
                d.reasoning.append(
                    f"Traffic and interest are arriving, but '{d.weakest_stage}' "
                    f"is below its floor. That is an offer problem, not a product problem."
                )
            else:
                d.action = KILL
                d.headline = (f"Kill it. {conf * 100:.0f}% confident this cannot "
                              f"reach breakeven.")
                d.reasoning.append(
                    "You have bought the answer. Spending more only raises the "
                    "price of the same answer."
                )
        else:
            d.action = KEEP_TESTING
            d.headline = (f"Too early to judge. Another {d.spend_to_verdict:,.0f} "
                          f"buys a real verdict.")
            d.reasoning.append(
                "Stopping now would be a coin flip dressed up as a decision."
            )
        _attach_fix_steps(d, test)
        return d

    # ---------------------------------------------------- with purchases ----
    d.reasoning.append(
        f"{purchases} sale(s) on {spend:,.2f} spend. Observed CPA "
        f"{d.observed_cpa:,.2f}; true CPA is between {d.cpa_best_case:,.2f} and "
        f"{d.cpa_worst_case:,.2f} at {conf * 100:.0f}% confidence."
    )
    d.reasoning.append(
        f"Breakeven CPA is {be_cpa:,.2f} (ROAS {ue.breakeven_roas:.2f}x). "
        f"Target CPA for a {config.target_net_margin * 100:.0f}% net margin is "
        f"{tgt_cpa:,.2f} (ROAS {ue.target_roas():.2f}x)."
    )

    if d.cpa_worst_case <= tgt_cpa:
        d.action = SCALE
        d.headline = "Scale it. Even the pessimistic case beats your target."
        d.reasoning.append(
            "The entire confidence interval sits under target CPA. This is as "
            "close to certainty as ad data gets."
        )
    elif d.cpa_best_case > be_cpa:
        d.action = KILL
        d.headline = "Kill it. Even the optimistic case loses money."
        d.reasoning.append(
            "The whole plausible range is above breakeven. More spend will not "
            "move it to the other side."
        )
    elif d.observed_cpa <= tgt_cpa:
        d.action = SCALE if budget_spent else HOLD
        d.headline = ("Profitable and past its test budget - scale, carefully."
                      if budget_spent else
                      "Profitable so far. Hold the budget and finish the test.")
        d.reasoning.append(
            "Point estimate beats target but the interval still straddles it. "
            "Raise budget in steps, not jumps, and re-check after each step."
        )
    elif d.observed_cpa <= be_cpa:
        d.action = HOLD
        d.headline = "Above water, below target. Improve the margin, not the budget."
        d.reasoning.append(
            "It pays for itself but not for your time. The fastest fix is AOV: "
            "an upsell that lifts AOV 15% moves target ROAS more than any bid change."
        )
    else:
        if budget_spent:
            if d.weakest_stage:
                d.action = ITERATE
                d.headline = (f"Over breakeven, but '{d.weakest_stage}' is the "
                              f"cause. One rebuild, then decide.")
            else:
                d.action = KILL
                d.headline = "Over breakeven with the budget spent and no clear leak."
                d.reasoning.append(
                    "No single stage is broken, which means the product simply "
                    "costs more to sell than it earns."
                )
        else:
            d.action = KEEP_TESTING
            d.headline = (f"Losing money so far, but the test is not finished "
                          f"({spend:,.0f} of {planned:,.0f}).")

    _attach_fix_steps(d, test)
    return d


def _attach_fix_steps(d: Decision, test: AdTest) -> None:
    """Turn the verdict into things you can do this afternoon."""
    if d.action == KILL:
        d.next_steps = [
            "Turn the campaign off today - do not 'give it one more day'",
            "Archive the creative and write down the one thing you learned",
            "Move the remaining budget to the next A-tier product",
        ]
    elif d.action == SCALE:
        d.next_steps = [
            "Raise daily budget by 20-25%, then wait 48h before the next step",
            "Duplicate the winning ad set into a broader audience rather than "
            "editing the proven one",
            "Confirm supplier stock and lead time BEFORE the volume arrives",
            "Set a stop-loss: if CPA exceeds breakeven for 3 straight days, step back down",
        ]
    elif d.action == HOLD:
        d.next_steps = [
            "Leave the budget alone - edits reset the learning phase",
            "Add a post-purchase upsell or bundle to lift AOV",
            "Trim the worst-performing placement or creative, nothing else",
        ]
    elif d.action == ITERATE:
        cause, fixes = _STAGE_FIXES.get(
            d.weakest_stage,
            ("Unclear leak - instrument the funnel before spending more.",
             ["Verify the pixel fires on view, add-to-cart, checkout and purchase"]),
        )
        d.reasoning.append(cause)
        d.next_steps = list(fixes) + ["Re-run the test with the same budget once fixed"]
    elif d.action == KEEP_TESTING:
        d.next_steps = [
            f"Keep spending to the planned budget ({test.planned_budget:,.0f})",
            "Change nothing mid-test - each edit restarts the data you are buying",
        ]
        if d.weakest_stage:
            cause, fixes = _STAGE_FIXES[d.weakest_stage]
            d.next_steps.append(f"Watch '{d.weakest_stage}': {cause}")


# ------------------------------------------------------------- test design --

@dataclass
class TestPlan:
    product_name: str
    total_budget: float
    daily_budget: float
    days: int
    creatives: int
    audiences: int
    breakeven_cpa: float
    breakeven_roas: float
    target_cpa: float
    target_roas: float
    checkpoints: list[dict] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)


def plan_test(product_name: str, ue: UnitEconomics, config: Config,
              days: int = 5, creatives: int = 3) -> TestPlan:
    """Design a test that can actually produce a verdict.

    Budget is set by statistics, not by what feels affordable: below roughly
    3x breakeven CPA a zero-sale result is indistinguishable from bad luck.
    """
    alpha = 1.0 - config.confidence
    k = max(3.0, -math.log(alpha))
    total = max(50.0, round(ue.breakeven_cpa * k / 10.0) * 10.0)
    daily = round(total / days, 2)

    plan = TestPlan(
        product_name=product_name,
        total_budget=total,
        daily_budget=daily,
        days=days,
        creatives=creatives,
        audiences=1,
        breakeven_cpa=ue.breakeven_cpa,
        breakeven_roas=ue.breakeven_roas,
        target_cpa=ue.target_cpa(),
        target_roas=ue.target_roas(),
    )

    plan.checkpoints = [
        {"at_spend": round(total * 0.25, 2), "day": 1,
         "look_at": "CTR and CPM only",
         "act_if": f"CTR below {BENCHMARKS['ctr'][0] * 100:.1f}% - swap creative, "
                   f"do not touch budget"},
        {"at_spend": round(total * 0.50, 2), "day": 2,
         "look_at": "add-to-cart rate",
         "act_if": f"ATC below {BENCHMARKS['atc_rate'][0] * 100:.0f}% with 25+ "
                   f"landing views - the product page is the problem"},
        {"at_spend": round(total * 0.75, 2), "day": 3,
         "look_at": "checkout and purchase rate",
         "act_if": "carts but no purchases - price shock or payment friction"},
        {"at_spend": total, "day": days,
         "look_at": "cost per purchase against breakeven",
         "act_if": "run the decision engine and obey it"},
    ]

    plan.rules = [
        f"Do not spend past {total:,.0f} without a decision. That is the whole point of a test.",
        "Change one variable at a time. Two changes produce no information.",
        "No budget edits before the checkpoint - edits restart the learning phase.",
        f"Zero sales at {total:,.0f} spend is a {config.confidence * 100:.0f}% "
        f"confident kill, not bad luck.",
        "Write the hypothesis down before launch. If you cannot state what would "
        "prove you wrong, you are not testing, you are hoping.",
    ]
    return plan


def scale_ladder(current_daily: float, ue: UnitEconomics, config: Config,
                 steps: int = 6) -> list[dict]:
    """A budget ramp that does not blow up the account.

    Ad platforms re-enter the learning phase on large budget changes, so the
    ladder climbs in steps with a mandatory hold between them, and every rung
    carries its own stop-loss.
    """
    rows = []
    daily = current_daily
    for step in range(1, steps + 1):
        daily = round(daily * (1 + config.scale_step), 2)
        expected_orders = daily / ue.target_cpa() if ue.target_cpa() > 0 else 0.0
        rows.append({
            "step": step,
            "daily_budget": daily,
            "hold_days": 2,
            "expected_orders_per_day": round(expected_orders, 1),
            "expected_daily_profit": round(
                expected_orders * (ue.contribution_margin - ue.target_cpa()), 2),
            "stop_loss_cpa": round(ue.breakeven_cpa, 2),
            "revert_if": f"CPA above {ue.breakeven_cpa:,.2f} for 3 consecutive days",
            "cash_needed": round(daily * 2 + expected_orders * 2 * ue.variable_cogs, 2),
        })
    return rows
