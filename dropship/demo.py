"""Seed a realistic example store.

Deliberately not a success story. The demo contains a winner, a loser, a
product that needs its offer fixed, one that fails the research gates outright,
and a handful of orders drifting toward chargebacks - because that mix is what
a real month looks like, and it is what the system exists to sort out.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import AdTest, LedgerEntry, Order, Product, Supplier
from .store import Store


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def seed(store: Store) -> Store:
    store.config.business_name = "Northbound Goods"
    store.config.starting_cash = 4000.0
    store.config.fixed_monthly_costs = 220.0
    store.config.payout_delay_days = 5

    # ------------------------------------------------------------ suppliers
    cj = Supplier(
        name="CJ Dropshipping", platform="cj", country="CN",
        unit_price=8.40, ship_cost=3.10, handling_days=2, transit_days=10,
        tracking_quality=8, defect_rate=0.025, response_hours=12,
        stock_depth=7, custom_packaging=True, sample_ordered=True,
        sample_notes="Sample arrived day 11. Packaging plain, no inserts. Solid.")
    ali = Supplier(
        name="Shenzhen Hualin (AliExpress)", platform="aliexpress", country="CN",
        unit_price=6.80, ship_cost=2.20, handling_days=4, transit_days=19,
        tracking_quality=3, defect_rate=0.07, response_hours=72,
        stock_depth=3, sample_ordered=False,
        notes="Cheapest quote, but tracking stalls and support is slow.")
    for supplier in (cj, ali):
        store.add(supplier)

    # ------------------------------------------------------------- products
    products = [
        Product(  # the winner
            name="Posture Corrector Pro", sku="PCP-01", category="wellness",
            supplier_id=cj.id, price=44.99, cogs=8.40, ship_cost=3.10,
            upsell_revenue=7.50, upsell_cogs=1.80,
            demand=8, competition=6, creative_potential=9, problem_solving=9,
            wow_factor=7, seasonality=8, return_risk=4, delivery_days=12,
            status="scaling",
            notes="Before/after video is doing the selling."),
        Product(  # needs its offer fixed, not its ads
            name="Magnetic Cable Organiser", sku="MCO-02", category="desk",
            supplier_id=cj.id, price=29.99, cogs=5.20, ship_cost=2.60,
            demand=6, competition=8, creative_potential=6, problem_solving=6,
            wow_factor=5, seasonality=9, return_risk=3, delivery_days=12,
            status="testing"),
        Product(  # the loser
            name="LED Sunset Lamp", sku="LSL-03", category="decor",
            supplier_id=ali.id, price=34.99, cogs=7.90, ship_cost=3.40,
            demand=5, competition=9, creative_potential=7, problem_solving=3,
            wow_factor=8, seasonality=4, return_risk=5, delivery_days=21,
            status="testing",
            notes="Saturated. Everyone ran this in 2021."),
        Product(  # fails the gates: margin too thin, delivery too slow
            name="Silicone Kitchen Scraper Set", sku="SKS-04", category="kitchen",
            supplier_id=ali.id, price=19.99, cogs=9.10, ship_cost=2.20,
            demand=4, competition=7, creative_potential=3, problem_solving=4,
            wow_factor=2, seasonality=9, return_risk=2, delivery_days=23,
            status="candidate"),
        Product(  # promising, not yet launched
            name="Pet Hair Remover Roller", sku="PHR-05", category="pet",
            supplier_id=cj.id, price=39.99, cogs=7.10, ship_cost=2.90,
            upsell_revenue=6.00, upsell_cogs=1.40,
            demand=9, competition=5, creative_potential=9, problem_solving=9,
            wow_factor=8, seasonality=9, return_risk=2, delivery_days=11,
            status="candidate"),
    ]
    for product in products:
        store.add(product)
    winner, organiser, lamp, scraper, roller = products

    # ----------------------------------------------------------------- tests
    store.add(AdTest(
        product_id=winner.id, channel="meta", notes="PCP - before/after - broad",
        angle="before_after", planned_budget=120, daily_budget=85,
        started=_ago(24), spend=290.0, impressions=44000, clicks=760,
        landing_views=640, add_to_carts=68, checkouts=31, purchases=16,
        revenue=839.84,
        hypothesis="A silent before/after clip beats a talking-head explainer."))

    store.add(AdTest(
        product_id=organiser.id, channel="meta", notes="MCO - desk setup - broad",
        angle="demonstration", planned_budget=90, daily_budget=30,
        started=_ago(6), spend=142.0, impressions=21400, clicks=520,
        landing_views=455, add_to_carts=44, checkouts=19, purchases=1,
        revenue=29.99,
        hypothesis="Cable clutter is felt strongly enough to buy on impulse."))

    store.add(AdTest(
        product_id=lamp.id, channel="tiktok", notes="LSL - aesthetic room",
        angle="wow", planned_budget=110, daily_budget=35,
        started=_ago(9), spend=268.0, impressions=96000, clicks=1450,
        landing_views=1180, add_to_carts=38, checkouts=9, purchases=2,
        revenue=69.98,
        hypothesis="Wow factor carries it despite the 21-day delivery."))

    # ---------------------------------------------------------------- orders
    # A realistic mix: mostly fine, a few drifting, one already disputed.
    plan = [
        (winner, 28, "delivered", 11), (winner, 24, "delivered", 10),
        (winner, 21, "delivered", 12), (winner, 19, "delivered", 11),
        (winner, 17, "delivered", 13), (winner, 15, "delivered", 11),
        (winner, 14, "refunded", None), (winner, 12, "delivered", 12),
        (winner, 10, "in_transit", None), (winner, 9, "in_transit", None),
        (winner, 8, "in_transit", None), (winner, 6, "awaiting_tracking", None),
        (winner, 5, "placed", None), (winner, 3, "received", None),
        (winner, 1, "received", None),
        (lamp, 26, "chargeback", None), (lamp, 22, "in_transit", None),
        (organiser, 4, "awaiting_supplier", None),
    ]
    for i, (product, age, status, delivered_in) in enumerate(plan, 1):
        order = Order(
            external_id=f"#10{i:02d}",
            product_id=product.id,
            customer=f"Customer {i}",
            email=f"buyer{i}@example.com",
            country="US",
            revenue=product.price + product.upsell_revenue,
            cogs=product.landed_cost,
            status=status,
            ordered_date=_ago(age),
            promised_days=product.delivery_days,
        )
        if status in ("placed", "awaiting_tracking", "in_transit", "delivered"):
            order.placed_date = _ago(max(0, age - 1))
        if status in ("in_transit", "delivered"):
            order.tracking_number = f"LP{4400000 + i}CN"
            order.tracking_date = _ago(max(0, age - 3))
        if delivered_in is not None:
            order.delivered_date = _ago(max(0, age - delivered_in))
        if status == "chargeback":
            order.issue = "Item never arrived - 21 day shipping"
        store.add(order)

    # An order that was paid two days ago and never placed: the single most
    # preventable failure in the whole system, so the demo includes one.
    store.add(Order(
        external_id="#1099", product_id=winner.id, customer="Priority Case",
        email="urgent@example.com", country="GB",
        revenue=winner.price, cogs=winner.landed_cost,
        status="awaiting_supplier", ordered_date=_ago(3),
        promised_days=winner.delivery_days))

    # ---------------------------------------------------------------- ledger
    entries = [
        LedgerEntry(date=_ago(30), kind="expense", category="software",
                    amount=-220.0, memo="Shopify + apps"),
        LedgerEntry(date=_ago(20), kind="revenue", category="payout",
                    amount=420.0, memo="Shopify payout"),
        LedgerEntry(date=_ago(8), kind="revenue", category="payout",
                    amount=390.0, memo="Shopify payout"),
        LedgerEntry(date=_ago(26), kind="expense", category="cogs",
                    amount=-240.0, memo="Supplier invoices"),
    ]
    for entry in entries:
        store.add(entry)

    # Ad spend goes in under the same convention the CSV importer uses, so a
    # later `dropship import ads --ledger` replaces these rather than stacking
    # a second copy on top.
    from .importers import ledger_from_ads
    for entry in ledger_from_ads(store.tests, store.ledger):
        store.add(entry)

    # Score everything so the portfolio is immediately meaningful.
    from . import research
    for product in store.products:
        result = research.score_product(product, store.config)
        product.score = result.score
        product.tier = result.tier
        product.test_budget = result.recommended_test_budget
    roller.status = "approved"
    scraper.status = "candidate"
    return store
