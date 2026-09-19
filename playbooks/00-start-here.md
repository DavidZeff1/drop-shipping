# Start here

## The honest part first

Most dropshipping stores lose money. The common public figure is that around
90% fail, and while that number is folklore rather than research, every
credible account points the same direction: the median outcome is a loss.

The losses are not random. They cluster in five places, and every one of them
is a decision made before or instead of a calculation:

| Where the money goes | What the system does about it |
|---|---|
| Products with no room for ad spend | `product score` gates on margin before anything else |
| Not knowing the real breakeven | `econ` prices in refunds, chargebacks and fees |
| Feeding a loser for three weeks | `test decide` kills on evidence, not on mood |
| Killing a winner on one bad day | The same interval stops premature kills |
| Running out of cash while profitable | `cash max-spend` caps spend at what payouts allow |

This system cannot make a bad product work. What it can do is stop you paying
to find out something you could have calculated, and stop you quitting on
something that was working.

**What actually separates the stores that make money:** they test more products
with less money each, they know their breakeven before launch, and they treat
fulfilment as a profit centre rather than an afterthought. None of that is
clever. All of it is boring, and that is why it is rare.

## Week one: build the foundation

Do not run a single ad this week.

```bash
python3 -m dropship init --name "Your Store"
```

**Day 1-2. Get your real numbers in.** Every calculation downstream depends on
these, and the defaults are guesses.

```bash
python3 -m dropship config show
python3 -m dropship config set payout_delay_days 3      # ask your processor
python3 -m dropship config set starting_cash 2000
python3 -m dropship config set fixed_monthly_costs 150
python3 -m dropship config set refund_rate 0.05         # measure it later
```

The payout delay is the one people skip and the one that decides how fast you
can scale. A new Shopify Payments or Stripe account is often 7 days, sometimes
21, occasionally with a rolling reserve. Ask before you need to know.

**Day 3-4. Source and vet suppliers.** Two minimum, so a stockout is an
inconvenience rather than an ending.

```bash
python3 -m dropship supplier add --name "CJ Dropshipping" --platform cj \
  --unit-price 8.40 --ship-cost 3.10 --handling-days 2 --transit-days 10 \
  --tracking 8 --defect-rate 0.025 --response-hours 12 --stock-depth 7
python3 -m dropship supplier checklist
```

**Order a sample.** To your own address, as a normal customer, without telling
them who you are. Time every stage. This is the step people skip and then
discover, at scale, that the tracking never updates.

**Day 5-7. Research products.** Aim for 15-20 candidates, expect 2-3 to survive.

```bash
python3 -m dropship product add --name "Pet Hair Remover Roller" \
  --price 39.99 --cogs 7.10 --ship-cost 2.90 --delivery-days 11 \
  --demand 9 --competition 5 --creative 9 --problem 9 --wow 8
python3 -m dropship product score --all
```

Score honestly. Inflating `demand` because you like the product produces a
number that agrees with you and costs you money. See
[product-research.md](product-research.md).

## Week two: first test

```bash
python3 -m dropship econ "Pet Hair"          # know breakeven before you spend
python3 -m dropship test plan "Pet Hair" --start
```

Read the budget it gives you. It is not a suggestion: below roughly 3x your
breakeven CPA, a zero-sale result is statistically indistinguishable from bad
luck, and you will have bought nothing but an opinion.

Then leave it alone until the checkpoint. Every mid-test edit restarts the
learning phase and destroys the data you are paying for.

```bash
python3 -m dropship test update <id> --spend 110 --impressions 24000 \
  --clicks 480 --landing-views 410 --add-to-carts 38 --checkouts 15 --purchases 4
```

Then do what it says. The entire value of the system is in that sentence.

## Week three onward: the loop

```bash
python3 -m dropship today       # every morning, before anything else
```

The loop is: kill losers fast, scale winners carefully, keep the fulfilment
queue at zero, and always have the next product ready. See
[daily-rhythm.md](daily-rhythm.md).

## Before you take a single order

Read [compliance-and-risk.md](compliance-and-risk.md). Not because it is
interesting, but because the failure modes there - a banned ad account, a
frozen processor, an IP complaint - do not degrade performance, they end the
business in a single afternoon.

## What "working" looks like

| Milestone | Signal | Typical timeline |
|---|---|---|
| First sale | Anything at all converts | Week 2-3 |
| Product-market fit | CPA under breakeven for 7 straight days | Week 4-8 |
| Repeatable | Scaled 3x while holding CPA | Month 3-4 |
| A business | Profitable after your own wages | Month 6+ |

If you are past month three with no product that has ever held CPA under
breakeven for a week, the honest read is that the process is working and the
answer is no. That is a real answer, and finding it cheaply is worth something.
