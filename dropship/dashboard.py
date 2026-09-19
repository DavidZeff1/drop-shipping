"""Single-file HTML dashboard.

Self-contained: no CDN, no build step, no network. Open the file and it works,
including on a phone.

Charts follow one rule that matters more than the styling: every number comes
with the threshold it should be compared against. A ROAS of 2.1x means nothing
on its own; 2.1x against a breakeven of 2.4x means stop spending.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from . import cashflow, daily, kpis, ops
from .economics import for_product
from .store import Store

# Palette slots, validated for both modes (lightness band, chroma floor, CVD
# separation, normal-vision floor, contrast).
_CSS = """
:root {
  color-scheme: light dark;
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --hairline: rgba(11,11,11,0.10);
  --pos: #2a78d6; --neg: #e34948;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --hairline: rgba(255,255,255,0.10);
    --pos: #3987e5; --neg: #e66767;
  }
}
:root[data-theme="dark"] {
  --surface-1: #1a1a19; --page: #0d0d0d;
  --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --hairline: rgba(255,255,255,0.10);
  --pos: #3987e5; --neg: #e66767;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink-1);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 32px 16px 80px; }
header { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
  justify-content: space-between; margin-bottom: 8px; }
h1 { font-size: 22px; margin: 0; letter-spacing: -0.01em; }
h2 { font-size: 15px; margin: 34px 0 12px; color: var(--ink-2);
  text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.sub { color: var(--ink-muted); font-size: 13px; }
.card { background: var(--surface-1); border: 1px solid var(--hairline);
  border-radius: 12px; padding: 20px; }
.hero { margin-top: 18px; }
.hero .figure { font-size: 48px; line-height: 1.05; font-weight: 650;
  letter-spacing: -0.02em; }
.hero .label { color: var(--ink-2); font-size: 13px; margin-bottom: 4px; }
.pos { color: var(--pos); } .neg { color: var(--neg); }
.tiles { display: grid; gap: 12px; margin-top: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.tile .label { color: var(--ink-2); font-size: 12px; }
.tile .value { font-size: 26px; font-weight: 600; letter-spacing: -0.01em;
  margin-top: 2px; }
.tile .note { color: var(--ink-muted); font-size: 12px; margin-top: 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  font-weight: 600; padding: 2px 9px; border-radius: 99px;
  border: 1px solid var(--hairline); white-space: nowrap; }
.chip .dot { width: 8px; height: 8px; border-radius: 99px; flex: none; }
.chip.good .dot { background: var(--good); }
.chip.warning .dot { background: var(--warning); }
.chip.serious .dot { background: var(--serious); }
.chip.critical .dot { background: var(--critical); }
.chip.info .dot { background: var(--ink-muted); }
ul.items { list-style: none; padding: 0; margin: 0; }
ul.items li { padding: 14px 0; border-top: 1px solid var(--hairline); }
ul.items li:first-child { border-top: 0; }
.item-head { display: flex; gap: 10px; align-items: center;
  flex-wrap: wrap; margin-bottom: 4px; }
.item-title { font-weight: 600; }
.item-detail { color: var(--ink-2); font-size: 14px; }
.item-action { font-size: 14px; margin-top: 6px; }
.item-action b { font-weight: 600; }
code { background: var(--page); border: 1px solid var(--hairline);
  border-radius: 5px; padding: 1px 6px; font-size: 12.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px;
  font-variant-numeric: tabular-nums; }
th { text-align: right; color: var(--ink-muted); font-weight: 600;
  font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 0 0 8px; border-bottom: 1px solid var(--axis); }
th:first-child, td:first-child { text-align: left; }
td { padding: 9px 0; border-bottom: 1px solid var(--hairline); text-align: right; }
tr:last-child td { border-bottom: 0; }
.scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.scroll table { min-width: 620px; }
figure { margin: 0; }
figcaption { color: var(--ink-2); font-size: 13px; margin-bottom: 14px; }
figcaption b { color: var(--ink-1); }
svg { display: block; width: 100%; height: auto; overflow: visible; }
.grid-line { stroke: var(--grid); stroke-width: 1; }
.axis-line { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--ink-muted); font-size: 11px; }
.dlabel { fill: var(--ink-2); font-size: 11.5px; font-weight: 600; }
.series-line { fill: none; stroke: var(--pos); stroke-width: 2;
  stroke-linejoin: round; stroke-linecap: round; }
.end-dot { fill: var(--pos); stroke: var(--surface-1); stroke-width: 2; }
.hit { fill: transparent; cursor: crosshair; }
.crosshair { stroke: var(--axis); stroke-width: 1; stroke-dasharray: 3 3;
  opacity: 0; pointer-events: none; }
.tip { position: fixed; z-index: 20; pointer-events: none; opacity: 0;
  transition: opacity .1s; background: var(--surface-1); color: var(--ink-1);
  border: 1px solid var(--hairline); border-radius: 8px; padding: 8px 11px;
  font-size: 12.5px; box-shadow: 0 6px 20px rgba(0,0,0,.14); max-width: 240px; }
.tip b { display: block; font-size: 13px; margin-bottom: 2px; }
details { margin-top: 14px; }
summary { cursor: pointer; color: var(--ink-muted); font-size: 12.5px;
  user-select: none; }
.empty { color: var(--ink-muted); font-size: 14px; padding: 8px 0; }
footer { margin-top: 48px; color: var(--ink-muted); font-size: 12px;
  border-top: 1px solid var(--hairline); padding-top: 16px; }
@media (max-width: 560px) {
  .wrap { padding: 20px 16px 60px; }
  .hero .figure { font-size: 38px; }
}
"""

_JS = """
(function () {
  var tip = document.createElement('div');
  tip.className = 'tip';
  document.body.appendChild(tip);

  function show(evt, html) {
    tip.innerHTML = html;
    tip.style.opacity = '1';
    var r = tip.getBoundingClientRect();
    var x = evt.clientX + 14, y = evt.clientY - r.height - 10;
    if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - 14;
    if (y < 8) y = evt.clientY + 18;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  function hide() { tip.style.opacity = '0'; }

  document.querySelectorAll('[data-tip]').forEach(function (el) {
    el.addEventListener('pointerenter', function (e) { show(e, el.dataset.tip); });
    el.addEventListener('pointermove', function (e) { show(e, el.dataset.tip); });
    el.addEventListener('pointerleave', hide);
  });

  document.querySelectorAll('svg[data-series]').forEach(function (svg) {
    var pts = JSON.parse(svg.dataset.series);
    var hair = svg.querySelector('.crosshair');
    var hit = svg.querySelector('.hit');
    if (!pts.length || !hit) return;
    hit.addEventListener('pointermove', function (e) {
      var box = svg.getBoundingClientRect();
      var scale = svg.viewBox.baseVal.width / box.width;
      var mx = (e.clientX - box.left) * scale;
      var best = pts[0], dist = Infinity;
      pts.forEach(function (p) {
        var d = Math.abs(p.x - mx);
        if (d < dist) { dist = d; best = p; }
      });
      if (hair) {
        hair.setAttribute('x1', best.x);
        hair.setAttribute('x2', best.x);
        hair.style.opacity = '1';
      }
      show(e, best.t);
    });
    hit.addEventListener('pointerleave', function () {
      if (hair) hair.style.opacity = '0';
      hide();
    });
  });
})();
"""


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _money(value: float, currency: str = "") -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{currency}{abs(value):,.0f}"


def _hbar(x0: float, y: float, width: float, height: float,
          positive: bool, radius: float = 4.0) -> str:
    """Bar with a rounded data-end and a square baseline end."""
    w = abs(width)
    r = max(0.0, min(radius, w, height / 2))
    if positive:
        x1 = x0 + w
        return (f"M{x0},{y} H{x1 - r} Q{x1},{y} {x1},{y + r} "
                f"V{y + height - r} Q{x1},{y + height} {x1 - r},{y + height} "
                f"H{x0} Z")
    x1 = x0 - w
    return (f"M{x0},{y} H{x1 + r} Q{x1},{y} {x1},{y + r} "
            f"V{y + height - r} Q{x1},{y + height} {x1 + r},{y + height} "
            f"H{x0} Z")


def _nice_ticks(lo: float, hi: float, count: int = 4) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / count
    mag = 10 ** (len(str(int(abs(raw)))) - 1) if abs(raw) >= 1 else 1
    step = max(mag, round(raw / mag) * mag)
    start = (lo // step) * step
    ticks, value = [], start
    while value <= hi + step * 0.5:
        ticks.append(value)
        value += step
    return ticks


# ------------------------------------------------------------ cash chart --

def _cash_chart(rows: list, currency: str) -> str:
    """Projected cash balance. One series, so the title names it - no legend."""
    if len(rows) < 2:
        return '<p class="empty">Not enough data to project cash.</p>'

    W, H = 720, 240
    pad_l, pad_r, pad_t, pad_b = 56, 26, 16, 28
    plot_w, plot_h = W - pad_l - pad_r, H - pad_t - pad_b

    values = [r.balance for r in rows]
    lo, hi = min(values + [0.0]), max(values)
    span = (hi - lo) or 1.0
    lo -= span * 0.08
    hi += span * 0.08
    span = hi - lo

    def px(day: int) -> float:
        return pad_l + (day - 1) / max(1, len(rows) - 1) * plot_w

    def py(value: float) -> float:
        return pad_t + (hi - value) / span * plot_h

    points = [(px(r.day), py(r.balance)) for r in rows]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)

    parts = [
        f'<svg viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Projected cash balance by day" data-series=\'%SERIES%\'>'
    ]
    for tick in _nice_ticks(lo, hi, 4):
        y = py(tick)
        if not (pad_t - 1 <= y <= pad_t + plot_h + 1):
            continue
        parts.append(f'<line class="grid-line" x1="{pad_l}" y1="{y:.1f}" '
                     f'x2="{pad_l + plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{pad_l - 8}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{_money(tick, currency)}</text>')

    if lo < 0 < hi:
        y0 = py(0.0)
        parts.append(f'<line class="axis-line" x1="{pad_l}" y1="{y0:.1f}" '
                     f'x2="{pad_l + plot_w}" y2="{y0:.1f}" '
                     f'stroke="var(--neg)" stroke-dasharray="4 3"/>')
        parts.append(f'<text class="tick" x="{pad_l + plot_w}" y="{y0 - 6:.1f}" '
                     f'text-anchor="end" fill="var(--neg)">insolvent below here</text>')

    for day in (1, len(rows) // 2, len(rows)):
        parts.append(f'<text class="tick" x="{px(day):.1f}" '
                     f'y="{pad_t + plot_h + 18}" text-anchor="middle">day {day}</text>')

    parts.append(f'<path class="series-line" d="{path}"/>')
    ex, ey = points[-1]
    parts.append(f'<circle class="end-dot" cx="{ex:.1f}" cy="{ey:.1f}" r="4.5"/>')
    parts.append(f'<text class="dlabel" x="{ex - 8:.1f}" y="{ey - 12:.1f}" '
                 f'text-anchor="end">{_money(values[-1], currency)}</text>')
    parts.append(f'<line class="crosshair" x1="0" y1="{pad_t}" x2="0" '
                 f'y2="{pad_t + plot_h}"/>')
    parts.append(f'<rect class="hit" x="{pad_l}" y="{pad_t}" width="{plot_w}" '
                 f'height="{plot_h}"/>')
    parts.append("</svg>")

    series = [
        {"x": round(px(r.day), 1),
         "t": f"<b>Day {r.day}</b>Balance {_money(r.balance, currency)}<br>"
              f"In {_money(r.cash_in + r.reserve_released, currency)} · "
              f"Out {_money(r.cash_out, currency)}"}
        for r in rows
    ]
    return "".join(parts).replace("%SERIES%", _e(json.dumps(series)))


# --------------------------------------------------------- profit chart --

def _profit_chart(rows: list[dict], currency: str) -> str:
    """Profit per product. Polarity, so a diverging pair around a zero baseline."""
    rows = [r for r in rows if r["spend"] > 0 or r["orders"] > 0][:10]
    if not rows:
        return '<p class="empty">No product has spend or orders yet.</p>'

    bar_h, gap = 22, 16
    W = 720
    pad_l, pad_r, pad_t, pad_b = 160, 24, 8, 10
    H = pad_t + len(rows) * (bar_h + gap) + pad_b
    plot_w = W - pad_l - pad_r

    values = [r["profit"] for r in rows]
    extent = max(abs(min(values + [0.0])), abs(max(values + [0.0]))) or 1.0
    zero_x = pad_l + plot_w / 2
    # Hold back room for the direct label so it never lands on the name gutter.
    label_room = 60
    half = max(20.0, plot_w / 2 - label_room)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="Profit and loss by product">']
    parts.append(f'<line class="axis-line" x1="{zero_x}" y1="{pad_t}" '
                 f'x2="{zero_x}" y2="{H - pad_b}"/>')

    for i, row in enumerate(rows):
        y = pad_t + i * (bar_h + gap)
        profit = row["profit"]
        width = abs(profit) / extent * half
        positive = profit >= 0
        colour = "var(--pos)" if positive else "var(--neg)"
        # 2px surface gap keeps the bar clear of the baseline rule.
        x0 = zero_x + (1 if positive else -1)
        tip = (f"<b>{_e(row['name'])}</b>"
               f"{'Profit' if positive else 'Loss'} {_money(abs(profit), currency)}<br>"
               f"{row['orders']} orders · spend {_money(row['spend'], currency)}<br>"
               f"ROAS {row['roas']:.2f}x vs breakeven {row['be_roas']:.2f}x")
        parts.append(
            f'<path d="{_hbar(x0, y, width, bar_h, positive)}" fill="{colour}" '
            f'data-tip="{_e(tip)}"><title>{_e(row["name"])}: '
            f'{_money(profit, currency)}</title></path>')
        parts.append(f'<text class="tick" x="{pad_l - 16}" y="{y + bar_h / 2 + 4:.0f}" '
                     f'text-anchor="end">{_e(row["name"][:20])}</text>')
        lx = x0 + (width + 8) * (1 if positive else -1)
        parts.append(f'<text class="dlabel" x="{lx:.0f}" y="{y + bar_h / 2 + 4:.0f}" '
                     f'text-anchor="{"start" if positive else "end"}">'
                     f'{_money(profit, currency)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                   for r in rows)
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


# ------------------------------------------------------------- rendering --

def render(store: Store, days: int = 90, today: date | None = None) -> str:
    today = today or date.today()
    config = store.config
    cur = {"USD": "$", "GBP": "£", "EUR": "€"}.get(config.currency, "")

    brief = daily.build(store, today)
    report = kpis.build(store.products, store.orders, store.tests, store.ledger,
                        config, 30, today)
    rows = daily.portfolio(store)
    queue = ops.action_queue(store.orders, config, today)

    # Cash projection from the live position, current spend and blended CPA.
    live_spend = sum(t.daily_budget for t in store.tests if not t.ended)
    cpa = report.blended_cac or 0.0
    cash_rows: list = []
    cash_note = ""
    if store.products:
        ue = for_product(
            max(store.products, key=lambda p: p.price), config)
        if not cpa:
            cpa = ue.target_cpa() or ue.breakeven_cpa
        if not live_spend:
            live_spend = cashflow.max_safe_daily_spend(
                ue, config, cpa, days, report.cash_position) * 0.5
            cash_note = " Projected at half your safe maximum, since no live budget is set."
        if live_spend > 0 and cpa > 0:
            sim = cashflow.simulate(ue, config, live_spend, cpa, days,
                                    report.cash_position)
            cash_rows = sim.rows

    profit_class = "pos" if report.net_profit >= 0 else "neg"
    roas_ok = report.blended_roas >= report.breakeven_roas and report.breakeven_roas > 0

    out: list[str] = []
    out.append(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(config.business_name)} - Operating Dashboard</title>
<style>{_CSS}</style></head><body><div class="wrap">
<header>
  <div><h1>{_e(config.business_name)}</h1>
    <div class="sub">Operating dashboard &middot; {today.isoformat()}</div></div>
  <div class="sub">{len(store.products)} products &middot;
    {len(store.orders)} orders &middot; {len(queue)} open actions</div>
</header>
<div class="card hero">
  <div class="label">Net profit, last 30 days</div>
  <div class="figure {profit_class}">{_money(report.net_profit, cur)}</div>
  <div class="sub">{_e(brief.headline)}</div>
</div>""")

    tiles = [
        ("Revenue (30d)", _money(report.revenue, cur), f"{report.orders} orders"),
        ("Blended ROAS", f"{report.blended_roas:.2f}x",
         f"breakeven {report.breakeven_roas:.2f}x - "
         f"{'above' if roas_ok else 'BELOW'}"),
        ("Blended CAC", _money(report.blended_cac, cur),
         f"ad spend {_money(report.ad_spend, cur)}"),
        ("Cash position", _money(report.cash_position, cur),
         f"{report.cash_position / max(1.0, config.fixed_monthly_costs):.1f} "
         f"months of fixed costs"),
        ("Refund rate", f"{report.refund_rate * 100:.1f}%",
         f"assumed {config.refund_rate * 100:.1f}%"),
        ("Chargeback rate", f"{report.chargeback_rate * 100:.2f}%",
         "1% is the processor danger line"),
    ]
    out.append('<div class="tiles">')
    for label, value, note in tiles:
        out.append(f'<div class="card tile"><div class="label">{_e(label)}</div>'
                   f'<div class="value">{_e(value)}</div>'
                   f'<div class="note">{_e(note)}</div></div>')
    out.append("</div>")

    # -- alerts
    out.append("<h2>What needs attention</h2><div class='card'><ul class='items'>")
    if brief.items:
        for item in brief.items[:12]:
            sev = {1: "critical", 2: "serious", 3: "warning"}.get(item.priority, "info")
            cmd = f" <code>{_e(item.command)}</code>" if item.command else ""
            out.append(
                f'<li><div class="item-head">'
                f'<span class="chip {sev}"><span class="dot"></span>{sev}</span>'
                f'<span class="item-title">{_e(item.title)}</span>'
                f'<span class="sub">{_e(item.area)}</span></div>'
                f'<div class="item-detail">{_e(item.detail)}</div>'
                f'<div class="item-action"><b>Do:</b> {_e(item.action)}{cmd}</div></li>')
    else:
        out.append('<li class="empty">Nothing outstanding.</li>')
    out.append("</ul></div>")

    # -- cash
    out.append("<h2>Cash projection</h2><div class='card'><figure>")
    if cash_rows:
        sim_min = min(r.balance for r in cash_rows)
        out.append(
            f'<figcaption>Balance over the next {days} days at '
            f'<b>{_money(live_spend, cur)}/day</b> ad spend and a '
            f'<b>{_money(cpa, cur)}</b> CPA, with your '
            f'{config.payout_delay_days}-day payout delay. Low point '
            f'<b>{_money(sim_min, cur)}</b>.{cash_note}</figcaption>')
        out.append(_cash_chart(cash_rows, cur))
        step = max(1, len(cash_rows) // 12)
        out.append("<details><summary>View as table</summary>" + _table(
            ["Day", "Orders", "Cash in", "Cash out", "Balance"],
            [[str(r.day), f"{r.orders:.1f}", _money(r.cash_in + r.reserve_released, cur),
              _money(r.cash_out, cur), _money(r.balance, cur)]
             for r in cash_rows[::step]]) + "</details>")
    else:
        out.append('<p class="empty">Add a product and a live test budget to '
                   'project cash.</p>')
    out.append("</figure></div>")

    # -- profit by product
    out.append("<h2>Profit by product</h2><div class='card'><figure>")
    out.append('<figcaption>Contribution margin earned minus ad spend. '
               'Blue is profit, red is loss.</figcaption>')
    out.append(_profit_chart(rows, cur))
    out.append("<details><summary>View as table</summary>" + _table(
        ["Product", "Status", "Orders", "Spend", "Revenue", "ROAS",
         "Breakeven", "Profit"],
        [[_e(r["name"]), _e(r["status"]), str(r["orders"]),
          _money(r["spend"], cur), _money(r["revenue"], cur),
          f"{r['roas']:.2f}x", f"{r['be_roas']:.2f}x",
          f'<span class="{"pos" if r["profit"] >= 0 else "neg"}">'
          f'{_money(r["profit"], cur)}</span>']
         for r in rows]) + "</details>")
    out.append("</figure></div>")

    # -- portfolio economics
    out.append("<h2>Unit economics</h2><div class='card'>")
    out.append(_table(
        ["Product", "Price", "Margin", "CM", "Breakeven CPA", "Breakeven ROAS",
         "Score", "Verdict"],
        [[_e(r["name"]), _money(r["price"], cur),
          f'{r["margin_multiple"]:.2f}x' if r["margin_multiple"] else "-",
          _money(r["cm"], cur), _money(r["be_cpa"], cur),
          f"{r['be_roas']:.2f}x", f"{r['score']:.0f} {_e(r['tier'])}",
          _e(r["verdict"] or "-")]
         for r in rows]) if rows else '<p class="empty">No products yet.</p>')
    out.append("</div>")

    # -- order queue
    out.append("<h2>Order action queue</h2><div class='card'>")
    if queue:
        out.append(_table(
            ["Order", "Severity", "Issue", "Age", "Value", "Do this"],
            [[_e(a.external_id),
              f'<span class="chip {a.severity if a.severity in ("critical","warning") else "serious"}">'
              f'<span class="dot"></span>{_e(a.severity)}</span>',
              _e(a.issue), f"{a.age_days}d", _money(a.value, cur), _e(a.do_this)]
             for a in queue[:25]]))
    else:
        out.append('<p class="empty">No orders need attention.</p>')
    out.append("</div>")

    out.append(f"""<footer>
Generated by <code>dropship dashboard</code> on {today.isoformat()}.
Figures use your configured refund rate ({config.refund_rate * 100:.1f}%),
chargeback rate ({config.chargeback_rate * 100:.2f}%) and
{config.payout_delay_days}-day payout delay. Measure these from your own
orders as soon as you have 50 - assumed rates make every number here
optimistic.
</footer></div><script>{_JS}</script></body></html>""")
    return "".join(out)


def write(store: Store, path: Path | str = "dashboard.html", days: int = 90,
          today: date | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(store, days, today), encoding="utf-8")
    return target
