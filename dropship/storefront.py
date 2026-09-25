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
import math
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import listings, research, shop_content
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
.buy.second { background: var(--surface); color: var(--ink-1);
  border: 1px solid var(--ink-1); font-size: 16px; padding: 12px 18px; }
.bundle { margin: 16px 0; }
.bundle b { font-size: 17px; }
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
.nav { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 14.5px; }
.nav a { text-decoration: none; color: var(--ink-2); }
.nav a:hover { color: var(--ink-1); }
.nav a[aria-current="page"] { color: var(--ink-1); font-weight: 600; }
.tiles { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.tile { display: grid; gap: 4px; text-decoration: none; }
.tile img, .tile .ph { aspect-ratio: 4 / 3; object-fit: cover; border-radius: 12px;
  border: 1px solid var(--hairline); background: var(--surface); width: 100%; }
.tile .name { font-weight: 600; margin-top: 6px; }
.tile .price { font-size: 17px; }
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
    sym = {"USD": "$", "GBP": "£", "EUR": "€", "ILS": "₪"}.get(config.currency)
    return f"{sym}{value:,.2f}" if sym else f"{value:,.2f} {config.currency}"


def _price(product: Product, config: Config) -> str:
    return (_money(product.price, config)
            if math.isfinite(product.price) and product.price > 0 else "Price not set")


def _delivery(days: float) -> str:
    return (f"{days:.0f}" if math.isfinite(days) and days > 0
            else "{delivery estimate in days}")


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
        figures.append(f"<figure>{_img(source, f'{product.name} - photo {i}', issues)}"
                       f"</figure>")
    return "".join(figures)


def _img(source: str, alt: str, issues: list[str]) -> str:
    """One image: a remote URL as it stands, a local file embedded in the page."""
    label = _e(alt)
    if source.startswith(("http://", "https://")):
        if source.startswith("http://"):
            issues.append(f"{source} loads over http, which browsers flag on a "
                          f"page that leads to a checkout. Use the https address.")
        return f'<img src="{_e(source)}" alt="{label}" loading="lazy">'

    path = Path(source)
    kind, _encoding = mimetypes.guess_type(path.name)
    if not path.is_file():
        issues.append(f"Photo not found: {path}. Fix the path and re-run with "
                      f"--image {path}")
        return f'<span class="ph">Missing: {_e(path)}</span>'
    if not (kind or "").startswith("image/"):
        issues.append(f"{path} is not an image a browser will show. Use a jpg, "
                      f"png or webp.")
        return f'<span class="ph">Not an image: {_e(path)}</span>'
    raw = path.read_bytes()
    if len(raw) > _MAX_PHOTO:
        issues.append(
            f"{path.name} is {len(raw) / 1024:.0f} KB. Compress it under "
            f"{_MAX_PHOTO // 1000} KB - the page has to load in 2.5s on 4G, and "
            f"a slow page is the most expensive leak on this list.")
    data = base64.b64encode(raw).decode("ascii")
    return f'<img src="data:{kind};base64,{data}" alt="{label}" loading="lazy">'


def _payment_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme == "https" and parsed.hostname
                    and not parsed.username and not parsed.password
                    and not any(char.isspace() for char in url))
    except ValueError:
        return False


def _buy(product: Product, config: Config, issues: list[str], sticky: bool = False) -> str:
    label = f"Buy now - {_money(product.price, config)}"
    if not product.pay_url:
        if not sticky:
            issues.append(
                "No payment link, so the buy button goes nowhere. Create a Stripe "
                "payment link or a PayPal button for this product, then: dropship "
                f"storefront \"{product.name}\" --pay https://...")
        return '<span class="buy off" aria-disabled="true">Payment link not set</span>'
    if not math.isfinite(product.price) or product.price <= 0:
        return '<span class="buy off" aria-disabled="true">Price not set</span>'
    if not _payment_url(product.pay_url):
        if not sticky:
            issues.append("The payment link is not https or has no valid host. "
                          "Use the complete https link your processor gives you.")
        return '<span class="buy off" aria-disabled="true">Payment link needs correction</span>'
    return f'<a class="buy" href="{_e(product.pay_url)}">{_e(label)}</a>'


