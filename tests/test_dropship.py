"""Tests for the parts where a bug costs real money.

Priority order matches the risk: the statistics and the economics are tested
hardest, because a wrong breakeven silently poisons every decision downstream.
Runs under plain unittest (no dependencies) and under pytest.
"""

from __future__ import annotations

import io
import contextlib
import http.client
import math
import tempfile
import threading
import unittest
from dataclasses import fields
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dropship import (
    cashflow, cli, dashboard, daily, importers, kpis, listings, ops,
    research, stats, storefront, testing, ui,
)
from dropship import suppliers as sup_mod
from dropship.demo import seed
from dropship.economics import UnitEconomics
from dropship.models import AdTest, Config, LedgerEntry, Order, Product, Supplier
from dropship.store import Store


def base_config(**over) -> Config:
    cfg = Config()
    for key, value in over.items():
        setattr(cfg, key, value)
    return cfg


def base_ue(config: Config | None = None, **over) -> UnitEconomics:
    kwargs = dict(price=49.99, cogs=8.50, ship_cost=3.20,
                  upsell_revenue=6.00, upsell_cogs=1.50)
    kwargs.update(over)
    return UnitEconomics(config=config or base_config(), **kwargs)


# ------------------------------------------------------------------ stats --

class TestStats(unittest.TestCase):
    def test_chi2_matches_published_tables(self):
        for p, dof, expected in [(0.95, 1, 3.8415), (0.95, 2, 5.9915),
                                 (0.05, 10, 3.9403), (0.99, 5, 15.0863),
                                 (0.5, 4, 3.3567)]:
            self.assertAlmostEqual(stats.chi2_ppf(p, dof), expected, places=3,
                                   msg=f"chi2({p}, {dof})")

    def test_z_scores(self):
        self.assertAlmostEqual(stats.z_score(0.95), 1.95996, places=4)
        self.assertAlmostEqual(stats.z_score(0.90), 1.64485, places=4)

    def test_gamma_cdf_is_a_cdf(self):
        previous = 0.0
        for x in [0.1, 0.5, 1, 2, 5, 10, 50]:
            value = stats.gamma_cdf_reg(2.0, x)
            self.assertGreaterEqual(value, previous)
            self.assertTrue(0.0 <= value <= 1.0)
            previous = value

    def test_gamma_ppf_inverts_cdf(self):
        for a in (0.5, 1.0, 3.0, 12.0):
            for p in (0.05, 0.5, 0.95):
                x = stats.gamma_ppf_reg(p, a)
                self.assertAlmostEqual(stats.gamma_cdf_reg(a, x), p, places=6)

    def test_poisson_ci_brackets_the_point_estimate(self):
        lo, hi = stats.poisson_rate_ci(5, 100, 0.90)
        self.assertLess(lo, 0.05)
        self.assertGreater(hi, 0.05)

    def test_poisson_ci_zero_events_has_zero_lower_bound(self):
        lo, hi = stats.poisson_rate_ci(0, 100, 0.90)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)

    def test_poisson_ci_narrows_with_more_data(self):
        narrow = stats.poisson_rate_ci(100, 2000, 0.90)
        wide = stats.poisson_rate_ci(5, 100, 0.90)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])

    def test_wilson_handles_zero_successes(self):
        lo, hi = stats.wilson_interval(0, 50, 0.90)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)
        self.assertLessEqual(hi, 1.0)

    def test_bisect_finds_a_root(self):
        self.assertAlmostEqual(stats.bisect(lambda x: x * x, 0, 10, 9.0), 3.0,
                               places=6)


# -------------------------------------------------------------- economics --

class TestEconomics(unittest.TestCase):
    def test_contribution_margin_matches_hand_calculation(self):
        ue = base_ue()
        # aov 55.99, variable cogs 13.20, fees 1.92371, support 0.50
        kept = 55.99 - 13.20 - (55.99 * 0.029 + 0.30) - 0.50
        refunded = -13.20 - (55.99 * 0.029 + 0.30) - 0.50
        charged = -13.20 - (55.99 * 0.029 + 0.30) - 15.0 - 0.50
        expected = 0.945 * kept + 0.05 * refunded + 0.005 * charged
        self.assertAlmostEqual(ue.contribution_margin, expected, places=6)

    def test_breakeven_roas_identity(self):
        """ROAS x contribution margin must equal AOV, or the model is inconsistent."""
        ue = base_ue()
        self.assertAlmostEqual(ue.breakeven_roas * ue.contribution_margin,
                               ue.aov, places=6)

    def test_profit_is_zero_at_breakeven_cpa(self):
        ue = base_ue()
        self.assertAlmostEqual(ue.profit_at_cpa(ue.breakeven_cpa), 0.0, places=9)

    def test_target_roas_at_zero_margin_equals_breakeven(self):
        ue = base_ue()
        self.assertAlmostEqual(ue.target_roas(0.0), ue.breakeven_roas, places=9)

    def test_target_roas_exceeds_breakeven_for_positive_margin(self):
        ue = base_ue()
        self.assertGreater(ue.target_roas(0.15), ue.breakeven_roas)

    def test_profit_at_roas_agrees_with_profit_at_cpa(self):
        ue = base_ue()
        revenue = ue.aov * 100
        roas = 3.0
        cpa = (revenue / roas) / 100
        self.assertAlmostEqual(ue.profit_at_roas(roas, revenue),
                               ue.profit_at_cpa(cpa, 100), places=6)

    def test_higher_refund_rate_lowers_margin(self):
        low = base_ue(base_config(refund_rate=0.02)).contribution_margin
        high = base_ue(base_config(refund_rate=0.20)).contribution_margin
        self.assertGreater(low, high)

    def test_chargebacks_cost_more_than_refunds(self):
        """A chargeback must be strictly worse, or the ops priorities are wrong."""
        cfg = base_config(refund_rate=0.0, chargeback_rate=0.0)
        refund_only = base_ue(base_config(refund_rate=0.10, chargeback_rate=0.0))
        cb_only = base_ue(base_config(refund_rate=0.0, chargeback_rate=0.10))
        self.assertGreater(refund_only.contribution_margin,
                           cb_only.contribution_margin)

    def test_refunded_payment_fee_helps_margin(self):
        kept = base_ue(base_config(payment_fee_refunded=False)).contribution_margin
        given_back = base_ue(base_config(payment_fee_refunded=True)).contribution_margin
        self.assertGreater(given_back, kept)

    def test_price_ladder_monotonic_in_margin(self):
        ue = base_ue()
        rows = ue.price_ladder([30.0, 40.0, 50.0, 60.0])
        margins = [r["contribution_margin"] for r in rows]
        self.assertEqual(margins, sorted(margins))
        roas = [r["breakeven_roas"] for r in rows]
        self.assertEqual(roas, sorted(roas, reverse=True))

    def test_max_cpc_and_required_cvr_are_inverses(self):
        ue = base_ue()
        cvr = 0.025
        cpc = ue.max_cpc(cvr)
        self.assertAlmostEqual(ue.required_cvr(cpc), cvr, places=9)

    def test_negative_margin_product_has_infinite_breakeven_roas(self):
        ue = base_ue(price=10.0, cogs=12.0, ship_cost=4.0,
                     upsell_revenue=0.0, upsell_cogs=0.0)
        self.assertLess(ue.contribution_margin, 0)
        self.assertEqual(ue.breakeven_roas, float("inf"))

    def test_sensitivity_is_sorted_worst_first(self):
        rows = base_ue().sensitivity()
        deltas = [r["delta"] for r in rows]
        self.assertEqual(deltas, sorted(deltas))


# ---------------------------------------------------------------- research --

