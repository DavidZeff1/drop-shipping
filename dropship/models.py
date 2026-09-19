"""Plain dataclasses for everything the system tracks.

Kept deliberately boring: every record round-trips through JSON so the store
stays human-readable and diffable. No ORM, no migrations, no surprises.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict, fields
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------- lifecycle --

# A product moves in one direction through these states. Anything that goes
# backwards (scaling -> testing) is a signal something broke, not a normal move.
PRODUCT_STATES = (
    "candidate",   # sourced, not yet scored
    "approved",    # passed research gates, waiting for a test slot
    "testing",     # money is being spent to find out
    "iterating",   # upper-funnel signal, offer/creative being reworked
    "scaling",     # proven under breakeven, budget climbing
    "winner",      # stable, profitable, defended
    "paused",      # stopped on purpose (seasonality, stock, cash)
    "killed",      # proven unprofitable. Do not resurrect without new evidence.
)

ORDER_STATES = (
    "received",            # customer paid
    "awaiting_supplier",   # not yet placed with supplier
    "placed",              # supplier has it
    "awaiting_tracking",   # placed, no tracking number yet
    "in_transit",
    "delivered",
    "refunded",
    "chargeback",
    "cancelled",
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class Record:
    """Mixin giving every dataclass symmetric to_dict / from_dict."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        known = {f.name for f in fields(cls)}
        # Unknown keys are dropped rather than raising so an old store file
        # never blocks an upgrade.
        return cls(**{k: v for k, v in data.items() if k in known})


# ----------------------------------------------------------------- supplier --

@dataclass
class Supplier(Record):
    name: str
    id: str = field(default_factory=lambda: new_id("sup"))
    platform: str = ""              # aliexpress / cj / zendrop / alibaba / domestic-3pl
    contact: str = ""
    country: str = ""
    unit_price: float = 0.0
    ship_cost: float = 0.0
    handling_days: float = 2.0      # order placed -> handed to carrier
    transit_days: float = 12.0      # carrier -> customer door
    tracking_quality: int = 5       # 0-10, does the tracking actually update?
    defect_rate: float = 0.03       # fraction arriving broken/wrong
    response_hours: float = 24.0    # how fast they answer a problem
    moq: int = 1
    stock_depth: int = 5            # 0-10, can they absorb a spike?
    custom_packaging: bool = False
    payment_terms: str = "prepaid"  # prepaid / net15 / net30
    sample_ordered: bool = False
    sample_notes: str = ""
    notes: str = ""
    created: str = field(default_factory=today_iso)

    @property
    def lead_days(self) -> float:
        return self.handling_days + self.transit_days

    @property
    def landed_cost(self) -> float:
        return self.unit_price + self.ship_cost


# ------------------------------------------------------------------ product --

@dataclass
class Product(Record):
    name: str
    id: str = field(default_factory=lambda: new_id("prd"))
    sku: str = ""
    category: str = ""
    supplier_id: str = ""

    # Pricing / cost
    price: float = 0.0              # what the customer pays for the core unit
    cogs: float = 0.0               # supplier unit price
    ship_cost: float = 0.0          # supplier shipping to the customer
    upsell_revenue: float = 0.0     # expected extra revenue per order
    upsell_cogs: float = 0.0        # cost of that extra revenue

    # Research inputs (0-10 unless noted). Entered by you; be honest.
    demand: int = 5                 # search volume / trend direction
    competition: int = 5            # 10 = saturated with big spenders
    creative_potential: int = 5     # can you show the value in 3 seconds?
    problem_solving: int = 5        # does it fix a real, felt annoyance?
    wow_factor: int = 5             # scroll-stopping in a silent video
    seasonality: int = 5            # 10 = evergreen, 0 = 6-week window
    return_risk: int = 5            # 10 = high (sizing, electronics, fragile)
    restricted: bool = False        # regulated / policy-banned / IP risk
    brand_risk: bool = False        # trademarked design, counterfeit risk
    delivery_days: float = 14.0     # promised door-to-door
    local_stock: bool = False       # domestic warehouse available?

    # Storefront: what the shop page needs and no calculation uses
    pay_url: str = ""               # payment link the buy button opens
    photos: list[str] = field(default_factory=list)   # image paths or URLs
    copy_problem: str = ""          # the annoyance, in the customer's words
    copy_outcome: str = ""          # what they get, in the customer's words
    bundle_price: float = 0.0       # two of them, at a price for two
    bundle_pay_url: str = ""        # the bundle's own payment link

    # Live state
    status: str = "candidate"
    score: float = 0.0
    tier: str = ""
    test_budget: float = 0.0
    notes: str = ""
    created: str = field(default_factory=today_iso)
    updated: str = field(default_factory=today_iso)

    @property
    def landed_cost(self) -> float:
        return self.cogs + self.ship_cost

    @property
    def margin_multiple(self) -> float:
        """Selling price / landed cost. The classic '3x rule' lives here."""
        return self.price / self.landed_cost if self.landed_cost > 0 else 0.0