def _bundle(product: Product, config: Config, issues: list[str]) -> str:
    """The cheapest lever on ad maths: two of the thing, at a price for two."""
    if not (product.bundle_price or product.bundle_pay_url):
        return ""
    if not (product.bundle_price and product.bundle_pay_url):
        issues.append("The bundle needs both a price and its own payment link, "
                      "or the buy button charges the wrong amount: dropship "
                      f"storefront \"{product.name}\" --bundle-price 69.98 "
                      f"--bundle-pay https://...")
        return ""
    if not _payment_url(product.bundle_pay_url):
        issues.append("The bundle payment link needs a complete https address "
                      "from your processor. Correct --bundle-pay before publishing.")
        return ""
    if not math.isfinite(product.bundle_price) or product.bundle_price <= 0:
        issues.append("Set a finite, positive bundle price with --bundle-price.")
        return ""
    saving = product.price * 2 - product.bundle_price
    if saving <= 0:
        issues.append(f"The bundle at {_money(product.bundle_price, config)} is "
                      f"not cheaper than two singles. Price it below "
                      f"{_money(product.price * 2, config)} or drop it.")
    deal = (f"Save {_money(saving, config)} against two singles" if saving > 0
            else "")
    return (f'<div class="card bundle"><b>Two for '
            f"{_e(_money(product.bundle_price, config))}</b>"
            f'<p class="fine">{_e(deal)}.</p>'
            f'<a class="buy second" href="{_e(product.bundle_pay_url)}">'
            f"Buy two - {_e(_money(product.bundle_price, config))}</a></div>")


def build(product: Product, config: Config, problem: str = "",
          outcome: str = "", site: bool = False,
          content: shop_content.Content | None = None) -> Page:
    """Render the page and collect everything still between it and going live.

    ``problem`` and ``outcome`` fall back to whatever is stored on the product,
    so the preview and the written file say the same thing.
    """
    ue = for_product(product, config)
    listing = listings.generate(product, ue, problem or product.copy_problem,
                                outcome or product.copy_outcome)
    issues: list[str] = []
    if not math.isfinite(product.price) or product.price <= 0:
        issues.append("Set a finite, positive product price before publishing.")
    if not math.isfinite(product.delivery_days) or product.delivery_days <= 0:
        issues.append("Set a verified, positive delivery_days estimate before publishing.")

    blockers = research.score_product(product, config).blockers
    if blockers:
        issues.append(f"This product fails a research gate: {blockers[0]} A shop "
                      f"page cannot fix that.")

    days = _delivery(product.delivery_days)
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

    # On its own the page carries its policies inline; inside a site it also
    # links the pages a payment provider expects to find separately.
    if site:
        head = (f'<a class="brand" href="index.html">{_e(config.business_name)}</a>'
                f"{_nav('')}")
        foot = " &middot; ".join(
            f'<a href="{name}">{_e(POLICIES[name][0])}</a>' for name in POLICIES)
    else:
        head = (f'<span class="brand">{_e(config.business_name)}</span>'
                f'<span class="ship">Delivery included &middot; arrives in '
                f"about {_copy(days)} days</span>")
        foot = '<a href="#policies">Delivery, returns and contact</a>'

    body = f"""<header class="bar">{head}</header>
<main>
<section class="hero">
  <div class="photos">{photos}</div>
  <div class="buybox">
    <h1>{_copy(title)}</h1>
    <p class="sub">{_copy(listing.subtitle)}</p>
    <p class="price">{_e(_price(product, config))}
      <span class="note">delivery included</span></p>
    <ul class="trust">{"".join(f"<li>{_copy(t)}</li>" for t in trust)}</ul>
    {buy}
    <p class="fine">Secure checkout on {_e(_processor(product))}. Your card
      details never touch this page.</p>
    {_bundle(product, config, issues)}
  </div>
</section>
<section><h2>Why this one</h2>
  <ul class="sell">{"".join(f"<li>{_copy(b)}</li>" for b in listing.bullets)}</ul>
</section>
<section>{_prose(listing.description, title)}</section>
<section><h2>Questions</h2>{faq}</section>
<section id="policies"><h2>Delivery, returns and contact</h2>
  {"".join(f"<h3>{_e(h)}</h3><p>{_copy(t)}</p>" for h, t in policies)}
</section>
</main>
<footer>{_e(config.business_name)} &middot; {foot}</footer>
<div class="sticky"><span class="price">{_e(_price(product, config))}</span>
{_buy(product, config, issues, sticky=True)}</div>"""

    page = Page(html=f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(listing.subtitle)}">
