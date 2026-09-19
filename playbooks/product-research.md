# Product research

You are not looking for a product you like. You are looking for a product that
can carry an ad budget, be demonstrated in three silent seconds, and arrive
before the customer regrets it.

```bash
python3 -m dropship product score --all
```

## The gates (no score rescues a failed gate)

**Margin multiple below 2.5x.** At 2x, half your revenue is cost before a
single click. There is no campaign that fixes arithmetic.

**Contribution margin under ~$15.** Percentage margin is a trap: 70% of $12 is
$8.40, and you cannot buy a customer for $8.40 on paid social in most markets.

**Delivery over ~18 days.** Every extra week converts directly into refund and
chargeback rate. A 30-day product is not cheap to sell, it is expensive to
refund.

**Restricted or regulated categories.** Supplements, weapons, vape, medical
claims, anything CBD. A banned ad account takes your pixel data with it, and
the pixel is usually worth more than the campaign.

**Trademark or counterfeit risk.** An IP complaint can take down the store, the
ad account and the payment processor in the same week. No product is worth that.

## The score (what actually predicts a winner)

| Weight | Component | What it really asks |
|---|---|---|
| 25% | Margin | Can this carry an ad budget? |
| 18% | Demand | Is anybody already looking for it? |
| 16% | Creative potential | Does it sell itself on video? |
| 14% | Competition | How crowded is the auction? |
| 12% | Fulfilment | How fast and how reliably does it land? |
| 8% | Return risk | How often do you eat the cost? |
| 7% | Durability | Evergreen, or a six-week window? |

**Creative potential is the one people underweight.** On paid social the ad is
the shop. A product that demonstrates itself needs no persuasion; one that has
to be explained needs a budget you do not have. If you cannot show the value in
three seconds with the sound off, the product is harder than it looks.

## Where to actually look

Good sources share one property: they show you what is *already selling*, not
what somebody wants to sell you.

- **TikTok / Reels, sorted by engagement, filtered to recent.** Comments asking
  "where do I get this" are the highest-quality demand signal that exists.
- **Amazon Movers & Shakers, and the 3-star reviews of bestsellers.** Three-star
  reviews are where the unmet need is written down in the customer's own words.
- **Reddit and niche forums.** Look for recurring complaints, not product
  mentions. A complaint is a product brief.
- **Google Trends, 5-year view.** Distinguishes a trend from a fad. You want
  the rising line, not the spike that already happened.
- **Competitors' ad libraries.** An ad running unchanged for 60+ days is
  profitable. That is the only free profitability data you will ever get.

Avoid: "winning product" lists (by the time it is on a list, the auction is
full), AliExpress best-sellers (saturated by construction), and anything a
course is selling you.

## Scoring honestly

The system is only as good as your inputs, and the failure mode is always the
same: you like the product, so `demand` becomes 9 and `competition` becomes 3.
Now the score agrees with you and tells you nothing.

Guard against it by writing the evidence next to the number:

- `demand 9` - "12 TikToks over 500k views in the last 30 days"
- `competition 3` - "only 4 advertisers in the ad library"
- `creative 9` - "the before/after is visible in one unbroken shot"

If you cannot write the evidence, the number is a feeling. Score it 5.

## Pricing

Do this before you launch, not after the first slow week.

```bash
python3 -m dropship econ --price 39.99 --cogs 7.10 --ship-cost 2.90
```

- Start at 3-4x landed cost. Most new stores underprice, because price is the
  scariest lever and cutting it feels like doing something.
- Check the price ladder. A 20% discount on a 3x product can push breakeven
  ROAS up by a third - you have to find 33% more efficiency to stand still.
- Build the upsell before launch, not after. Raising AOV 15% moves your target
  ROAS further than any bid adjustment you will ever make.
- Free shipping over a threshold set just above your core price pulls single
  orders into bundles. It is the cheapest AOV lever there is.

## The shortlist

Test A-tier first, always. A B-tier product tested because it was your idea is
how a month disappears. Keep 3-5 scored and approved so a kill never leaves a
test slot empty - the idle slot is the real cost of a bad week.
