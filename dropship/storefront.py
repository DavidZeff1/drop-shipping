"""A shop page you can actually put online.

    dropship storefront "Pet Hair" --image photo.jpg --pay https://buy.stripe.com/...

One self-contained HTML file per product: photos, price, an honest delivery
estimate, the listing copy from `listings.py`, questions, policies, and a buy
button pointing at whatever payment link you already have - a Stripe payment
link, a PayPal button, a Shopify buy link. No build step, no framework, no
fonts, no tracking scripts, nothing to install. Open the file, or drop it on
any static host.

Money never passes through this file. The processor's own page takes the card,
which is what keeps the compliance burden theirs; orders come back as their
CSV export and go in with `dropship import orders`.

Three things the page does on purpose, because each is what turns a sale into
a dispute:

  * Every {slot} the copy leaves for you stays visible and highlighted, and the
    command lists what is unfilled rather than letting you publish it.
  * The delivery estimate, the returns policy and a contact address sit on the
    page, not behind checkout.
  * There is no invented review count, no fake scarcity and no countdown. They
    lift conversion and lift chargebacks faster, and a fabricated review is the
    first thing a card network looks at.

Light mode only: unlike the operator dashboard, a shop page is a shop window,
and photos shot on white do not survive an inverted palette.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import listings, research
from .economics import for_product
from .models import Config, Product

# Tokens from the dashboard's validated light palette. The buy button is ink on
# surface (19:1); white on a green button is only 3.4:1 and fails at this size.
_CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --hairline: rgba(11,11,11,0.12); --slot: #fab219;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink-1);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-text-size-adjust: 100%; }
img { max-width: 100%; display: block; }
a { color: inherit; }
.bar { display: flex; flex-wrap: wrap; gap: 4px 16px; justify-content: space-between;
  align-items: baseline; padding: 14px 20px; border-bottom: 1px solid var(--hairline);
  background: var(--surface); }
.brand { font-weight: 650; letter-spacing: -0.01em; }
.bar .ship { color: var(--ink-2); font-size: 14px; }
main { max-width: 760px; margin: 0 auto; padding: 24px 20px 90px; }
section + section { margin-top: 40px; }
h1 { font-size: 30px; line-height: 1.2; letter-spacing: -0.02em; margin: 0 0 8px; }
h2 { font-size: 20px; letter-spacing: -0.01em; margin: 0 0 12px; }
h3 { font-size: 16px; margin: 20px 0 6px; }
p { margin: 10px 0; }
.sub { color: var(--ink-2); font-size: 17px; margin: 0 0 18px; }
.photos { display: grid; gap: 10px; grid-template-columns: repeat(3, 1fr); }
.photos figure { margin: 0; }
.photos figure:first-child { grid-column: 1 / -1; }
.photos img, .ph { border-radius: 12px; border: 1px solid var(--hairline);
  background: var(--surface); width: 100%; }
.ph { aspect-ratio: 4 / 3; display: flex; align-items: center; justify-content: center;
  text-align: center; padding: 14px; color: var(--ink-2); font-size: 13px; }
.buybox { margin-top: 26px; }
.price { font-size: 26px; font-weight: 650; margin: 0 0 4px; }
.price .note { font-size: 14px; font-weight: 400; color: var(--ink-2); }
.buy { display: block; text-align: center; text-decoration: none; font-weight: 650;
  font-size: 17px; padding: 16px 20px; border-radius: 12px; margin: 18px 0 10px;
  background: var(--ink-1); color: var(--surface); }
.buy.off { background: var(--surface); color: var(--ink-2);
  border: 1px dashed var(--ink-muted); }
.fine { color: var(--ink-2); font-size: 13.5px; margin: 0; }
ul.trust { list-style: none; margin: 14px 0; padding: 0; display: grid; gap: 6px; }
ul.trust li { padding-left: 22px; position: relative; font-size: 14.5px;
  color: var(--ink-2); }
ul.trust li::before { content: "✓"; position: absolute; left: 0; color: var(--ink-1); }
ul.sell { margin: 0; padding-left: 22px; }
ul.sell li { margin: 8px 0; }
details { border-top: 1px solid var(--hairline); padding: 12px 0; }
details:last-of-type { border-bottom: 1px solid var(--hairline); }
summary { cursor: pointer; font-weight: 600; }
details p { margin: 8px 0 0; color: var(--ink-2); }
.card { background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; padding: 18px 20px; }
mark.slot { background: var(--slot); color: #0b0b0b; padding: 0 4px;
  border-radius: 4px; font-size: 0.95em; }
footer { border-top: 1px solid var(--hairline); margin-top: 48px; padding: 20px;
  color: var(--ink-2); font-size: 13.5px; text-align: center; }
.sticky { position: fixed; left: 0; right: 0; bottom: 0; display: none;
  gap: 12px; align-items: center; padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: var(--surface); border-top: 1px solid var(--hairline); }
.sticky .price { font-size: 18px; margin: 0; }
.sticky .buy { margin: 0; flex: 1; padding: 13px 18px; }
@media (max-width: 640px) {
  h1 { font-size: 25px; }
  .photos { grid-template-columns: repeat(2, 1fr); }
  .sticky { display: flex; }
}
"""