<style>{_CSS}</style></head><body>
{body}
</body></html>""", issues=issues)

    page.html = shop_content.fill(page.html, (content or shop_content.Content()).for_product(product))
    # Include metadata as well as body copy, but never count stylesheet braces.
    page.slots = len(_SLOT.findall(_body_of(page.html)))
    if page.slots:
        issues.append(
            f"{page.slots} slots are still in braces and highlighted on the page. "
            "Save the answers in the store's .content.json file so they survive "
            "rebuilding. Create one with: dropship site --content-template <file>")
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


# ------------------------------------------------------------------ site --
#
# The shop page above is one product. A store is that page per product, plus
# the four pages a payment provider looks for before it approves an account,
# plus somewhere to land after paying. All static, all in one folder.

# Statuses that belong in a shop window. A killed or unscored product does not.
SELLING = ("approved", "testing", "iterating", "scaling", "winner")

NAV = (("index.html", "Shop"), ("shipping.html", "Delivery"),
       ("refunds.html", "Returns"), ("contact.html", "Contact"))

# Every policy below is mostly slots on purpose: these are answers only the
# operator has, and a policy page invented for them would be worse than none.
POLICIES = {
    "refunds.html": ("Refunds and returns", (
        ("The short version",
         "We would rather you keep it because it works than because you are "
         "stuck with it."),
        ("How long you have",
         "{your returns window, e.g. 30 days from delivery}. The item needs to "
         "be {what condition you require}."),
        ("Who pays the postage",
         "{who pays return postage - say it plainly, it is the question that "
         "causes disputes}."),
        ("How to start one",
         "Email {your support email} with your order number. We reply within "
         "{your response time}."),
        ("When the money arrives",
         "We refund within {number} business days of the return arriving, to "
         "the card you paid with. Banks then take another 5-10 days to show "
         "it, which is their timing and not ours."),
        ("Damaged or wrong on arrival",
         "{Your process and remedies for damaged or incorrect goods, including "
         "any evidence needed and who pays return shipping.}"),
    )),
    "shipping.html": ("Delivery", (
        ("Handling",
         "Orders leave our supplier within {your handling time, e.g. 2} "
         "business days."),
        ("How long it takes", "{transit}"),
        ("Tracking",
         "Every order gets a tracking link by email the moment it ships."),
        ("If tracking stops moving",
         "International parcels can sit at a customs checkpoint for several "
         "days without the tracking updating. That is normal. If yours has "
         "not moved in 7 days, email us and we will chase the carrier."),
        ("Where we ship", "{the countries you ship to}."),
        ("Cost", "Delivery is included in the price shown. There is nothing "
                 "added at checkout."),
    )),
    "privacy.html": ("Privacy", (
        ("Who we are", "{your business name}, {your address}."),
        ("What we collect",
         "Your name, email, delivery address and what you ordered. Card "
         "details go to our payment provider and never reach this site."),
        ("Why we have it",
         "To deliver your order and answer you when you write to us. Nothing "
         "else."),
        ("Who else sees it",
         "The supplier who ships your parcel, the payment provider who takes "
         "the payment, and {your email tool, if you use one}."),
        ("How long we keep it",
         "{how long you keep order records, e.g. 7 years for tax}."),
        ("Your rights",
         "Email {your support email} for a copy of what we hold, or to have "
         "it deleted."),
        ("Cookies",
         "This site sets none of its own. {If you add an advertising pixel "
         "later, say so here - and mean it.}"),
    )),
    "terms.html": ("Terms", (
        ("Who you are buying from", "{your business name}, {your address}."),
        ("Prices", "Shown in {currency}, delivery included. {Whether import "
                   "duty may be charged on arrival in your country.}"),
        ("Your order",
         "An order is accepted when we email your confirmation. You can "
         "cancel before it ships by emailing {your support email}."),
        ("Delivery dates",
         "The estimates on this site are estimates, not guarantees. If "
         "something is badly late, our returns policy still applies."),
        ("Governing law", "{your country}. None of this affects your "
                          "statutory consumer rights."),
    )),
    "contact.html": ("Contact", (
        ("Email", "{your support email} - we answer within {your response "
                  "time}, every working day."),
        ("Who we are", "{your business name}, {your address}."),
        ("Before you write",
         "If it is about where your order is, have your order number ready "
         "and check the tracking link in your shipping email first."),
    )),
}


def _nav(current: str) -> str:
    links = []
    for href, label in NAV:
        mark = ' aria-current="page"' if href == current else ""
        links.append(f'<a href="{href}"{mark}>{_e(label)}</a>')
    return f'<nav class="nav">{"".join(links)}</nav>'


def _shell(config: Config, title: str, body: str, current: str = "",
           description: str = "") -> str:
    """The frame every page of the site shares."""
    policy_links = " &middot; ".join(
        f'<a href="{name}">{_e(POLICIES[name][0])}</a>' for name in POLICIES)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<style>{_CSS}</style></head><body>
<header class="bar"><a class="brand" href="index.html">{_e(config.business_name)}</a>
{_nav(current)}</header>
{body}
<footer>{_e(config.business_name)} &middot; {policy_links}</footer>
</body></html>"""