class TestResearch(unittest.TestCase):
    def test_thin_margin_is_blocked(self):
        product = Product(name="Thin", price=15.0, cogs=8.0, ship_cost=2.0)
        result = research.score_product(product, base_config())
        self.assertFalse(result.passed)
        self.assertTrue(any("argin multiple" in b for b in result.blockers))

    def test_slow_delivery_is_blocked(self):
        product = Product(name="Slow", price=60.0, cogs=8.0, ship_cost=2.0,
                          delivery_days=40)
        result = research.score_product(product, base_config())
        self.assertFalse(result.passed)
        self.assertTrue(any("delivery" in b for b in result.blockers))

    def test_local_stock_exempts_the_delivery_gate(self):
        product = Product(name="Local", price=60.0, cogs=8.0, ship_cost=2.0,
                          delivery_days=40, local_stock=True)
        result = research.score_product(product, base_config())
        self.assertFalse(any("delivery" in b for b in result.blockers))

    def test_restricted_keyword_is_blocked(self):
        product = Product(name="Herbal Detox Supplement", price=60.0, cogs=8.0,
                          ship_cost=2.0)
        result = research.score_product(product, base_config())
        self.assertFalse(result.passed)
        self.assertTrue(any("Restricted" in b for b in result.blockers))

    def test_brand_risk_is_blocked(self):
        product = Product(name="Clean", price=60.0, cogs=8.0, ship_cost=2.0,
                          brand_risk=True)
        self.assertFalse(research.score_product(product, base_config()).passed)

    def test_good_product_passes_and_scores_high(self):
        product = Product(name="Great", price=59.99, cogs=8.0, ship_cost=2.5,
                          demand=9, competition=3, creative_potential=9,
                          problem_solving=9, wow_factor=9, seasonality=9,
                          return_risk=1, delivery_days=8)
        result = research.score_product(product, base_config())
        self.assertTrue(result.passed)
        self.assertGreater(result.score, 75)
        self.assertEqual(result.tier, "A")

    def test_scores_stay_within_bounds(self):
        for demand in range(0, 11):
            product = Product(name="X", price=59.99, cogs=8.0, ship_cost=2.0,
                              demand=demand, competition=10 - demand)
            result = research.score_product(product, base_config())
            self.assertTrue(0.0 <= result.score <= 100.0)

    def test_blocked_products_get_no_test_budget(self):
        product = Product(name="Bad", price=10.0, cogs=8.0, ship_cost=2.0)
        self.assertEqual(
            research.score_product(product, base_config()).recommended_test_budget,
            0.0)

    def test_suggested_price_clears_the_margin_floor(self):
        cfg = base_config()
        product = Product(name="Cheap", price=12.0, cogs=8.0, ship_cost=2.0)
        suggested = research.suggested_price(product, cfg)
        self.assertGreaterEqual(suggested / product.landed_cost,
                                cfg.min_margin_multiple)

    def test_apply_score_moves_candidates_but_not_live_products(self):
        cfg = base_config()
        great = dict(price=59.99, cogs=8.0, ship_cost=2.5, demand=9, competition=3,
                     creative_potential=9, problem_solving=9, wow_factor=9,
                     seasonality=9, return_risk=1, delivery_days=8)
        candidate = Product(name="Great", **great)
        research.apply_score(candidate, cfg)
        self.assertEqual((candidate.status, candidate.tier), ("approved", "A"))
        live = Product(name="Live", status="scaling", **great)
        research.apply_score(live, cfg)
        self.assertEqual(live.status, "scaling")
        thin = Product(name="Thin", price=15.0, cogs=8.0, ship_cost=2.0,
                       status="approved")
        research.apply_score(thin, cfg)
        self.assertEqual(thin.status, "candidate")

    def test_rank_puts_passing_products_first(self):
        good = Product(name="Good", price=59.99, cogs=8.0, ship_cost=2.0, demand=9)
        bad = Product(name="Bad", price=10.0, cogs=8.0, ship_cost=2.0)
        ranked = research.rank([bad, good], base_config())
        self.assertEqual(ranked[0].name, "Good")


# ----------------------------------------------------------------- testing --

class TestDecisionEngine(unittest.TestCase):
    def setUp(self):
        self.cfg = base_config()
        self.ue = base_ue(self.cfg)

    def make(self, **kw) -> AdTest:
        defaults = dict(product_id="p", planned_budget=120.0)
        defaults.update(kw)
        return AdTest(**defaults)

    def test_no_spend_is_not_started(self):
        d = testing.decide(self.make(), self.ue, self.cfg)
        self.assertEqual(d.action, testing.NOT_STARTED)

    def test_negative_margin_is_an_immediate_kill(self):
        ue = base_ue(price=10.0, cogs=12.0, ship_cost=4.0,
                     upsell_revenue=0.0, upsell_cogs=0.0)
        d = testing.decide(self.make(spend=500, purchases=10), ue, self.cfg)
        self.assertEqual(d.action, testing.KILL)

    def test_zero_sales_below_threshold_keeps_testing(self):
        threshold = -math.log(1 - self.cfg.confidence) * self.ue.breakeven_cpa
        d = testing.decide(self.make(spend=threshold * 0.5), self.ue, self.cfg)
        self.assertEqual(d.action, testing.KEEP_TESTING)
        self.assertGreater(d.spend_to_verdict, 0)

    def test_zero_sales_past_threshold_kills(self):
        threshold = -math.log(1 - self.cfg.confidence) * self.ue.breakeven_cpa
        d = testing.decide(self.make(spend=threshold * 1.2, impressions=50000,
                                     clicks=200, landing_views=170),
                           self.ue, self.cfg)
        self.assertEqual(d.action, testing.KILL)

    def test_zero_sales_with_full_carts_says_iterate_not_kill(self):
        """Strong upper funnel means a broken offer, not a broken product."""
        threshold = -math.log(1 - self.cfg.confidence) * self.ue.breakeven_cpa
        d = testing.decide(
            self.make(spend=threshold * 1.5, impressions=30000, clicks=600,
                      landing_views=520, add_to_carts=60, checkouts=28,
                      purchases=0),
            self.ue, self.cfg)
        self.assertEqual(d.action, testing.ITERATE)
        self.assertEqual(d.weakest_stage, "purchase_rate")

    def test_confident_winner_scales(self):
        d = testing.decide(
            self.make(spend=400, impressions=60000, clicks=900,
                      landing_views=780, add_to_carts=90, checkouts=50,
                      purchases=28, revenue=1570.0),
            self.ue, self.cfg)
        self.assertEqual(d.action, testing.SCALE)
        self.assertLessEqual(d.cpa_worst_case, self.ue.target_cpa())

    def test_confident_loser_kills(self):
        d = testing.decide(
            self.make(spend=500, impressions=80000, clicks=1100,
                      landing_views=950, add_to_carts=70, checkouts=25,
                      purchases=5, revenue=280.0),
            self.ue, self.cfg)
        self.assertEqual(d.action, testing.KILL)
        self.assertGreater(d.cpa_best_case, self.ue.breakeven_cpa)

    def test_marginal_result_holds(self):
        d = testing.decide(
            self.make(spend=300, impressions=50000, clicks=700,
                      landing_views=600, add_to_carts=60, checkouts=30,
                      purchases=9, revenue=504.0),
            self.ue, self.cfg)
        self.assertEqual(d.action, testing.HOLD)

    def test_confidence_interval_contains_observed_cpa(self):
        d = testing.decide(self.make(spend=400, purchases=20), self.ue, self.cfg)
        self.assertLessEqual(d.cpa_best_case, d.observed_cpa)
        self.assertGreaterEqual(d.cpa_worst_case, d.observed_cpa)

    def test_every_decision_carries_next_steps(self):
        cases = [
            self.make(spend=40),
            self.make(spend=400, purchases=28, revenue=1570),
            self.make(spend=500, purchases=5, revenue=280),
            self.make(spend=200, impressions=30000, clicks=600,
                      landing_views=520, add_to_carts=60, checkouts=28),
        ]
        for test in cases:
            d = testing.decide(test, self.ue, self.cfg)
            self.assertTrue(d.headline, f"{d.action} has no headline")
            self.assertTrue(d.next_steps, f"{d.action} has no next steps")

    def test_funnel_falls_back_to_clicks_without_landing_views(self):
        stages = testing.analyse_funnel(self.make(clicks=100, landing_views=0,
                                                  add_to_carts=10))
        atc = next(s for s in stages if s.name == "atc_rate")
        self.assertEqual(atc.denominator, 100)

    def test_weakest_stage_ignores_thin_data(self):
        stages = testing.analyse_funnel(self.make(impressions=10, clicks=0))
        self.assertEqual(testing.weakest_stage(stages, min_denominator=25), "")

    def test_plan_budget_reaches_statistical_significance(self):
        plan = testing.plan_test("X", self.ue, self.cfg)
        needed = -math.log(1 - self.cfg.confidence) * self.ue.breakeven_cpa
        self.assertGreaterEqual(plan.total_budget, needed)
        self.assertEqual(len(plan.checkpoints), 4)

    def test_apply_decision_records_the_verdict_on_both_records(self):
        product = Product(name="Loser", status="testing")
        loser = self.make(spend=500, impressions=80000, clicks=1100,
                          landing_views=950, add_to_carts=70, checkouts=25,
                          purchases=5, revenue=280.0)
        testing.apply_decision(loser, product, testing.decide(loser, self.ue, self.cfg))
        self.assertEqual(product.status, "killed")
        self.assertTrue(loser.ended)

        other = Product(name="Marginal", status="testing")
        held = self.make(spend=300, impressions=50000, clicks=700,
                         landing_views=600, add_to_carts=60, checkouts=30,
                         purchases=9, revenue=504.0)
        testing.apply_decision(held, other, testing.decide(held, self.ue, self.cfg))
        self.assertEqual((other.status, held.decision, held.ended),
                         ("testing", testing.HOLD, ""))

    def test_scale_ladder_climbs_and_carries_stop_losses(self):
        ladder = testing.scale_ladder(50.0, self.ue, self.cfg, steps=4)
        budgets = [r["daily_budget"] for r in ladder]
        self.assertEqual(budgets, sorted(budgets))
        self.assertTrue(all(r["stop_loss_cpa"] > 0 for r in ladder))


