"""A very basic web interface: the daily loop, in a browser.

    python -m dropship ui

Serves a handful of pages from the standard library's http.server: today's
briefing, the portfolio, one page per product, the order queue and the
settings, plus the existing dashboard. Every request reads the store fresh
from disk and every form writes through the same functions the CLI uses, so
the two never disagree about a number or a verdict.

It listens on 127.0.0.1 only and has no login. Keep it that way: anyone who
can reach the port can change the data.
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from . import cashflow, daily, dashboard, ops, research, storefront, testing
from .demo import seed
from .economics import UnitEconomics, for_product
from .models import ORDER_STATES, AdTest, Config, Order, Product, today_iso
from .store import Store

DEFAULT_PORT = 8765
CHANNELS = ("meta", "tiktok", "google", "organic")
ORDER_ROWS = 50

# Layered on the dashboard's stylesheet so the validated palette tokens are
# shared, not copied, and no new colour is introduced. Checked in both modes:
# small text uses --ink-2 (7.5:1 or better; --ink-muted is only 3.5:1 in light
# mode, too faint for the thresholds printed beside every number), input
# borders --ink-muted (3.4:1), the focus ring --pos (4.3:1), and buttons are
# ink on surface (17:1).
_CSS = """
.sub, .hint, .empty, .tile .note, th, summary { color: var(--ink-2); }
nav.top { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 18px;
  padding-bottom: 12px; margin-bottom: 22px; border-bottom: 1px solid var(--hairline); }
nav.top .brand { font-weight: 650; margin-right: auto; }
nav.top a { color: var(--ink-2); text-decoration: none; }
nav.top a:hover { color: var(--ink-1); }
nav.top a[aria-current="page"] { color: var(--ink-1); font-weight: 600;
  text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 6px; }
a { color: inherit; text-underline-offset: 2px; }
:focus-visible { outline: 2px solid var(--pos); outline-offset: 2px; }
h1 + .sub { margin-top: 4px; }
h3 { font-size: 12px; margin: 18px 0 6px; color: var(--ink-2); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em; }
.card > h3:first-child { margin-top: 0; }
.card > details:first-child { margin-top: 0; }
p { margin: 8px 0; }
.lead { font-size: 17px; font-weight: 600; margin: 14px 0 0; }
.flash { margin: 0 0 18px; padding: 10px 14px; border-radius: 8px;
  background: var(--surface-1); border: 1px solid var(--hairline);
  border-left: 4px solid var(--good); }
