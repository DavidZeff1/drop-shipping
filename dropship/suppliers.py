"""Supplier vetting.

The supplier decides your refund rate, your chargeback rate and your review
score - which means the supplier decides your margin. Price is the least
important thing on this scorecard and it is weighted accordingly.

A supplier you have not ordered a sample from is not a vetted supplier. The
sample checklist below is the part people skip and then regret.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Config, Supplier

WEIGHTS = {
    "speed": 26,        # lead time is the #1 driver of refunds
    "reliability": 22,  # defect rate
    "tracking": 16,     # tracking that updates prevents most WISMO tickets
    "cost": 14,         # price matters, but least of the five
    "service": 12,      # how fast they answer when something breaks
    "capacity": 10,     # can they absorb a winner without going out of stock
}

SAMPLE_CHECKLIST = [
    "Order to your own address as a normal customer - do not announce yourself",
    "Time it: order placed -> tracking issued -> delivered. Record all three",
    "Photograph the packaging exactly as it arrived - this is your unboxing",
    "Check for supplier branding, foreign invoices or competitor inserts",
    "Verify the product matches the listing photos, not a cheaper variant",
    "Stress the product the way a customer will in week one",
    "Message support with a fake problem and time the reply",
    "Ask what happens on a damaged item - who pays, and how fast",
    "Ask for their stock depth and restock lead time in writing",
    "Confirm whether they can ship from a domestic warehouse at volume",
]

RED_FLAGS = [
    ("no_tracking", "Tracking numbers that never update are indistinguishable "
                    "from lost parcels to a customer - and to their bank."),
    ("slow_response", "A supplier who answers in days cannot help you inside a "
                      "chargeback window."),
    ("high_defect", "Above 5% defects, refunds and reviews eat the margin "
                    "faster than ads can replace it."),
    ("no_sample", "You are about to sell something you have never held."),
    ("thin_stock", "A winner that goes out of stock is a winner you have lost; "
                   "the ad account loses its learning too."),
    ("long_lead", "Past ~20 days, chargebacks rise faster than any discount "
                  "can offset."),
]


@dataclass
class SupplierScore:
    supplier_id: str
    name: str
    score: float = 0.0
    grade: str = "F"
    components: dict[str, float] = field(default_factory=dict)
    red_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    landed_cost: float = 0.0
    lead_days: float = 0.0


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def score_supplier(s: Supplier, config: Config,
                   price_benchmark: float | None = None) -> SupplierScore:
    """Score 0-100. Anything under 60 will cost you more in refunds than it saves."""
    out = SupplierScore(supplier_id=s.id, name=s.name,
                        landed_cost=s.landed_cost, lead_days=s.lead_days)

    # 5 days -> 10, 12 days -> 6.5, 20 days -> 2.5, 25+ -> 0
    speed = _clamp(10.0 - max(0.0, s.lead_days - 5.0) * 0.5)
    reliability = _clamp(10.0 - s.defect_rate * 150.0)  # 3% -> 5.5, 6.7% -> 0
    tracking = _clamp(s.tracking_quality)
    # 24h -> 8, 48h -> 6, 72h -> 4
    service = _clamp(10.0 - (s.response_hours / 12.0))
    capacity = _clamp(s.stock_depth)

    if price_benchmark and price_benchmark > 0:
        ratio = s.landed_cost / price_benchmark
        cost = _clamp((2.0 - ratio) * 10.0)  # at benchmark -> 10, 2x -> 0
    else:
        cost = 5.0
        out.notes.append("No price benchmark given - cost scored neutral. "
                         "Quote at least three suppliers before committing.")

    out.components = {"speed": speed, "reliability": reliability,
                      "tracking": tracking, "cost": cost,
                      "service": service, "capacity": capacity}
    total = sum(out.components[k] * w for k, w in WEIGHTS.items())
    out.score = round(total / sum(WEIGHTS.values()) * 10.0, 1)

    out.grade = ("A" if out.score >= 80 else "B" if out.score >= 70 else
                 "C" if out.score >= 60 else "D" if out.score >= 45 else "F")

    flags = dict(RED_FLAGS)
    if s.tracking_quality < 5:
        out.red_flags.append(flags["no_tracking"])
    if s.response_hours > 48:
        out.red_flags.append(flags["slow_response"])
    if s.defect_rate > 0.05:
        out.red_flags.append(flags["high_defect"])
    if not s.sample_ordered:
        out.red_flags.append(flags["no_sample"])
    if s.stock_depth < 4:
        out.red_flags.append(flags["thin_stock"])
    if s.lead_days > 20:
        out.red_flags.append(flags["long_lead"])

    if s.custom_packaging:
        out.notes.append("Supports custom packaging - the cheapest route to "
                         "repeat purchases and a defensible brand.")
    if s.payment_terms != "prepaid":
        out.notes.append(f"Offers {s.payment_terms} terms. Worth more than a "
                         f"price cut: it moves COGS after the customer pays.")
    if s.moq > 1:
        out.notes.append(f"MOQ {s.moq} - that is inventory, not dropshipping. "
                         f"Model the cash tied up before agreeing.")
    return out


def compare(suppliers: list[Supplier], config: Config) -> list[SupplierScore]:
    """Rank suppliers against each other, benchmarking cost on the cheapest."""
    if not suppliers:
        return []
    benchmark = min(s.landed_cost for s in suppliers if s.landed_cost > 0) or None
    scores = [score_supplier(s, config, benchmark) for s in suppliers]
    scores.sort(key=lambda x: -x.score)
    return scores


def risk_of_single_supplier(suppliers: list[Supplier], product_supplier_id: str
                            ) -> str | None:
    """Warn when a product has no backup source."""
    alternatives = [s for s in suppliers if s.id != product_supplier_id]
    if not alternatives:
        return ("Only one supplier on file. A single price rise, stockout or "
                "account suspension takes the product offline with no fallback. "
                "Qualify a second source before you scale, not after.")
    return None