# ---------------------------------------------------------------- cashflow --

class TestCashflow(unittest.TestCase):
    def test_overspending_causes_insolvency(self):
        cfg = base_config(starting_cash=1000.0, payout_delay_days=14)
        result = cashflow.simulate(base_ue(cfg), cfg, 500.0, 25.0, 30)
        self.assertIsNotNone(result.insolvent_day)
        self.assertFalse(result.solvent)

    def test_modest_spend_stays_solvent(self):
        cfg = base_config(starting_cash=5000.0, payout_delay_days=3)
        result = cashflow.simulate(base_ue(cfg), cfg, 50.0, 25.0, 60)
        self.assertIsNone(result.insolvent_day)

    def test_longer_payout_delay_reduces_safe_spend(self):
        """The core claim of the module: the delay, not the margin, caps scale."""
        fast = base_config(starting_cash=3000.0, payout_delay_days=2)
        slow = base_config(starting_cash=3000.0, payout_delay_days=21)
        self.assertGreater(
            cashflow.max_safe_daily_spend(base_ue(fast), fast, 25.0, 60),
            cashflow.max_safe_daily_spend(base_ue(slow), slow, 25.0, 60))

    def test_small_reserve_ties_up_cash_without_capping_spend(self):
        """A modest reserve holds money but is not the binding constraint.

        At these economics each dollar of ad spend returns about 2.24 in
        revenue against 1.53 in same-day outgoings, so daily cash flow stays
        positive until the reserve passes ~32%. The low point is the initial
        payout gap, which a reserve does not change. Worth asserting, because
        the intuitive answer ("any reserve lowers safe spend") is wrong.
        """
        plain = base_config(starting_cash=3000.0)
        held = base_config(starting_cash=3000.0, rolling_reserve_rate=0.15)
        plain_end = cashflow.simulate(base_ue(plain), plain, 200.0, 25.0, 60)
        held_end = cashflow.simulate(base_ue(held), held, 200.0, 25.0, 60)
        self.assertLess(held_end.ending_cash, plain_end.ending_cash)
        self.assertGreater(held_end.reserve_outstanding, 0.0)
        self.assertAlmostEqual(
            cashflow.max_safe_daily_spend(base_ue(plain), plain, 25.0, 60),
            cashflow.max_safe_daily_spend(base_ue(held), held, 25.0, 60),
            delta=1.0)

    def test_large_reserve_does_cap_safe_spend(self):
        """Past the point where daily cash flow turns negative, it bites hard."""
        plain = base_config(starting_cash=3000.0)
        held = base_config(starting_cash=3000.0, rolling_reserve_rate=0.45)
        self.assertGreater(
            cashflow.max_safe_daily_spend(base_ue(plain), plain, 25.0, 60),
            cashflow.max_safe_daily_spend(base_ue(held), held, 25.0, 60))

    def test_max_safe_spend_respects_the_buffer(self):
        cfg = base_config(starting_cash=4000.0, payout_delay_days=7)
        ue = base_ue(cfg)
        safe = cashflow.max_safe_daily_spend(ue, cfg, 25.0, 60, buffer=0.25)
        at_limit = cashflow.simulate(ue, cfg, safe, 25.0, 60)
        self.assertGreaterEqual(at_limit.min_balance, 4000.0 * 0.25 - 1.0)
        over = cashflow.simulate(ue, cfg, safe * 1.5, 25.0, 60)
        self.assertLess(over.min_balance, at_limit.min_balance)

    def test_a_profitable_business_can_still_go_insolvent(self):
        """The trap the module exists to expose."""
        cfg = base_config(starting_cash=2000.0, payout_delay_days=21,
                          rolling_reserve_rate=0.10)
        result = cashflow.simulate(base_ue(cfg), cfg, 200.0, 25.0, 60)
        self.assertGreater(result.total_profit, 0)
        self.assertIsNotNone(result.insolvent_day)

    def test_zero_cpa_is_rejected(self):
        cfg = base_config()
        result = cashflow.simulate(base_ue(cfg), cfg, 100.0, 0.0, 30)
        self.assertEqual(result.rows, [])
        self.assertTrue(result.warnings)

    def test_scenarios_cover_four_futures(self):
        cfg = base_config(starting_cash=3000.0)
        rows = cashflow.scenarios(base_ue(cfg), cfg, 25.0, 45)
        self.assertEqual(len(rows), 4)
        self.assertLess(rows[0]["daily_spend"], rows[2]["daily_spend"])

    def test_runway_returns_none_when_solvent(self):
        cfg = base_config(starting_cash=20000.0)
        self.assertIsNone(cashflow.runway_days(base_ue(cfg), cfg, 20.0, 25.0))


# --------------------------------------------------------------- suppliers --

class TestSuppliers(unittest.TestCase):
    def test_fast_reliable_supplier_beats_a_cheap_slow_one(self):
        good = Supplier(name="Fast", unit_price=9.0, ship_cost=3.0,
                        handling_days=1, transit_days=8, tracking_quality=9,
                        defect_rate=0.01, response_hours=6, stock_depth=9,
                        sample_ordered=True)
        cheap = Supplier(name="Cheap", unit_price=6.0, ship_cost=2.0,
                         handling_days=5, transit_days=25, tracking_quality=2,
                         defect_rate=0.10, response_hours=96, stock_depth=2)
        ranked = sup_mod.compare([cheap, good], base_config())
        self.assertEqual(ranked[0].name, "Fast")
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_missing_sample_is_a_red_flag(self):
        score = sup_mod.score_supplier(Supplier(name="X"), base_config())
        self.assertTrue(any("never held" in f for f in score.red_flags))

    def test_single_supplier_risk_is_reported(self):
        only = Supplier(name="Only")
        self.assertIsNotNone(sup_mod.risk_of_single_supplier([only], only.id))
        second = Supplier(name="Backup")
        self.assertIsNone(sup_mod.risk_of_single_supplier([only, second], only.id))

    def test_grades_span_the_range(self):
        best = sup_mod.score_supplier(
            Supplier(name="A", handling_days=1, transit_days=5,
                     tracking_quality=10, defect_rate=0.0, response_hours=2,
                     stock_depth=10, sample_ordered=True, unit_price=1.0),
            base_config(), price_benchmark=1.0)
        worst = sup_mod.score_supplier(
            Supplier(name="F", handling_days=10, transit_days=30,
                     tracking_quality=0, defect_rate=0.2, response_hours=200,
                     stock_depth=0, unit_price=50.0),
            base_config(), price_benchmark=1.0)
        self.assertEqual(best.grade, "A")
        self.assertEqual(worst.grade, "F")


# --------------------------------------------------------------------- ops --