.flash.err { border-left-color: var(--critical); }
.cols { display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.stack > * + * { margin-top: 12px; }
dl.kv { display: grid; grid-template-columns: max-content 1fr; gap: 7px 18px; margin: 0; }
dl.kv dt { color: var(--ink-2); font-size: 13.5px; }
dl.kv dd { margin: 0; font-variant-numeric: tabular-nums; }
ul.plain, ol.plain { margin: 6px 0 0; padding-left: 20px; }
ul.plain li, ol.plain li { margin: 4px 0; }
th + th, td + td { padding-left: 14px; }
th.l, td.l { text-align: left; }
.compact table { min-width: 0; }
td input, td select { width: 100%; }
.fields { display: grid; gap: 12px 14px; margin: 12px 0;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
label.f { display: block; font-size: 12.5px; color: var(--ink-2); }
label.f input, label.f select, label.f textarea { display: block; width: 100%;
  margin-top: 4px; }
label.check { display: flex; gap: 8px; align-items: center; font-size: 14px;
  margin-top: 10px; }
.hint { display: block; font-size: 12px; margin-top: 3px; }
input, select, textarea { font: inherit; font-size: 14px; color: var(--ink-1);
  background: var(--page); border: 1px solid var(--ink-muted); border-radius: 7px;
  padding: 6px 9px; min-width: 0; }
input[type="checkbox"] { margin: 0; accent-color: var(--ink-1); }
textarea { min-height: 64px; resize: vertical; }
button { font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  border-radius: 7px; padding: 7px 14px; background: var(--ink-1);
  color: var(--surface-1); border: 1px solid var(--ink-1); }
button.ghost { background: transparent; color: var(--ink-1);
  border-color: var(--ink-muted); }
.actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin-top: 14px; }
.order-form { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: flex-end;
  margin-top: 10px; }
.order-form label.f { flex: 1 1 150px; }
.issue { margin-top: 8px; }
.item-links { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center;
  margin-top: 6px; font-size: 13.5px; }
pre.macro { white-space: pre-wrap; background: var(--page);
  font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  border: 1px solid var(--hairline); border-radius: 8px; padding: 12px; }
"""

VERDICT_KIND = {
    testing.KILL: "critical", testing.ITERATE: "warning", testing.HOLD: "warning",
    testing.SCALE: "good", testing.KEEP_TESTING: "info", testing.NOT_STARTED: "info",
}
SEVERITY_KIND = {"critical": "critical", "high": "serious", "medium": "warning",
                 "low": "info"}
PRIORITY_KIND = {1: "critical", 2: "serious", 3: "warning"}
FUNNEL_KIND = {"weak": "critical", "ok": "warning", "good": "good"}
STAGE_NAMES = {"ctr": "Click-through", "lpv_rate": "Page views per click",
               "atc_rate": "Add to cart", "checkout_rate": "Checkout started",
               "purchase_rate": "Purchase"}


# ------------------------------------------------------------ formatting --

def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _money(value: float, config: Config) -> str:
    if math.isinf(value):
        return "n/a"
    sym = {"USD": "$", "GBP": "£", "EUR": "€"}.get(config.currency, "")
    return f"{'-' if value < 0 else ''}{sym}{abs(value):,.2f}"


def _times(value: float) -> str:
    return "n/a" if math.isinf(value) else f"{value:.2f}x"


def _pct(value: float, places: int = 1) -> str:
    return f"{value * 100:.{places}f}%"


def _plain(value: float) -> str:
    """A number as a form value: no exponent, no trailing zeros."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _signed(value: float, config: Config) -> str:
    """Profit or loss. The sign carries the meaning; the colour repeats it."""
    if value == 0:
        return _money(value, config)
    tone = "pos" if value > 0 else "neg"
    return f'<span class="{tone}">{_money(value, config)}</span>'


def _url(path: str, **params: str) -> str:
    params = {k: v for k, v in params.items() if v}
    if not params:
        return path
    return path + ("&" if "?" in path else "?") + urlencode(params)


def _link(href: str, text: str) -> str:
    return f'<a href="{_e(href)}">{_e(text)}</a>'


def _chip(label: str, kind: str) -> str:
    return f'<span class="chip {kind}"><span class="dot"></span>{_e(label)}</span>'


def _verdict_chip(action: str) -> str:
    return _chip(action.replace("_", " "), VERDICT_KIND.get(action, "info"))


def _ul(items: list[str], ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    rows = "".join(f"<li>{_e(item)}</li>" for item in items)
    return f'<{tag} class="plain">{rows}</{tag}>'


def _kv(rows: list[tuple[str, str, str]]) -> str:
    """(label, value as trusted HTML, note as plain text) - value then threshold."""
    out = []
    for label, value, note in rows:
        tail = f' <span class="sub">{_e(note)}</span>' if note else ""
        out.append(f"<dt>{_e(label)}</dt><dd>{value}{tail}</dd>")
    return f'<dl class="kv">{"".join(out)}</dl>'


def _table(headers: list[str], rows: list[list[str]], left: tuple[int, ...] = (),
           compact: bool = False) -> str:
    """Cells are trusted HTML: escape anything user-supplied before passing it in."""
    def cell(tag: str, i: int, content: str) -> str:
        cls = ' class="l"' if i in left else ""
        return f"<{tag}{cls}>{content}</{tag}>"

    head = "".join(cell("th", i, _e(h)) for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(cell("td", i, c) for i, c in enumerate(row))
                   + "</tr>" for row in rows)
    wrap = "scroll compact" if compact else "scroll"
    return (f'<div class="{wrap}"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _tiles(tiles: list[tuple[str, str, str, str]]) -> str:
    """(label, value, note, tone) - every figure next to what it is judged against."""
    out = []
    for label, value, note, tone in tiles:
        out.append(f'<div class="card tile"><div class="label">{_e(label)}</div>'
                   f'<div class="value {tone}">{_e(value)}</div>'
                   f'<div class="note">{_e(note)}</div></div>')
    return f'<div class="tiles">{"".join(out)}</div>'


# ----------------------------------------------------------------- forms --

class _Invalid(Exception):
    """A form value the engine cannot use. The message says how to fix it."""


def _text(form: dict[str, str], name: str) -> str:
    return form.get(name, "").strip()


def _flag(form: dict[str, str], name: str) -> bool:
    return name in form


def _number(form: dict[str, str], name: str, label: str, default: float,
            lo: float = 0.0, hi: float | None = None) -> float:
    """Parse a number; a blank field keeps the current value."""
    raw = _text(form, name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise _Invalid(f"{label} must be a number, not '{raw}'.") from None
    if not math.isfinite(value) or value < lo or (hi is not None and value > hi):
        bound = f"between {lo:g} and {hi:g}" if hi is not None else f"{lo:g} or more"
        raise _Invalid(f"{label} must be {bound}, not '{raw}'.")
    return value


def _whole(form: dict[str, str], name: str, label: str, default: int,
           lo: float = 0.0, hi: float | None = None) -> int:
    value = _number(form, name, label, float(default), lo, hi)
    if not value.is_integer():
        raise _Invalid(f"{label} must be a whole number, not '{_text(form, name)}'.")
    return int(value)


def _back(form: dict[str, str]) -> str:
    """Where to return after a rejected form. Local paths only: no open redirect."""
    back = form.get("back", "")
    if back.startswith("/") and not back.startswith("//") and "\\" not in back:
        return back
    return "/"


def _hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{name}" value="{_e(value)}">'


def _input(label: str, name: str, value: str = "", *, kind: str = "number",
           step: str = "any", lo: float | None = 0, hi: float | None = None,
           required: bool = False, hint: str = "") -> str:
    attrs = [f'type="{kind}"', f'name="{name}"', f'value="{_e(value)}"']
    if kind == "number":
        attrs.append(f'step="{step}"')
        if lo is not None:
            attrs.append(f'min="{lo:g}"')
        if hi is not None:
            attrs.append(f'max="{hi:g}"')
    if required:
        attrs.append("required")
    tail = f'<span class="hint">{_e(hint)}</span>' if hint else ""
    return f'<label class="f">{_e(label)}<input {" ".join(attrs)}>{tail}</label>'


def _select(label: str, name: str, options: list[tuple[str, str]],
            selected: str) -> str:
    opts = []
    for value, text in options:
        mark = " selected" if value == selected else ""
        opts.append(f'<option value="{_e(value)}"{mark}>{_e(text)}</option>')
    return (f'<label class="f">{_e(label)}<select name="{name}">'
            f'{"".join(opts)}</select></label>')


def _check(label: str, name: str, checked: bool, hint: str = "") -> str:
    mark = " checked" if checked else ""
    tail = f'<span class="hint">{_e(hint)}</span>' if hint else ""
    return (f'<div><label class="check"><input type="checkbox" name="{name}" '
            f'value="1"{mark}>{_e(label)}</label>{tail}</div>')


# ---------------------------------------------------------------- layout --

NAV = (("/", "Today"), ("/products", "Products"), ("/orders", "Orders"),
       ("/settings", "Settings"), ("/dashboard", "Dashboard"))


@dataclass
class Response:
    status: int
    body: str = ""
    location: str = ""


def _redirect(location: str) -> Response:
    # 303 so a refresh after saving re-reads the page instead of re-posting.
    return Response(303, f'<a href="{_e(location)}">Continue</a>', location)


def _layout(store: Store, title: str, body: str, current: str = "",
            query: dict[str, str] | None = None) -> str:
    query = query or {}
    links = []
    for href, label in NAV:
        mark = ' aria-current="page"' if href == current else ""
        links.append(f'<a href="{href}"{mark}>{label}</a>')
    flash = ""
    if query.get("msg"):
        flash += f'<p class="flash" role="status">{_e(query["msg"])}</p>'
    if query.get("err"):
        flash += f'<p class="flash err" role="alert">{_e(query["err"])}</p>'
    name = _e(store.config.business_name)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_e(title)} - {name}</title>"
            f"<style>{dashboard._CSS}{_CSS}</style></head>"
            '<body><div class="wrap"><nav class="top" aria-label="Main">'
            f'<span class="brand">{name}</span>{"".join(links)}</nav>'
            f"<main>{flash}{body}</main></div></body></html>")


def _bare_page(message: str) -> str:
    """For when the store itself cannot be read, so no layout can be built."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>dropship</title><style>{dashboard._CSS}{_CSS}</style></head>"
            '<body><div class="wrap"><h1>Something went wrong</h1>'
            f'<p>{_e(message)}</p><p><a href="/">Try again</a></p></div></body></html>')


def _not_found(store: Store, message: str) -> Response:
    body = (f"<h1>Not found</h1><p>{_e(message)}</p>"
            '<p><a href="/">Back to today</a></p>')
    return Response(404, _layout(store, "Not found", body))


def _has_records(store: Store) -> bool:
    return any((store.products, store.orders, store.suppliers, store.tests,
                store.ledger))


# ----------------------------------------------------------------- today --

# Where a briefing item leads when it does not name a product.
AREA_PAGES = {"ops": ("/orders", "Open orders"),
              "cash": ("/dashboard", "Open the cash projection"),
              "metrics": ("/dashboard", "Open the dashboard"),
              "growth": ("/products", "Open products")}
_REF = re.compile(r"\b(?:prd|tst)_[0-9a-f]{10}\b")


def _item_link(store: Store, item: daily.BriefItem) -> tuple[str, str] | None:
    """The page that fixes a briefing item: its product's page if it names one."""
    product = None
    ref = _REF.search(item.command)
    if ref:
        test = store.test(ref.group(0)) if ref.group(0).startswith("tst_") else None
        product = store.product(test.product_id if test else ref.group(0))
    if product is None:
        named = [p for p in store.products if p.name and p.name in item.title]
        product = max(named, key=lambda p: len(p.name), default=None)
    if product is not None:
        return _url("/product", id=product.id), f"Open {product.name}"
    return AREA_PAGES.get(item.area)


def _brief_list(store: Store, items: list[daily.BriefItem], start: int) -> str:
    rows = []
    for n, item in enumerate(items, start):
        kind = PRIORITY_KIND.get(item.priority, "info")
        extras = []
        link = _item_link(store, item)
        if link:
            extras.append(_link(*link))
        if item.command:
            extras.append(f"<code>{_e(item.command)}</code>")
        links = f'<div class="item-links">{" ".join(extras)}</div>' if extras else ""
        rows.append(f'<li><div class="item-head">{_chip(kind, kind)}'
                    f'<span class="item-title">{n}. {_e(item.title)}</span>'
                    f'<span class="sub">{_e(item.area)}</span></div>'
                    f'<div class="item-detail">{_e(item.detail)}</div>'
                    f'<div class="item-action"><b>Do:</b> {_e(item.action)}</div>'
                    f"{links}</li>")
    return f'<ul class="items">{"".join(rows)}</ul>'


def page_today(store: Store, query: dict[str, str]) -> str:
    config = store.config
    brief = daily.build(store)
    board = brief.scoreboard
    be_roas = board["breakeven_roas"]
    if be_roas > 0:
        side = "above" if board["blended_roas"] >= be_roas else "below"
        roas_note = f"breakeven {be_roas:.2f}x - {side}"
    else:
        roas_note = "no orders yet to set a breakeven"
    months = board["cash"] / max(1.0, config.fixed_monthly_costs)
    profit = board["net_profit_30d"]
    tiles = [
        ("Net profit, 30 days", _money(profit, config), "after ads and fixed costs",
         "pos" if profit >= 0 else "neg"),
        ("Revenue, 30 days", _money(board["revenue_30d"], config),
         f"{board['orders_30d']} orders", ""),
        ("Blended ROAS", f"{board['blended_roas']:.2f}x", roas_note, ""),
        ("Cash", _money(board["cash"], config),
         f"{months:.1f} months of fixed costs - alert below 2", ""),
        ("Order actions", str(board["open_actions"]),
         f"{board['critical_actions']} critical", ""),
    ]
    parts = [f'<h1>Today</h1><p class="sub">{_e(brief.date)}</p>',
             f'<p class="lead">{_e(brief.headline)}</p>', _tiles(tiles),
             "<h2>Do these first</h2>"]
    first, rest = brief.focus, brief.items[len(brief.focus):]
    if first:
        parts.append(f'<div class="card">{_brief_list(store, first, 1)}</div>')
    else:
        parts.append('<div class="card"><p class="empty">Nothing outstanding.</p></div>')
    if rest:
        parts.append("<h2>Then</h2>")
        parts.append(f'<div class="card">{_brief_list(store, rest, len(first) + 1)}</div>')
    if not _has_records(store):
        parts.append(
            '<h2>Just looking?</h2><form method="post" action="/demo" class="card">'
            "<p>Load the demo store: a winner, a loser, a product that fails its "
            "gates and a few orders drifting toward chargebacks. It also replaces "
            "the business name and the cash settings.</p>"
            f'{_hidden("back", "/")}<button>Load demo data</button></form>')
    return _layout(store, "Today", "".join(parts), "/", query)


# -------------------------------------------------------------- products --

_RESEARCH_FIELDS = (
    ("Demand", "demand", "search volume and trend"),
    ("Competition", "competition", "10 = saturated"),
    ("Creative potential", "creative_potential", "value shown in 3 silent seconds"),
    ("Problem solving", "problem_solving", "fixes a real, felt annoyance"),
    ("Wow factor", "wow_factor", "scroll-stopping"),
    ("Seasonality", "seasonality", "10 = evergreen"),
    ("Return risk", "return_risk", "10 = high"),
)


def page_products(store: Store, query: dict[str, str]) -> str:
    config = store.config
    rows = daily.portfolio(store)
    if rows:
        table = _table(
            ["Product", "Status", "Score", "Price", "Margin", "Breakeven ROAS",
             "Orders", "Profit", "Verdict"],
            [[_link(_url("/product", id=r["id"]), r["name"]), _e(r["status"]),
              f"{r['score']:.0f} {_e(r['tier'])}" if r["tier"] else "-",
              _money(r["price"], config), _money(r["cm"], config),
              _times(r["be_roas"]), str(r["orders"]), _signed(r["profit"], config),
              _verdict_chip(r["verdict"]) if r["verdict"] else "-"]
             for r in rows],
            left=(1, 8))
    else:
        table = '<p class="empty">No products yet. Add the first one below.</p>'
    body = ('<h1>Products</h1><p class="sub">Sorted by profit. Margin is the '
            "contribution margin per order: what is left after costs, fees and "
            "expected refunds, before ads. It is the most you can pay for a sale.</p>"
            f'<div class="card">{table}</div>'
            f"<h2>Add a product</h2>{_add_product_form(store)}")
    return _layout(store, "Products", body, "/products", query)


def _add_product_form(store: Store) -> str:
    c = store.config
    suppliers = [("", "None yet")] + [(s.id, s.name) for s in store.suppliers]
    scores = "".join(_input(label, name, "5", step="1", hi=10, hint=hint)
                     for label, name, hint in _RESEARCH_FIELDS)
    gates = (f"Gates: price at least {c.min_margin_multiple:g}x landed cost, "
             f"contribution margin at least {_money(c.min_contribution_margin, c)}, "
             f"delivery within {c.max_delivery_days:g} days unless stocked locally, "
             f"nothing restricted or trademarked. Fail one and the product is not "
             f"tested, whatever it scores.")
    return ('<form method="post" action="/products/add" class="card">'
            + _hidden("back", "/products") + '<div class="fields">'
            + _input("Name", "name", kind="text", required=True)
            + _input("Price", "price", required=True, hint="what the customer pays")
            + _input("Supplier cost", "cogs", required=True, hint="per unit")
            + _input("Shipping cost", "ship_cost", "0", hint="supplier to customer")
            + _input("Delivery days", "delivery_days", "14", hint="door to door, as promised")
            + _select("Supplier", "supplier", suppliers, "")
            + _input("SKU", "sku", kind="text")
            + _input("Category", "category", kind="text")
            + "</div><details><summary>Upsell, research scores and risk flags</summary>"
            + '<p class="hint">Scores run 0-10 and come from you. The score is only '
            + "as honest as they are.</p><div class=\"fields\">"
            + _input("Upsell revenue", "upsell_revenue", "0", hint="extra per order")
            + _input("Upsell cost", "upsell_cogs", "0")
            + scores + "</div>"
            + _check("Stocked in a local warehouse", "local_stock", False)
            + _check("Restricted or regulated category", "restricted", False)
            + _check("Trademark or counterfeit risk", "brand_risk", False)
            + '<div class="fields">' + _input("Notes", "notes", kind="text") + "</div>"
            + f'</details><p class="hint">{_e(gates)}</p>'
            + '<div class="actions"><button>Add and score</button></div></form>')


# --------------------------------------------------------------- product --

_BREAKDOWN = (("product cost", "product_cost"), ("shipping", "shipping_cost"),
              ("payment fees", "payment_fees"), ("platform fees", "platform_fees"),
              ("support", "support_cost"), ("expected refunds", "expected_refund_cost"),
              ("expected chargebacks", "expected_chargeback_cost"))

# (label, field, is money). Counts are whole numbers.
_RESULT_FIELDS = (("Spend", "spend", True), ("Revenue", "revenue", True),
                  ("Impressions", "impressions", False), ("Link clicks", "clicks", False),
                  ("Landing page views", "landing_views", False),
                  ("Adds to cart", "add_to_carts", False),
                  ("Checkouts started", "checkouts", False),
                  ("Purchases", "purchases", False))


def page_product(store: Store, query: dict[str, str]) -> str | Response:
    product = store.product(query.get("id", ""))
    if product is None:
        return _not_found(store, "No such product. It may have been deleted.")
    config = store.config
    ue = for_product(product, config)
    result = research.score_product(product, config)
    here = _url("/product", id=product.id)
    supplier = store.supplier(product.supplier_id)
    facts = [product.status, product.sku, product.category,
             f"supplier {supplier.name}" if supplier else "",
             f"added {product.created}"]
    facts_line = " · ".join(f for f in facts if f)
    delete = ('<form method="post" action="/product/delete" class="actions" '
              "onsubmit=\"return confirm('Delete this product? Its tests and orders "
              "stay in the store.')\">"
              f'{_hidden("id", product.id)}{_hidden("back", here)}'
              '<button class="ghost">Delete product</button></form>')
    body = (f'<h1>{_e(product.name)}</h1><p class="sub">{_e(facts_line)}</p>'
            '<div class="cols">'
            f"{_economics_card(product, ue, config)}"
            f"{_research_card(product, result, config, here)}</div>"
            f"<h2>Test</h2>{_test_section(store, product, ue, result, here)}"
            f"<h2>Shop page</h2>{_shop_card(product, here)}"
            f"{delete}")
    return _layout(store, product.name, body, "/products", query)


def _shop_card(product: Product, here: str) -> str:
    """The customer-facing page: where it points, and what it still needs."""
    photos = (f"{len(product.photos)} photo(s) on file"
              if product.photos else "No photos yet")
    command = (f'dropship storefront "{product.name}" '
               f"--image shot1.jpg --image shot2.jpg")
    return ('<div class="card">'
            "<p>One self-contained HTML file: photos, price, the listing copy, "
            "policies and a buy button that opens your payment link. Put it on "
            "any static host. The payment page stays with your processor, so "
            "card details never touch it.</p>"
            '<form method="post" action="/product/shop">'
            f'{_hidden("id", product.id)}{_hidden("back", here)}'
            '<div class="fields">'
            f'{_input("Payment link", "pay_url", product.pay_url, kind="text", hint="Stripe or PayPal link for this product; https only")}'
            f'{_input("The problem", "copy_problem", product.copy_problem, kind="text", hint="a noun phrase: pet hair on every cushion")}'
            f'{_input("The outcome", "copy_outcome", product.copy_outcome, kind="text", hint="a fur-free sofa in one pass")}'
            f'{_input("Bundle price", "bundle_price", _plain(product.bundle_price), hint="two of them, at a price for two")}'
            f'{_input("Bundle payment link", "bundle_pay_url", product.bundle_pay_url, kind="text", hint="its own link, charging the bundle price")}'
            "</div>"
            '<div class="actions"><button class="ghost">Save</button></div></form>'
            f'<p class="hint">{_e(photos)}. Photos are files, so they go in from '
            f"the terminal: <code>{_e(command)}</code></p>"
            f'<div class="actions">{_link(_url("/shop", id=product.id), "Preview the shop page")}'
            f'<span class="hint">Write this page: <code>dropship storefront '
            f'"{_e(product.name)}"</code> &nbsp; The whole shop, with policy '
            f"pages: <code>dropship site</code></span></div></div>")


def _economics_card(product: Product, ue: UnitEconomics, config: Config) -> str:
    b = ue.breakdown()
    rows = [
        ("Price", _money(product.price, config),
         f"{_money(ue.aov, config)} per order with the upsell"
         if product.upsell_revenue else ""),
        ("Landed cost", _money(product.landed_cost, config),
         f"{product.margin_multiple:.2f}x markup, floor {config.min_margin_multiple:g}x"),
        ("Contribution margin", _signed(ue.contribution_margin, config),
         f"{_pct(ue.contribution_margin_pct, 0)} of order value, floor "
         f"{_money(config.min_contribution_margin, config)}"),
        ("Breakeven CPA", _money(ue.breakeven_cpa, config),
         "the most you can pay per sale"),
        ("Breakeven ROAS", _times(ue.breakeven_roas),
         f"target {_times(ue.target_roas())} for a "
         f"{_pct(config.target_net_margin, 0)} net margin"),
    ]
    lines = [["Order value", _money(b["aov"], config)]]
    lines += [[f"less {label}", _money(-b[key], config)]
              for label, key in _BREAKDOWN if b[key]]
    lines.append(["<b>Contribution margin</b>",
                  f"<b>{_money(b['contribution_margin'], config)}</b>"])
    return ('<div class="card"><h3>Unit economics</h3>' + _kv(rows)
            + "<details><summary>Where the money goes</summary>"
            + _table(["Per order", "Amount"], lines, compact=True)
            + '<p class="hint">Price ladder and sensitivity: '
            + f"<code>dropship econ {_e(product.id)}</code></p></details></div>")


def _research_card(product: Product, result: research.ResearchResult,
                   config: Config, here: str) -> str:
    parts = ['<div class="card"><h3>Research</h3>',
             f"<p><b>{result.score:.0f}/100, tier {_e(result.tier)}.</b> "
             f"{_e(result.verdict)}</p>"]
    if result.blockers:
        parts.append("<h3>Blockers</h3>" + _ul(result.blockers))
        # Only a fix when the price is the problem, not when delivery is.
        if result.recommended_price > product.price:
            parts.append(f"<p>Price that would clear the floor: "
                         f"<b>{_money(result.recommended_price, config)}</b></p>")
    if result.risks:
        parts.append("<h3>Risks</h3>" + _ul(result.risks))
    if result.strengths:
        parts.append("<h3>Strengths</h3>" + _ul(result.strengths))
    if (product.score, product.tier) != (result.score, result.tier):
        stored = f"{product.score:.0f} ({product.tier})" if product.tier else "no score"
        parts.append('<form method="post" action="/product/score" class="actions">'
                     f'{_hidden("id", product.id)}{_hidden("back", here)}'
                     '<button class="ghost">Save this score</button>'
                     f'<span class="hint">The portfolio still shows {_e(stored)}. '
                     "Saving can move it between candidate and approved.</span></form>")
    parts.append("</div>")
    return "".join(parts)


def _test_section(store: Store, product: Product, ue: UnitEconomics,
                  result: research.ResearchResult, here: str) -> str:
    active = store.active_test(product.id)
    history = sorted(store.tests_for(product.id), key=lambda t: t.started)
    latest = active or (history[-1] if history else None)
    parts = []
    if latest is not None:
        parts.append(_test_card(store, product, ue, latest, latest is active, here))
    if active is not None:
        parts.append(_results_form(active, here))
    else:
        parts.append(_start_card(store, product, ue, result, here))
    return f'<div class="stack">{"".join(parts)}</div>'


def _cash_note(store: Store, ue: UnitEconomics) -> str:
    """The daily budget's threshold: what cash can carry at the target CPA."""
    config = store.config
    if ue.contribution_margin <= 0:
        return "no budget is safe - every order loses money"
    cpa = ue.target_cpa() if ue.target_cpa() > 0 else ue.breakeven_cpa
    cash = config.starting_cash + sum(e.amount for e in store.ledger)
    safe = cashflow.max_safe_daily_spend(ue, config, cpa, 45, cash)
    if safe <= 0:
        return "cash cannot carry any daily budget right now"
    return f"cash allows up to {_money(safe, config)}/day"


def _test_card(store: Store, product: Product, ue: UnitEconomics, test: AdTest,
               live: bool, here: str) -> str:
    config = store.config
    d = testing.decide(test, ue, config)
    when = f"started {test.started}" + (f", ended {test.ended}" if test.ended else "")
    title = f"{'Live' if live else 'Last'} test · {test.channel} · {when}"

    rows = [("Spend", _money(test.spend, config),
             f"of {_money(test.planned_budget, config)} planned"
             if test.planned_budget else ""),
            ("Purchases", str(test.purchases), f"{_money(test.revenue, config)} revenue"),
            ("Observed CPA",
             _money(d.observed_cpa, config) if test.purchases else "no sales yet",
             f"breakeven {_money(d.breakeven_cpa, config)}, "
             f"target {_money(d.target_cpa, config)}")]
    if test.spend > 0 and d.breakeven_cpa > 0:
        span = (f"{_money(d.cpa_best_case, config)} to "
                f"{_money(d.cpa_worst_case, config)}" if test.purchases
                else f"at least {_money(d.cpa_best_case, config)}")
        rows.append(("True CPA", span, f"{_pct(d.confidence, 0)} confidence"))
    rows.append(("Profit so far", _signed(d.profit_so_far, config),
                 "margin earned minus spend"))
    if d.action == testing.KEEP_TESTING and d.spend_to_verdict > 0:
        rows.append(("Spend to a verdict", _money(d.spend_to_verdict, config),
                     "before zero sales means anything"))
    if live:
        rows.append(("Daily budget", _money(test.daily_budget, config),
                     _cash_note(store, ue)))

    apply = ""
    target = testing.STATUS_AFTER.get(d.action)
    if live and target and product.status != target:
        label = {testing.KILL: "The campaign is off - mark it killed",
                 testing.SCALE: "Mark as scaling",
                 testing.ITERATE: "Mark as iterating"}[d.action]
        note = f"Records the verdict and moves the product to {target}"
        note += ", ending the test." if d.action == testing.KILL else "."
        apply = ('<form method="post" action="/product/decide" class="actions">'
                 f'{_hidden("id", test.id)}{_hidden("back", here)}'
                 f'<button>{_e(label)}</button><span class="hint">{_e(note)}</span></form>')

    funnel = ""
    if any(s.denominator for s in d.funnel):
        funnel = "<h3>Funnel</h3>" + _table(
            ["Stage", "Rate", "Counts", "Floor", "Status"],
            [[_e(STAGE_NAMES.get(s.name, s.name)), _pct(s.value, 2),
              f"{s.numerator:,}/{s.denominator:,}", _pct(s.low),
              _chip(s.status, FUNNEL_KIND.get(s.status, "info"))] for s in d.funnel],
            left=(4,), compact=True)
        if d.weakest_stage:
            weakest = STAGE_NAMES.get(d.weakest_stage, d.weakest_stage)
            funnel += f"<p>Weakest link: <b>{_e(weakest)}</b></p>"

    reasoning = "".join(f'<p class="item-detail">{_e(line)}</p>' for line in d.reasoning)
    return (f'<div class="card"><h3>{_e(title)}</h3>'
            f'<div class="item-head">{_verdict_chip(d.action)}'
            f"<b>{_e(d.headline)}</b></div>"
            f"<h3>Do this</h3>{_ul(d.next_steps, ordered=True)}{apply}"
            f"<h3>Evidence</h3>{_kv(rows)}{reasoning}{funnel}</div>")


def _results_form(test: AdTest, here: str) -> str:
    inputs = "".join(_input(label, name, _plain(getattr(test, name)),
                            step="any" if money else "1")
                     for label, name, money in _RESULT_FIELDS)
    inputs += _input("Daily budget", "daily_budget", _plain(test.daily_budget))
    return ('<form method="post" action="/product/test" class="card">'
            "<h3>Record results</h3>"
            '<p class="hint">Totals for the whole test so far, exactly as the ad '
            "platform reports them - not today's numbers. Change nothing else "
            "mid-test: each edit restarts the data you are paying for.</p>"
            f'{_hidden("id", test.id)}{_hidden("back", here)}'
            f'<div class="fields">{inputs}</div>'
            '<div class="actions"><button>Save and decide</button></div></form>')


def _start_card(store: Store, product: Product, ue: UnitEconomics,
                result: research.ResearchResult, here: str) -> str:
    config = store.config
    if result.blockers:
        return ('<div class="card"><h3>Start a test</h3><p>Not until the blockers '
                "above are fixed. No amount of creative solves a broken gate.</p></div>")
    plan = testing.plan_test(product.name, ue, config)
    warning = ""
    if product.status == "killed":
        warning = ('<p class="flash err">This product was killed. Do not resurrect it '
                   "without new evidence: a new angle, a new price or a new supplier.</p>")
    rows = [("Total budget", _money(plan.total_budget, config),
             "set by statistics, not by feel"),
            ("Daily budget", _money(plan.daily_budget, config), f"over {plan.days} days"),
            ("Breakeven CPA", _money(plan.breakeven_cpa, config),
             f"ROAS {_times(plan.breakeven_roas)}"),
            ("Target CPA", _money(plan.target_cpa, config),
             f"ROAS {_times(plan.target_roas)}")]
    checkpoints = _table(
        ["Day", "At spend", "Look at", "Act if"],
        [[str(cp["day"]), _money(cp["at_spend"], config), _e(cp["look_at"]),
          _e(cp["act_if"])] for cp in plan.checkpoints],
        left=(2, 3), compact=True)
    channels = [(channel, channel) for channel in CHANNELS]
    return ('<form method="post" action="/product/start" class="card">'
            f"<h3>Start a test</h3>{warning}{_kv(rows)}"
            f"<details><summary>Checkpoints and rules</summary>{checkpoints}"
            f"{_ul(plan.rules)}</details>"
            f'{_hidden("id", product.id)}{_hidden("back", here)}'
            '<div class="fields">'
            f'{_select("Channel", "channel", channels, "meta")}'
            f'{_input("Angle", "angle", kind="text", hint="e.g. before/after")}'
            "</div>"
            '<label class="f">Hypothesis<textarea name="hypothesis" required></textarea>'
            '<span class="hint">What result would prove you wrong? If you cannot say, '
            "you are not testing, you are hoping.</span></label>"
            '<div class="actions"><button>Start test</button></div></form>')


# ---------------------------------------------------------------- orders --

def _status_options(current: str) -> str:
    out = []
    for state in ORDER_STATES:
        mark = " selected" if state == current else ""
        out.append(f'<option value="{state}"{mark}>{state.replace("_", " ")}</option>')
    return "".join(out)


def _macro_fields(order: Order, product: str, config: Config) -> dict[str, str]:
    """Fill what the store knows. The rest stays visible as {slot}, on purpose."""
    values = {"name": order.customer.split(" ")[0] if order.customer else "",
              "order_id": order.external_id or order.id,
              "order_date": order.ordered_date,
              "total": _money(order.revenue, config),
              "promised_days": f"{order.promised_days:g}",
              "tracking_number": order.tracking_number,
              "delivered_date": order.delivered_date,
              "product_name": product}
    return {k: v for k, v in values.items() if v}


def _order_card(order: Order, actions: list[ops.Action], product: str,
                config: Config) -> str:
    worst = actions[0]
    meta = " · ".join(x for x in (product, _money(order.revenue, config),
                                  f"paid {order.ordered_date}", order.customer) if x)
    issues = []
    for a in actions:
        template = ""
        if a.macro:
            text = ops.render_macro(a.macro, **_macro_fields(order, product, config))
            template = (f"<details><summary>Email template: "
                        f"{_e(ops.MACROS[a.macro]['name'])}</summary>"
                        f'<pre class="macro">{_e(text)}</pre></details>')
        issues.append(f'<div class="issue"><b>{_e(a.issue)}</b>'
                      f'<div class="item-detail">{_e(a.why_it_matters)}</div>'
                      f'<div class="item-action"><b>Do:</b> {_e(a.do_this)}</div>'
                      f"{template}</div>")
    review = ""
    if any(a.macro == "review_request" for a in actions):
        review = ('<form method="post" action="/orders/review" class="actions">'
                  f'{_hidden("id", order.id)}{_hidden("back", "/orders")}'
                  '<button class="ghost">Review request sent</button></form>')
    form = ('<form method="post" action="/orders/update" class="order-form">'
            f'{_hidden("id", order.id)}{_hidden("back", "/orders")}'
            f'<label class="f">Status<select name="status">'
            f"{_status_options(order.status)}</select></label>"
            f'{_input("Tracking number", "tracking", order.tracking_number, kind="text")}'
            f'{_input("Open issue", "issue", order.issue, kind="text")}'
            '<button class="ghost">Save</button></form>')
    kind = SEVERITY_KIND.get(worst.severity, "info")
    return (f'<li><div class="item-head">{_chip(worst.severity, kind)}'
            f'<span class="item-title">{_e(order.external_id or order.id)}</span>'
            f'<span class="sub">{_e(meta)}</span></div>'
            f'{"".join(issues)}{review}{form}</li>')


def _order_row(order: Order, product: str, config: Config) -> list[str]:
    """One table row, its controls tied to a per-row form by the form attribute."""
    fid = _e(f"o-{order.id}")
    ref = order.external_id or order.id
    return [
        f'{_e(ref)}<form id="{fid}" method="post" action="/orders/update">'
        f'{_hidden("id", order.id)}{_hidden("back", "/orders")}</form>',
        _e(product), _e(order.ordered_date), _money(order.revenue, config),
        f'<select form="{fid}" name="status" aria-label="{_e("Status of " + ref)}">'
        f"{_status_options(order.status)}</select>",
        f'<input form="{fid}" name="tracking" value="{_e(order.tracking_number)}" '
        f'aria-label="{_e("Tracking number for " + ref)}">',
        f'<input form="{fid}" name="issue" value="{_e(order.issue)}" '
        f'aria-label="{_e("Open issue on " + ref)}">',
        f'<button form="{fid}" class="ghost">Save</button>',
    ]


def page_orders(store: Store, query: dict[str, str]) -> str:
    config = store.config
    health = ops.fulfilment_health(store.orders, config)
    queue = ops.action_queue(store.orders, config)
    names = {p.id: p.name for p in store.products}
    delivered = health["delivered"] > 0
    tiles = [
        ("On time", _pct(health["on_time_rate"], 0) if delivered else "-",
         f"within {config.max_delivery_days:g} days, target 85%+", ""),
        ("Average delivery",
         f"{health['avg_delivery_days']:.1f} days" if delivered else "-",
         f"promise limit {config.max_delivery_days:g} days", ""),
        ("Refund rate", _pct(health["refund_rate"]),
         f"economics assume {_pct(config.refund_rate)}", ""),
        ("Chargeback rate", _pct(health["chargeback_rate"], 2),
         "1% is the processor danger line", ""),
        ("Placed, no tracking", str(health["untracked"]),
         f"flagged after {ops.SLA['tracking']} days", ""),
    ]

    # One card per order, worst first; the queue is already sorted that way.
    groups: dict[str, list[ops.Action]] = {}
    for action in queue:
        groups.setdefault(action.order_id, []).append(action)
    by_id = {o.id: o for o in store.orders}
    urgent = [(by_id[k], v) for k, v in groups.items() if v[0].severity != "low"]
    low = [(by_id[k], v) for k, v in groups.items() if v[0].severity == "low"]

    def cards(items) -> str:
        return '<ul class="items">' + "".join(
            _order_card(o, acts, names.get(o.product_id, ""), config)
            for o, acts in items) + "</ul>"

    parts = ['<h1>Orders</h1><p class="sub">Fulfilment before ads, always. '
             "Work the list top-down.</p>", _tiles(tiles),
             f"<h2>Needs action ({len(urgent)})</h2>"]
    parts.append(f'<div class="card">{cards(urgent)}</div>' if urgent else
                 '<div class="card"><p class="empty">Nothing drifting. '
                 "Rare and good.</p></div>")
    if low:
        parts.append(f"<h2>Low priority ({len(low)})</h2>"
                     '<div class="card"><details><summary>Reviews to request and '
                     f"orders still inside their window</summary>{cards(low)}"
                     "</details></div>")

    recent = sorted(store.orders, key=lambda o: o.ordered_date, reverse=True)
    parts.append("<h2>All orders</h2>")
    if recent:
        rows = [_order_row(o, names.get(o.product_id, "-"), config)
                for o in recent[:ORDER_ROWS]]
        table = _table(["Order", "Product", "Paid", "Value", "Status", "Tracking",
                        "Open issue", ""], rows, left=(1, 4, 5, 6))
        more = ""
        if len(recent) > ORDER_ROWS:
            more = (f'<p class="hint">Showing the {ORDER_ROWS} most recent of '
                    f"{len(recent)}. For the rest: <code>dropship orders list "
                    f"--limit {len(recent)}</code></p>")
        parts.append(f'<div class="card">{table}{more}</div>')
    else:
        parts.append('<div class="card"><p class="empty">No orders yet. Import a '
                     "platform export: <code>dropship import orders "
                     "orders_export.csv</code></p></div>")
    return _layout(store, "Orders", "".join(parts), "/orders", query)


# -------------------------------------------------------------- settings --

# Grouped as in models.Config. Rates are fractions: 0.05 means 5%.
SETTINGS = (
    ("Business", (
        ("business_name", "Business name", ""),
        ("currency", "Currency", "USD, GBP and EUR show a symbol"),
    )),
    ("Payment processing", (
        ("payment_rate", "Payment fee rate", "0.029 = 2.9% of each order"),
        ("payment_fixed", "Payment fee, fixed", "per order"),
        ("platform_rate", "Platform fee rate", "marketplace or extra gateway"),
        ("chargeback_fee", "Chargeback fee", "per dispute"),
        ("payment_fee_refunded", "Processor returns its fee on refunds",
         "most keep it - check yours"),
    )),
    ("Loss rates - measure these once you have 50 orders", (
        ("refund_rate", "Refund rate", "0.05 = 5% of orders"),
        ("chargeback_rate", "Chargeback rate", "processors act above 0.01"),
        ("goods_loss_on_refund", "Goods lost on a refund", "1 = never comes back"),
        ("cs_cost_per_order", "Support cost per order", "time and apps"),
    )),
    ("Cash - what actually stops a store scaling", (
        ("payout_delay_days", "Payout delay, days", "new accounts: often 7-21"),
        ("rolling_reserve_rate", "Rolling reserve", "0.10 = 10% held back"),
        ("reserve_release_days", "Reserve held for, days", ""),
        ("ad_payment_delay_days", "Ad bill delay, days", "0 = prepaid card"),
        ("refund_lag_days", "Refund lag, days", "sale to refund"),
        ("fixed_monthly_costs", "Fixed costs per month", "store, apps, tools"),
        ("starting_cash", "Starting cash", "the ledger is added to this"),
    )),
    ("Decision thresholds", (
        ("target_net_margin", "Target net margin", "0.15 = 15% after ads"),
        ("min_margin_multiple", "Minimum markup", "research gate: price / cost"),
        ("min_contribution_margin", "Minimum contribution margin", "research gate"),
        ("max_delivery_days", "Maximum delivery days", "research gate"),
        ("confidence", "Decision confidence", "0.90 = 90% sure to kill or scale"),
        ("scale_step", "Scale step", "0.25 = +25% budget per step"),
    )),
)

# Shares of a whole. Confidence must stay strictly inside (0, 1) or the
# statistics behind every kill and scale decision cannot be computed.
_BOUNDS = {name: (0.0, 1.0) for name in (
    "payment_rate", "platform_rate", "refund_rate", "chargeback_rate",
    "goods_loss_on_refund", "rolling_reserve_rate", "target_net_margin")}
_BOUNDS["confidence"] = (0.5, 0.999)


def page_settings(store: Store, query: dict[str, str]) -> str:
    config = store.config
    types = {f.name: f.type for f in fields(Config)}
    sections = []
    for title, group in SETTINGS:
        inputs, checks = [], []
        for name, label, hint in group:
            value, kind = getattr(config, name), types[name]
            if kind == "bool":
                checks.append(_check(label, name, value, hint))
            elif kind == "str":
                inputs.append(_input(label, name, value, kind="text", hint=hint))
            else:
                lo, hi = _BOUNDS.get(name, (0.0, None))
                inputs.append(_input(label, name, _plain(value), lo=lo, hi=hi,
                                     step="1" if kind == "int" else "any", hint=hint))
        sections.append(f"<h2>{_e(title)}</h2><div class=\"card\">"
                        f'<div class="fields">{"".join(inputs)}</div>'
                        f'{"".join(checks)}</div>')
    body = ('<h1>Settings</h1><p class="sub">These drive every calculation. The '
            "defaults are deliberately pessimistic; replace them with measured "
            "numbers as soon as you have them - assumed rates make every projection "
            f"optimistic. Saved to {_e(store.path)}.</p>"
            '<form method="post" action="/settings">' + _hidden("back", "/settings")
            + "".join(sections)
            + '<div class="actions"><button>Save settings</button></div></form>')
    return _layout(store, "Settings", body, "/settings", query)


def page_shop(store: Store, query: dict[str, str]) -> str | Response:
    """The customer-facing page as it will look, with a bar the file will not have."""
    product = store.product(query.get("id", ""))
    if product is None:
        return _not_found(store, "No such product. It may have been deleted.")
    page = storefront.build(product, store.config)
    issues = "".join(f"<li>{_e(issue)}</li>" for issue in page.issues)
    back = _url("/product", id=product.id)
    banner = (
        '<div style="background:#fab219;color:#0b0b0b;padding:10px 16px;'
        'font:13.5px/1.5 system-ui,-apple-system,sans-serif">'
        f'<b>Preview.</b> This bar is not in the file. <a href="{_e(back)}" '
        'style="color:inherit">Back to the product</a>'
        + (f'<ul style="margin:6px 0 0;padding-left:20px">{issues}</ul>'
           if issues else " Nothing left to fix.")
        + "</div>")
    return page.html.replace("<body>", "<body>" + banner, 1)


def page_dashboard(store: Store, query: dict[str, str]) -> str:
    return dashboard.render(store).replace(
        '<div class="wrap">',
        '<div class="wrap"><p class="sub"><a href="/">Back to today</a></p>', 1)


# --------------------------------------------------------------- actions --
#
# Each takes a freshly loaded store and the posted form, changes the store
# through the engine, saves, and redirects to the page that shows the result.
# A value the engine cannot use raises _Invalid before anything is saved.

def _product_from(store: Store, form: dict[str, str]) -> Product:
    product = store.product(_text(form, "id"))
    if product is None:
        raise _Invalid("That product no longer exists.")
    return product


def _test_from(store: Store, form: dict[str, str]) -> tuple[AdTest, Product]:
    test = store.test(_text(form, "id"))
    product = store.product(test.product_id) if test else None
    if test is None or product is None:
        raise _Invalid("That test no longer exists, or its product was deleted.")
    return test, product


def _order_from(store: Store, form: dict[str, str]) -> Order:
    order = store.order(_text(form, "id"))
    if order is None:
        raise _Invalid("That order no longer exists.")
    return order


def act_add_product(store: Store, form: dict[str, str]) -> Response:
    name = _text(form, "name")
    if not name:
        raise _Invalid("Give the product a name.")
    if not _text(form, "price") or not _text(form, "cogs"):
        raise _Invalid("Enter both the price and the supplier cost - without them "
                       "the economics are unknowable.")
    supplier = store.supplier(_text(form, "supplier"))
    scores = {key: _whole(form, key, label, 5, 0, 10)
              for label, key, _ in _RESEARCH_FIELDS}
    product = Product(
        name=name, sku=_text(form, "sku"), category=_text(form, "category"),
        supplier_id=supplier.id if supplier else "",
        price=_number(form, "price", "Price", 0.0),
        cogs=_number(form, "cogs", "Supplier cost", 0.0),
        ship_cost=_number(form, "ship_cost", "Shipping cost", 0.0),
        upsell_revenue=_number(form, "upsell_revenue", "Upsell revenue", 0.0),
        upsell_cogs=_number(form, "upsell_cogs", "Upsell cost", 0.0),
        delivery_days=_number(form, "delivery_days", "Delivery days", 14.0),
        local_stock=_flag(form, "local_stock"), restricted=_flag(form, "restricted"),
        brand_risk=_flag(form, "brand_risk"), notes=_text(form, "notes"), **scores)
    store.add(product)
    result = research.apply_score(product, store.config)
    store.save()
    return _redirect(_url("/product", id=product.id, msg=(
        f"Added and scored: {result.score:.0f}/100, tier {result.tier}. "
        f"{result.verdict}")))


def act_start_test(store: Store, form: dict[str, str]) -> Response:
    product = _product_from(store, form)
    config = store.config
    if store.active_test(product.id):
        raise _Invalid("This product already has a live test. Record its results "
                       "instead of starting another.")
    if research.score_product(product, config).blockers:
        raise _Invalid("Fix the blockers first - the research card lists each one.")
    hypothesis = _text(form, "hypothesis")
    if not hypothesis:
        raise _Invalid("Write the hypothesis first: what result would prove you wrong?")
    channel = _text(form, "channel") or "meta"
    if channel not in CHANNELS:
        raise _Invalid(f"Unknown channel '{channel}'. Pick one of: {', '.join(CHANNELS)}.")
    # Same test the CLI's `test plan --start` creates.
    plan = testing.plan_test(product.name, for_product(product, config), config)
    store.add(AdTest(product_id=product.id, channel=channel,
                     planned_budget=plan.total_budget, daily_budget=plan.daily_budget,
                     hypothesis=hypothesis, angle=_text(form, "angle")))
    product.status = "testing"
    store.save()
    return _redirect(_url("/product", id=product.id, msg=(
        f"Test started: {_money(plan.total_budget, config)} over {plan.days} days at "
        f"{_money(plan.daily_budget, config)}/day. Record the totals each evening.")))


def _decided(store: Store, test: AdTest, product: Product, prefix: str) -> Response:
    d = testing.decide(test, for_product(product, store.config), store.config)
    testing.apply_decision(test, product, d)
    store.save()
    verdict = d.action.replace("_", " ")
    return _redirect(_url("/product", id=product.id,
                          msg=f"{prefix} Verdict: {verdict}. {d.headline}"))


def act_record_results(store: Store, form: dict[str, str]) -> Response:
    test, product = _test_from(store, form)
    for label, name, money in _RESULT_FIELDS:
        parse = _number if money else _whole
        setattr(test, name, parse(form, name, label, getattr(test, name)))
    test.daily_budget = _number(form, "daily_budget", "Daily budget", test.daily_budget)
    return _decided(store, test, product, "Saved.")


def act_decide(store: Store, form: dict[str, str]) -> Response:
    test, product = _test_from(store, form)
    return _decided(store, test, product, "Recorded.")


def act_rescore(store: Store, form: dict[str, str]) -> Response:
    product = _product_from(store, form)
    result = research.apply_score(product, store.config)
    store.save()
    return _redirect(_url("/product", id=product.id, msg=(
        f"Scored {result.score:.0f}/100, tier {result.tier}. "
        f"Status: {product.status}.")))


def act_save_shop(store: Store, form: dict[str, str]) -> Response:
    product = _product_from(store, form)
    url = _text(form, "pay_url")
    if url and not url.startswith("https://"):
        raise _Invalid("A payment link must start with https:// - nobody should "
                       "type card details on an unencrypted page, and the browser "
                       "will say so on yours.")
    bundle = _text(form, "bundle_pay_url")
    if bundle and not bundle.startswith("https://"):
        raise _Invalid("The bundle's payment link must start with https:// too.")
    product.pay_url = url
    product.bundle_pay_url = bundle
    product.bundle_price = _number(form, "bundle_price", "Bundle price",
                                   product.bundle_price)
    product.copy_problem = _text(form, "copy_problem")
    product.copy_outcome = _text(form, "copy_outcome")
    product.updated = today_iso()
    store.save()
    return _redirect(_url("/product", id=product.id, msg=(
        f"Shop page saved. Buy button opens {url}" if url
        else "Shop page saved. It still has no payment link.")))


def act_delete_product(store: Store, form: dict[str, str]) -> Response:
    product = _product_from(store, form)
    store.remove(product)
    store.save()
    return _redirect(_url("/products", msg=(
        f"Deleted {product.name}. Its tests and orders are still in the store.")))


def act_update_order(store: Store, form: dict[str, str]) -> Response:
    order = _order_from(store, form)
    try:
        ops.update_order(order, status=_text(form, "status") or None,
                         tracking_number=form.get("tracking"), issue=form.get("issue"))
    except ValueError as exc:
        message = str(exc)
        raise _Invalid(message[:1].upper() + message[1:] + ".") from None
    store.save()
    status = order.status.replace("_", " ")
    return _redirect(_url("/orders", msg=f"{order.external_id or order.id} is now {status}."))


def act_review_sent(store: Store, form: dict[str, str]) -> Response:
    order = _order_from(store, form)
    ops.update_order(order, review_requested=True)
    store.save()
    return _redirect(_url("/orders", msg=(
        f"Logged the review request for {order.external_id or order.id}.")))


def act_save_settings(store: Store, form: dict[str, str]) -> Response:
    config = store.config
    types = {f.name: f.type for f in fields(Config)}
    changes = []
    for _, group in SETTINGS:
        for name, label, _ in group:
            old, kind = getattr(config, name), types[name]
            if kind == "bool":
                new = _flag(form, name)
            elif kind == "str":
                new = _text(form, name) or old
            else:
                lo, hi = _BOUNDS.get(name, (0.0, None))
                parse = _whole if kind == "int" else _number
                new = parse(form, name, label, old, lo, hi)
            if new != old:
                setattr(config, name, new)
                changes.append(f"{name} {old} -> {new}")
    if not changes:
        return _redirect(_url("/settings", msg="Nothing changed."))
    store.save()
    return _redirect(_url("/settings", msg=(
        "Saved: " + "; ".join(changes) + ". Every number now uses these.")))


def act_load_demo(store: Store, form: dict[str, str]) -> Response:
    if _has_records(store):
        raise _Invalid("The demo only loads into an empty store, and this one has "
                       "data. To explore it separately: dropship --store "
                       "data/store-demo.json demo, then dropship --store "
                       "data/store-demo.json ui --port 8766")
    seed(store)
    store.save()
    return _redirect(_url("/", msg="Loaded the demo store. Start at the top of the list."))


PAGES = {"/": page_today, "/products": page_products, "/product": page_product,
         "/orders": page_orders, "/settings": page_settings,
         "/dashboard": page_dashboard, "/shop": page_shop}
ACTIONS = {"/products/add": act_add_product, "/product/start": act_start_test,
           "/product/test": act_record_results, "/product/decide": act_decide,
           "/product/score": act_rescore, "/product/shop": act_save_shop,
           "/product/delete": act_delete_product, "/orders/update": act_update_order,
           "/orders/review": act_review_sent, "/settings": act_save_settings,
           "/demo": act_load_demo}


# ---------------------------------------------------------------- server --

class App:
    """Everything but the socket: routes a request to a page or an action.

    Kept apart from the HTTP handler so tests can drive it without a server.
    """

    def __init__(self, store_path: Path | str):
        self.store_path = Path(store_path)
        # One writer at a time, so two quick saves cannot interleave their
        # load-change-save and silently drop one of them.
        self._lock = threading.Lock()

    def handle(self, method: str, path: str, query: dict[str, str],
               form: dict[str, str]) -> Response:
        try:
            if path == "/favicon.ico":
                return Response(204)
            if method == "GET" and path in PAGES:
                result = PAGES[path](Store.load(self.store_path), query)
                return result if isinstance(result, Response) else Response(200, result)
            if method == "POST" and path in ACTIONS:
                with self._lock:
                    store = Store.load(self.store_path)
                    try:
                        return ACTIONS[path](store, form)
                    except _Invalid as exc:
                        return _redirect(_url(_back(form), err=str(exc)))
            return _not_found(Store.load(self.store_path), f"There is no page at {path}.")
        except json.JSONDecodeError as exc:
            backup = self.store_path.with_suffix(".bak.json")
            return Response(500, _bare_page(
                f"Could not read {self.store_path}: {exc}. Fix the file by hand, or "
                f"restore the backup that every save keeps: {backup}"))
        except Exception as exc:
            traceback.print_exc()
            return Response(500, _bare_page(
                f"{type(exc).__name__}: {exc}. The full traceback is in the terminal "
                "running dropship ui."))


def _first(parsed: dict[str, list[str]]) -> dict[str, str]:
    return {key: values[0] for key, values in parsed.items()}


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "dropship"
    MAX_FORM = 1_000_000

    def do_GET(self) -> None:
        self._serve("GET")

    def do_POST(self) -> None:
        self._serve("POST")

    def _serve(self, method: str) -> None:
        if self.headers.get("Host", "") not in self.server.hosts:
            # Another site pointing its own domain at 127.0.0.1 (DNS
            # rebinding) arrives with its own name in the Host header.
            self._send(Response(403, "Unexpected Host header."))
            return
        origin = self.headers.get("Origin")
        if method == "POST" and origin is not None and origin not in self.server.origins:
            # A form on some other web page, posting here while the UI runs.
            self._send(Response(403, "Cross-site form submission refused."))
            return
        url = urlsplit(self.path)
        form: dict[str, str] = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= self.MAX_FORM:
                self._send(Response(400, "Bad form length."))
                return
            raw = self.rfile.read(length).decode("utf-8", "replace")
            form = _first(parse_qs(raw, keep_blank_values=True))
        self._send(self.server.app.handle(method, url.path, _first(parse_qs(url.query)),
                                          form))

    def _send(self, response: Response) -> None:
        body = response.body.encode("utf-8")
        self.send_response(response.status)
        if response.location:
            self.send_header("Location", response.location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Pages with a delete button must not be framed by another site.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # a line per request buries the one that matters; errors print their own


class _Server(ThreadingHTTPServer):
    def __init__(self, port: int, app: App):
        super().__init__(("127.0.0.1", port), _Handler)
        self.app = app
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    def handle_error(self, request, client_address) -> None:
        # A browser dropping a connection mid-reply is routine, not an error.
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def make_server(store_path: Path | str, port: int = DEFAULT_PORT) -> _Server:
    """Bound to 127.0.0.1 only. Port 0 picks a free port."""
    return _Server(port, App(store_path))


def serve(store_path: Path | str, port: int = DEFAULT_PORT,
          open_browser: bool = True) -> None:
    path = Path(store_path).resolve()
    try:
        server = make_server(path, port)
    except OSError as exc:
        sys.exit(f"Could not listen on port {port} ({exc.strerror or exc}). If the UI "
                 f"is already running, open http://127.0.0.1:{port}/ - otherwise pick "
                 f"another port: dropship ui --port {port + 1}")
    url = f"http://127.0.0.1:{server.server_port}/"
    state = "" if path.exists() else " (new - created on the first save)"
    # Flushed: serve_forever() blocks, and a piped stdout would hold these back.
    print(f"Data: {path}{state}", flush=True)
    print(f"Open: {url}   this machine only, no login. Ctrl+C stops it.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
