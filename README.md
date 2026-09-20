# dropship

**Launching your own business?** Start with the [current launch status and next steps](START-BUSINESS.md).
The included Northbound Goods records are demonstration data, not real sales.

A complete operating system for a dropshipping business: product research,
unit economics, ad-test decisions, cash-flow planning, fulfilment, customer
service and reporting — in one command-line tool with no dependencies.

```bash
python3 -m dropship today
```

```
Northbound Goods - 2026-09-19
============================================================

  4 order(s) need rescuing before anything else. Fulfilment failures cost
  more than any ad decision.

  Revenue (30d)              $932.31
  Net profit (30d)           -$346.81
  Blended ROAS               1.33x  breakeven 1.57x
  Cash                       $3,650.00
  Open actions               14 (4 critical)

DO THESE FIRST (3)
----------------------------

  1. [ops] #1014: Paid 3 days ago, never placed with the supplier
     Every day here is added to a delivery window the customer has already
     been promised. This is the cheapest failure to prevent and the most
     expensive to ignore.
     Do: Place it with the supplier now, then find out why it was missed.

  2. [decision] KILL: LED Sunset Lamp
     Even the optimistic case loses money. Spent $268 for 2 sales;
     breakeven CPA is $19.88.
     Do: Turn the campaign off today. Every further day is a known loss.
     $ dropship test decide tst_a4fe1ea541
```

## Start

Python 3.10 or newer. Nothing to install.

```bash
git clone https://github.com/DavidZeff1/drop-shipping.git
cd drop-shipping

python3 -m dropship demo        # load an example store and look around
python3 -m dropship today
python3 -m dropship portfolio
python3 -m dropship dashboard   # writes dashboard.html, opens offline
python3 -m dropship ui          # the same, clickable, in your browser
```

When you are ready with your own:

```bash
python3 -m dropship init --name "Your Store"
```

Optional shortcut: `alias dropship='python3 -m dropship'`.

## What it is actually for

Dropshipping stores mostly do not fail at marketing. They fail because five
calculations never got made, and this tool exists to make them:

| Question | Command | Why it decides the outcome |
|---|---|---|
| Is this worth testing? | `product score` | Hard gates on margin, delivery and category, before any score |
| What is my real breakeven? | `econ` | Prices in refunds, chargebacks, fees and support — not just COGS |
| Is this test a winner? | `test decide` | Confidence interval on true CPA, not the point estimate |
| Can I afford to scale? | `cash max-spend` | Day-by-day simulation of payout delays and reserves |
| What do I do right now? | `today` | Every signal ordered by what it costs to ignore |

## The four ideas that do the work

**1. Contribution margin, not gross margin.** An order is modelled as an
expected value over three outcomes — kept, refunded, charged back — so the
breakeven you act on already includes the 5% who refund and the 0.5% who
dispute. This is usually 15-25% worse than the number people carry in their
head, and it is the number every other calculation uses.

**2. Decide on the interval, not the average.** With 3 sales on $200, your
observed CPA of $66 is nearly meaningless: the true value could plausibly sit
anywhere from $30 to $180. The engine computes an exact Poisson confidence
interval and acts only when the *whole range* sits on one side of breakeven.
That is what stops both premature kills and expensive hope.

**3. Zero sales is a measurement, and it has a price.** If the true CPA were
exactly breakeven, spend of 3x breakeven CPA would be expected to produce three
sales. Seeing none has roughly a 5% probability — a defensible kill. Below that
threshold, a kill is a guess. Test budgets are set from this, not from comfort.

**4. Cash flow is a separate constraint from profit.** You pay for ads and
goods today; the processor pays you in 3 days, or 21. Scale into that gap and a
profitable store runs out of money. The simulator finds the day it happens.

## Commands

```
today          what to do right now, ordered by cost of ignoring it
doctor         check your assumptions before they cost money
portfolio      every product, its economics and its live verdict

product        add / list / score / set / delete
supplier       add / list / score / checklist
econ           unit economics, price ladder, sensitivity

test plan      a budget that can actually produce a verdict
test update    record spend and results
test decide    kill / iterate / hold / scale, with funnel diagnosis
test ladder    a budget ramp with stop-losses and a cash ceiling

cash sim       day-by-day cash projection
cash max-spend the most you can spend per day without going broke
cash scenarios four futures side by side

listing        titles, bullets, FAQ, 10 ad angles, UGC brief, email flow
orders sla     what is drifting toward a chargeback
cs             nine support templates, incl. a chargeback evidence pack

import orders  Shopify / WooCommerce CSV export
import ads     Meta / TikTok / Google CSV export
kpi            blended performance with threshold-aware alerts
dashboard      offline single-file HTML
ui             a basic web interface on this machine
storefront     a shop page you can put online
site           the whole shop as a folder you can upload
config         show / set
```

