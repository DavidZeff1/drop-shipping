# Ad testing

The goal of a test is not a sale. It is a *verdict*, bought for the smallest
amount of money that can produce one.

## Budget is set by statistics, not by comfort

If the true CPA were exactly breakeven, sales arrive at roughly
`spend / breakeven_CPA`. Spend 3x breakeven CPA and you would expect three
sales; seeing zero then has about a 5% probability. That is a defensible kill.

Spend 1x and see zero, and you have learned nothing - you had a ~37% chance of
that outcome even on a perfectly viable product. Most "this product doesn't
work" conclusions are made right here, on data that could not support them.

```bash
python3 -m dropship test plan "Product Name" --start
```

## Structure

- **One product, one angle, 3-5 hooks.** Hooks are what you test. The first
  three seconds carry most of the variance.
- **Broad targeting.** In 2026 the algorithm beats your interest stack almost
  everywhere. Narrow audiences mostly buy you higher CPMs.
- **One ad set.** Splitting a small budget across five ad sets gives you five
  results too thin to read.
- **Leave it alone.** Every edit restarts the learning phase. If you cannot
  resist touching it, close the tab.

## Checkpoints

| Spend | Look at | Act if |
|---|---|---|
| 25% | CTR, CPM | CTR under 0.8% - swap creative, do not touch budget |
| 50% | Add-to-cart rate | Under 5% with 25+ landing views - the page is the problem |
| 75% | Checkout + purchase rate | Carts but no purchases - price shock or payment friction |
| 100% | Cost per purchase | Run the decision engine and obey it |

```bash
python3 -m dropship test update <id> --spend 110 --impressions 24000 \
  --clicks 480 --landing-views 410 --add-to-carts 38 --checkouts 15 --purchases 4
```

## Reading the funnel

The funnel tells you *what* is broken, which is the difference between "wrong
product" and "wrong offer" - a distinction worth hundreds of dollars.

| Broken stage | What it means | What to change |
|---|---|---|
| CTR | The ad is not earning the click | Hooks, creative format, audience breadth |
| Landing page views | They click and leave before it loads | Page speed. Test on 4G, target under 2.5s |
| Add to cart | Interest does not become intent | Demo above the fold, reviews, benefit-led copy |
| Checkout started | Price shock | Show shipping early, add trust, raise perceived value |
| Purchase | Checkout is leaking | Express wallets, fewer fields, no forced accounts |

**Good CTR with no add-to-carts is the most useful failure you can get.** It
means the ad works and the offer does not - a rebuild, not a burial. The engine
returns ITERATE rather than KILL for exactly this case.

## The decisions

- **KILL** - the whole plausible CPA range is above breakeven. Turn it off
  today. Spending more only raises the price of the same answer.
- **ITERATE** - a specific funnel stage is broken. One rebuild, then decide.
- **HOLD** - profitable but below target. Do not raise budget; raise AOV.
- **SCALE** - even the pessimistic case beats target. Step up 20-25%, hold 48h.
- **KEEP_TESTING** - not enough data yet. Change nothing.

## Creative

Creative is the only input with uncapped upside. Bids, audiences and placements
have ceilings; a better hook does not.

- Shoot 3 hooks for every 1 body. The hook is the test.
- Vertical, phone-shot, sound-off legible. Polish reduces trust on social.
- The first frame must contain the product or the problem. No logos, no intro.
- One continuous shot of it working beats any edit.
- Refresh hooks when frequency passes ~2.5 on a cold audience.

See the generated angle library and UGC brief:

```bash
python3 -m dropship listing "Product Name" --out brief.md
```

## Mistakes that cost the most

1. **Killing at 1x breakeven CPA.** You bought noise and called it a signal.
2. **Editing mid-test.** The learning phase restarts and your spend bought nothing.
3. **Scaling by doubling.** Large budget jumps re-enter learning and reset a
   working campaign. Step, hold, verify.
4. **Trusting platform ROAS.** It attributes generously. Reconcile against the
   bank with `dropship kpi`.
5. **Testing five products at once on a small budget.** Five unreadable results
   cost more than one clear answer.