_SLOT = re.compile(r"\{[^{}]{1,200}\}")
_MAX_PHOTO = 300_000          # bytes; above this a phone on 4G feels it
_MAX_PAGE = 2_000_000


@dataclass
class Page:
    """A rendered shop page and everything still standing between it and live."""

    html: str = ""
    issues: list[str] = field(default_factory=list)   # each names its own fix
    slots: int = 0

    @property
    def size(self) -> int:
        return len(self.html.encode("utf-8"))

    @property
    def publishable(self) -> bool:
        return not self.issues


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _money(value: float, config: Config) -> str:
    sym = {"USD": "$", "GBP": "£", "EUR": "€"}.get(config.currency, "")
    return f"{sym}{value:,.2f}"


def _copy(text: str) -> str:
    """Escape, then make every unfilled {slot} impossible to miss."""
    return _SLOT.sub(lambda m: f'<mark class="slot">{m.group(0)}</mark>', _e(text))


def _prose(text: str, title: str = "") -> str:
    """The listing description's headings and paragraphs, as HTML.

    A heading the page has already said as its title is dropped rather than
    repeated - the copy generator writes the outcome in both places.
    """
    out, paragraph = [], []

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            out.append(f"<h3>{_copy(line[4:])}</h3>")
        elif line.startswith("## "):
            flush()
            if line[3:].strip().lower() not in title.lower():
                out.append(f"<h2>{_copy(line[3:])}</h2>")
        else:
            paragraph.append(_copy(line))
    flush()
    return "".join(out)


def _slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-") or "shop"


def _photos(product: Product, issues: list[str]) -> str:
    """Photos embedded in the file, so nothing can break on the way to a host."""
    if not product.photos:
        issues.append(
            "No photos. A product page without them does not convert, whatever "
            "the copy says. Add three or more: dropship storefront "
            f"\"{product.name}\" --image shot1.jpg --image shot2.jpg")
        wants = ["the product doing its job, in one frame",
                 "scale and detail - a hand, a desk, something familiar",
                 "exactly what arrives in the box"]
        return "".join(
            f'<figure><div class="ph">Photo {i}<br>{_e(want)}</div></figure>'
            for i, want in enumerate(wants, 1))

    figures = []
    for i, source in enumerate(product.photos, 1):
        alt = _e(f"{product.name} - photo {i}")
        if source.startswith(("http://", "https://")):
            if source.startswith("http://"):
                issues.append(f"Photo {i} loads over http, which browsers flag on "
                              f"a checkout page. Use the https address.")
            figures.append(f'<figure><img src="{_e(source)}" alt="{alt}" '
                           f'loading="lazy"></figure>')
            continue
        path = Path(source)
        kind, _ = mimetypes.guess_type(path.name)
        if not path.is_file():
            issues.append(f"Photo not found: {path}. Fix the path and re-run with "
                          f"--image {path}")
            figures.append(f'<figure><div class="ph">Missing: {_e(path)}</div></figure>')
            continue
        if not (kind or "").startswith("image/"):
            issues.append(f"{path} is not an image the browser will show. Use a "
                          f"jpg, png or webp.")
            continue
        raw = path.read_bytes()
        if len(raw) > _MAX_PHOTO:
            issues.append(
                f"{path.name} is {len(raw) / 1024:.0f} KB. Compress it under "
                f"{_MAX_PHOTO // 1000} KB - the page has to load in 2.5s on 4G, "
                f"and a slow page is the most expensive leak on this list.")
        data = base64.b64encode(raw).decode("ascii")
        figures.append(f'<figure><img src="data:{kind};base64,{data}" alt="{alt}" '
                       f'loading="lazy"></figure>')
    return "".join(figures)


def _buy(product: Product, config: Config, issues: list[str], sticky: bool = False) -> str:
    label = f"Buy now - {_money(product.price, config)}"
    if not product.pay_url:
        if not sticky:
            issues.append(
                "No payment link, so the buy button goes nowhere. Create a Stripe "
                "payment link or a PayPal button for this product, then: dropship "
                f"storefront \"{product.name}\" --pay https://...")
        return '<span class="buy off" aria-disabled="true">Payment link not set</span>'
    if not product.pay_url.startswith("https://") and not sticky:
        issues.append(
            "The payment link is not https. Nobody should type card details on an "
            "unencrypted page, and browsers say so loudly. Use the https link your "
            "processor gives you.")
    return f'<a class="buy" href="{_e(product.pay_url)}">{_e(label)}</a>'