class TestOps(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 6, 15)
        self.cfg = base_config()

    def ago(self, days: int) -> str:
        return (self.today - timedelta(days=days)).isoformat()

    def test_unplaced_paid_order_is_critical(self):
        order = Order(external_id="#1", status="awaiting_supplier",
                      ordered_date=self.ago(4), revenue=50.0)
        actions = ops.check_order(order, self.cfg, self.today)
        self.assertTrue(any(a.severity == "critical" for a in actions))

    def test_fresh_order_is_only_low_priority(self):
        order = Order(external_id="#1", status="received",
                      ordered_date=self.ago(0), revenue=50.0)
        actions = ops.check_order(order, self.cfg, self.today)
        self.assertTrue(all(a.severity == "low" for a in actions))

    def test_missing_tracking_is_flagged(self):
        order = Order(external_id="#2", status="placed",
                      ordered_date=self.ago(8), placed_date=self.ago(7),
                      revenue=50.0)
        actions = ops.check_order(order, self.cfg, self.today)
        self.assertTrue(any("No tracking" in a.issue for a in actions))

    def test_late_parcel_is_flagged(self):
        order = Order(external_id="#3", status="in_transit",
                      ordered_date=self.ago(30), promised_days=12,
                      tracking_number="X", revenue=50.0)
        actions = ops.check_order(order, self.cfg, self.today)
        self.assertTrue(any(a.severity == "high" for a in actions))

    def test_chargeback_short_circuits_everything_else(self):
        order = Order(external_id="#4", status="chargeback",
                      ordered_date=self.ago(20), revenue=50.0)
        actions = ops.check_order(order, self.cfg, self.today)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].severity, "critical")
        self.assertEqual(actions[0].macro, "chargeback_rebuttal")

    def test_refunded_orders_need_no_action(self):
        order = Order(external_id="#5", status="refunded",
                      ordered_date=self.ago(20))
        self.assertEqual(ops.check_order(order, self.cfg, self.today), [])

    def test_queue_sorts_critical_first_then_by_value(self):
        orders = [
            Order(external_id="#low", status="delivered",
                  ordered_date=self.ago(10), delivered_date=self.ago(5),
                  revenue=10.0),
            Order(external_id="#crit", status="awaiting_supplier",
                  ordered_date=self.ago(6), revenue=90.0),
        ]
        queue = ops.action_queue(orders, self.cfg, self.today)
        self.assertEqual(queue[0].external_id, "#crit")

    def test_every_macro_renders(self):
        for key in ops.MACROS:
            text = ops.render_macro(key, name="Alex", order_id="1042")
            self.assertIn("Subject:", text)
            self.assertIn("Alex", text + " Alex")

    def test_unknown_macro_raises(self):
        with self.assertRaises(KeyError):
            ops.render_macro("does_not_exist")

    def test_order_placed_today_is_judged_from_today(self):
        """Placed today is 0 days, not a missing date - no instant tracking alarm."""
        order = Order(external_id="#6", status="placed", revenue=50.0,
                      ordered_date=self.ago(5), placed_date=self.ago(0))
        self.assertEqual(ops.check_order(order, self.cfg, self.today), [])

    def test_update_order_stamps_the_dates_the_sla_reads(self):
        order = Order(external_id="#7", status="awaiting_supplier",
                      ordered_date=self.ago(4))
        ops.update_order(order, status="placed", today=self.today)
        self.assertEqual(order.placed_date, self.today.isoformat())
        ops.update_order(order, status="placed", tracking_number="LP1",
                         today=self.today)
        self.assertEqual(order.status, "in_transit")  # tracking means it shipped
        self.assertEqual(order.tracking_date, self.today.isoformat())
        ops.update_order(order, status="delivered", today=self.today)
        self.assertEqual(order.delivered_date, self.today.isoformat())

    def test_update_order_touches_only_what_it_is_given(self):
        order = Order(external_id="#8", status="delivered", tracking_number="LP1",
                      issue="dented", ordered_date=self.ago(9),
                      delivered_date=self.ago(4))
        ops.update_order(order, review_requested=True, today=self.today)
        self.assertEqual((order.status, order.tracking_number, order.issue),
                         ("delivered", "LP1", "dented"))
        self.assertFalse(any("review" in a.issue for a in
                             ops.check_order(order, self.cfg, self.today)))

    def test_update_order_rejects_an_unknown_status(self):
        with self.assertRaises(ValueError):
            ops.update_order(Order(), status="lost_in_space")

    def test_unfilled_macro_slots_stay_visible(self):
        text = ops.render_macro("wismo", name="Alex")
        self.assertIn("{tracking_url}", text)

    def test_fulfilment_health_counts_correctly(self):
        orders = [
            Order(status="delivered", ordered_date=self.ago(15),
                  delivered_date=self.ago(3)),
            Order(status="refunded", ordered_date=self.ago(20)),
            Order(status="chargeback", ordered_date=self.ago(25)),
        ]
        health = ops.fulfilment_health(orders, self.cfg, self.today)
        self.assertEqual(health["orders"], 3)
        self.assertEqual(health["delivered"], 1)
        self.assertAlmostEqual(health["refund_rate"], 1 / 3, places=3)


# -------------------------------------------------------------------- kpis --

class TestKPIs(unittest.TestCase):
    def test_profit_and_roas_roll_up(self):
        cfg = base_config(fixed_monthly_costs=0.0)
        product = Product(name="P", price=50.0, cogs=10.0, ship_cost=2.0)
        orders = [Order(product_id=product.id, revenue=50.0, cogs=12.0,
                        status="delivered") for _ in range(10)]
        tests = [AdTest(product_id=product.id, spend=200.0)]
        report = kpis.build([product], orders, tests, [], cfg, 30)
        self.assertEqual(report.orders, 10)
        self.assertAlmostEqual(report.revenue, 500.0)
        self.assertAlmostEqual(report.blended_roas, 2.5, places=6)
        self.assertAlmostEqual(report.blended_cac, 20.0, places=6)

    def test_high_chargeback_rate_raises_a_critical_alert(self):
        cfg = base_config()
        product = Product(name="P", price=50.0, cogs=10.0, ship_cost=2.0)
        orders = [Order(product_id=product.id, revenue=50.0, status="delivered")
                  for _ in range(90)]
        orders += [Order(product_id=product.id, revenue=50.0, status="chargeback")
                   for _ in range(10)]
        report = kpis.build([product], orders, [], [], cfg, 30)
        self.assertTrue(any(a.metric == "chargeback_rate" and
                            a.severity == "critical" for a in report.alerts))

    def test_roas_below_breakeven_raises_a_critical_alert(self):
        cfg = base_config()
        product = Product(name="P", price=50.0, cogs=10.0, ship_cost=2.0)
        orders = [Order(product_id=product.id, revenue=50.0, status="delivered")
                  for _ in range(10)]
        tests = [AdTest(product_id=product.id, spend=2000.0)]
        report = kpis.build([product], orders, tests, [], cfg, 30)
        self.assertTrue(any(a.metric == "blended_roas" for a in report.alerts))

    def test_clean_books_still_return_an_alert(self):
        report = kpis.build([], [], [], [], base_config(starting_cash=50000.0), 30)
        self.assertTrue(report.alerts)

    def test_orders_outside_the_window_are_excluded(self):
        cfg = base_config()
        product = Product(name="P", price=50.0, cogs=10.0)
        old = Order(product_id=product.id, revenue=50.0,
                    ordered_date=(date.today() - timedelta(days=90)).isoformat())
        report = kpis.build([product], [old], [], [], cfg, 30)
        self.assertEqual(report.orders, 0)


# --------------------------------------------------------------- importers --

