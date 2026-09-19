"""Import real data from platform CSV exports.

No API keys, no OAuth, no app review. Every platform that matters can export a
CSV, and a CSV works whether you are on Shopify, WooCommerce, TikTok Shop or a
spreadsheet.

Column names drift between platforms and between versions of the same platform,
so matching is done on normalised substrings against a list of known aliases
rather than exact headers.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import AdTest, LedgerEntry, Order, Product

# ---------------------------------------------------------- column aliases --

ORDER_COLUMNS = {
    "external_id": ["name", "order name", "order id", "order number", "order #", "id"],
    "email": ["email", "customer email", "contact email", "buyer email"],
    "customer": ["billing name", "customer name", "shipping name", "buyer name", "recipient"],
    "revenue": ["total", "order total", "total price", "grand total", "amount"],
    "quantity": ["lineitem quantity", "quantity", "qty", "items"],
    "sku": ["lineitem sku", "sku", "variant sku", "product sku"],
    "product_name": ["lineitem name", "product title", "product name", "item name", "title"],
    "ordered_date": ["created at", "paid at", "order date", "date", "created"],
    "delivered_date": ["delivered at", "delivery date", "fulfilled at", "delivered"],
    "tracking_number": ["tracking number", "tracking", "tracking id", "awb"],
    "country": ["shipping country", "country", "shipping province name", "billing country"],
    "financial_status": ["financial status", "payment status", "status"],
    "fulfillment_status": ["fulfillment status", "fulfilment status", "shipment status"],
}

AD_COLUMNS = {
    "campaign": ["campaign name", "campaign", "ad name", "ad group name", "ad set name"],
    "spend": ["amount spent", "spend", "cost", "amount spent (usd)", "total spent"],
    "impressions": ["impressions", "impr.", "impression"],
    "clicks": ["link clicks", "clicks", "clicks (all)", "clicks (link)"],
    "landing_views": ["landing page views", "landing page view", "page views"],
    "add_to_carts": ["adds to cart", "add to cart", "website adds to cart", "atc"],
    "checkouts": ["checkouts initiated", "initiate checkout", "checkouts",
                  "website checkouts initiated"],
    "purchases": ["purchases", "website purchases", "conversions", "results", "orders"],
    "revenue": ["purchases conversion value", "conversion value", "total conversion value",
                "website purchase roas", "revenue"],
    "date": ["reporting starts", "day", "date", "reporting start"],
}

# Shopify's financial/fulfilment vocabulary mapped onto our order states.
STATUS_MAP = {
    "refunded": "refunded",
    "partially_refunded": "refunded",
    "voided": "cancelled",
    "chargeback": "chargeback",
    "fulfilled": "in_transit",
    "delivered": "delivered",
    "unfulfilled": "awaiting_supplier",
    "partial": "in_transit",
    "pending": "received",
    "paid": "received",
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def _build_map(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    """Match each wanted field to the best-fitting header in the file."""
    normalised = {_norm(h): h for h in headers}
    found: dict[str, str] = {}
    for field_name, options in aliases.items():
        for option in options:
            if option in normalised:            # exact normalised hit
                found[field_name] = normalised[option]
                break
        else:
            for option in options:              # substring fallback
                hit = next((orig for norm, orig in normalised.items()
                            if option in norm), None)
                if hit:
                    found[field_name] = hit
                    break
    return found


def _num(value: str) -> float:
    if value is None:
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _iso_date(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",
                "%Y/%m/%d", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text[:len(fmt) + 8].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    unmatched_products: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    mapped_columns: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        parts = [f"{self.created} created", f"{self.updated} updated"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        return ", ".join(parts)


# ------------------------------------------------------------------ orders --

def import_orders(path: Path | str, products: list[Product], orders: list[Order],
                  default_promised_days: float = 14.0) -> ImportResult:
    """Import an order export. Re-importing updates existing orders in place."""
    result = ImportResult()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        result.warnings.append("File is empty.")
        return result

    cmap = _build_map(list(rows[0].keys()), ORDER_COLUMNS)
    result.mapped_columns = cmap
    for required in ("external_id", "revenue"):
        if required not in cmap:
            result.warnings.append(
                f"No column matched '{required}'. Found: {', '.join(rows[0].keys())}")
            return result

    by_sku = {p.sku.lower(): p for p in products if p.sku}
    by_name = {p.name.lower(): p for p in products}
    existing = {o.external_id: o for o in orders if o.external_id}

    for row in rows:
        ext = str(row.get(cmap["external_id"], "")).strip()
        if not ext:
            result.skipped += 1
            continue

        revenue = _num(row.get(cmap["revenue"], 0))
        # Shopify repeats the order header row per line item with a blank total
        # on continuation lines. Those are line items, not new orders.
        if revenue == 0 and ext in existing:
            result.skipped += 1
            continue

        product = None
        raw_sku = str(row.get(cmap.get("sku", ""), "")).strip()
        raw_name = str(row.get(cmap.get("product_name", ""), "")).strip()
        sku, pname = raw_sku.lower(), raw_name.lower()
        if sku and sku in by_sku:
            product = by_sku[sku]
        elif pname and pname in by_name:
            product = by_name[pname]
        elif pname:
            product = next((p for p in products if p.name.lower() in pname), None)
        if product is None and (sku or pname):
            # Report it exactly as the file spells it, so it can be searched for.
            result.unmatched_products.add(raw_sku or raw_name)

        fin = _norm(str(row.get(cmap.get("financial_status", ""), "")))
        ful = _norm(str(row.get(cmap.get("fulfillment_status", ""), "")))
        status = STATUS_MAP.get(fin) or STATUS_MAP.get(ful) or "received"
        tracking = str(row.get(cmap.get("tracking_number", ""), "")).strip()
        delivered = _iso_date(row.get(cmap.get("delivered_date", ""), ""))
        if delivered and status == "in_transit":
            status = "delivered"
        if status == "in_transit" and not tracking:
            status = "awaiting_tracking"

        qty = int(_num(row.get(cmap.get("quantity", ""), 1)) or 1)
        order = existing.get(ext)
        if order is None:
            order = Order(external_id=ext)
            orders.append(order)
            existing[ext] = order
            result.created += 1
        else:
            result.updated += 1

        order.revenue = revenue
        order.quantity = qty
        order.status = status
        order.email = str(row.get(cmap.get("email", ""), "")).strip()
        order.customer = str(row.get(cmap.get("customer", ""), "")).strip()
        order.country = str(row.get(cmap.get("country", ""), "")).strip()
        order.tracking_number = tracking
        order.delivered_date = delivered
        order.ordered_date = _iso_date(row.get(cmap.get("ordered_date", ""), "")) \
            or order.ordered_date
        order.promised_days = default_promised_days
        if product:
            order.product_id = product.id
            order.cogs = product.landed_cost * qty
            order.promised_days = product.delivery_days

    if result.unmatched_products:
        result.warnings.append(
            f"{len(result.unmatched_products)} product(s) in the file did not "
            f"match anything in the store, so their COGS is unknown and profit "
            f"figures will be optimistic. Set matching SKUs to fix it.")
    return result


# --------------------------------------------------------------- ad spend --

def import_ads(path: Path | str, tests: list[AdTest], products: list[Product],
               product_id: str = "", channel: str = "meta") -> ImportResult:
    """Import an ad platform export into tests.

    Rows are matched to tests by campaign name first; failing that, by a
    product name appearing inside the campaign name - which is why naming
    campaigns after the product pays off.
    """
    result = ImportResult()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        result.warnings.append("File is empty.")
        return result

    cmap = _build_map(list(rows[0].keys()), AD_COLUMNS)
    result.mapped_columns = cmap
    if "spend" not in cmap:
        result.warnings.append(
            f"No spend column found. Headers: {', '.join(rows[0].keys())}")
        return result

    by_campaign = {t.notes.lower(): t for t in tests if t.notes}

    for row in rows:
        campaign = str(row.get(cmap.get("campaign", ""), "")).strip()
        spend = _num(row.get(cmap["spend"], 0))
        if spend <= 0 and not campaign:
            result.skipped += 1
            continue

        target_product = product_id
        if not target_product and campaign:
            match = next((p for p in products
                          if p.name.lower() in campaign.lower()
                          or (p.sku and p.sku.lower() in campaign.lower())), None)
            if match:
                target_product = match.id
        if not target_product:
            result.skipped += 1
            result.unmatched_products.add(campaign or "(unnamed campaign)")
            continue

        test = by_campaign.get(campaign.lower())
        if test is None:
            test = next((t for t in tests
                         if t.product_id == target_product and not t.ended), None)
        if test is None:
            test = AdTest(product_id=target_product, channel=channel, notes=campaign)
            started = _iso_date(row.get(cmap.get("date", ""), ""))
            if started:
                test.started = started
            tests.append(test)
            by_campaign[campaign.lower()] = test
            result.created += 1
        else:
            result.updated += 1

        # Platform exports are cumulative for the selected window, so replace
        # rather than accumulate - otherwise a second import doubles the spend.
        test.spend = spend
        test.impressions = int(_num(row.get(cmap.get("impressions", ""), 0)))
        test.clicks = int(_num(row.get(cmap.get("clicks", ""), 0)))
        test.landing_views = int(_num(row.get(cmap.get("landing_views", ""), 0)))
        test.add_to_carts = int(_num(row.get(cmap.get("add_to_carts", ""), 0)))
        test.checkouts = int(_num(row.get(cmap.get("checkouts", ""), 0)))
        test.purchases = int(_num(row.get(cmap.get("purchases", ""), 0)))
        test.revenue = _num(row.get(cmap.get("revenue", ""), 0))

    if result.unmatched_products:
        result.warnings.append(
            "Some campaigns did not match a product. Name campaigns after the "
            "product (or pass --product) so spend lands on the right test.")
    return result


def ledger_from_ads(tests: list[AdTest],
                    existing: list[LedgerEntry] | None = None) -> list[LedgerEntry]:
    """Turn ad spend into ledger entries so cash reporting sees it.

    Idempotent: one entry per test, replaced in place on re-import. Without
    this, importing the same export twice silently doubles your ad spend and
    every profit figure downstream becomes fiction.
    """
    existing = existing if existing is not None else []
    by_memo = {e.memo: e for e in existing if e.category == "ads"}
    created: list[LedgerEntry] = []
    for test in tests:
        if test.spend <= 0:
            continue
        memo = f"Ad spend: {test.id}"
        entry = by_memo.get(memo)
        if entry is not None:
            entry.amount = -test.spend      # replace, never accumulate
            entry.date = test.started
            continue
        created.append(LedgerEntry(
            date=test.started, kind="expense", category="ads",
            amount=-test.spend, product_id=test.product_id, memo=memo))
    return created
