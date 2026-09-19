# Compliance and risk

Not legal advice. This is a checklist of the things that end dropshipping
businesses suddenly rather than slowly - a banned ad account, a frozen
processor, an IP complaint. Rules differ by country and change often; confirm
the current position for your own market, and take proper advice on tax.

## The four single points of failure

You are one decision away from losing each of these, and losing any one stops
the business the same day:

1. **The ad account.** Policy violations, repeated disapprovals, or a spike in
   negative feedback. Losing it takes your pixel history too, which is often
   worth more than the account.
2. **The payment processor.** A chargeback rate above ~1% triggers monitoring;
   above ~2% brings account closure and held funds.
3. **The store platform.** IP complaints and consumer-protection reports.
4. **The supplier.** A stockout or a suspension with no second source.

Every item below exists to protect one of those four.

## Advertising claims

- Do not claim what you cannot evidence. Health, income, safety and "cures"
  are the fastest routes to both a ban and a regulator.
- Never fabricate reviews, ratings, review counts or scarcity timers. In the US
  the FTC's rule on fake reviews carries civil penalties; the UK's DMCC Act and
  the EU's Omnibus Directive treat it as a banned practice. These are actively
  enforced.
- "Before and after" imagery must be the same subject under the same
  conditions, or it is a misleading claim.
- Countdown timers that reset on refresh are a false-urgency violation almost
  everywhere. Remove them.
- Disclose paid partnerships and ambassador content clearly.

## Delivery promises

- **Show the real delivery estimate before checkout, not after.** This is the
  single highest-leverage compliance item because it is also the single highest
  -leverage refund-prevention item.
- In the US, the FTC Mail Order Rule requires you to ship within the time
  promised, or within 30 days if you promised nothing - and to offer a cancel
  option if you cannot. "Processing time" does not pause the clock.
- The EU and UK give consumers a 14-day right to withdraw, starting from
  delivery, on most goods bought at distance. Your policy has to say so.
- If it will take 15 days, say 15 days. Customers accept a long wait they
  agreed to and dispute a short one they did not get.

## Tax

Get advice; this is the area where cheerful amateurism becomes expensive.

- **US sales tax** is per-state, driven by economic nexus thresholds. You can
  acquire an obligation in a state you have never visited simply by volume.
- **EU VAT / IOSS** applies from the first euro on imports. Without IOSS
  registration your customers get surprise handling fees at the door, which
  converts directly into refunds and chargebacks.
- **UK VAT** applies to imported consignments at the point of sale under £135.
- Customs and duty: make clear who pays. "DDU" surprises are a refund engine.

## Product safety

- CE / UKCA marking where required. Electronics, anything for children, and
  anything touching skin carry real liability.
- Batteries, magnets, lasers and cosmetics have specific rules and shipping
  restrictions.
- Keep supplier documentation. If you cannot produce it on request, you are the
  manufacturer as far as a regulator is concerned.
- Product liability insurance is cheap next to one incident.

## Data

- GDPR and UK GDPR apply to EU/UK customers regardless of where you are.
- Privacy policy, cookie consent, and a real route to deletion.
- Do not export customer data to a supplier beyond what fulfilment needs.
- CCPA/CPRA for California residents.

## Chargebacks

Chargebacks are the mechanism by which all of the above turns into a closed
account. The thresholds are not guidelines.

| Rate | What happens |
|---|---|
| Under 0.5% | Healthy |
| 0.5-1% | Watch it closely |
| Over 1% | Monitoring programmes, reserves, higher fees |
| Over 2% | Account closure, funds held for months |

**Prevention, in order of effect:**

1. Accurate delivery estimates, shown before payment.
2. Tracking on every order, with proactive updates.
3. Support replies inside 24 hours.
4. A recognisable billing descriptor - "unknown charge" is a common cause.
5. Refund proactively on anything late. A refund costs roughly a third of a
   dispute, and it is the cheapest insurance available.

```bash
python3 -m dropship cs chargeback_rebuttal --field order_id=1042
```

Submit evidence even when it is thin. A missed deadline is an automatic loss;
weak evidence sometimes wins.

## Store hygiene

- Real business name, real contact details, a working phone or address.
- Terms, refund, shipping and privacy policies visible before checkout.
- A support email that is monitored, not a form nobody reads.
- No stock photos of "the team". It reads as a scam and it is the first thing
  a suspicious customer checks.