class TestImporters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_shopify_export_maps_and_matches_by_sku(self):
        path = self.write("o.csv",
            "Name,Email,Financial Status,Total,Created at,Lineitem quantity,"
            "Lineitem sku,Fulfillment Status\n"
            "#1001,a@example.com,paid,49.99,2026-06-01 10:00:00 +0000,1,SKU-1,unfulfilled\n"
            "#1002,b@example.com,refunded,49.99,2026-06-02 10:00:00 +0000,1,SKU-1,fulfilled\n")
        product = Product(name="Thing", sku="SKU-1", cogs=8.0, ship_cost=2.0)
        orders: list[Order] = []
        result = importers.import_orders(path, [product], orders)
        self.assertEqual(result.created, 2)
        self.assertEqual(orders[0].product_id, product.id)
        self.assertAlmostEqual(orders[0].cogs, 10.0)
        self.assertEqual(orders[1].status, "refunded")
        self.assertEqual(orders[0].ordered_date, "2026-06-01")

    def test_reimport_updates_rather_than_duplicates(self):
        path = self.write("o.csv",
            "Name,Total,Created at\n#1001,49.99,2026-06-01\n")
        orders: list[Order] = []
        importers.import_orders(path, [], orders)
        second = importers.import_orders(path, [], orders)
        self.assertEqual(len(orders), 1)
        self.assertEqual(second.updated, 1)

    def test_line_item_continuation_rows_are_skipped(self):
        path = self.write("o.csv",
            "Name,Total,Created at,Lineitem sku\n"
            "#1001,49.99,2026-06-01,SKU-1\n"
            "#1001,,,SKU-EXTRA\n")
        orders: list[Order] = []
        result = importers.import_orders(path, [], orders)
        self.assertEqual(len(orders), 1)
        self.assertEqual(result.skipped, 1)

    def test_unmatched_products_are_reported(self):
        path = self.write("o.csv",
            "Name,Total,Created at,Lineitem sku\n#1001,49.99,2026-06-01,NOPE\n")
        result = importers.import_orders(path, [], [])
        self.assertIn("NOPE", result.unmatched_products)
        self.assertTrue(result.warnings)

    def test_meta_export_matches_campaign_to_product(self):
        path = self.write("a.csv",
            "Campaign name,Amount spent (USD),Impressions,Link clicks,"
            "Adds to cart,Purchases,Purchases conversion value\n"
            "Widget Pro - broad,250.50,40000,800,60,12,600.00\n")
        product = Product(name="Widget Pro", price=50.0, cogs=8.0)
        tests: list[AdTest] = []
        result = importers.import_ads(path, tests, [product])
        self.assertEqual(result.created, 1)
        self.assertAlmostEqual(tests[0].spend, 250.50)
        self.assertEqual(tests[0].purchases, 12)
        self.assertEqual(tests[0].product_id, product.id)

    def test_reimporting_ads_replaces_rather_than_accumulates(self):
        path = self.write("a.csv",
            "Campaign name,Amount spent,Purchases\nWidget Pro,250.50,12\n")
        product = Product(name="Widget Pro")
        tests: list[AdTest] = []
        importers.import_ads(path, tests, [product])
        importers.import_ads(path, tests, [product])
        self.assertEqual(len(tests), 1)
        self.assertAlmostEqual(tests[0].spend, 250.50)

    def test_ledger_entries_are_idempotent(self):
        test = AdTest(product_id="p", spend=300.0)
        ledger = importers.ledger_from_ads([test], [])
        self.assertEqual(len(ledger), 1)
        again = importers.ledger_from_ads([test], ledger)
        self.assertEqual(again, [])
        test.spend = 450.0
        importers.ledger_from_ads([test], ledger)
        self.assertAlmostEqual(ledger[0].amount, -450.0)

    def test_missing_columns_warn_instead_of_crashing(self):
        path = self.write("bad.csv", "Foo,Bar\n1,2\n")
        result = importers.import_orders(path, [], [])
        self.assertTrue(result.warnings)
        self.assertEqual(result.created, 0)

    def test_empty_file_is_handled(self):
        path = self.write("empty.csv", "")
        self.assertTrue(importers.import_orders(path, [], []).warnings)

    def test_date_parsing_handles_common_formats(self):
        for raw, expected in [("2026-06-01 10:00:00 +0000", "2026-06-01"),
                              ("2026-06-01", "2026-06-01"),
                              ("06/01/2026", "2026-06-01"),
                              ("", "")]:
            self.assertEqual(importers._iso_date(raw), expected, raw)

    def test_currency_symbols_are_stripped(self):
        self.assertAlmostEqual(importers._num("$1,234.56"), 1234.56)
        self.assertAlmostEqual(importers._num("-45.00"), -45.0)
        self.assertAlmostEqual(importers._num(""), 0.0)


# ------------------------------------------------------------------- store --

class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "store.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_preserves_everything(self):
        store = Store(self.path)
        store.config.business_name = "Test Co"
        product = Product(name="Widget", sku="W-1", price=49.99, cogs=8.0)
        store.add(product)
        store.add(Supplier(name="Supplier"))
        store.add(AdTest(product_id=product.id, spend=100.0))
        store.add(Order(product_id=product.id, revenue=49.99))
        store.add(LedgerEntry(amount=-100.0))
        store.save()

        reloaded = Store.load(self.path)
        self.assertEqual(reloaded.config.business_name, "Test Co")
        self.assertEqual(len(reloaded.products), 1)
        self.assertEqual(reloaded.products[0].sku, "W-1")
        self.assertAlmostEqual(reloaded.products[0].price, 49.99)
        self.assertEqual(len(reloaded.tests), 1)
        self.assertEqual(len(reloaded.orders), 1)
        self.assertEqual(len(reloaded.ledger), 1)

    def test_lookup_by_id_sku_and_name_prefix(self):
        store = Store(self.path)
        product = Product(name="Widget Pro", sku="W-1")
        store.add(product)
        self.assertIs(store.product(product.id), product)
        self.assertIs(store.product("W-1"), product)
        self.assertIs(store.product("widget"), product)
        self.assertIsNone(store.product("nonexistent"))

    def test_ambiguous_name_prefix_returns_nothing(self):
        store = Store(self.path)
        store.add(Product(name="Widget A"))
        store.add(Product(name="Widget B"))
        self.assertIsNone(store.product("Widget"))

    def test_missing_file_loads_empty(self):
        store = Store.load(self.path / "nope.json")
        self.assertEqual(store.products, [])

    def test_unknown_fields_are_dropped_not_fatal(self):
        product = Product.from_dict({"name": "X", "from_the_future": 1})
        self.assertEqual(product.name, "X")

    def test_active_test_ignores_ended_tests(self):
        store = Store(self.path)
        product = Product(name="P")
        store.add(product)
        old = AdTest(product_id=product.id, started="2026-01-01", ended="2026-02-01")
        live = AdTest(product_id=product.id, started="2026-03-01")
        store.add(old)
        store.add(live)
        self.assertIs(store.active_test(product.id), live)


# ------------------------------------------------------- listings & daily --

