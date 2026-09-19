# Customer service

Support is not a cost centre in dropshipping. It is the thing standing between
a late parcel and a chargeback that costs you three times as much.

```bash
python3 -m dropship cs                 # list templates
python3 -m dropship cs wismo --field name=Alex --field order_id=1042
```

## The economics

| Outcome | What it costs you |
|---|---|
| Kept order | Nothing - full margin |
| Refund | Revenue + goods + the kept processing fee |
| Chargeback | All of that, plus a ~$15 fee, plus rate damage |

A refund is roughly a third of the cost of a dispute. So whenever the choice is
between refunding now and arguing, refund. You are not conceding; you are
buying the cheaper of two outcomes.

## The rules

1. **Reply inside 24 hours.** Always. The single strongest predictor of whether
   a frustrated customer contacts you or their bank.
2. **Contact them first.** A proactive delay email converts most would-be
   disputes back into ordinary refunds. `dropship orders sla` finds them before
   the customer notices.
3. **Never argue about damage.** Replace or refund. The goods cost less than
   the dispute, and far less than the review.
4. **Offer a choice.** "Partial refund and keep waiting, or full refund now" -
   people who choose do not dispute.
5. **Set a default.** "If I do not hear back by Friday I will refund you
   automatically." Nobody should have to chase you twice.
6. **Log it on the order.** Support history is chargeback evidence.

## The templates

| Key | When |
|---|---|
| `wismo` | Where is my order |
| `delay_apology` | Proactive, before they ask |
| `damaged_item` | Arrived broken - replace, no return required |
| `wrong_item` | Wrong product sent |
| `return_request` | Standard return |
| `refund_approved` | Refund processed |
| `chargeback_rebuttal` | Dispute evidence pack |
| `review_request` | 3 days after delivery |
| `stock_delay` | Out of stock |

Unfilled `{slots}` stay visible on purpose. A placeholder you can see beats a
guess you cannot.

## Prevent the ticket instead

Most support volume is created at checkout, not after it.

- Accurate delivery estimate on the product page and in the confirmation email.
- A confirmation email that explains what happens next and when.
- Tracking sent automatically the moment it exists.
- An "it may sit at customs without updating" line in the shipping email.
  One sentence, and it removes a large share of WISMO tickets.
- A visible returns policy. Ambiguity becomes a dispute.

## Turning support into margin

- Ask for a photo review 3 days after delivery. Photo reviews lift conversion
  more than any copy change you will make.
- When you refund, ask what went wrong - and actually use it. Your refund
  reasons are the most honest product research you will ever get.
- Cross-sell at 21 days post-delivery. A repeat customer costs nothing to
  acquire, which is the only durable answer to rising ad costs.
