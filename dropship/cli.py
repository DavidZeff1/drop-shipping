"""Command line interface.

One entry point for the whole operation:

    python -m dropship today

Design rule: every command that reports a number also reports the threshold it
should be judged against, and every command that reports a problem ends with
the command that fixes it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import cashflow, dashboard, daily, importers, kpis, listings, ops
from . import research, suppliers as sup_mod, testing
from .economics import UnitEconomics, for_product
from .models import AdTest, Config, LedgerEntry, Order, Product, Supplier, today_iso
from .store import Store, DEFAULT_PATH

# ------------------------------------------------------------- formatting --

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW, BLUE = "\033[31m", "\033[32m", "\033[33m", "\033[34m"
_COLOUR = sys.stdout.isatty()

ACTION_COLOUR = {
    "KILL": RED, "SCALE": GREEN, "HOLD": YELLOW,
    "ITERATE": YELLOW, "KEEP_TESTING": BLUE, "NOT_STARTED": DIM,
}


def c(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if _COLOUR else text


def header(text: str) -> None:
    print(f"\n{c(text.upper(), BOLD)}")
    print(c("-" * max(28, len(text)), DIM))


def kv(label: str, value, note: str = "") -> None:
    suffix = f"  {c(note, DIM)}" if note else ""
    print(f"  {label:<26} {value}{suffix}")


def table(headers: list[str], rows: list[list[str]], right: set[int] | None = None) -> None:
    if not rows:
        print(c("  (nothing yet)", DIM))
        return
    right = right or set(range(1, len(headers)))
    widths = [max(len(str(headers[i])), max(len(str(r[i])) for r in rows))
              for i in range(len(headers))]
    line = "  " + "  ".join(
        (str(h).rjust(widths[i]) if i in right else str(h).ljust(widths[i]))
        for i, h in enumerate(headers))
    print(c(line, DIM))
    for row in rows:
        print("  " + "  ".join(
            (str(cell).rjust(widths[i]) if i in right else str(cell).ljust(widths[i]))
            for i, cell in enumerate(row)))


def bullets(items: list[str], marker: str = "-") -> None:
    for item in items:
        print(f"  {marker} {item}")


def money(value: float, config: Config) -> str:
    sym = {"USD": "$", "GBP": "£", "EUR": "€"}.get(config.currency, "")
    if value == float("inf"):
        return "n/a"
    return f"{'-' if value < 0 else ''}{sym}{abs(value):,.2f}"


def load(args) -> Store:
    return Store.load(args.store)


def need_product(store: Store, ident: str) -> Product:
    product = store.product(ident)
    if not product:
        sys.exit(f"No product matching '{ident}'. Try: dropship product list")
    return product


# ------------------------------------------------------------------ init --

def cmd_init(args) -> None:
    path = Path(args.store)
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists. Use --force to overwrite.")
    store = Store(path)
    store.config = Config(business_name=args.name or "My Store",
                          currency=args.currency)
    store.save()
    print(f"Created {c(str(path), BOLD)}")
    header("Next")
    bullets([
        "Set your real numbers:  dropship config set payout_delay_days 3",
        "Add a supplier:         dropship supplier add --name 'CJ Dropshipping'",
        "Add a product:          dropship product add --name '...' --price 49.99 --cogs 8.50",
        "Or explore with data:   dropship demo",
    ])
    print(c("\n  The defaults are deliberately pessimistic. Replace them with "
            "measured\n  numbers as soon as you have 50 orders - assumed rates "
            "make every\n  projection optimistic.", DIM))


def cmd_demo(args) -> None:
    from .demo import seed
    store = Store.load(args.store)
    seed(store)
    store.save()
    print(f"Seeded demo data into {c(str(store.path), BOLD)} "
          f"({len(store.products)} products, {len(store.orders)} orders).")
    print("Try:  dropship today   |   dropship portfolio   |   dropship dashboard")


# ---------------------------------------------------------------- config --

def cmd_config_show(args) -> None:
    store = load(args)
    header("Configuration")
    for key, value in store.config.to_dict().items():
        kv(key, value)
    print(c("\n  Change with: dropship config set <key> <value>", DIM))


def cmd_config_set(args) -> None:
    store = load(args)
    current = store.config.to_dict()
    if args.key not in current:
        sys.exit(f"Unknown key '{args.key}'. See: dropship config show")
    old = current[args.key]
    try:
        new = (args.value.lower() in ("true", "1", "yes")) if isinstance(old, bool) \
            else type(old)(args.value) if old is not None else args.value
    except ValueError:
        sys.exit(f"'{args.value}' is not a valid {type(old).__name__}")
    setattr(store.config, args.key, new)
    store.save()
    print(f"{args.key}: {old} -> {c(str(new), BOLD)}")


# -------------------------------------------------------------- supplier --

def cmd_supplier_add(args) -> None:
    store = load(args)
    supplier = Supplier(
        name=args.name, platform=args.platform or "", country=args.country or "",
        unit_price=args.unit_price, ship_cost=args.ship_cost,
        handling_days=args.handling_days, transit_days=args.transit_days,
        tracking_quality=args.tracking, defect_rate=args.defect_rate,
        response_hours=args.response_hours, moq=args.moq,
        stock_depth=args.stock_depth, custom_packaging=args.custom_packaging,
        payment_terms=args.payment_terms, sample_ordered=args.sample,
    )
    store.add(supplier)
    store.save()
    print(f"Added supplier {c(supplier.name, BOLD)} ({supplier.id})")
    score = sup_mod.score_supplier(supplier, store.config)
    print(f"Score {score.score:.0f}/100 (grade {score.grade}), "
          f"lead time {supplier.lead_days:.0f} days")
    if not supplier.sample_ordered:
        print(c("\n  You have not ordered a sample. Do that before anything else:", YELLOW))
        bullets(sup_mod.SAMPLE_CHECKLIST[:4])
        print(c("  Full checklist: dropship supplier checklist", DIM))


def cmd_supplier_list(args) -> None:
    store = load(args)
    scores = sup_mod.compare(store.suppliers, store.config)
    header("Suppliers")
    table(["Name", "Grade", "Score", "Landed", "Lead", "Flags"],
          [[s.name[:24], s.grade, f"{s.score:.0f}",
            money(s.landed_cost, store.config), f"{s.lead_days:.0f}d",
            str(len(s.red_flags))] for s in scores])


def cmd_supplier_score(args) -> None:
    store = load(args)
    supplier = store.supplier(args.supplier)
    if not supplier:
        sys.exit(f"No supplier matching '{args.supplier}'")
    benchmark = min((s.landed_cost for s in store.suppliers if s.landed_cost > 0),
                    default=None)
    score = sup_mod.score_supplier(supplier, store.config, benchmark)
    header(f"{supplier.name} - grade {score.grade} ({score.score:.0f}/100)")
    kv("Landed cost", money(score.landed_cost, store.config))
    kv("Lead time", f"{score.lead_days:.0f} days",
       "over 20 days and chargebacks climb")
    print()
    table(["Component", "Score", "Weight"],
          [[k, f"{v:.1f}/10", f"{sup_mod.WEIGHTS[k]}%"]
           for k, v in sorted(score.components.items(), key=lambda kv: -kv[1])])
    if score.red_flags:
        header("Red flags")
        bullets(score.red_flags, c("!", RED))
    if score.notes:
        header("Notes")
        bullets(score.notes)


def cmd_supplier_checklist(args) -> None:
    header("Sample order checklist")
    print(c("  A supplier you have not ordered from is not a vetted supplier.\n", DIM))
    for i, step in enumerate(sup_mod.SAMPLE_CHECKLIST, 1):
        print(f"  {i:>2}. {step}")


# --------------------------------------------------------------- product --

def cmd_product_add(args) -> None:
    store = load(args)
    product = Product(
        name=args.name, sku=args.sku or "", category=args.category or "",
        price=args.price, cogs=args.cogs, ship_cost=args.ship_cost,
        upsell_revenue=args.upsell_revenue, upsell_cogs=args.upsell_cogs,
        supplier_id=(store.supplier(args.supplier).id
                     if args.supplier and store.supplier(args.supplier) else ""),
        demand=args.demand, competition=args.competition,
        creative_potential=args.creative, problem_solving=args.problem,
        wow_factor=args.wow, seasonality=args.seasonality,
        return_risk=args.return_risk, restricted=args.restricted,
        brand_risk=args.brand_risk, delivery_days=args.delivery_days,
        local_stock=args.local_stock, notes=args.notes or "",
    )
    store.add(product)
    result = research.score_product(product, store.config)
    product.score, product.tier = result.score, result.tier
    product.test_budget = result.recommended_test_budget
    product.status = "approved" if result.passed and result.tier in ("A", "B") \
        else "candidate"
    store.save()
    print(f"Added {c(product.name, BOLD)} ({product.id})")
    _print_research(result, product, store)


def cmd_product_list(args) -> None:
    store = load(args)
    rows = daily.portfolio(store)
    if args.status:
        rows = [r for r in rows if r["status"] == args.status]
    header("Products")
    table(["Name", "Status", "Score", "Price", "CM", "BE ROAS", "Orders",
           "Profit", "Verdict"],
          [[r["name"][:22], r["status"], f"{r['score']:.0f}{r['tier']}",
            money(r["price"], store.config), money(r["cm"], store.config),
            f"{r['be_roas']:.2f}x", str(r["orders"]),
            money(r["profit"], store.config),
            c(r["verdict"], ACTION_COLOUR.get(r["verdict"], "")) if r["verdict"] else "-"]
           for r in rows])


def _print_research(result: research.ResearchResult, product: Product,
                    store: Store) -> None:
    ue = for_product(product, store.config)
    header(f"{result.name} - {result.score:.0f}/100 (tier {result.tier})")
    print(f"  {c(result.verdict, BOLD)}\n")
    kv("Price", money(product.price, store.config))
    kv("Landed cost", money(product.landed_cost, store.config),
       f"{product.margin_multiple:.2f}x markup")
    kv("Contribution margin", money(ue.contribution_margin, store.config),
       f"{ue.contribution_margin_pct * 100:.0f}% of AOV")
    kv("Breakeven CPA", money(ue.breakeven_cpa, store.config))
    kv("Breakeven ROAS", f"{ue.breakeven_roas:.2f}x",
       f"target {ue.target_roas():.2f}x")
    if result.recommended_test_budget:
        kv("Test budget", money(result.recommended_test_budget, store.config),
           "enough spend for a real verdict")

    if result.blockers:
        header("Blockers")
        bullets(result.blockers, c("x", RED))
        kv("Price that would clear the floor",
           money(result.recommended_price, store.config))
    if result.strengths:
        header("Strengths")
        bullets(result.strengths, c("+", GREEN))
    if result.risks:
        header("Risks")
        bullets(result.risks, c("!", YELLOW))
    print()
    table(["Component", "Score", "Weight"],
          [[k, f"{v:.1f}/10", f"{research.WEIGHTS[k]}%"]
           for k, v in sorted(result.components.items(), key=lambda kv: -kv[1])])


def cmd_product_score(args) -> None:
    store = load(args)
    targets = store.products if args.all else [need_product(store, args.product)]
    if not targets:
        sys.exit("No products. Add one: dropship product add --name '...'")
    for product in targets:
        result = research.score_product(product, store.config)
        product.score, product.tier = result.score, result.tier
        product.test_budget = result.recommended_test_budget
        product.updated = today_iso()
        if product.status == "candidate" and result.passed and result.tier in ("A", "B"):
            product.status = "approved"
        if not result.passed and product.status in ("candidate", "approved"):
            product.status = "candidate"
        if args.all:
            flag = c("OK ", GREEN) if result.passed else c("REJ", RED)
            print(f"  {flag} {result.score:>5.1f} {result.tier:<6} {result.name}")
        else:
            _print_research(result, product, store)
    store.save()


def cmd_product_set(args) -> None:
    store = load(args)
    product = need_product(store, args.product)
    current = product.to_dict()
    if args.key not in current:
        sys.exit(f"Unknown field '{args.key}'. Fields: {', '.join(sorted(current))}")
    old = current[args.key]
    try:
        new = (args.value.lower() in ("true", "1", "yes")) if isinstance(old, bool) \
            else type(old)(args.value) if old is not None else args.value
    except ValueError:
        sys.exit(f"'{args.value}' is not a valid {type(old).__name__}")
    setattr(product, args.key, new)
    product.updated = today_iso()
    store.save()
    print(f"{product.name}.{args.key}: {old} -> {c(str(new), BOLD)}")


def cmd_product_delete(args) -> None:
    store = load(args)
    product = need_product(store, args.product)
    store.remove(product)
    store.save()
    print(f"Deleted {product.name}")


# ------------------------------------------------------------ economics --

def cmd_econ(args) -> None:
    store = load(args)
    if args.product:
        product = need_product(store, args.product)
        ue = for_product(product, store.config)
        name = product.name
    else:
        if args.price is None or args.cogs is None:
            sys.exit("Give --product, or both --price and --cogs.")
        ue = UnitEconomics(price=args.price, cogs=args.cogs,
                           ship_cost=args.ship_cost,
                           upsell_revenue=args.upsell_revenue,
                           upsell_cogs=args.upsell_cogs, config=store.config)
        name = "Ad-hoc"

    b = ue.breakdown()
    header(f"Unit economics - {name}")
    kv("Average order value", money(b["aov"], store.config))
    print(c("  " + "-" * 44, DIM))
    for label, key in (("Product cost", "product_cost"),
                       ("Shipping", "shipping_cost"),
                       ("Payment fees", "payment_fees"),
                       ("Platform fees", "platform_fees"),
                       ("Support", "support_cost"),
                       ("Expected refunds", "expected_refund_cost"),
                       ("Expected chargebacks", "expected_chargeback_cost")):
        if b[key]:
            kv(f"  less {label}", money(-b[key], store.config))
    print(c("  " + "-" * 44, DIM))
    kv(c("Contribution margin", BOLD), c(money(b["contribution_margin"], store.config), BOLD),
       f"{b['contribution_margin_pct'] * 100:.1f}% of AOV")

    header("What this means")
    kv("Max you can pay per sale", money(ue.breakeven_cpa, store.config),
       "breakeven CPA")
    kv("Breakeven ROAS", f"{ue.breakeven_roas:.2f}x",
       "ad dashboard must beat this")
    kv(f"Target ROAS ({store.config.target_net_margin * 100:.0f}% net)",
       f"{ue.target_roas():.2f}x")
    kv("Max CPC at 2% CVR", money(ue.max_cpc(0.02), store.config))
    kv("CVR needed at $1 CPC", f"{ue.required_cvr(1.0) * 100:.2f}%")
    kv("Orders/mo to cover fixed costs", f"{ue.breakeven_orders():.0f}",
       "before any ad spend")

    header("Price ladder")
    ladder = ue.price_ladder([round(ue.price * m, 2)
                              for m in (0.8, 0.9, 1.0, 1.1, 1.25, 1.5)])
    table(["Price", "CM", "CM %", "Breakeven ROAS", "Markup"],
          [[money(r["price"], store.config), money(r["contribution_margin"], store.config),
            f"{r['cm_pct'] * 100:.0f}%", f"{r['breakeven_roas']:.2f}x",
            f"{r['margin_multiple']:.2f}x"] for r in ladder])
    print(c("\n  Discounting moves breakeven ROAS faster than it moves volume. "
            "Check\n  this table before you run a sale.", DIM))

    header("What hurts most if you are wrong")
    table(["Scenario", "CM", "Change", "Breakeven ROAS"],
          [[r["scenario"], money(r["contribution_margin"], store.config),
            money(r["delta"], store.config), f"{r['breakeven_roas']:.2f}x"]
           for r in ue.sensitivity()])


# ----------------------------------------------------------------- tests --

def cmd_test_plan(args) -> None:
    store = load(args)
    product = need_product(store, args.product)
    ue = for_product(product, store.config)
    plan = testing.plan_test(product.name, ue, store.config, args.days, args.creatives)

    header(f"Test plan - {plan.product_name}")
    kv("Total budget", money(plan.total_budget, store.config),
       "set by statistics, not by feel")
    kv("Daily budget", money(plan.daily_budget, store.config),
       f"over {plan.days} days")
    kv("Creatives", f"{plan.creatives} hooks, 1 angle")
    kv("Breakeven CPA", money(plan.breakeven_cpa, store.config))
    kv("Target CPA", money(plan.target_cpa, store.config),
       f"ROAS {plan.target_roas:.2f}x")

    header("Checkpoints")
    table(["Day", "At spend", "Look at", "Act if"],
          [[str(cp["day"]), money(cp["at_spend"], store.config),
            cp["look_at"], cp["act_if"][:52]] for cp in plan.checkpoints],
          right={1})

    header("Rules")
    bullets(plan.rules)

    if args.start:
        test = AdTest(product_id=product.id, channel=args.channel,
                      planned_budget=plan.total_budget,
                      daily_budget=plan.daily_budget,
                      hypothesis=args.hypothesis or "", angle=args.angle or "")
        store.add(test)
        product.status = "testing"
        store.save()
        print(f"\nStarted test {c(test.id, BOLD)}. Record results with:")
        print(f"  dropship test update {test.id} --spend 0 --clicks 0 --purchases 0")


def cmd_test_update(args) -> None:
    store = load(args)
    test = store.test(args.test) if args.test else None
    if test is None and args.product:
        product = need_product(store, args.product)
        test = store.active_test(product.id)
    if test is None:
        sys.exit("No test found. Start one: dropship test plan <product> --start")

    for field_name in ("spend", "impressions", "clicks", "landing_views",
                       "add_to_carts", "checkouts", "purchases", "revenue"):
        value = getattr(args, field_name, None)
        if value is not None:
            setattr(test, field_name, value)
    if args.daily_budget is not None:
        test.daily_budget = args.daily_budget
    store.save()
    print(f"Updated {test.id}: spend {test.spend:,.2f}, "
          f"{test.purchases} purchases, {test.clicks} clicks")
    _decide_and_print(store, test)


def _decide_and_print(store: Store, test: AdTest) -> None:
    product = store.product(test.product_id)
    if not product:
        sys.exit("Test is not linked to a product.")
    ue = for_product(product, store.config)
    d = testing.decide(test, ue, store.config)
    test.decision, test.decision_date = d.action, today_iso()

    header(f"Verdict: {c(d.action, ACTION_COLOUR.get(d.action, ''))}")
    print(f"  {c(d.headline, BOLD)}\n")
    for line in d.reasoning:
        print(f"  {line}")

    print()
    kv("Observed CPA", money(d.observed_cpa, store.config))
    kv("True CPA range",
       f"{money(d.cpa_best_case, store.config)} - {money(d.cpa_worst_case, store.config)}",
       f"{d.confidence * 100:.0f}% confidence")
    kv("Breakeven CPA", money(d.breakeven_cpa, store.config))
    kv("Target CPA", money(d.target_cpa, store.config))
    kv("Profit so far", money(d.profit_so_far, store.config))

    header("Funnel")
    table(["Stage", "Rate", "Counts", "Floor", "Status"],
          [[s.name, f"{s.value * 100:.2f}%", f"{s.numerator}/{s.denominator}",
            f"{s.low * 100:.1f}%",
            c(s.status, {"weak": RED, "ok": YELLOW, "good": GREEN}.get(s.status, DIM))]
           for s in d.funnel])
    if d.weakest_stage:
        print(c(f"\n  Weakest link: {d.weakest_stage}", YELLOW))

    header("Do this")
    bullets(d.next_steps, ">")

    # Reflect the verdict in product state so the portfolio stays truthful.
    if d.action == testing.KILL:
        product.status = "killed"
        test.ended = today_iso()
    elif d.action == testing.SCALE:
        product.status = "scaling"
    elif d.action == testing.ITERATE:
        product.status = "iterating"
    store.save()


def cmd_test_decide(args) -> None:
    store = load(args)
    test = store.test(args.test) if args.test else None
    if test is None and args.product:
        test = store.active_test(need_product(store, args.product).id)
    if test is None:
        sys.exit("No test found.")
    _decide_and_print(store, test)


def cmd_test_list(args) -> None:
    store = load(args)
    header("Tests")
    rows = []
    for test in store.tests:
        product = store.product(test.product_id)
        rows.append([
            test.id, (product.name[:20] if product else "?"), test.channel,
            money(test.spend, store.config), str(test.purchases),
            money(test.spend / test.purchases, store.config) if test.purchases else "-",
            c(test.decision or "-", ACTION_COLOUR.get(test.decision, "")),
            "ended" if test.ended else "live",
        ])
    table(["ID", "Product", "Channel", "Spend", "Sales", "CPA", "Verdict", "State"], rows)


def cmd_test_ladder(args) -> None:
    store = load(args)
    test = store.test(args.test) if args.test else None
    if test is None and args.product:
        test = store.active_test(need_product(store, args.product).id)
    if test is None:
        sys.exit("No test found.")
    product = store.product(test.product_id)
    ue = for_product(product, store.config)
    current = test.daily_budget or (test.spend / 5)
    cashflow_guard = cashflow.max_safe_daily_spend(
        ue, store.config, ue.target_cpa(), 45, _cash_position(store))

    header(f"Scale ladder - {product.name}")
    kv("Current daily budget", money(current, store.config))
    kv("Cash allows up to", money(cashflow_guard, store.config), "per day")
    print()
    ladder = testing.scale_ladder(current, ue, store.config, args.steps)
    table(["Step", "Daily", "Hold", "Orders/day", "Profit/day", "Cash needed", "Revert if"],
          [[str(r["step"]), money(r["daily_budget"], store.config),
            f"{r['hold_days']}d", f"{r['expected_orders_per_day']:.1f}",
            money(r["expected_daily_profit"], store.config),
            money(r["cash_needed"], store.config),
            f"CPA > {money(r['stop_loss_cpa'], store.config)} x3d"]
           for r in ladder])
    over = [r for r in ladder if r["daily_budget"] > cashflow_guard]
    if over:
        print(c(f"\n  ! Step {over[0]['step']} exceeds what your cash can cover "
                f"({money(cashflow_guard, store.config)}/day).\n"
                f"    Stop there until payouts catch up, or you will be "
                f"profitable and broke.", YELLOW))


# ------------------------------------------------------------------ cash --

def cmd_cash_sim(args) -> None:
    store = load(args)
    ue = (for_product(need_product(store, args.product), store.config)
          if args.product else _first_ue(store))
    cash = args.cash if args.cash is not None else _cash_position(store)
    result = cashflow.simulate(ue, store.config, args.daily, args.cpa, args.days,
                               cash, args.growth)

    header(f"Cash simulation - {args.days} days")
    kv("Starting cash", money(result.starting_cash, store.config))
    kv("Daily ad spend", money(args.daily, store.config),
       f"+{args.growth * 100:.0f}%/day" if args.growth else "")
    kv("Assumed CPA", money(args.cpa, store.config))
    kv("Payout delay", f"{store.config.payout_delay_days} days")
    print()
    kv("Ending cash", money(result.ending_cash, store.config))
    kv("Lowest balance", money(result.min_balance, store.config),
       f"on day {result.min_balance_day}")
    kv("Peak working capital", money(result.peak_working_capital, store.config),
       "most you are out of pocket at once")
    kv("Paper profit", money(result.total_profit, store.config))
    if result.insolvent_day:
        print(c(f"\n  ! INSOLVENT on day {result.insolvent_day}", RED))

    for warning in result.warnings:
        print(c(f"  ! {warning}", YELLOW))

    step = max(1, args.days // 12)
    header("Ledger")
    table(["Day", "Orders", "In", "Out", "Balance"],
          [[str(r.day), f"{r.orders:.1f}",
            money(r.cash_in + r.reserve_released, store.config),
            money(r.cash_out, store.config), money(r.balance, store.config)]
           for r in result.rows[::step]])


def cmd_cash_max(args) -> None:
    store = load(args)
    ue = (for_product(need_product(store, args.product), store.config)
          if args.product else _first_ue(store))
    cash = args.cash if args.cash is not None else _cash_position(store)
    cpa = args.cpa if args.cpa is not None else ue.target_cpa()
    safe = cashflow.max_safe_daily_spend(ue, store.config, cpa, args.days, cash,
                                         args.buffer)
    header("Maximum safe daily ad spend")
    kv("Starting cash", money(cash, store.config))
    kv("Assumed CPA", money(cpa, store.config))
    kv("Payout delay", f"{store.config.payout_delay_days} days")
    kv("Safety buffer", f"{args.buffer * 100:.0f}% of cash held back")
    print()
    kv(c("Safe daily spend", BOLD), c(money(safe, store.config), BOLD))
    kv("Monthly equivalent", money(safe * 30, store.config))
    if safe <= 0:
        print(c(f"\n  ! Contribution margin is "
                f"{money(ue.contribution_margin, store.config)} - this product "
                f"loses money on\n    every order, so no daily budget is safe. "
                f"Fix price or cost first:\n    dropship econ", RED))
    else:
        print(c("\n  This is a cash constraint, not a profitability one. Even a "
                "product with\n  perfect unit economics cannot outrun a payout "
                "delay.", DIM))


def cmd_cash_scenarios(args) -> None:
    store = load(args)
    ue = (for_product(need_product(store, args.product), store.config)
          if args.product else _first_ue(store))
    cash = args.cash if args.cash is not None else _cash_position(store)
    cpa = args.cpa if args.cpa is not None else ue.target_cpa()
    header(f"Cash scenarios over {args.days} days")
    table(["Scenario", "Daily", "End cash", "Low point", "Day", "Profit", "Insolvent"],
          [[r["scenario"], money(r["daily_spend"], store.config),
            money(r["ending_cash"], store.config),
            money(r["min_balance"], store.config), str(r["min_day"]),
            money(r["profit"], store.config),
            c(f"day {r['insolvent_day']}", RED) if r["insolvent_day"] else "no"]
           for r in cashflow.scenarios(ue, store.config, cpa, args.days, cash)])


def _first_ue(store: Store) -> UnitEconomics:
    live = [p for p in store.products
            if p.status in ("testing", "scaling", "winner", "approved")]
    pool = live or store.products
    if not pool:
        sys.exit("No products yet. Add one, or pass --product.")
    return for_product(max(pool, key=lambda p: p.price), store.config)


def _cash_position(store: Store) -> float:
    return store.config.starting_cash + sum(e.amount for e in store.ledger)


# --------------------------------------------------------------- listing --

def cmd_listing(args) -> None:
    store = load(args)
    product = need_product(store, args.product)
    ue = for_product(product, store.config)
    listing = listings.generate(product, ue, args.problem or "", args.outcome or "")

    header(f"Listing draft - {listing.product_name}")
    print(c("  Anything in {braces} is a slot you must fill before publishing.\n", DIM))

    header("Title options")
    bullets(listing.titles)
    header("Bullets")
    bullets(listing.bullets)
    header("Description")
    print("\n".join(f"  {line}" for line in listing.description.splitlines()))
    header("FAQ")
    for question, answer in listing.faq:
        print(f"  {c(question, BOLD)}\n    {answer}\n")
    header("Trust blocks")
    bullets(listing.trust_blocks)
    header("Raising AOV (the cheapest lever on target ROAS)")
    bullets(listing.upsell_ideas)

    header("Ad angles - test angles against each other, not wordings")
    for hook in listing.ad_hooks:
        print(f"  {c(hook['name'], BOLD)}")
        print(f"    Hook: {hook['hook']}")
        print(f"    Body: {hook['body']}")
        print(c(f"    Use when: {hook['use_when']}\n", DIM))

    header("UGC brief")
    print("\n".join(f"  {line}" for line in listing.ugc_brief.splitlines()))

    header("Email / SMS flow")
    table(["Trigger", "Delay", "Goal"],
          [[f["trigger"], f["delay"], f["goal"]] for f in listing.email_flow],
          right=set())
    for flow in listing.email_flow:
        print(f"\n  {c(flow['trigger'] + ' + ' + flow['delay'], BOLD)}")
        print(f"    {flow['content']}")

    header("Before you publish")
    bullets(listing.todo, ">")

    if args.out:
        path = Path(args.out)
        path.write_text(_listing_markdown(listing), encoding="utf-8")
        print(f"\nWritten to {c(str(path), BOLD)}")


def _listing_markdown(listing: listings.Listing) -> str:
    parts = [f"# {listing.product_name}\n", f"_{listing.subtitle}_\n",
             "## Title options\n"]
    parts += [f"- {t}" for t in listing.titles]
    parts.append("\n## Bullets\n")
    parts += [f"- {b}" for b in listing.bullets]
    parts.append("\n## Description\n")
    parts.append(listing.description)
    parts.append("\n## FAQ\n")
    parts += [f"**{q}**\n\n{a}\n" for q, a in listing.faq]
    parts.append("\n## Upsells\n")
    parts += [f"- {u}" for u in listing.upsell_ideas]
    parts.append("\n## Ad angles\n")
    for hook in listing.ad_hooks:
        parts.append(f"### {hook['name']}\n\n- Hook: {hook['hook']}\n"
                     f"- Body: {hook['body']}\n- Use when: {hook['use_when']}\n")
    parts.append("\n## UGC brief\n\n```\n" + listing.ugc_brief + "\n```\n")
    parts.append("\n## Email flow\n")
    for flow in listing.email_flow:
        parts.append(f"- **{flow['trigger']} ({flow['delay']})** - "
                     f"{flow['goal']}: {flow['content']}")
    parts.append("\n## Before publishing\n")
    parts += [f"- [ ] {t}" for t in listing.todo]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- orders --

def cmd_order_add(args) -> None:
    store = load(args)
    product = store.product(args.product) if args.product else None
    order = Order(external_id=args.id or "", product_id=product.id if product else "",
                  customer=args.customer or "", email=args.email or "",
                  revenue=args.revenue, quantity=args.quantity,
                  cogs=(product.landed_cost * args.quantity) if product else 0.0,
                  status=args.status,
                  promised_days=product.delivery_days if product else 14.0)
    store.add(order)
    store.save()
    print(f"Added order {c(order.external_id or order.id, BOLD)}")


def cmd_order_list(args) -> None:
    store = load(args)
    orders = store.orders
    if args.status:
        orders = [o for o in orders if o.status == args.status]
    header("Orders")
    table(["Order", "Status", "Revenue", "Ordered", "Tracking", "Issue"],
          [[o.external_id or o.id, o.status, money(o.revenue, store.config),
            o.ordered_date, o.tracking_number or "-", o.issue or "-"]
           for o in orders[-args.limit:]])


def cmd_order_sla(args) -> None:
    store = load(args)
    queue = ops.action_queue(store.orders, store.config)
    health = ops.fulfilment_health(store.orders, store.config)

    header("Fulfilment health")
    kv("Orders", health["orders"])
    kv("Delivered", f"{health['delivery_rate'] * 100:.0f}%")
    kv("Average delivery", f"{health['avg_delivery_days']:.1f} days")
    kv("On time", f"{health['on_time_rate'] * 100:.0f}%", "target 85%+")
    kv("Refund rate", f"{health['refund_rate'] * 100:.1f}%")
    kv("Chargeback rate", f"{health['chargeback_rate'] * 100:.2f}%",
       "1% is the processor danger line")
    kv("Untracked orders", health["untracked"])

    header(f"Action queue ({len(queue)})")
    if not queue:
        print(c("  Nothing drifting. Rare and good.", GREEN))
        return
    for action in queue[:args.limit]:
        colour = {"critical": RED, "high": YELLOW}.get(action.severity, DIM)
        print(f"\n  {c(action.severity.upper(), colour)}  "
              f"{c(action.external_id, BOLD)} - {action.issue}")
        print(f"    Why: {action.why_it_matters}")
        print(f"    Do:  {action.do_this}")
        if action.macro:
            print(c(f"    Template: dropship cs {action.macro}", DIM))


def cmd_cs(args) -> None:
    if not args.macro:
        header("Support templates")
        table(["Key", "Name"],
              [[k, v["name"]] for k, v in sorted(ops.MACROS.items())], right=set())
        print(c("\n  dropship cs wismo --field name=Alex --field order_id=1042", DIM))
        return
    fields = {}
    for pair in args.field or []:
        if "=" not in pair:
            sys.exit(f"--field expects key=value, got '{pair}'")
        key, value = pair.split("=", 1)
        fields[key.strip()] = value.strip()
    try:
        print("\n" + ops.render_macro(args.macro, **fields))
    except KeyError as exc:
        sys.exit(str(exc))


# --------------------------------------------------------------- import --

def cmd_import_orders(args) -> None:
    store = load(args)
    result = importers.import_orders(args.file, store.products, store.orders)
    store.save()
    print(f"Orders: {result.summary()}")
    if result.mapped_columns:
        print(c("  Mapped: " + ", ".join(f"{k}<-{v}" for k, v in
                                         result.mapped_columns.items()), DIM))
    for warning in result.warnings:
        print(c(f"  ! {warning}", YELLOW))


def cmd_import_ads(args) -> None:
    store = load(args)
    product_id = ""
    if args.product:
        product_id = need_product(store, args.product).id
    result = importers.import_ads(args.file, store.tests, store.products,
                                  product_id, args.channel)
    if args.ledger:
        store.ledger.extend(
            importers.ledger_from_ads(store.tests, store.ledger))
    store.save()
    print(f"Ad data: {result.summary()}")
    for warning in result.warnings:
        print(c(f"  ! {warning}", YELLOW))
    for test in store.tests:
        if not test.ended and test.spend > 0:
            product = store.product(test.product_id)
            if product:
                d = testing.decide(test, for_product(product, store.config),
                                   store.config)
                print(f"  {product.name[:24]:<26} "
                      f"{c(d.action, ACTION_COLOUR.get(d.action, ''))}")


# ------------------------------------------------------------------ kpi --

def cmd_kpi(args) -> None:
    store = load(args)
    report = kpis.build(store.products, store.orders, store.tests, store.ledger,
                        store.config, args.days)
    header(f"KPIs - {report.start} to {report.end}")
    kv("Revenue", money(report.revenue, store.config), f"{report.orders} orders")
    kv("AOV", money(report.aov, store.config))
    kv("Ad spend", money(report.ad_spend, store.config))
    kv("Contribution margin", money(report.contribution_margin, store.config))
    kv("Fixed costs", money(report.fixed_costs, store.config))
    kv(c("Net profit", BOLD),
       c(money(report.net_profit, store.config),
         GREEN if report.net_profit >= 0 else RED),
       f"{report.net_margin * 100:.1f}% margin")
    print()
    kv("Blended ROAS", f"{report.blended_roas:.2f}x",
       f"breakeven {report.breakeven_roas:.2f}x")
    kv("Blended CAC", money(report.blended_cac, store.config))
    kv("Refund rate", f"{report.refund_rate * 100:.1f}%",
       f"assumed {store.config.refund_rate * 100:.1f}%")
    kv("Chargeback rate", f"{report.chargeback_rate * 100:.2f}%", "danger above 1%")
    kv("On-time delivery", f"{report.on_time_rate * 100:.0f}%")
    kv("Cash position", money(report.cash_position, store.config))

    header("Alerts")
    for alert in report.alerts:
        colour = {"critical": RED, "warning": YELLOW}.get(alert.severity, DIM)
        print(f"\n  {c(alert.severity.upper(), colour)}  {alert.message}")
        print(f"    Fix: {alert.fix}")

    if report.by_product:
        header("By product")
        table(["Product", "Orders", "Revenue", "Spend", "ROAS", "Breakeven", "Profit"],
              [[r["name"][:22], str(r["orders"]), money(r["revenue"], store.config),
                money(r["ad_spend"], store.config), f"{r['roas']:.2f}x",
                f"{r['breakeven_roas']:.2f}x", money(r["profit"], store.config)]
               for r in report.by_product])


# --------------------------------------------------------------- today --

def cmd_today(args) -> None:
    store = load(args)
    brief = daily.build(store, focus_count=args.focus)
    board = brief.scoreboard

    print(f"\n{c(store.config.business_name + ' - ' + brief.date, BOLD)}")
    print(c("=" * 60, DIM))
    print(f"\n  {brief.headline}\n")

    kv("Revenue (30d)", money(board["revenue_30d"], store.config))
    kv("Net profit (30d)",
       c(money(board["net_profit_30d"], store.config),
         GREEN if board["net_profit_30d"] >= 0 else RED))
    kv("Blended ROAS", f"{board['blended_roas']:.2f}x",
       f"breakeven {board['breakeven_roas']:.2f}x")
    kv("Cash", money(board["cash"], store.config))
    kv("Testing / scaling",
       f"{board['products_testing']} / {board['products_scaling']}")
    kv("Open actions", f"{board['open_actions']} "
                       f"({board['critical_actions']} critical)")

    items = brief.items if args.all else brief.focus
    header(f"Do these {'' if args.all else 'first'} ({len(items)})")
    if not items:
        print(c("  Nothing outstanding.", GREEN))
    for i, item in enumerate(items, 1):
        colour = {1: RED, 2: YELLOW, 3: BLUE}.get(item.priority, DIM)
        print(f"\n  {c(str(i) + '.', BOLD)} {c('[' + item.area + ']', colour)} "
              f"{c(item.title, BOLD)}")
        print(f"     {item.detail}")
        print(f"     {c('Do:', BOLD)} {item.action}")
        if item.command:
            print(c(f"     $ {item.command}", DIM))

    if not args.all and len(brief.items) > len(items):
        print(c(f"\n  ({len(brief.items) - len(items)} more - "
                f"dropship today --all)", DIM))


def cmd_portfolio(args) -> None:
    store = load(args)
    rows = daily.portfolio(store)
    header("Portfolio")
    table(["Product", "Status", "Score", "CM", "BE CPA", "BE ROAS", "Orders",
           "Spend", "Profit", "Verdict"],
          [[r["name"][:20], r["status"], f"{r['score']:.0f}{r['tier']}",
            money(r["cm"], store.config), money(r["be_cpa"], store.config),
            f"{r['be_roas']:.2f}x", str(r["orders"]),
            money(r["spend"], store.config), money(r["profit"], store.config),
            c(r["verdict"], ACTION_COLOUR.get(r["verdict"], "")) if r["verdict"] else "-"]
           for r in rows])
    total = sum(r["profit"] for r in rows)
    print(f"\n  {c('Total profit', BOLD)}: "
          f"{c(money(total, store.config), GREEN if total >= 0 else RED)}")


def cmd_dashboard(args) -> None:
    store = load(args)
    path = dashboard.write(store, args.out, args.days)
    print(f"Wrote {c(str(path.resolve()), BOLD)}")
    print(c("  Open it in a browser. Works offline, no dependencies.", DIM))


def cmd_doctor(args) -> None:
    """Check the config against reality before it costs you money."""
    store = load(args)
    config = store.config
    problems, notes = [], []

    if config.refund_rate == 0.05 and len(store.orders) >= 50:
        measured = len([o for o in store.orders if o.status == "refunded"]) / len(store.orders)
        if abs(measured - config.refund_rate) > 0.02:
            problems.append(
                f"refund_rate is still the default 5% but your orders show "
                f"{measured * 100:.1f}%. Every breakeven in the system is wrong "
                f"until you run: dropship config set refund_rate {measured:.3f}")
    if config.payout_delay_days == 3:
        notes.append("payout_delay_days is the default 3. Confirm it with your "
                     "processor - new accounts are often 7-21 days, and that "
                     "changes how fast you can scale by an order of magnitude.")
    if config.starting_cash <= config.fixed_monthly_costs * 3:
        problems.append(
            f"starting_cash ({money(config.starting_cash, config)}) is under three "
            f"months of fixed costs. Testing needs a runway; you will be forced "
            f"to kill tests for cash reasons rather than evidence.")
    if not store.suppliers:
        problems.append("No suppliers recorded, so no lead times or defect rates "
                        "feed the economics.")
    unsampled = [s.name for s in store.suppliers if not s.sample_ordered]
    if unsampled:
        problems.append(f"No sample ordered from: {', '.join(unsampled)}. "
                        f"You are about to sell something you have never held.")
    unscored = [p.name for p in store.products if p.score == 0]
    if unscored:
        notes.append(f"Unscored products: {', '.join(unscored[:5])}. "
                     f"Run: dropship product score --all")
    if config.min_margin_multiple < 2.5:
        problems.append(f"min_margin_multiple is {config.min_margin_multiple}. "
                        f"Below 2.5x there is not enough room to buy traffic.")
    live_tests = [t for t in store.tests if not t.ended and t.spend > 0]
    for test in live_tests:
        if test.planned_budget and test.spend > test.planned_budget * 1.5:
            product = store.product(test.product_id)
            problems.append(
                f"Test on {product.name if product else test.id} has spent "
                f"{test.spend:,.0f} against a {test.planned_budget:,.0f} budget. "
                f"That is not a test any more.")

    header("Doctor")
    if problems:
        print(c(f"  {len(problems)} problem(s):\n", RED))
        bullets(problems, c("x", RED))
    else:
        print(c("  No problems found.", GREEN))
    if notes:
        header("Worth checking")
        bullets(notes, c("?", YELLOW))


# ------------------------------------------------------------------ main --

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dropship",
        description="A dropshipping operating system: research, economics, "
                    "test decisions, cash flow, fulfilment and reporting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""start here:
  dropship init --name "My Store"     create the store
  dropship demo                        load example data to explore
  dropship today                       what to do right now
  dropship doctor                      check your assumptions
""")
    p.add_argument("--store", default=str(DEFAULT_PATH),
                   help="path to the data file (default: data/store.json)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create a new store")
    s.add_argument("--name"); s.add_argument("--currency", default="USD")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("demo", help="load example data")
    s.set_defaults(func=cmd_demo)

    # config
    cfg = sub.add_parser("config", help="view or change settings").add_subparsers(
        dest="sub", required=True)
    cfg.add_parser("show", help="print all settings").set_defaults(func=cmd_config_show)
    s = cfg.add_parser("set", help="change one setting")
    s.add_argument("key"); s.add_argument("value")
    s.set_defaults(func=cmd_config_set)

    # supplier
    sp = sub.add_parser("supplier", help="source and vet suppliers").add_subparsers(
        dest="sub", required=True)
    s = sp.add_parser("add")
    s.add_argument("--name", required=True)
    s.add_argument("--platform"); s.add_argument("--country")
    s.add_argument("--unit-price", type=float, default=0.0)
    s.add_argument("--ship-cost", type=float, default=0.0)
    s.add_argument("--handling-days", type=float, default=2.0)
    s.add_argument("--transit-days", type=float, default=12.0)
    s.add_argument("--tracking", type=int, default=5, help="0-10 tracking quality")
    s.add_argument("--defect-rate", type=float, default=0.03)
    s.add_argument("--response-hours", type=float, default=24.0)
    s.add_argument("--moq", type=int, default=1)
    s.add_argument("--stock-depth", type=int, default=5)
    s.add_argument("--custom-packaging", action="store_true")
    s.add_argument("--payment-terms", default="prepaid")
    s.add_argument("--sample", action="store_true", help="sample already ordered")
    s.set_defaults(func=cmd_supplier_add)
    sp.add_parser("list").set_defaults(func=cmd_supplier_list)
    s = sp.add_parser("score"); s.add_argument("supplier")
    s.set_defaults(func=cmd_supplier_score)
    sp.add_parser("checklist", help="sample order checklist").set_defaults(
        func=cmd_supplier_checklist)

    # product
    pr = sub.add_parser("product", help="research and manage products").add_subparsers(
        dest="sub", required=True)
    s = pr.add_parser("add")
    s.add_argument("--name", required=True)
    s.add_argument("--sku"); s.add_argument("--category"); s.add_argument("--supplier")
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--cogs", type=float, required=True)
    s.add_argument("--ship-cost", type=float, default=0.0)
    s.add_argument("--upsell-revenue", type=float, default=0.0)
    s.add_argument("--upsell-cogs", type=float, default=0.0)
    s.add_argument("--demand", type=int, default=5, help="0-10")
    s.add_argument("--competition", type=int, default=5, help="0-10, 10=saturated")
    s.add_argument("--creative", type=int, default=5, help="0-10")
    s.add_argument("--problem", type=int, default=5, help="0-10")
    s.add_argument("--wow", type=int, default=5, help="0-10")
    s.add_argument("--seasonality", type=int, default=5, help="0-10, 10=evergreen")
    s.add_argument("--return-risk", type=int, default=5, help="0-10, 10=high")
    s.add_argument("--delivery-days", type=float, default=14.0)
    s.add_argument("--local-stock", action="store_true")
    s.add_argument("--restricted", action="store_true")
    s.add_argument("--brand-risk", action="store_true")
    s.add_argument("--notes")
    s.set_defaults(func=cmd_product_add)
    s = pr.add_parser("list"); s.add_argument("--status")
    s.set_defaults(func=cmd_product_list)
    s = pr.add_parser("score")
    s.add_argument("product", nargs="?"); s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_product_score)
    s = pr.add_parser("set")
    s.add_argument("product"); s.add_argument("key"); s.add_argument("value")
    s.set_defaults(func=cmd_product_set)
    s = pr.add_parser("delete"); s.add_argument("product")
    s.set_defaults(func=cmd_product_delete)

    # econ
    s = sub.add_parser("econ", help="unit economics and breakeven")
    s.add_argument("product", nargs="?")
    s.add_argument("--price", type=float); s.add_argument("--cogs", type=float)
    s.add_argument("--ship-cost", type=float, default=0.0)
    s.add_argument("--upsell-revenue", type=float, default=0.0)
    s.add_argument("--upsell-cogs", type=float, default=0.0)
    s.set_defaults(func=cmd_econ)

    # test
    ts = sub.add_parser("test", help="plan, record and decide product tests"
                        ).add_subparsers(dest="sub", required=True)
    s = ts.add_parser("plan")
    s.add_argument("product")
    s.add_argument("--days", type=int, default=5)
    s.add_argument("--creatives", type=int, default=3)
    s.add_argument("--channel", default="meta")
    s.add_argument("--hypothesis"); s.add_argument("--angle")
    s.add_argument("--start", action="store_true", help="also create the test")
    s.set_defaults(func=cmd_test_plan)
    s = ts.add_parser("update")
    s.add_argument("test", nargs="?"); s.add_argument("--product")
    for name in ("spend", "revenue", "daily-budget"):
        s.add_argument(f"--{name}", type=float)
    for name in ("impressions", "clicks", "landing-views", "add-to-carts",
                 "checkouts", "purchases"):
        s.add_argument(f"--{name}", type=int)
    s.set_defaults(func=cmd_test_update)
    s = ts.add_parser("decide")
    s.add_argument("test", nargs="?"); s.add_argument("--product")
    s.set_defaults(func=cmd_test_decide)
    ts.add_parser("list").set_defaults(func=cmd_test_list)
    s = ts.add_parser("ladder", help="budget ramp for a winner")
    s.add_argument("test", nargs="?"); s.add_argument("--product")
    s.add_argument("--steps", type=int, default=6)
    s.set_defaults(func=cmd_test_ladder)

    # cash
    ca = sub.add_parser("cash", help="cash flow, the real scaling limit"
                        ).add_subparsers(dest="sub", required=True)
    s = ca.add_parser("sim")
    s.add_argument("--product"); s.add_argument("--daily", type=float, required=True)
    s.add_argument("--cpa", type=float, required=True)
    s.add_argument("--days", type=int, default=90)
    s.add_argument("--cash", type=float); s.add_argument("--growth", type=float, default=0.0)
    s.set_defaults(func=cmd_cash_sim)
    s = ca.add_parser("max-spend")
    s.add_argument("--product"); s.add_argument("--cpa", type=float)
    s.add_argument("--days", type=int, default=60)
    s.add_argument("--cash", type=float)
    s.add_argument("--buffer", type=float, default=0.25)
    s.set_defaults(func=cmd_cash_max)
    s = ca.add_parser("scenarios")
    s.add_argument("--product"); s.add_argument("--cpa", type=float)
    s.add_argument("--days", type=int, default=60); s.add_argument("--cash", type=float)
    s.set_defaults(func=cmd_cash_scenarios)

    # listing
    s = sub.add_parser("listing", help="generate listing copy and ad angles")
    s.add_argument("product")
    s.add_argument("--problem"); s.add_argument("--outcome")
    s.add_argument("--out", help="also write a markdown file")
    s.set_defaults(func=cmd_listing)

    # orders
    od = sub.add_parser("orders", help="fulfilment and SLA").add_subparsers(
        dest="sub", required=True)
    s = od.add_parser("add")
    s.add_argument("--id"); s.add_argument("--product")
    s.add_argument("--customer"); s.add_argument("--email")
    s.add_argument("--revenue", type=float, default=0.0)
    s.add_argument("--quantity", type=int, default=1)
    s.add_argument("--status", default="received")
    s.set_defaults(func=cmd_order_add)
    s = od.add_parser("list")
    s.add_argument("--status"); s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_order_list)
    s = od.add_parser("sla", help="what is drifting toward a refund")
    s.add_argument("--limit", type=int, default=15)
    s.set_defaults(func=cmd_order_sla)

    # cs
    s = sub.add_parser("cs", help="customer service templates")
    s.add_argument("macro", nargs="?")
    s.add_argument("--field", action="append", help="key=value, repeatable")
    s.set_defaults(func=cmd_cs)

    # import
    im = sub.add_parser("import", help="import platform CSV exports").add_subparsers(
        dest="sub", required=True)
    s = im.add_parser("orders"); s.add_argument("file")
    s.set_defaults(func=cmd_import_orders)
    s = im.add_parser("ads")
    s.add_argument("file"); s.add_argument("--product")
    s.add_argument("--channel", default="meta")
    s.add_argument("--ledger", action="store_true", help="also record as cash out")
    s.set_defaults(func=cmd_import_ads)

    # reporting
    s = sub.add_parser("kpi", help="performance and health alerts")
    s.add_argument("--days", type=int, default=30)
    s.set_defaults(func=cmd_kpi)

    s = sub.add_parser("today", help="what to do right now")
    s.add_argument("--all", action="store_true")
    s.add_argument("--focus", type=int, default=3)
    s.set_defaults(func=cmd_today)

    sub.add_parser("portfolio", help="every product on one screen").set_defaults(
        func=cmd_portfolio)

    s = sub.add_parser("dashboard", help="write an HTML dashboard")
    s.add_argument("--out", default="dashboard.html")
    s.add_argument("--days", type=int, default=90)
    s.set_defaults(func=cmd_dashboard)

    sub.add_parser("doctor", help="check your assumptions before they cost money"
                   ).set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