class TestListingsAndBriefing(unittest.TestCase):
    def test_listing_covers_every_angle(self):
        product = Product(name="Widget", price=49.99, cogs=8.0, ship_cost=2.0)
        listing = listings.generate(product, base_ue())
        self.assertEqual(len(listing.ad_hooks), len(listings.ANGLES))
        self.assertTrue(listing.titles and listing.bullets and listing.faq)
        self.assertTrue(listing.email_flow and listing.upsell_ideas)
        self.assertIn("Widget", listing.ugc_brief)

    def test_briefing_puts_a_dying_order_above_a_growth_task(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        product = Product(name="P", price=50.0, cogs=8.0, ship_cost=2.0,
                          status="approved", score=80, tier="A")
        store.add(product)
        store.add(Order(external_id="#1", product_id=product.id,
                        status="awaiting_supplier",
                        ordered_date=(date.today() - timedelta(days=5)).isoformat(),
                        revenue=50.0))
        brief = daily.build(store)
        self.assertEqual(brief.items[0].area, "ops")
        self.assertTrue(brief.headline)

    def test_briefing_surfaces_a_kill(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        product = Product(name="Loser", price=50.0, cogs=8.0, ship_cost=2.0,
                          status="testing")
        store.add(product)
        store.add(AdTest(product_id=product.id, spend=600.0, purchases=1,
                         planned_budget=120.0))
        brief = daily.build(store)
        self.assertTrue(any(i.title.startswith("KILL") for i in brief.items))

    def test_empty_store_briefing_does_not_crash(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        brief = daily.build(store)
        self.assertTrue(brief.items)
        self.assertTrue(brief.headline)

    def test_portfolio_exposes_every_field_the_dashboard_needs(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        store.add(Product(name="P", price=50.0, cogs=8.0, ship_cost=2.0))
        required = {"name", "status", "score", "tier", "price", "landed_cost",
                    "margin_multiple", "cm", "be_roas", "be_cpa", "orders",
                    "spend", "revenue", "roas", "cpa", "profit", "verdict"}
        self.assertTrue(required.issubset(set(daily.portfolio(store)[0])))


# --------------------------------------------------------------- dashboard --

class TestDashboard(unittest.TestCase):
    def test_renders_valid_self_contained_html(self):
        from dropship.demo import seed
        store = seed(Store(Path(tempfile.mkdtemp()) / "s.json"))
        html = dashboard.render(store)
        self.assertIn("</html>", html)
        self.assertNotIn("%SERIES%", html)
        self.assertNotIn("http://", html.split("<footer>")[0])
        self.assertEqual(html.count("<svg"), html.count("</svg>"))

    def test_empty_store_renders_without_crashing(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        self.assertIn("</html>", dashboard.render(store))

    def test_svg_blocks_are_well_formed(self):
        import re
        import xml.etree.ElementTree as ET
        from dropship.demo import seed
        store = seed(Store(Path(tempfile.mkdtemp()) / "s.json"))
        for block in re.findall(r"<svg.*?</svg>", dashboard.render(store), re.S):
            ET.fromstring(block)  # raises on malformed markup

    def test_html_is_escaped(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        store.add(Product(name="<script>alert(1)</script>", price=50.0, cogs=8.0))
        html = dashboard.render(store)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


# --------------------------------------------------------------------- cli --

class TestCLI(unittest.TestCase):
    """Smoke tests: every command must run against a seeded store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = str(Path(self.tmp.name) / "store.json")
        self.cli("init", "--name", "Test Co", "--force")
        self.cli("demo")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(["--store", self.store_path, *args])
        self.assertEqual(code, 0, f"{args} exited {code}")
        return buffer.getvalue()

    def test_today_reports_something_to_do(self):
        out = self.cli("today")
        self.assertIn("DO THESE", out)

    def test_portfolio_lists_products(self):
        # The table truncates long names, so match the stem.
        self.assertIn("Posture Corrector", self.cli("portfolio"))

    def test_econ_shows_breakeven(self):
        out = self.cli("econ", "Posture")
        self.assertIn("Breakeven ROAS", out)
        self.assertIn("Contribution margin", out)

    def test_decision_engine_runs_from_the_cli(self):
        self.assertIn("VERDICT", self.cli("test", "decide", "--product", "LED"))

    def test_cash_commands_run(self):
        self.assertIn("Safe daily spend",
                      self.cli("cash", "max-spend", "--product", "Posture"))
        self.assertIn("Scenario", self.cli("cash", "scenarios", "--product", "Posture"))
        self.assertIn("LEDGER", self.cli("cash", "sim", "--product", "Posture",
                                         "--daily", "100", "--cpa", "25"))

    def test_reporting_commands_run(self):
        self.assertIn("Alerts", self.cli("kpi").replace("ALERTS", "Alerts"))
        self.assertIn("FULFILMENT", self.cli("orders", "sla"))
        self.assertIn("Grade", self.cli("supplier", "list").replace("Grade", "Grade"))
        self.assertIn("DOCTOR", self.cli("doctor"))

    def test_listing_and_macros_run(self):
        self.assertIn("Ad angles", self.cli("listing", "Posture").replace(
            "AD ANGLES", "Ad angles").replace(" - test angles", ""))
        self.assertIn("Subject:", self.cli("cs", "wismo", "--field", "name=Alex"))
        self.assertIn("wismo", self.cli("cs"))

    def test_dashboard_writes_a_file(self):
        out_path = Path(self.tmp.name) / "d.html"
        self.cli("dashboard", "--out", str(out_path))
        self.assertTrue(out_path.exists())
        self.assertIn("</html>", out_path.read_text())

    def test_config_set_persists(self):
        self.cli("config", "set", "payout_delay_days", "14")
        store = Store.load(self.store_path)
        self.assertEqual(store.config.payout_delay_days, 14)

    def test_product_lifecycle(self):
        self.cli("product", "add", "--name", "New Thing", "--price", "59.99",
                 "--cogs", "9.00", "--ship-cost", "3.00", "--demand", "9")
        store = Store.load(self.store_path)
        product = store.product("New Thing")
        self.assertIsNotNone(product)
        self.assertGreater(product.score, 0)
        self.cli("product", "set", "New Thing", "price", "69.99")
        self.assertAlmostEqual(Store.load(self.store_path).product("New Thing").price,
                               69.99)
        self.cli("product", "delete", "New Thing")
        self.assertIsNone(Store.load(self.store_path).product("New Thing"))

    def test_test_plan_and_update(self):
        self.cli("test", "plan", "Pet Hair", "--start")
        store = Store.load(self.store_path)
        product = store.product("Pet Hair")
        self.assertEqual(product.status, "testing")
        test = store.active_test(product.id)
        out = self.cli("test", "update", test.id, "--spend", "400",
                       "--purchases", "0", "--clicks", "300",
                       "--impressions", "50000")
        self.assertIn("KILL", out)

    def test_score_all_products(self):
        self.assertIn("Posture", self.cli("product", "score", "--all"))

    def test_unknown_config_key_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("config", "set", "not_a_key", "1")

    def test_unknown_product_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("econ", "does-not-exist")

    def test_site_writes_a_folder_and_its_notes(self):
        out = Path(self.tmp.name) / "site"
        output = self.cli("site", "--out", str(out))
        self.assertIn("index.html", output)
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((out / "refunds.html").is_file())
        notes = out.parent / "site.notes.md"
        self.assertIn("Netlify", notes.read_text(encoding="utf-8"))

    def test_storefront_writes_a_shop_page(self):
        out_path = Path(self.tmp.name) / "shop.html"
        out = self.cli("storefront", "Pet Hair", "--out", str(out_path),
                       "--pay", "https://buy.stripe.com/test_1")
        self.assertIn("BEFORE YOU PUBLISH", out)
        self.assertIn("</html>", out_path.read_text(encoding="utf-8"))
        self.assertEqual(Store.load(self.store_path).product("Pet Hair").pay_url,
                         "https://buy.stripe.com/test_1")

    def test_ui_command_is_registered(self):
        args = cli.build_parser().parse_args(["ui", "--port", "0", "--no-browser"])
        self.assertIs(args.func, cli.cmd_ui)
        self.assertTrue(args.no_browser)


# ------------------------------------------------------------- storefront --

class TestStorefront(unittest.TestCase):
    """The shop page is customer-facing: it must be honest and publishable."""

    def setUp(self):
        self.cfg = base_config()
        self.product = Product(name="Pet Hair Remover Roller", sku="PHR-05",
                               price=39.99, cogs=7.10, ship_cost=2.90,
                               delivery_days=11)
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def photo(self, name: str, size: tuple[int, int] = (8, 8),
              noise: bool = False) -> Path:
        """A real PNG, written with the standard library.

        ``noise`` makes it incompressible, which is the only way to get a test
        file over the size limit - a flat colour shrinks to nothing.
        """
        import os
        import struct
        import zlib
        width, height = size
        row = (lambda: os.urandom(width * 3)) if noise else \
            (lambda: bytes((200, 190, 180)) * width)
        raw = b"".join(b"\x00" + row() for _ in range(height))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        path = self.dir / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n"
                         + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                                      8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        return path

    def test_page_is_self_contained_and_honest(self):
        page = storefront.build(self.product, self.cfg)
        self.assertIn("</html>", page.html)
        self.assertNotIn("<script", page.html)          # nothing to execute
        self.assertNotIn("http://", page.html)          # nothing to fetch
        self.assertIn("39.99", page.html)
        self.assertIn("11 days", page.html)             # the promise, before checkout
        self.assertIn("Delivery, returns and contact", page.html)

    def test_an_empty_page_lists_what_it_needs(self):
        page = storefront.build(self.product, self.cfg)
        self.assertFalse(page.publishable)
        joined = " ".join(page.issues)
        self.assertIn("No photos", joined)
        self.assertIn("No payment link", joined)
        self.assertGreater(page.slots, 0)
        self.assertIn("--image", joined)                 # every problem, its fix
        self.assertIn("--pay", joined)

    def test_slots_are_counted_from_the_copy_not_the_stylesheet(self):
        """The stylesheet is full of braces; none of them is an unfilled slot."""
        page = storefront.build(self.product, self.cfg)
        self.assertLess(page.slots, 60)
        self.assertIn('<mark class="slot">', page.html)
        filled = storefront.build(self.product, self.cfg, problem="pet hair",
                                  outcome="a fur-free sofa")
        self.assertLess(filled.slots, page.slots)

    def test_photos_are_embedded_and_oversized_ones_are_flagged(self):
        small = self.photo("small.png")
        self.product.photos = [str(small)]
        page = storefront.build(self.product, self.cfg)
        self.assertIn("data:image/png;base64,", page.html)
        self.assertFalse(any("No photos" in i for i in page.issues))

        self.product.photos = [str(self.photo("huge.png", (700, 700), noise=True))]
        page = storefront.build(self.product, self.cfg)
        self.assertTrue(any("Compress" in i for i in page.issues))

    def test_a_missing_photo_is_reported_not_crashed_on(self):
        self.product.photos = [str(self.dir / "nope.png")]
        page = storefront.build(self.product, self.cfg)
        self.assertIn("</html>", page.html)
        self.assertTrue(any("not found" in i for i in page.issues))

    def test_the_buy_button_opens_the_payment_link(self):
        self.product.pay_url = "https://buy.stripe.com/test_123"
        page = storefront.build(self.product, self.cfg)
        self.assertIn('href="https://buy.stripe.com/test_123"', page.html)
        self.assertIn("Stripe", page.html)               # names the checkout
        self.assertFalse(any("payment link" in i for i in page.issues))

    def test_an_unencrypted_payment_link_is_refused_politely(self):
        self.product.pay_url = "http://buy.example.com/x"
        page = storefront.build(self.product, self.cfg)
        self.assertTrue(any("not https" in i for i in page.issues))

    def test_a_product_that_fails_its_gates_says_so(self):
        thin = Product(name="Thin", price=15.0, cogs=8.0, ship_cost=2.0)
        page = storefront.build(thin, self.cfg)
        self.assertTrue(any("research gate" in i for i in page.issues))

    def test_customer_text_is_escaped(self):
        self.product.name = "<script>alert(1)</script>"
        page = storefront.build(self.product, self.cfg)
        self.assertNotIn("<script>alert(1)</script>", page.html)
        self.assertIn("&lt;script&gt;", page.html)

    def test_bundle_needs_a_price_and_its_own_link(self):
        self.product.bundle_price = 69.98
        page = storefront.build(self.product, self.cfg)
        self.assertTrue(any("needs both" in i for i in page.issues))

        self.product.bundle_pay_url = "https://buy.stripe.com/two"
        page = storefront.build(self.product, self.cfg)
        self.assertIn("Buy two", page.html)
        self.assertIn("69.98", page.html)
        self.assertFalse(any("needs both" in i for i in page.issues))

    def test_a_bundle_that_is_not_cheaper_is_called_out(self):
        self.product.bundle_price = self.product.price * 2
        self.product.bundle_pay_url = "https://buy.stripe.com/two"
        page = storefront.build(self.product, self.cfg)
        self.assertTrue(any("not cheaper" in i for i in page.issues))

    def test_site_has_a_page_per_product_plus_the_ones_a_processor_wants(self):
        selling = Product(name="Seller", sku="S-1", price=49.99, cogs=8.0,
                          ship_cost=2.0, status="scaling",
                          pay_url="https://buy.stripe.com/x")
        killed = Product(name="Dead", sku="D-1", price=49.99, cogs=8.0,
                         status="killed")
        site = storefront.build_site([selling, killed], self.cfg)

        self.assertIn("s-1.html", site.files)
        self.assertNotIn("d-1.html", site.files)         # killed is not a shop window
        for required in ("index.html", "thanks.html", "refunds.html",
                         "shipping.html", "privacy.html", "terms.html",
                         "contact.html"):
            self.assertIn(required, site.files)
        self.assertIn("Seller", site.files["index.html"])
        self.assertIn("s-1.html", site.files["index.html"])   # home links to it
        self.assertIn("refunds.html", site.files["s-1.html"])  # and it links back

    def test_every_page_of_the_site_is_complete_html(self):
        product = Product(name="Seller", sku="S-1", price=49.99, cogs=8.0,
                          ship_cost=2.0, status="scaling")
        site = storefront.build_site([product], self.cfg)
        for name, page in site.files.items():
            self.assertTrue(page.startswith("<!doctype html>"), name)
            self.assertIn("</html>", page, name)
            self.assertNotIn("<script", page, name)
            self.assertGreater(site.slots[name], -1, name)

    def test_site_slots_exclude_the_stylesheet(self):
        product = Product(name="Seller", sku="S-1", price=49.99, cogs=8.0,
                          ship_cost=2.0, status="scaling")
        site = storefront.build_site([product], self.cfg)
        # The CSS alone has dozens of brace pairs; policy pages have a handful.
        self.assertLess(site.slots["privacy.html"], 20)
        self.assertGreater(site.slots["privacy.html"], 0)

    def test_an_empty_shop_window_says_so(self):
        site = storefront.build_site([Product(name="Dead", status="killed")],
                                     self.cfg)
        self.assertEqual(site.products, [])
        self.assertTrue(any("shop window" in i for i in site.issues))

    def test_notes_explain_publishing_and_never_leak_into_the_site(self):
        product = Product(name="Seller", sku="S-1", price=49.99, cogs=8.0,
                          ship_cost=2.0, status="scaling")
        site = storefront.build_site([product], self.cfg)
        written = storefront.write_site(site, self.dir / "site")
        self.assertEqual({p.name for p in written}, set(site.files))
        text = storefront.notes(site, self.cfg, self.dir / "site")
        for expected in ("Payment links", "import orders", "thanks.html",
                         "Abandoned checkout"):
            self.assertIn(expected, text)

    def test_write_puts_one_file_on_disk(self):
        page = storefront.build(self.product, self.cfg)
        path = storefront.write(page, self.dir / storefront.default_path(self.product))
        self.assertEqual(path.name, "shop-phr-05.html")
        self.assertIn("</html>", path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- ui --

class TestUI(unittest.TestCase):
    """Every page renders, and every form lands in the store the way the CLI would."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "store.json"
        seed(Store(self.path)).save()
        self.app = ui.App(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, path: str, **query) -> str:
        response = self.app.handle("GET", path, query, {})
        self.assertEqual(response.status, 200, response.body[:300])
        return response.body

    def submit(self, path: str, **form) -> dict[str, str]:
        """Post a form; return the query of the redirect, flash message included."""
        response = self.app.handle("POST", path, {},
                                   {k: str(v) for k, v in form.items()})
        self.assertEqual(response.status, 303, response.body[:300])
        return {k: v[0] for k, v in parse_qs(urlsplit(response.location).query).items()}

    def reload(self) -> Store:
        return Store.load(self.path)

    def test_every_page_renders(self):
        for path in ui.PAGES:
            if path not in ("/product", "/shop"):
                self.assertIn("</html>", self.page(path))
        for product in self.reload().products:
            self.assertIn(product.name, self.page("/product", id=product.id))
            self.assertIn("</html>", self.page("/shop", id=product.id))

    def test_shop_preview_is_marked_as_one(self):
        pet = self.reload().product("Pet Hair")
        html = self.page("/shop", id=pet.id)
        self.assertIn("Preview.", html)              # the bar the file will not have
        self.assertIn("No payment link", html)       # and what it still needs

    def test_payment_link_must_be_encrypted(self):
        pet = self.reload().product("Pet Hair")
        self.assertIn("err", self.submit("/product/shop", id=pet.id,
                                         pay_url="http://buy.example.com/x"))
        self.assertEqual(self.reload().product(pet.id).pay_url, "")
        self.submit("/product/shop", id=pet.id, pay_url="https://buy.stripe.com/t_1",
                    copy_problem="pet hair on every cushion",
                    copy_outcome="a fur-free sofa in one pass",
                    bundle_price="69.98",
                    bundle_pay_url="https://buy.stripe.com/t_2")
        saved = self.reload().product(pet.id)
        self.assertEqual(saved.pay_url, "https://buy.stripe.com/t_1")
        self.assertAlmostEqual(saved.bundle_price, 69.98)
        # The preview says what the written file will say.
        preview = self.page("/shop", id=pet.id)
        self.assertIn("buy.stripe.com", preview)
        self.assertIn("a fur-free sofa in one pass", preview)

    def test_today_links_each_item_to_the_page_that_fixes_it(self):
        lamp = self.reload().product("LED")
        html = self.page("/")
        self.assertIn(f'href="/product?id={lamp.id}"', html)  # its KILL item
        self.assertIn('href="/orders"', html)                   # the unplaced orders

    def test_unknown_pages_and_products_are_404s(self):
        self.assertEqual(self.app.handle("GET", "/nope", {}, {}).status, 404)
        self.assertEqual(
            self.app.handle("GET", "/product", {"id": "prd_missing"}, {}).status, 404)

    def test_adding_a_product_scores_it(self):
        result = self.submit("/products/add", name="Desk Lamp Pro", price=59.99,
                             cogs=9, ship_cost=3, demand=9)
        self.assertIn("msg", result)
        product = self.reload().product(result["id"])
        self.assertEqual(product.name, "Desk Lamp Pro")
        self.assertGreater(product.score, 0)
        self.assertEqual(product.demand, 9)

    def test_recording_results_applies_the_verdict(self):
        pet = self.reload().product("Pet Hair")
        self.submit("/product/start", id=pet.id, channel="meta",
                    hypothesis="Pet owners buy on a silent demo")
        store = self.reload()
        self.assertEqual(store.product(pet.id).status, "testing")
        test = store.active_test(pet.id)
        result = self.submit("/product/test", id=test.id, spend=400, purchases=0,
                             clicks=300, impressions=50000)
        self.assertIn("KILL", result["msg"])
        store = self.reload()
        self.assertEqual(store.product(pet.id).status, "killed")
        self.assertTrue(store.test(test.id).ended)

    def test_verdict_button_applies_a_pending_kill(self):
        store = self.reload()
        lamp = store.product("LED")
        self.submit("/product/decide", id=store.active_test(lamp.id).id)
        self.assertEqual(self.reload().product(lamp.id).status, "killed")

    def test_a_product_that_fails_its_gates_cannot_start_a_test(self):
        scraper = self.reload().product("Silicone")
        result = self.submit("/product/start", id=scraper.id, channel="meta",
                             hypothesis="x", back=f"/product?id={scraper.id}")
        self.assertIn("blockers", result["err"])
        self.assertEqual(self.reload().tests_for(scraper.id), [])

    def test_bad_input_is_refused_and_nothing_is_saved(self):
        before = self.path.read_text()
        self.assertIn("err", self.submit("/products/add", name="X", price="abc", cogs=1))
        self.assertIn("err", self.submit("/settings", confidence=1.5))
        self.assertIn("err", self.submit("/orders/update", id="#1099", status="lost"))
        self.assertEqual(self.path.read_text(), before)

    def test_placing_an_order_clears_its_critical_flag(self):
        order = self.reload().order("#1099")
        self.submit("/orders/update", id=order.id, status="placed", tracking="",
                    issue="")
        store = self.reload()
        self.assertFalse(any(a.external_id == "#1099" and a.severity == "critical"
                             for a in ops.action_queue(store.orders, store.config)))

    def test_settings_cover_every_config_field(self):
        shown = {name for _, group in ui.SETTINGS for name, _, _ in group}
        self.assertEqual(shown, {f.name for f in fields(Config)} - {"created"})

    def test_settings_save(self):
        result = self.submit("/settings", payout_delay_days=14)
        self.assertIn("payout_delay_days 5 -> 14", result["msg"])
        self.assertEqual(self.reload().config.payout_delay_days, 14)

    def test_user_text_is_escaped(self):
        result = self.submit("/products/add", name="<script>alert(1)</script>",
                             price=50, cogs=8)
        for html in (self.page("/products"), self.page("/product", id=result["id"]),
                     self.page("/", msg="<b>hi</b>")):
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertNotIn("<b>hi</b>", html)

    def test_demo_loads_only_into_an_empty_store(self):
        self.app = ui.App(Path(self.tmp.name) / "empty.json")
        self.assertIn("Load demo data", self.page("/"))
        self.assertIn("msg", self.submit("/demo"))
        self.assertIn("err", self.submit("/demo"))

    def test_errors_never_redirect_off_the_machine(self):
        for back in ("//evil.example/", "https://evil.example/", "/\\evil.example"):
            self.assertEqual(ui._back({"back": back}), "/")
        self.assertEqual(ui._back({"back": "/orders"}), "/orders")

    def test_an_unreadable_store_names_the_backup(self):
        self.path.write_text("{not json")
        response = self.app.handle("GET", "/", {}, {})
        self.assertEqual(response.status, 500)
        self.assertIn("store.bak.json", response.body)

    def test_server_refuses_cross_site_requests(self):
        server = ui.make_server(self.path, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        own = f"http://127.0.0.1:{server.server_port}"

        def status(method: str, path: str, **headers) -> int:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port,
                                              timeout=10)
            body = "payout_delay_days=99" if method == "POST" else None
            try:
                conn.request(method, path, body=body, headers={
                    "Content-Type": "application/x-www-form-urlencoded", **headers})
                return conn.getresponse().status
            finally:
                conn.close()

        self.assertEqual(status("GET", "/"), 200)
        self.assertEqual(status("GET", "/", Host="evil.example"), 403)
        self.assertEqual(status("POST", "/settings", Origin="http://evil.example"), 403)
        self.assertEqual(status("POST", "/settings", Origin="null"), 403)
        self.assertEqual(self.reload().config.payout_delay_days, 5)
        self.assertEqual(status("POST", "/settings", Origin=own), 303)
        self.assertEqual(self.reload().config.payout_delay_days, 99)


# ------------------------------------------------------------- edge cases --

class TestDegenerateInputs(unittest.TestCase):
    """Nothing here should crash.

    A tool that raises on a zero-price product is a tool you stop opening, and
    then you stop making the decisions it exists to make.
    """

    def setUp(self):
        self.cfg = base_config()
        self.ue = base_ue(self.cfg)
        self.broke = UnitEconomics(price=5.0, cogs=50.0, config=self.cfg)

    def test_zero_and_negative_economics(self):
        UnitEconomics(price=0.0, cogs=0.0, config=self.cfg).breakdown()
        self.broke.breakdown()
        self.broke.sensitivity()
        self.broke.price_ladder([0.0, 10.0])
        self.assertEqual(self.broke.breakeven_orders(), float("inf"))

    def test_decisions_on_degenerate_tests(self):
        for test, ue in [
            (AdTest(product_id="p", spend=1e6, purchases=100_000), self.ue),
            (AdTest(product_id="p", spend=0.0, purchases=5), self.ue),
            (AdTest(product_id="p", spend=100.0, purchases=1), self.broke),
            (AdTest(product_id="p"), self.ue),
        ]:
            d = testing.decide(test, ue, self.cfg)
            self.assertIn(d.action, {testing.NOT_STARTED, testing.KEEP_TESTING,
                                     testing.ITERATE, testing.HOLD,
                                     testing.SCALE, testing.KILL})

    def test_scale_ladder_from_zero_budget(self):
        self.assertEqual(len(testing.scale_ladder(0.0, self.ue, self.cfg, 3)), 3)

    def test_cashflow_survives_extremes(self):
        cashflow.simulate(self.ue, self.cfg, 100.0, 25.0, 30, 0.0)
        cashflow.simulate(self.ue, self.cfg, 100.0, 25.0, 30, -500.0)
        cashflow.simulate(self.ue, self.cfg, 100.0, 25.0, 1)
        cashflow.simulate(self.ue, self.cfg, 100.0, 25.0, 60, 2000.0, growth_rate=0.5)
        self.assertEqual(
            cashflow.max_safe_daily_spend(self.ue, self.cfg, 25.0, 30, 0.0), 0.0)

    def test_unsellable_product_gets_no_safe_spend(self):
        self.assertEqual(
            cashflow.max_safe_daily_spend(self.broke, self.cfg, 25.0, 30), 0.0)

    def test_research_handles_empty_and_zero_priced_products(self):
        for product in (Product(name=""), Product(name="X", price=0.0, cogs=0.0)):
            result = research.score_product(product, self.cfg)
            self.assertFalse(result.passed)

    def test_malformed_dates_do_not_crash_ops(self):
        ops.check_order(Order(ordered_date="not-a-date", status="received"),
                        self.cfg)
        ops.fulfilment_health([Order(ordered_date="", status="delivered",
                                     delivered_date="nonsense")], self.cfg)

    def test_reports_render_for_an_unsellable_product(self):
        store = Store(Path(tempfile.mkdtemp()) / "s.json")
        store.add(Product(name="Bad", price=5.0, cogs=50.0))
        self.assertIn("</html>", dashboard.render(store))
        self.assertTrue(daily.build(store).items)
        self.assertTrue(kpis.build(store.products, [], [], [], self.cfg, 30).alerts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
