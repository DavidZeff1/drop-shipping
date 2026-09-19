# Daily operating rhythm

The order below is not preference. It is cost: a fulfilment failure costs more
than an ad decision, which costs more than a creative idea. Work down, never up.

```bash
python3 -m dropship today
```

## Every morning (20 minutes)

**1. Clear the critical queue first.** Before the ad manager. Before email.

```bash
python3 -m dropship orders sla
```

An unplaced paid order is the cheapest failure to prevent and the most
expensive to ignore: it becomes a late delivery, then a refund, then a
chargeback that costs you the goods, the revenue and a fee - roughly three
times the damage of a plain refund.

**2. Act on any test that has reached a verdict.**

```bash
python3 -m dropship test decide --product "..."
```

If it says KILL, kill it today. The single most expensive habit in this
business is giving a dead test one more day, repeatedly, for a fortnight.

**3. Check cash before raising any budget.**

```bash
python3 -m dropship cash max-spend
```

**4. Reply to support.** Under 24 hours, always. A customer who feels heard
almost never calls their bank; a customer who waits three days often does.

## Every evening (10 minutes)

Update the day's ad numbers and let the engine decide.

```bash
python3 -m dropship test update <id> --spend 140 --purchases 5 --clicks 520
```

Do not act on a single day in isolation unless the decision engine says to.
Daily variance in a small account is enormous, and reacting to it is the main
way people destroy campaigns that were working.

## Every Monday (45 minutes)

```bash
python3 -m dropship kpi --days 7
python3 -m dropship kpi --days 30
python3 -m dropship dashboard && open dashboard.html
python3 -m dropship doctor
```

- Reconcile the ad platform against your bank. Platforms attribute generously;
  blended ROAS (all revenue over all ad spend) cannot be flattered.
- Update `refund_rate` and `chargeback_rate` from measured data once you have
  50+ orders. Until you do, every breakeven in the system is a guess.
- Launch one new test. An idle test slot is the real cost of a slow week.
- Brief three new creatives. Creative is the only input with uncapped upside.

## Every month

- Re-score the portfolio: `product score --all`.
- Re-quote suppliers. Prices drift up quietly and nobody sends a notice.
- Review the price ladder: `econ <product>`. Most stores are underpriced,
  because price is the lever people are most afraid of and it moves margin
  more than any bid change.
- Ask the boring question: is this profitable after paying myself?

## The four rules

1. **Fulfilment before ads.** Always. No exceptions.
2. **One variable at a time.** Two changes produce no information.
3. **Obey the decision engine.** You built it precisely so that tired-you at
   9pm cannot overrule calm-you at the point of a real decision.
4. **Write the hypothesis before launch.** If you cannot state what would
   prove you wrong, you are not testing. You are hoping.