# --------------------------------------------------------------------- test --

@dataclass
class AdTest(Record):
    """One product test. Spend, clicks and purchases are cumulative."""

    product_id: str
    id: str = field(default_factory=lambda: new_id("tst"))
    channel: str = "meta"           # meta / tiktok / google / organic
    hypothesis: str = ""
    angle: str = ""
    planned_budget: float = 0.0
    daily_budget: float = 0.0
    started: str = field(default_factory=today_iso)
    ended: str = ""

    # Cumulative metrics, pasted or imported from the ad platform
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    landing_views: int = 0
    add_to_carts: int = 0
    checkouts: int = 0
    purchases: int = 0
    revenue: float = 0.0

    decision: str = ""              # last decision the engine returned
    decision_date: str = ""
    notes: str = ""


# -------------------------------------------------------------------- order --

@dataclass
class Order(Record):
    id: str = field(default_factory=lambda: new_id("ord"))
    external_id: str = ""           # Shopify order name, e.g. #1042
    product_id: str = ""
    customer: str = ""
    email: str = ""
    country: str = ""
    quantity: int = 1
    revenue: float = 0.0
    cogs: float = 0.0
    status: str = "received"
    ordered_date: str = field(default_factory=today_iso)
    placed_date: str = ""
    tracking_number: str = ""
    tracking_date: str = ""
    delivered_date: str = ""
    promised_days: float = 14.0
    issue: str = ""                 # free text: damaged / wrong / lost / late
    notes: str = ""


# ------------------------------------------------------------------- ledger --

@dataclass
class LedgerEntry(Record):
    """Anything that moves cash. Ad spend, payouts, COGS, fixed costs."""

    id: str = field(default_factory=lambda: new_id("led"))
    date: str = field(default_factory=today_iso)
    kind: str = "expense"           # revenue / expense / payout / refund
    category: str = ""              # ads / cogs / software / fees / other
    amount: float = 0.0             # positive in, negative out
    product_id: str = ""
    memo: str = ""


# ------------------------------------------------------------------- config --

@dataclass
class Config(Record):
    """Business-wide settings. These drive every calculation, so get them right.

    The defaults are deliberately conservative: it is much cheaper to be
    pleasantly surprised than to discover your real breakeven after £3k of ads.
    """

    business_name: str = "My Store"
    currency: str = "USD"

    # Payment processing
    payment_rate: float = 0.029
    payment_fixed: float = 0.30
    payment_fee_refunded: bool = False   # most processors keep it. Verify yours.
    platform_rate: float = 0.0           # marketplace / extra gateway %
    chargeback_fee: float = 15.0

    # Loss rates - measure these from your own orders as soon as you have 50+
    refund_rate: float = 0.05
    chargeback_rate: float = 0.005
    goods_loss_on_refund: float = 1.0    # 1.0 = you never get the item back
    cs_cost_per_order: float = 0.50      # support time + apps, per order

    # Cash mechanics - these are what actually kill scaling stores
    payout_delay_days: int = 3
    rolling_reserve_rate: float = 0.0    # e.g. 0.10 for a held reserve
    reserve_release_days: int = 90
    ad_payment_delay_days: int = 0       # 0 = prepaid card, 30 = net-30 terms
    refund_lag_days: int = 12

    fixed_monthly_costs: float = 150.0   # store + apps + tools + subscriptions
    starting_cash: float = 2000.0

    # Decision thresholds
    target_net_margin: float = 0.15      # what "good" looks like after ads
    min_margin_multiple: float = 2.5     # hard gate in research
    min_contribution_margin: float = 15.0
    max_delivery_days: float = 18.0
    confidence: float = 0.90             # for the kill/scale statistics
    scale_step: float = 0.25             # budget increase per scale step
    created: str = field(default_factory=today_iso)
