# Your business launch

Checked 25 September 2026. Status: preparation, not ready to accept orders.

Confirmed by you: **business location Israel; total startup limit US$5,000**.
See the [Israel setup and staged budget](playbooks/israel-launch.md). You confirmed
you had neither business registration nor a PayPal Business account on
20 September. An updated status and the first customer market are still needed.

## Work completed on 25 September

Continuation: [four alternative sourcing leads and two specific quote requests](playbooks/supplier-shortlist.md)
are prepared, with cost ceilings for an Israel research case. Israel remains a
provisional research market, not an owner-confirmed customer destination. The
official Tax Authority application link was opened in Chrome and reached the
sign-in screen; the next registration step requires the owner to sign in privately.
No credentials were entered, messages sent, or payments made.

- Checked the two supplier leads and competitor pricing. The roller stays at
  research stage: current public item prices leave little room for shipping and
  acquisition. Read the [sourcing decision and calculations](playbooks/sourcing-decision.md).
- Created `data/store-launch.json` for actual onboarding, separate from the
  original demo. It has one unverified candidate, no orders, no advertising tests,
  no ledger entries and no funded cash recorded. The $5,000 limit is a spending
  ceiling, not a bank balance. Zero costs/prices and other defaults are not quotes.
- Created `data/store-launch.content.json`, a private answer sheet for copy and
  policy facts. Answers now survive regeneration and appear in the UI preview.
  Unknown answers remain blank; no product claims or business policies were invented.
- Added read-only shop validation and checked export. Fixed invalid payment links,
  ambiguous ILS prices, colliding filenames and leftover old product pages. Unknown
  prices/delivery estimates remain unset in the preview. Removed
  the empty reviews requirement and unverified payment confirmation.
- Verified **194 tests pass**. No spending, supplier messages, business filings,
  account creation or public deployment occurred.

Open the working app with:

```bash
python3 -m dropship --store data/store-launch.json ui
```

Use that `--store` path for real onboarding. `data/store.json` and the existing
`site/` remain the old demo. Both local stores and the answer sheet are ignored
by git. Keep identity documents and credentials in the official services.

After verified product information and policies are saved:

```bash
python3 -m dropship --store data/store-launch.json site --check
python3 -m dropship --store data/store-launch.json site --ready --out site-release
```

The check currently fails as expected: the candidate is not approved and the
business facts are incomplete. A passing check establishes technical completeness,
not verified fulfillment, legal eligibility or a successful payment.

## What is already done

You have a local management app, product and supplier records, profit calculations,
order tracking, and a generator for shop pages. More software is not the first
thing you need to buy or build.

The current Northbound Goods store is populated with demonstration data:
all 19 order emails end in `@example.com`, and the products and supplier sample
notes match `dropship/demo.py`. Its sales, cash balance, advertising results,
and sample delivery claims are not evidence of a real business.

The five original demo product records have no photos or payment links. The 11 generated
shop pages contain 129 highlighted unfilled fields. No working checkout,
verified supplier relationship, real sales, or public deployment was established
in this audit. Existing files have been preserved.

## The order we will work in

| Step | Work to complete | What is needed from you | Done when |
| --- | --- | --- | --- |
| 1. Set limits | Choose one customer market and an affordable experiment | Business country, maximum loss budget and currency, existing accounts | Country and spending limit are explicit |
| 2. Check one product | Compare alternatives, obtain two supplier quotes, calculate margin | Account access where needed; approval of an exact sample order | Destination-specific cost and delivery are documented |
| 3. Verify the sample | Test it, record delivery, prepare honest photos and demonstrations | Receive and physically try the sample, or arrange a tester | The actual item works and matches the proposed listing |
| 4. Prepare the business | Check local registration/tax requirements, payment eligibility, support and returns arrangements | Legal identity, bank verification, factual business details | Required setup and payment account are ready |
| 5. Finish the shop | Add one verified product, photos, policies and checkout; test fulfillment and refunds | Confirm the offer and actual policies | A test order reaches the correct workflow with the right item, currency, address and total |
| 6. Find customers | Publish demonstrations, measure visits and purchases, improve the offer | A social account and any required publishing approval | Real customer behavior is recorded; spending stays within the agreed limit |

I can research, compare quotes, calculate prices, write copy, configure the site,
prepare marketing, and test the order workflow. Identity verification, banking,
physical sample testing, and factual legal declarations need your participation.
The next owner step is the registration preparation described in the Israel
plan. The first customer market still needs selection. Do not put passwords,
card numbers or identity documents in this repository.

## First product investigated

A reusable pet-hair roller for people cleaning fabric furniture. This is a
research candidate, not a validated winner or a recommendation to buy stock.
It has a specific problem and a demonstration that can be filmed with a sample.
The price and demand scores in the demo must not be reused as verified inputs.
The [25 September screening](playbooks/sourcing-decision.md) found that the two
current leads need better delivered economics before a sample purchase is justified.

[Prepared supplier request, listing draft and video scripts](playbooks/first-product-launch.md).

## Money rules for this launch

The total limit is US$5,000. Until real quotes and checkout are verified, the
proposed advertising spend is zero. The first preparation stage is capped at $500;
this is a planning limit, not money already spent or permission for arbitrary charges.
Start with one product and original demonstration content. Organic traffic takes
work and may produce no sales; it is not a promise of free customer acquisition.

Before pricing, collect the supplier cost, destination shipping, applicable
taxes/duties, processor fees, currency costs, return costs and payout terms.
Calculate money left per order after all variable costs, then deduct customer
acquisition and fixed costs. A positive per-order figure alone is not net profit.
Keep enough cash to fulfill paid orders and handle refunds while payouts are held.
The staged budget initially protects $2,500 and sets aside $1,000 for fulfillment
and refunds. Recalculate these amounts when costs and payout terms are verified.

Do not use the demo's $4,000 starting cash or assumed upsell revenue as your funds
or expected revenue. Keep demo records separate from real orders when onboarding.

## Payment setup depends on your country

The repository mentions Stripe, but availability must be checked for the actual
business location. Israel is not listed on [Stripe's supported-country page](https://stripe.com/global)
as checked on this date. [PayPal's Israeli business site](https://www.paypal.com/il/)
offers business payment acceptance; account approval and the specific checkout
features still need verification. No provider has been selected or account opened.

Use the chosen provider's supported test environment first. PayPal provides a
[sandbox](https://developer.paypal.com/sandbox-testing/overview/). Confirm receipt,
shipping address, product identification, confirmation page, refund workflow and
order export. Test importing that export into a separate store before using real
orders: payment reports are not necessarily fulfillment-ready order reports.

## What is needed to continue

1. First customer country and a representative delivery postcode for quotes.
2. Current business-registration and payment-account status; give provider names,
   not credentials. The official registration route requires your identity, bank
   evidence and truthful income/turnover estimates, which are not available here.
3. A supplier account for exact quotes, followed by the exact sample order details
   and a real sample inspection. Public listings cannot replace either.
4. Factual trading name, public contact details, returns arrangement and applicable
   policies. Add licensed/original sample photos and a tested checkout link afterward.

These are missing inputs and external verification steps, not software tasks.
Customer-market selection and account/sample status were requested in this session;
no answer was received during preparation. The staging budget remains unchanged.

## Registration handoff

Open the official registration instructions linked in the Israel plan and check
eligibility. Sign in yourself if proceeding to the application. Review all real
business details and estimates before submission; the $5,000 startup budget is
not a revenue forecast. If a field is unclear, share its label without private data.

Profit is not guaranteed; the immediate objective is a verified offer and a
working first-order process.