def build(product: Product, config: Config, problem: str = "",
          outcome: str = "") -> Page:
    """Render the page and collect everything still between it and going live.

    ``problem`` and ``outcome`` fall back to whatever is stored on the product,
    so the preview and the written file say the same thing.
    """
    ue = for_product(product, config)
    listing = listings.generate(product, ue, problem or product.copy_problem,
                                outcome or product.copy_outcome)
    issues: list[str] = []

    blockers = research.score_product(product, config).blockers
    if blockers:
        issues.append(f"This product fails a research gate: {blockers[0]} A shop "
                      f"page cannot fix that.")

    days = f"{product.delivery_days:.0f}"
    title = listing.titles[0]
    photos = _photos(product, issues)
    buy = _buy(product, config, issues)

    trust = [f"Delivery included, arrives in about {days} days",
             "Tracking emailed the moment it ships",
             "{your returns window, e.g. 30 days, and who pays return postage}",
             "{how fast you answer support, e.g. within 24 hours}"]

    faq = "".join(
        f"<details><summary>{_copy(q)}</summary><p>{_copy(a)}</p></details>"
        for q, a in listing.faq)

    policies = [
        ("Delivery", f"Orders leave the warehouse within {{your handling time, "
                     f"e.g. 2 business days}} and arrive in about {days} days. "
                     f"Every order gets a tracking link by email."),
        ("Returns and refunds", "{Your returns window, who pays return postage, "
                                "and how long a refund takes. State it plainly: "
                                "vagueness here is what a bank reads as a red flag.}"),
        ("Contact", "{your support email} - we answer within {your response time}. "
                    "{Your business name and registered address, if you have one.}"),
    ]

    body = f"""<header class="bar"><span class="brand">{_e(config.business_name)}</span>
<span class="ship">Delivery included &middot; arrives in about {days} days</span></header>
<main>
<section class="hero">
  <div class="photos">{photos}</div>
  <div class="buybox">
    <h1>{_copy(title)}</h1>
    <p class="sub">{_copy(listing.subtitle)}</p>
    <p class="price">{_e(_money(product.price, config))}
      <span class="note">delivery included</span></p>
    <ul class="trust">{"".join(f"<li>{_copy(t)}</li>" for t in trust)}</ul>
    {buy}
    <p class="fine">Secure checkout on {_e(_processor(product))}. Your card
      details never touch this page.</p>
  </div>
</section>
<section><h2>Why this one</h2>
  <ul class="sell">{"".join(f"<li>{_copy(b)}</li>" for b in listing.bullets)}</ul>
</section>
<section>{_prose(listing.description, title)}</section>
<section><h2>Reviews</h2><div class="card">
  <p>{_copy("{Paste your real reviews here, with photos where you have them. "
            "Invent none: fabricated reviews are illegal, and they are the first "
            "thing a card network checks in a dispute.}")}</p></div>
</section>
<section><h2>Questions</h2>{faq}</section>
<section id="policies"><h2>Delivery, returns and contact</h2>
  {"".join(f"<h3>{_e(h)}</h3><p>{_copy(t)}</p>" for h, t in policies)}
</section>
</main>
<footer>{_e(config.business_name)} &middot; <a href="#policies">Delivery, returns
and contact</a></footer>
<div class="sticky"><span class="price">{_e(_money(product.price, config))}</span>
{_buy(product, config, issues, sticky=True)}</div>"""

    page = Page(html=f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(listing.subtitle)}">
<style>{_CSS}</style></head><body>
{body}
</body></html>""", issues=issues)

    # Counted on the body alone: the stylesheet is full of braces that are not slots.
    page.slots = len(_SLOT.findall(body))
    if page.slots:
        issues.append(
            f"{page.slots} slots are still in braces and highlighted on the page. "
            f"Open the file in any text editor and replace each one - an unfilled "
            f"{{slot}} is the fastest way to look like a scam.")
    if page.size > _MAX_PAGE:
        issues.append(f"The page is {page.size / 1_000_000:.1f} MB. Compress the "
                      f"photos; on 4G this is several seconds of blank screen.")
    return page


def _processor(product: Product) -> str:
    """Name the checkout the buy button hands over to, from its link."""
    url = product.pay_url
    for host, name in (("stripe.com", "Stripe"), ("paypal.", "PayPal"),
                       ("shopify.com", "Shopify"), ("square", "Square"),
                       ("gumroad.com", "Gumroad"), ("lemonsqueezy", "Lemon Squeezy")):
        if host in url:
            return name
    return "your payment provider"


def write(page: Page, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page.html, encoding="utf-8")
    return target


def default_path(product: Product) -> str:
    return f"shop-{_slug(product.sku or product.name)}.html"
