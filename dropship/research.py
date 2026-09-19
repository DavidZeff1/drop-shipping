"""Product research: decide what deserves your money before you spend it.

Two stages, deliberately in this order:

  1. GATES   - hard, non-negotiable rejections. No score can rescue a product
               that cannot be delivered in time or cannot carry an ad budget.
  2. SCORE   - a weighted 0-100 on the things that actually predict a winner.

The gates matter more than the score. Nearly every catastrophic dropshipping
loss traces back to shipping something a gate would have rejected: a 40-day
delivery window, a 1.8x markup, or a trademarked product.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .economics import UnitEconomics, for_product
from .models import Config, Product, today_iso

# Categories that are either policy-banned on the major ad platforms, legally
# regulated, or reliably generate chargebacks. Not exhaustive - check the
# current Meta/TikTok/Google policies before every launch.
RESTRICTED_KEYWORDS = (
    "weapon", "knife", "gun", "ammo", "taser", "pepper spray",
    "cbd", "thc", "vape", "nicotine", "tobacco", "kratom",
    "supplement", "weight loss", "detox", "slimming",
    "prescription", "medical device", "covid", "cure", "treatment",
    "adult", "sex", "counterfeit", "replica", "knockoff",
    "drone jammer", "laser pointer", "lockpick", "surveillance",
    "crypto", "forex", "gambling", "lottery",
    "baby sleep", "car seat", "helmet", "airbag",
)

WEIGHTS = {
    "margin": 25,       # can the product carry an ad budget at all
    "demand": 18,       # is anybody looking for it
    "competition": 14,  # how crowded is the auction
    "creative": 16,     # can you show the value in three silent seconds
    "fulfillment": 12,  # how fast and how reliably it lands
    "returns": 8,       # how often you eat the cost
    "durability": 7,    # evergreen vs a six-week window
}


@dataclass
class ResearchResult:
    product_id: str
    name: str
    score: float = 0.0
    tier: str = "reject"
    blockers: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    recommended_test_budget: float = 0.0
    recommended_price: float = 0.0
    verdict: str = ""

    @property
    def passed(self) -> bool:
        return not self.blockers


def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def check_gates(product: Product, ue: UnitEconomics, config: Config) -> list[str]:
    """Hard rejections. Each one is a scar somebody else already earned."""
    blockers: list[str] = []
    text = f"{product.name} {product.category} {product.notes}".lower()

    if product.restricted or any(k in text for k in RESTRICTED_KEYWORDS):
        hit = next((k for k in RESTRICTED_KEYWORDS if k in text), "flagged manually")
        blockers.append(
            f"Restricted or regulated category ('{hit}'). Ad accounts get banned "
            f"for these, and a banned account takes the pixel data with it."
        )

    if product.brand_risk:
        blockers.append(
            "Trademark / counterfeit risk. An IP complaint can take down the "
            "store, the ad account and the payment processor in the same week."
        )

    if product.landed_cost <= 0 or product.price <= 0:
        blockers.append("Price or landed cost is missing - economics are unknowable.")
    else:
        if product.margin_multiple < config.min_margin_multiple:
            blockers.append(
                f"Margin multiple {product.margin_multiple:.2f}x is below the "
                f"{config.min_margin_multiple:.2f}x floor. There is not enough "
                f"room between cost and price to pay for traffic."
            )
        if ue.contribution_margin < config.min_contribution_margin:
            blockers.append(
                f"Contribution margin {ue.contribution_margin:.2f} is below the "
                f"{config.min_contribution_margin:.2f} floor. Even a perfect "
                f"campaign cannot buy a customer for less than this."
            )

    if product.delivery_days > config.max_delivery_days and not product.local_stock:
        blockers.append(
            f"{product.delivery_days:.0f}-day delivery exceeds the "
            f"{config.max_delivery_days:.0f}-day limit. Long waits convert into "
            f"refunds and chargebacks, which cost far more than the sale."
        )

    return blockers


def _component_scores(product: Product, ue: UnitEconomics, config: Config
                      ) -> dict[str, float]:
    """Each component is normalised 0-10 before weighting."""
    mult = product.margin_multiple
    # 2.5x -> 3, 3x -> 5, 4x -> 7.5, 5x+ -> 10
    margin_raw = _clamp((mult - 2.0) * 2.5)
    # A high multiple on a cheap product still cannot fund ads, so temper it
    # with the absolute margin: below $20 CM you are fighting for scraps.
    abs_raw = _clamp(ue.contribution_margin / 4.0)
    margin_score = 0.6 * margin_raw + 0.4 * abs_raw

    demand_score = _clamp(product.demand)
    competition_score = _clamp(10 - product.competition)

    # Creative potential is the strongest single predictor on paid social:
    # a product that demonstrates itself needs no persuasion.
    creative_score = _clamp(
        0.4 * product.creative_potential
        + 0.35 * product.wow_factor
        + 0.25 * product.problem_solving
    )

    # 5 days -> 10, 10 days -> 7, 15 days -> 4, 20 days -> 1
    ship_raw = _clamp(10 - max(0.0, product.delivery_days - 5) * 0.6)
    if product.local_stock:
        ship_raw = _clamp(ship_raw + 2.5)
    fulfillment_score = ship_raw

    returns_score = _clamp(10 - product.return_risk)
    durability_score = _clamp(product.seasonality)

    return {
        "margin": margin_score,
        "demand": demand_score,
        "competition": competition_score,
        "creative": creative_score,
        "fulfillment": fulfillment_score,
        "returns": returns_score,
        "durability": durability_score,
    }


def _tier(score: float) -> str:
    if score >= 75:
        return "A"
    if score >= 62:
        return "B"
    if score >= 50:
        return "C"
    return "reject"


def recommended_test_budget(ue: UnitEconomics, config: Config) -> float:
    """Enough spend to reach a statistically honest verdict, and no more.

    Three times the breakeven CPA: if the true CPA were at breakeven you would
    expect three sales, so seeing zero is ~95% evidence the product is under
    water. Spending less than this and killing is guessing; spending more and
    hoping is donating.
    """
    base = ue.breakeven_cpa * 3.0
    # Round to something you can actually type into an ad manager.
    return max(50.0, round(base / 10.0) * 10.0)


def suggested_price(product: Product, config: Config) -> float:
    """Price that clears the margin floor with a charm-pricing ending."""
    target = product.landed_cost * max(config.min_margin_multiple, 3.0)
    return max(0.0, round(target) - 0.01)


def score_product(product: Product, config: Config) -> ResearchResult:
    ue = for_product(product, config)
    result = ResearchResult(product_id=product.id, name=product.name)
    result.blockers = check_gates(product, ue, config)
    result.components = _component_scores(product, ue, config)
    result.recommended_price = suggested_price(product, config)

    total = sum(result.components[k] * w for k, w in WEIGHTS.items())
    result.score = round(total / sum(WEIGHTS.values()) * 10.0, 1)

    if result.blockers:
        result.tier = "reject"
        result.verdict = (
            "Do not test. Fix the blockers below or drop the product - no "
            "amount of creative solves a broken gate."
        )
        result.recommended_test_budget = 0.0
    else:
        result.tier = _tier(result.score)
        result.recommended_test_budget = recommended_test_budget(ue, config)
        result.verdict = {
            "A": "Test now. Fund it properly and give it the full budget.",
            "B": "Worth testing, but only when no A-tier product is waiting.",
            "C": "Marginal. Test only if you can fix the weakest component first.",
            "reject": "Score too low. The economics or the demand are not there.",
        }[result.tier]

    # Narrative: the point is to tell you what to fix, not just hand you a number.
    for key, value in sorted(result.components.items(), key=lambda kv: -kv[1]):
        label = _NARRATIVE[key]
        if value >= 7.5:
            result.strengths.append(f"{label['name']}: {label['high']}")
        elif value <= 4.0:
            result.risks.append(f"{label['name']}: {label['low']}")

    if ue.breakeven_roas > 2.5 and not result.blockers:
        result.risks.append(
            f"Breakeven ROAS is {ue.breakeven_roas:.2f}x. That is achievable but "
            f"unforgiving - raise price or add an upsell before you launch."
        )

    return result


def apply_score(product: Product, config: Config) -> ResearchResult:
    """Score a product and record the result on it.

    A candidate that clears the gates at tier A or B is promoted to approved;
    one that fails a gate drops back to candidate. A product already in a test
    or on sale keeps its status - a re-score is not a verdict on a test.
    """
    result = score_product(product, config)
    product.score, product.tier = result.score, result.tier
    product.test_budget = result.recommended_test_budget
    product.updated = today_iso()
    if product.status == "candidate" and result.passed and result.tier in ("A", "B"):
        product.status = "approved"
    if not result.passed and product.status in ("candidate", "approved"):
        product.status = "candidate"
    return result


_NARRATIVE = {
    "margin": {
        "name": "Margin",
        "high": "there is real room to pay for traffic and still keep profit.",
        "low": "too thin to buy customers. Raise price, cut cost, or bundle.",
    },
    "demand": {
        "name": "Demand",
        "high": "people are already looking for this - you are meeting demand, not creating it.",
        "low": "little evidence anybody wants it. You would be paying to educate a cold market.",
    },
    "competition": {
        "name": "Competition",
        "high": "the auction is not crowded, so clicks should stay cheap.",
        "low": "saturated. Expect high CPMs and buyers who have seen the offer five times.",
    },
    "creative": {
        "name": "Creative potential",
        "high": "it sells itself on video - the strongest predictor on paid social.",
        "low": "hard to demonstrate. If you cannot show the value in three silent seconds, skip it.",
    },
    "fulfillment": {
        "name": "Fulfillment",
        "high": "fast, trackable delivery. Fewer refunds, fewer disputes, better reviews.",
        "low": "slow delivery. Every extra week converts directly into refund and chargeback rate.",
    },
    "returns": {
        "name": "Return risk",
        "high": "low return risk - no sizing, no fragility, no electronics failure.",
        "low": "high return risk. Model the refund rate at double your default before committing.",
    },
    "durability": {
        "name": "Durability",
        "high": "evergreen demand. Creative and data keep their value.",
        "low": "seasonal or fad-driven. Plan the exit before the entry.",
    },
}


def rank(products: list[Product], config: Config) -> list[ResearchResult]:
    """Score a portfolio and order it by what to test next."""
    results = [score_product(p, config) for p in products]
    results.sort(key=lambda r: (r.passed, r.score), reverse=True)
    return results