`--help` works on every command.

## Prefer clicking?

```bash
python3 -m dropship ui
```

Opens a basic web interface at http://127.0.0.1:8765: today's briefing, the
portfolio, a page per product with its economics and live test verdict, the
order queue, and the settings. It reads and writes the same store through the
same engine as the CLI, so the two never disagree - use whichever is nearer.

Its **Admin** tab is where everything goes in: add or edit any record -
products, suppliers, orders, ad tests, cash entries - upload product photos,
and import a CSV without touching the terminal. It opens with a setup
checklist of what is still missing and a link to each thing that fixes it.

It listens on this machine only and has no login. Do not expose the port.

## Somewhere to send the traffic

```bash
python3 -m dropship site
```

Writes the whole shop into `site/`: a home page, a page for each product you
are actually selling, the policy pages a payment provider reads before it
approves an account, and a thank-you page for after payment. Upload the folder
to any static host. No build step, no framework, no monthly fee.

Next to it, `site.notes.md` says how to publish it, what is still unfilled,
and which six emails are worth setting up.

One product at a time, with its photos and payment link:

```bash
python3 -m dropship storefront "Pet Hair" \
  --image shot1.jpg --image shot2.jpg \
  --pay https://buy.stripe.com/your_link \
  --bundle-price 69.98 --bundle-pay https://buy.stripe.com/your_two_pack
```

Money never passes through the file. The processor's page takes the card,
which keeps the compliance burden theirs, and their CSV export comes back in
through `import orders`.

Every slot the copy leaves you stays visible and highlighted, and the command
lists what is unfilled rather than letting you publish it. There is no
invented review count, no fake scarcity and no countdown: they raise disputes
faster than they raise conversion, and a fabricated review is the first thing
a card network looks at.

## Bring your real data

No API keys. Export a CSV from wherever you already work; column names are
matched fuzzily, so platform differences and version drift are handled.

```bash
python3 -m dropship import orders ~/Downloads/orders_export.csv
python3 -m dropship import ads ~/Downloads/meta-ads.csv --ledger
```

Re-importing the same file updates in place rather than double-counting.
Samples are in `data/samples/`.

## Playbooks

The tool makes the decisions; these explain the judgement behind them.

- **[Start here](playbooks/00-start-here.md)** — an honest assessment, and a
  three-week launch plan
- [Launch checklist](playbooks/launch-checklist.md) — the accounts, samples and
  answers only you can supply, in the order that costs least
- [Daily rhythm](playbooks/daily-rhythm.md) — the 20-minute morning loop
- [Product research](playbooks/product-research.md) — the gates, the score,
  and where to actually look
- [Ad testing](playbooks/ad-testing.md) — budgets, checkpoints, reading the
  funnel
- [Scaling and cash](playbooks/scaling-and-cash.md) — why profitable stores
  go broke
- [Compliance and risk](playbooks/compliance-and-risk.md) — the four things
  that end a store in one afternoon
- [Customer service](playbooks/customer-service.md) — support as margin
  protection

## Your data

Everything lives in one readable JSON file, `data/store.json`, gitignored by
default. Back it up by copying it. Point elsewhere with `--store` or
`DROPSHIP_STORE`.

```bash
python3 -m dropship --store ~/stores/uk.json today
```

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

176 tests, no dependencies. Weighted toward the statistics and economics,
where a silent error would poison every decision downstream.

## Honest limitations

- **It cannot tell you a product will sell.** Nothing can. It tells you when
  you have spent enough to stop guessing.
- **Its outputs are only as good as your inputs.** A `refund_rate` left at the
  default while your real rate is 12% makes every breakeven wrong. Run
  `doctor` and measure it once you have 50 orders.
- **No live API integration.** Deliberate: CSV import works on every platform,
  on day one, without app review.
- **Statistics assume a stable test.** Change the creative mid-test and the
  interval is measuring two different things.
- **Not legal or tax advice.** The compliance playbook is a checklist of where
  to look, not a substitute for advice in your jurisdiction.