def _policy_page(config: Config, filename: str, products: list[Product]) -> str:
    title, sections = POLICIES[filename]
    days = sorted({p.delivery_days for p in products
                   if math.isfinite(p.delivery_days) and p.delivery_days > 0})
    transit = ("{your verified delivery estimate}" if not days else
               f"About {days[0]:.0f} days to your door."
               if len(days) == 1 else
               f"Between about {days[0]:.0f} and {days[-1]:.0f} days to your "
               f"door, depending on the item.")
    body = []
    for heading, text in sections:
        filled = _copy(text.replace("{transit}", transit))
        body.append(f"<h3>{_e(heading)}</h3><p>{filled}</p>")
    return _shell(config, f"{title} - {config.business_name}",
                  f'<main><section><h1>{_e(title)}</h1>{"".join(body)}</section></main>',
                  filename, title)


def _index_page(config: Config, products: list[Product], issues: list[str]) -> str:
    cards = []
    for product in products:
        cards.append(
            f'<a class="tile" href="{_e(page_name(product))}">'
            f'{_thumb(product)}<span class="name">{_e(product.name)}</span>'
            f'<span class="price">{_e(_price(product, config))}</span>'
            f'<span class="fine">Delivery included, about '
            f"{_copy(_delivery(product.delivery_days))} days</span></a>")
    if not products:
        issues.append("No products are in a state that belongs in a shop "
                      "window. Approve or launch one first: dropship product "
                      "score --all")
        cards.append('<p class="fine">Nothing to sell yet.</p>')
    body = f"""<main>
<section><h1>{_copy("{Your one-line promise: what this shop is for, in the "
                     "customer's words}")}</h1>
<p class="sub">{_copy("{One more sentence. Who it is for, and why you, rather "
                      "than the marketplace that sells everything.}")}</p></section>
<section><div class="tiles">{"".join(cards)}</div></section>
</main>"""
    return _shell(config, config.business_name, body, "index.html")


def _thumb(product: Product) -> str:
    """The first photo, or a labelled gap where one should be."""
    if not product.photos:
        return '<span class="ph">Photo goes here</span>'
    return _img(product.photos[0], f"{product.name} - photo 1", [])


