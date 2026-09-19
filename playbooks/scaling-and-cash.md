# Scaling and cash

The counter-intuitive fact that ends more working dropshipping stores than bad
products: **you can go broke while profitable.**

You pay for ads today. You pay your supplier today. Your processor pays you in
3 days, or 7, or 21 - and it may hold a rolling reserve on top. Scale into that
gap fast enough and the bank balance hits zero while the P&L looks excellent.

```bash
python3 -m dropship cash max-spend
python3 -m dropship cash scenarios
```

## What the payout delay actually costs

Same product, same margins, same CPA, $2,000 starting cash, 25% safety buffer.
The only thing that changes is how long the processor holds your money:

| Payout delay | Max safe daily spend |
|---|---|
| 3 days | ~$324 |
| 21 days | ~$42 |

That is not a rounding difference. It is the difference between a business and
a hobby, and it is decided by a setting in an account you probably have not
looked at.

Reproduce it for your own numbers:

```bash
python3 -m dropship config set payout_delay_days 21
python3 -m dropship cash max-spend --cpa 25
```

**A rolling reserve is a separate, subtler problem.** At these margins a 10%
reserve does not lower safe spend at all - the binding constraint is the
initial payout gap, which a reserve does not change. It still ties up real
money (`cash sim` reports it as `reserve_outstanding`), and once it grows large
enough to push daily cash flow negative - around 32% here - it bites very hard
and very suddenly. Do not assume a small reserve is harmless just because the
number does not move.

**So negotiate the delay before you negotiate anything else.** It is worth more
than a supplier price cut, and it costs nothing but a support ticket. Faster
payouts usually follow a clean dispute record and a few weeks of history - which
is another reason fulfilment discipline pays twice.

## The ladder

```bash
python3 -m dropship test ladder --product "Winner"
```

- Raise daily budget 20-25% per step. Larger jumps re-enter the learning phase
  and can reset a campaign that was working.
- Hold 48 hours between steps. Two days of data, not two hours.
- Every rung carries a stop-loss: CPA above breakeven for 3 consecutive days
  means step back down, not "wait and see".
- Duplicate winning ad sets into broader audiences rather than editing the
  proven one. Never edit a winner.
- Stop at what cash allows, not at what the campaign could absorb. The ladder
  marks the step where you run out.

## Before you scale anything

1. **Confirm supplier stock and lead time.** A winner that goes out of stock is
   a winner you have lost, and the ad account loses its learning with it.
2. **Have a second supplier qualified.** One price rise or suspension should be
   an inconvenience, not an ending.
3. **Check support capacity.** 10x the orders is 10x the tickets, and slow
   support at volume is how a chargeback rate goes from 0.4% to 2%.
4. **Re-measure refund rate.** It usually rises with volume as you move past
   your earliest, most forgiving customers.

## Where the money is tied up

At any moment you are out of pocket by roughly:

```
(daily ad spend + daily COGS) x payout delay in days
```

At $300/day spend and $150/day COGS with a 7-day delay, that is about $3,150
permanently in flight. It is not lost, but it is not available either, and it
scales linearly with everything you do.

```bash
python3 -m dropship cash sim --daily 300 --cpa 25 --days 90 --growth 0.03
```

`peak_working_capital` in that output is the real number to hold in reserve.

## Sources of headroom, cheapest first

1. **Shorter payouts.** Free. Ask.
2. **Higher AOV.** More margin per unit of working capital. Bundles and
   post-purchase upsells cost nothing to add.
3. **Supplier terms.** Net-15 or net-30 moves COGS to after the customer pays
   and is worth more than an equivalent price cut.
4. **A credit card with a 30-day cycle for ads.** Real headroom, and real risk
   if a campaign turns while you are not watching. Use the stop-losses.
5. **Slower scaling.** Unglamorous, always available, never wrong.

## Warning signs

- Cash dips below 20% of starting balance during a ramp - one chargeback wave
  ends the run.
- Processor mentions "reserve" or "review" - stop scaling that day and clean up
  fulfilment before anything else.
- Refund rate rising while volume rises - you are outrunning your fulfilment,
  and the bill arrives two weeks later.
- Blended ROAS falling while platform ROAS holds - the platform is
  over-attributing. Trust the bank.
