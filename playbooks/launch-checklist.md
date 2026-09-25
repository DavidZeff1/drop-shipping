# Launch checklist

These steps depend on real accounts, supplier evidence and facts about your
business. The software can prepare and check pages; it cannot verify those facts.

The order matters. It is arranged so that the cheapest way to find out you
should stop comes first, and the first bill comes last.

---

## 1. Decide what you are selling before you buy anything

```bash
python3 -m dropship product add --name "..." --price 39.99 --cogs 7.10 \
  --ship-cost 2.90 --delivery-days 11
```

- [ ] The product clears the gates (`product score` says so, not you)
- [ ] You can say, in one sentence, who buys it and what annoyance it removes
- [ ] You can show it working in three silent seconds on video

If any of those is no, stop here. Everything below costs money.

## 2. A supplier who has actually shipped you one

- [ ] Two suppliers quoted, not one
- [ ] **A sample ordered to your own address, as a normal customer**
- [ ] Timed: order placed → tracking issued → delivered
- [ ] Photographed the parcel exactly as it arrived
- [ ] Asked what happens on a damaged item, in writing
- [ ] Their answer arrived in hours, not days

`python3 -m dropship supplier checklist` is the long version. Skipping this is
the single most common way people discover, at volume, that the tracking never
updates.

## 3. The answers your shop pages need

Every `{slot}` in the generated pages is one of these. Save answers once in
the private `<store>.content.json` file; use `site --content-template <file>`
to create it without overwriting existing answers:

- [ ] Returns window, and **who pays return postage**
- [ ] How fast you answer support, and the address you answer from
- [ ] Handling time before it ships
- [ ] Countries you ship to
- [ ] Your business name and address, as you will put them on the page
- [ ] How long you keep order records

These are not paperwork. They are what a bank reads when someone disputes a
charge, and what a payment provider reads before it approves you at all.

## 4. A payment provider

- [ ] An eligible payment account opened with the correct business details;
      for this Israel-based launch, follow the [Israel plan](israel-launch.md)
- [ ] Bank account connected, identity verified
- [ ] **Ask what your payout delay is, and whether there is a rolling reserve**
- [ ] One payment link per product, at the price your page shows
- [ ] Each link's confirmation page pointed at your own `thanks.html`

```bash
python3 -m dropship config set payout_delay_days 7      # whatever they said
python3 -m dropship storefront "..." --pay https://...
```

The payout delay is the number that decides how fast you can scale. New
accounts are often 7 days, sometimes 21. Ask before you need to know.

## 5. The shop itself

```bash
python3 -m dropship --store data/store-launch.json site --check
python3 -m dropship --store data/store-launch.json site --ready --out site-release
```

- [ ] Photos in: three or more per product, under 300 KB each
- [ ] Every `{slot}` answered in the private content file, then regenerated
- [ ] Policy pages read like a person wrote them for this shop
- [ ] Opened on your own phone, on mobile data, and it drew in under 2.5s
- [ ] A domain bought and pointed at the host
- [ ] A sandbox purchase and refund completed using the provider's supported
      test accounts; any necessary live payment is separately authorized

Confirm the correct item, quantity, currency, total and delivery address; receipt,
order record, refund and return URL must work. Check the exported fields before
importing: a payment activity CSV is not necessarily a supported order export.
The local app does not retain a full delivery address; use the verified provider
order record for fulfillment. Visiting `thanks.html` alone proves no payment.

## 6. Only now, traffic

```bash
python3 -m dropship test plan "..." --start
```

- [ ] Ad account and pixel live, purchase event firing (check it on your test order)
- [ ] Test budget is the one the tool calculated, not the one that feels safe
- [ ] Hypothesis written down before launch
- [ ] Calendar reminder to check it at the checkpoint, not hourly

## 7. The day after the first sale

- [ ] Order placed with the supplier the same day
- [ ] Tracking emailed to the customer
- [ ] `import orders` run against the payment provider's CSV
- [ ] `python3 -m dropship today` run before you open the ad manager

---

## What this does not cover

Tax registration, company formation, and whether you need either where you
live. Product liability and safety marks for what you are selling. Data
protection registration. None of it is exotic, all of it is local, and none of
it is advice this repository can give you. See
[compliance-and-risk.md](compliance-and-risk.md) for where the sharp edges are.

## The honest gate

If you have worked down this list and cannot tick section 1, you have saved
yourself the cost of sections 2 to 7. That is the list doing its job.
