"""Unit economics: the number that decides everything.

Most failed dropshipping stores did not fail at marketing. They failed because
nobody ever computed the real contribution margin per order - the one that
survives payment fees, refunds, chargebacks and support time - and so every
"profitable" ROAS on the ad dashboard was quietly a loss.

The model here prices an order as an expected value over three outcomes:

    KEPT        the customer keeps it            prob 1 - r - c
    REFUNDED    you refund, goods are gone       prob r
    CHARGEBACK  bank claws it back plus a fee    prob c

Every downstream decision (breakeven ROAS, max CPC, kill rules, scale ladders,
cash runway) is derived from the expected contribution margin this produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Config, Product


@dataclass
class UnitEconomics:
    """Per-order economics, all figures in the store currency."""

    price: float
    cogs: float
    ship_cost: float = 0.0
    upsell_revenue: float = 0.0
    upsell_cogs: float = 0.0
    config: Config = field(default_factory=Config)

    # ------------------------------------------------------------ top line --

    @property
    def aov(self) -> float:
        """Average order value. This is the revenue an ad platform will report."""
        return self.price + self.upsell_revenue

    @property
    def variable_cogs(self) -> float:
        """Everything you pay the supplier to put goods on a doorstep."""
        return self.cogs + self.ship_cost + self.upsell_cogs

    @property
    def margin_multiple(self) -> float:
        return self.price / (self.cogs + self.ship_cost) if (self.cogs + self.ship_cost) else 0.0

    # --------------------------------------------------------------- fees --

    @property
    def payment_fees(self) -> float:
        c = self.config
        return self.aov * c.payment_rate + c.payment_fixed

    @property
    def platform_fees(self) -> float:
        return self.aov * self.config.platform_rate

    # ---------------------------------------------------- outcome branches --

    def _kept(self) -> float:
        """Margin when the order sticks."""
        return (self.aov
                - self.variable_cogs
                - self.payment_fees
                - self.platform_fees
                - self.config.cs_cost_per_order)

    def _refunded(self) -> float:
        """Margin when you refund. Revenue goes back; the goods usually don't.

        Most processors keep the percentage fee on a refund (Shopify Payments,
        Stripe and PayPal all changed to this). ``payment_fee_refunded`` lets
        you model the friendlier case if your processor still returns it.
        """
        c = self.config
        kept_fee = c.payment_fixed if c.payment_fee_refunded else self.payment_fees
        return (0.0
                - self.variable_cogs * c.goods_loss_on_refund
                - kept_fee
                - self.platform_fees
                - c.cs_cost_per_order)

    def _chargeback(self) -> float:
        """Margin on a chargeback. Worst case: no revenue, no goods, plus a fee."""
        c = self.config
        return (0.0
                - self.variable_cogs
                - self.payment_fees
                - self.platform_fees
                - c.chargeback_fee
                - c.cs_cost_per_order)

    # ------------------------------------------------- headline quantities --

    @property
    def contribution_margin(self) -> float:
        """Expected margin per PAID order, before a cent of ad spend.

        This is the single most important number in the business. It is also
        the maximum you can pay to acquire a customer and still break even.
        """
        c = self.config
        r, cb = c.refund_rate, c.chargeback_rate
        kept_p = max(0.0, 1.0 - r - cb)
        return kept_p * self._kept() + r * self._refunded() + cb * self._chargeback()

    @property
    def contribution_margin_pct(self) -> float:
        return self.contribution_margin / self.aov if self.aov else 0.0

    @property
    def gross_margin(self) -> float:
        """Naive margin most people quote. Shown only to contrast with the real one."""
        return self.aov - self.variable_cogs

    @property
    def breakeven_cpa(self) -> float:
        """Max cost per purchase. Spend more than this and you lose money."""
        return self.contribution_margin

    @property
    def breakeven_roas(self) -> float:
        """The ROAS your ad dashboard must show just to stand still."""
        cm = self.contribution_margin
        return self.aov / cm if cm > 0 else float("inf")

    def target_roas(self, net_margin: float | None = None) -> float:
        """ROAS required to hit a given net margin on revenue."""
        m = self.config.target_net_margin if net_margin is None else net_margin
        denom = self.contribution_margin - m * self.aov
        return self.aov / denom if denom > 0 else float("inf")

    def target_cpa(self, net_margin: float | None = None) -> float:
        m = self.config.target_net_margin if net_margin is None else net_margin
        return self.contribution_margin - m * self.aov

    # ------------------------------------------------------- funnel levers --

    def max_cpc(self, conversion_rate: float) -> float:
        """Most you can pay per click at a given site conversion rate."""
        return self.breakeven_cpa * conversion_rate

    def required_cvr(self, cpc: float) -> float:
        """Conversion rate you need at a given cost per click."""
        return cpc / self.breakeven_cpa if self.breakeven_cpa > 0 else float("inf")

    def profit_at_cpa(self, cpa: float, orders: int = 1) -> float:
        return (self.contribution_margin - cpa) * orders

    def profit_at_roas(self, roas: float, revenue: float) -> float:
        """Net profit for a given blended ROAS and revenue figure."""
        if roas <= 0:
            return -float("inf")
        ad_spend = revenue / roas
        orders = revenue / self.aov if self.aov else 0.0
        return orders * self.contribution_margin - ad_spend

    def breakeven_orders(self, monthly_costs: float | None = None) -> float:
        """Orders/month whose contribution margin alone covers fixed costs.

        A floor, not a target: it assumes zero ad spend. Real volume needs to
        clear this plus every order's share of acquisition cost.
        """
        fixed = self.config.fixed_monthly_costs if monthly_costs is None else monthly_costs
        cm = self.contribution_margin
        return fixed / cm if cm > 0 else float("inf")

    def orders_for_profit(self, target_profit: float, cpa: float) -> float:
        """Orders needed to clear a profit target at a given CPA."""
        per_order = self.contribution_margin - cpa
        if per_order <= 0:
            return float("inf")
        return (target_profit + self.config.fixed_monthly_costs) / per_order

    # ------------------------------------------------------------ reports --

    def breakdown(self) -> dict[str, float]:
        """Line-by-line, so you can see exactly where the money goes."""
        c = self.config
        r, cb = c.refund_rate, c.chargeback_rate
        return {
            "aov": self.aov,
            "product_cost": self.cogs + self.upsell_cogs,
            "shipping_cost": self.ship_cost,
            "payment_fees": self.payment_fees,
            "platform_fees": self.platform_fees,
            "support_cost": c.cs_cost_per_order,
            "expected_refund_cost": r * (self._kept() - self._refunded()),
            "expected_chargeback_cost": cb * (self._kept() - self._chargeback()),
            "gross_margin": self.gross_margin,
            "contribution_margin": self.contribution_margin,
            "contribution_margin_pct": self.contribution_margin_pct,
            "margin_multiple": self.margin_multiple,
            "breakeven_cpa": self.breakeven_cpa,
            "breakeven_roas": self.breakeven_roas,
            "target_roas": self.target_roas(),
            "target_cpa": self.target_cpa(),
        }

    def price_ladder(self, prices: list[float]) -> list[dict[str, float]]:
        """What happens to breakeven if you change price. Run this before discounting.

        Discounting is the most expensive habit in dropshipping: a 20% price cut
        on a 3x product can more than double the ROAS you need.
        """
        rows = []
        for p in prices:
            ue = UnitEconomics(
                price=p,
                cogs=self.cogs,
                ship_cost=self.ship_cost,
                upsell_revenue=self.upsell_revenue,
                upsell_cogs=self.upsell_cogs,
                config=self.config,
            )
            rows.append({
                "price": p,
                "contribution_margin": ue.contribution_margin,
                "cm_pct": ue.contribution_margin_pct,
                "breakeven_roas": ue.breakeven_roas,
                "breakeven_cpa": ue.breakeven_cpa,
                "margin_multiple": ue.margin_multiple,
            })
        return rows

    def sensitivity(self) -> list[dict[str, object]]:
        """Which input hurts most if you are wrong about it by a realistic amount.

        Tells you where to spend your verification effort: usually refund rate
        and shipping cost, which people guess and then never measure.
        """
        base = self.contribution_margin
        scenarios = [
            ("COGS +20%", {"cogs": self.cogs * 1.2}),
            ("Shipping +50%", {"ship_cost": self.ship_cost * 1.5}),
            ("Refund rate 2x", {"_refund": self.config.refund_rate * 2}),
            ("Chargeback rate 3x", {"_chargeback": self.config.chargeback_rate * 3}),
            ("Price -10%", {"price": self.price * 0.9}),
            ("No upsells", {"upsell_revenue": 0.0, "upsell_cogs": 0.0}),
        ]
        rows = []
        for label, change in scenarios:
            cfg = Config.from_dict(self.config.to_dict())
            if "_refund" in change:
                cfg.refund_rate = change.pop("_refund")
            if "_chargeback" in change:
                cfg.chargeback_rate = change.pop("_chargeback")
            kwargs = {
                "price": self.price, "cogs": self.cogs, "ship_cost": self.ship_cost,
                "upsell_revenue": self.upsell_revenue, "upsell_cogs": self.upsell_cogs,
            }
            kwargs.update(change)
            ue = UnitEconomics(config=cfg, **kwargs)
            rows.append({
                "scenario": label,
                "contribution_margin": ue.contribution_margin,
                "delta": ue.contribution_margin - base,
                "breakeven_roas": ue.breakeven_roas,
            })
        rows.sort(key=lambda r: r["delta"])
        return rows


def for_product(product: Product, config: Config) -> UnitEconomics:
    """Build the economics for a stored product."""
    return UnitEconomics(
        price=product.price,
        cogs=product.cogs,
        ship_cost=product.ship_cost,
        upsell_revenue=product.upsell_revenue,
        upsell_cogs=product.upsell_cogs,
        config=config,
    )