def _thanks_page(config: Config, products: list[Product]) -> str:
    days = _delivery(max((p.delivery_days for p in products), default=0.0))
    others = [p for p in products if p.pay_url][:3]
    more = ""
    if others:
        rows = "".join(
            f'<a class="tile" href="{_e(page_name(p))}">{_thumb(p)}'
            f'<span class="name">{_e(p.name)}</span>'
            f'<span class="price">{_e(_price(p, config))}</span></a>'
            for p in others)
        more = (f'<section><h2>Also from {_e(config.business_name)}</h2>'
                f'<p class="fine">If you add another order in the next day or '
                f'two we can usually ship them together.</p>'
                f'<div class="tiles">{rows}</div></section>')
    body = f"""<main>
<section><h1>Thank you for your order</h1>
<p>Check your payment provider's receipt for confirmation and your order number.
This page cannot verify payment. If you have no receipt, contact us before paying again.</p>
<h3>What happens now</h3>
<p>We place your order with the warehouse within {{your handling time, e.g. 2}}
business days, then email you a tracking link. Expect the parcel within about
{days} days - the estimate on the product you bought is the one that
applies.</p>
<h3>If something looks wrong</h3>
<p>Email {{your support email}} with your order number. We answer within
{{your response time}}, and it is much faster than your bank.</p></section>
{more}
</main>"""
    return _shell(config, f"Thank you - {config.business_name}",
                  _copy_block(body), "", "Check your receipt and next steps")


def _copy_block(html: str) -> str:
    """Highlight slots in text that was written here rather than by listings."""
    return _SLOT.sub(lambda m: f'<mark class="slot">{m.group(0)}</mark>', html)


def page_name(product: Product) -> str:
    return f"{_slug(product.sku or product.name)}.html"


@dataclass
class Site:
    """Every file of the shop, and what is still missing from it."""

    files: dict[str, str] = field(default_factory=dict)   # name -> HTML
    products: list[Product] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    slots: dict[str, int] = field(default_factory=dict)   # name -> unfilled slots

    @property
    def size(self) -> int:
        return sum(len(page.encode("utf-8")) for page in self.files.values())

    @property
    def total_slots(self) -> int:
        return sum(self.slots.values())

    @property
    def publishable(self) -> bool:
        return not self.issues


def build_site(products: list[Product], config: Config,
               content: shop_content.Content | None = None) -> Site:
    """The whole shop: a page per product, the policy pages, and a thank-you page."""
    site = Site()
    content = content or shop_content.Content()
    site.products = [p for p in products if p.status in SELLING]

    for product in site.products:
        page = build(product, config, site=True, content=content)
        name = page_name(product)
        if name in {"index.html", "thanks.html", *POLICIES} or name in site.files:
            raise ValueError(f"Duplicate or reserved product filename '{name}'. "
                             "Give every product a distinct SKU before generating the site.")
        site.files[name] = page.html
        site.slots[name] = page.slots
        # Name the product, or a five-page report says "no payment link" twice.
        site.issues += [f"{product.name}: {issue}" for issue in page.issues
                        if "slots are still" not in issue]

    site.files["index.html"] = _index_page(config, site.products, site.issues)
    site.files["thanks.html"] = _thanks_page(config, site.products)
    for name in POLICIES:
        site.files[name] = _policy_page(config, name, site.products)
    for name in ["index.html", "thanks.html", *POLICIES]:
        site.files[name] = shop_content.fill(site.files[name], content.shared)
        site.slots[name] = len(_SLOT.findall(_body_of(site.files[name])))

    if site.total_slots:
        worst = sorted(site.slots.items(), key=lambda kv: -kv[1])[:3]
        where = ", ".join(f"{name} ({count})" for name, count in worst if count)
        site.issues.append(
            f"{site.total_slots} slots still to fill, most of them in {where}. "
            "Save factual answers in the store's .content.json file, then rebuild. "
            "Create the answer sheet with: dropship site --content-template <file>")
    return site


def _body_of(page: str) -> str:
    """The page without its stylesheet, which is full of braces that are not slots."""
    return re.sub(r"<style>.*?</style>", "", page, flags=re.S)


def write_site(site: Site, out_dir: Path | str) -> list[Path]:
    target = Path(out_dir)
    stale = {p.name for p in target.glob("*.html")} - set(site.files)
    if stale:
        raise ValueError("Output contains pages not in this shop: "
                         + ", ".join(sorted(stale))
                         + ". Use a fresh --out folder or archive the old folder first.")
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, page in site.files.items():
        path = target / name
        path.write_text(page, encoding="utf-8")
        written.append(path)
    return written


def notes(site: Site, config: Config, out_dir: Path | str) -> str:
    """The part that is not a file to upload: how to publish it, and what to send."""
    folder = Path(out_dir).name or "site"
    lines = [
        f"# Publishing {config.business_name}",
        "",
        f"`{folder}/` is the whole shop: {len(site.files)} files, "
        f"{site.size / 1000:,.0f} KB, no dependencies. Nothing here is a "
        f"secret, and nothing here takes a card - the buy buttons hand over to "
        f"your payment provider.",
        "",
        "## 1. Fill in the blanks first",
        "",
        "Save answers to the highlighted {braces} in the private .content.json "
        "file beside your store. `site --content-template <file>` creates the "
        "answer sheet. Rebuild with `site --content <file> --ready`; this refuses "
        "to write a shop with outstanding issues. The counts:",
        "",
    ]
    for name, count in sorted(site.slots.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{name}` - {count} to fill" if count
                     else f"- `{name}` - done")
    lines += [
        "",
        "The policy pages matter more than they look: Stripe and PayPal both "
        "read them before approving an account, and they are the evidence you "
        "submit when someone disputes a charge.",
        "",
        "## 2. Get a payment link per product",
        "",
        "In Stripe: Payment links, new link, one per product at the price the "
        "page shows. In PayPal: the equivalent under pay and get paid. Set the "
        "link's confirmation page to your own `thanks.html` once the site is "
        "live, so buyers land back on your shop instead of a receipt screen.",
        "",
        "Then put each link on its product:",
        "",
        "```bash",
        *[f'python3 -m dropship storefront "{p.name}" --pay https://...'
          for p in site.products[:3]],
        "```",
        "",
        "## 3. Put the folder online",
        "",
        f"Any static host serves this folder as it stands, free:",
        "",
        "- Netlify: drag the folder onto app.netlify.com/drop.",
        "- Cloudflare Pages or GitHub Pages: point them at the folder.",
        "",
        "Then buy a domain and point it at the host. A shop on a free "
        "subdomain converts worse and gets rejected by ad platforms more often "
        "than one on its own name.",
        "",
        "## 4. When orders arrive",
        "",
        "They land in your payment provider, not in this folder. Validate a "
        "sandbox order export in a separate test store first: a payment report "
        "may lack the product, quantity or shipping address needed for fulfillment. "
        "For supported Shopify/WooCommerce order CSVs, run:",
        "",
        "```bash",
        "python3 -m dropship import orders ~/Downloads/payments.csv",
        "```",
        "",
        "Then `python3 -m dropship today` tells you what to do about them.",
        "",
        "## 5. The emails to set up",
        "",
        "Six emails carry most of the money that a shop this size leaves on "
        "the table. Write them once in whatever tool sends your receipts.",
        "",
    ]
    for product in site.products[:1]:
        ue = for_product(product, config)
        for flow in listings.generate(product, ue).email_flow:
            lines.append(f"**{flow['trigger']} - {flow['delay']}** "
                         f"({flow['goal']})  ")
            lines.append(f"{flow['content']}")
            lines.append("")
    lines += [
        "## What this shop deliberately does not do",
        "",
        "No cart, so one order is one product plus whatever bundle you offer "
        "on the page. No fake reviews, no countdown timers, no invented stock "
        "counts: they lift conversion a little and lift disputes a lot. If a "
        "product earns its keep, that is the point to move it onto a platform "
        "with a real cart - not before.",
        "",
    ]
    return "\n".join(lines)
