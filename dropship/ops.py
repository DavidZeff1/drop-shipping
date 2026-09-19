"""Order operations: SLA breaches, the action queue, and support macros.

Fulfilment is where dropshipping margin quietly disappears. A parcel with no
tracking for six days becomes a WISMO ticket, then a refund, then a chargeback
- and a chargeback costs you the goods, the revenue and a fee, roughly three
times the damage of a plain refund.

So this module watches the clock rather than the inbox: it flags orders that
are drifting *before* the customer notices, and ranks them by what the failure
will actually cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import ORDER_STATES, Config, Order

# Days after which each state is a problem. Tight on purpose: every one of
# these thresholds sits well inside the chargeback window.
SLA = {
    "place_order": 1,      # paid -> placed with supplier
    "tracking": 3,         # placed -> tracking number exists
    "transit_grace": 5,    # promised delivery -> "this is now late"
    "review_request": 3,   # delivered -> ask for a review
    "stuck_tracking": 7,   # tracking exists but hasn't moved
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _days_since(iso: str, today: date | None = None) -> int | None:
    if not iso:
        return None
    try:
        then = date.fromisoformat(iso)
    except ValueError:
        return None
    return ((today or date.today()) - then).days


@dataclass
class Action:
    order_id: str
    external_id: str
    severity: str           # critical / high / medium / low
    issue: str
    why_it_matters: str
    do_this: str
    macro: str = ""
    age_days: int = 0
    value: float = 0.0

    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER.get(self.severity, 9), -self.value, -self.age_days)


def check_order(order: Order, config: Config, today: date | None = None
                ) -> list[Action]:
    """Every way this one order can be drifting toward a refund."""
    actions: list[Action] = []
    age = _days_since(order.ordered_date, today) or 0

    def add(sev, issue, why, do, macro=""):
        actions.append(Action(
            order_id=order.id, external_id=order.external_id or order.id,
            severity=sev, issue=issue, why_it_matters=why, do_this=do,
            macro=macro, age_days=age, value=order.revenue,
        ))

    if order.status in ("refunded", "cancelled"):
        return actions

    if order.status == "chargeback":
        add("critical",
            "Chargeback opened",
            "You lose the revenue, the goods and a fee. Response windows are "
            "short and missing one is an automatic loss.",
            "Submit evidence today: tracking with delivery confirmation, the "
            "order confirmation email, your published policies and any support "
            "thread showing you responded.",
            "chargeback_rebuttal")
        return actions

    if order.status in ("received", "awaiting_supplier"):
        if age > SLA["place_order"]:
            add("critical",
                f"Paid {age} days ago, never placed with the supplier",
                "Every day here is added to a delivery window the customer has "
                "already been promised. This is the cheapest failure to prevent "
                "and the most expensive to ignore.",
                "Place it with the supplier now, then find out why it was missed.")
        else:
            add("low", "Awaiting supplier order",
                "Within SLA, but the clock is running.",
                "Place with supplier today.")

    elif order.status in ("placed", "awaiting_tracking") and not order.tracking_number:
        # Placed today is 0 days, not "unknown" - only a missing date falls back.
        placed = _days_since(order.placed_date, today)
        since = age if placed is None else placed
        if since > SLA["tracking"]:
            add("high",
                f"No tracking {since} days after placing",
                "No tracking means no chargeback defence. Without delivery "
                "proof you lose the dispute by default.",
                "Chase the supplier for a tracking number today. If they cannot "
                "produce one in 24h, refund proactively - it is cheaper than the "
                "chargeback.",
                "delay_apology")

    elif order.status == "in_transit":
        expected = order.promised_days + SLA["transit_grace"]
        if age > expected:
            add("high",
                f"{age} days out, promised {order.promised_days:.0f}",
                "Past the promise is when refunds turn into disputes. Reaching "
                "out first converts most of them back into refunds.",
                "Email the customer before they email you. Offer a partial "
                "refund or a reship and let them choose.",
                "delay_apology")
        elif order.tracking_date:
            stuck = _days_since(order.tracking_date, today) or 0
            if stuck > SLA["stuck_tracking"]:
                add("medium",
                    f"Tracking has not updated in {stuck} days",
                    "Stalled tracking usually means a lost parcel, and it always "
                    "means an anxious customer.",
                    "Open a claim with the carrier and tell the customer you have "
                    "done so. Being told is most of what they want.",
                    "wismo")

    elif order.status == "delivered":
        since = _days_since(order.delivered_date, today) or 0
        if since >= SLA["review_request"] and "review" not in order.notes.lower():
            add("low",
                "Delivered, no review requested",
                "Photo reviews raise conversion more than any copy change, and "
                "they cost nothing.",
                "Send the review request and log it in notes.",
                "review_request")

    if order.issue:
        add("high",
            f"Reported issue: {order.issue}",
            "An unresolved complaint is a chargeback with a delay on it.",
            "Resolve within 24h. Refund or reship beats arguing - the goods cost "
            "less than the dispute.",
            "damaged_item")

    return actions


def update_order(order: Order, status: str | None = None,
                 tracking_number: str | None = None, issue: str | None = None,
                 review_requested: bool = False, today: date | None = None) -> None:
    """Record a fulfilment step, stamping the dates the SLA checks read.

    ``None`` leaves a field alone. Without the stamps, an order marked placed
    today would be judged against the day it was paid for.
    """
    stamp = (today or date.today()).isoformat()
    if status is not None and status not in ORDER_STATES:
        raise ValueError(f"unknown order status '{status}'. "
                         f"Options: {', '.join(ORDER_STATES)}")
    target = order.status if status is None else status

    if tracking_number is not None:
        tracking_number = tracking_number.strip()
        if tracking_number != order.tracking_number:
            # Tracking on a placed order means it has shipped, and only an
            # order in transit is watched for late or stalled delivery.
            if (tracking_number and not order.tracking_number
                    and target == order.status
                    and target in ("placed", "awaiting_tracking")):
                target = "in_transit"
            order.tracking_number = tracking_number
            order.tracking_date = stamp if tracking_number else ""

    order.status = target
    if target in ("placed", "awaiting_tracking", "in_transit", "delivered") \
            and not order.placed_date:
        order.placed_date = stamp
    if target == "delivered" and not order.delivered_date:
        order.delivered_date = stamp
    if issue is not None:
        order.issue = issue.strip()
    if review_requested and "review" not in order.notes.lower():
        order.notes = f"{order.notes}\nreview requested {stamp}".strip()


def action_queue(orders: list[Order], config: Config, today: date | None = None
                 ) -> list[Action]:
    """Everything that needs a human, worst first."""
    actions: list[Action] = []
    for order in orders:
        actions.extend(check_order(order, config, today))
    actions.sort(key=lambda a: a.sort_key())
    return actions


def fulfilment_health(orders: list[Order], config: Config,
                      today: date | None = None) -> dict:
    """Fulfilment metrics that predict next month's refund rate."""
    live = [o for o in orders if o.status not in ("cancelled",)]
    total = len(live) or 1
    delivered = [o for o in live if o.status == "delivered"]

    times = []
    for o in delivered:
        start, end = o.ordered_date, o.delivered_date
        if start and end:
            d = _days_since(start, date.fromisoformat(end)) if end else None
            if d is not None and d >= 0:
                times.append(d)

    breaches = [a for a in action_queue(live, config, today)
                if a.severity in ("critical", "high")]
    untracked = [o for o in live
                 if o.status in ("placed", "awaiting_tracking") and not o.tracking_number]

    return {
        "orders": len(live),
        "delivered": len(delivered),
        "delivery_rate": len(delivered) / total,
        "avg_delivery_days": sum(times) / len(times) if times else 0.0,
        "max_delivery_days": max(times) if times else 0.0,
        "refund_rate": len([o for o in orders if o.status == "refunded"]) / total,
        "chargeback_rate": len([o for o in orders if o.status == "chargeback"]) / total,
        "sla_breaches": len(breaches),
        "untracked": len(untracked),
        "on_time_rate": (len([t for t in times if t <= config.max_delivery_days])
                         / len(times)) if times else 0.0,
    }


# ------------------------------------------------------------- CS macros ----
#
# Written to defuse rather than to argue. In a dispute the bank reads the tone
# as well as the facts, and a customer who feels heard rarely calls their bank.

MACROS: dict[str, dict[str, str]] = {
    "wismo": {
        "name": "Where is my order",
        "subject": "Your order {order_id} - here is exactly where it is",
        "body": """Hi {name},

Thanks for checking in. Your order shipped on {ship_date} and is currently
{status}. Here is the tracking link: {tracking_url}

Based on where it is now, it should reach you around {eta}.

International parcels often sit for a few days at a customs checkpoint without
the tracking updating. That is normal and it does not mean the parcel is lost.

If it has not arrived by {escalation_date}, reply to this email and I will
either reship it or refund you in full - your choice, no questions asked.

{signature}""",
    },
    "delay_apology": {
        "name": "Proactive delay apology",
        "subject": "Your order {order_id} is running late - here is what I am doing",
        "body": """Hi {name},

I am reaching out before you had to chase me: your order is taking longer than
the {promised_days} days we quoted, and that is on us.

Here is where it actually is: {status}

Two options, whichever you prefer:
  1. I refund {partial_refund} now for the delay and the order keeps coming
  2. I cancel and refund the full {total} today

Just reply with 1 or 2. If I do not hear from you by {deadline} I will apply
option 1 automatically, because you should not have to chase this twice.

{signature}""",
    },
    "damaged_item": {
        "name": "Damaged or faulty on arrival",
        "subject": "Sorry about your order {order_id} - sorting it now",
        "body": """Hi {name},

That should not have happened and I am not going to make you prove it.

A replacement is going out today at no cost - you do not need to return the
damaged one. Tracking will follow within {handling_days} business days.

If you would rather have a refund instead, reply and I will process it the same
day.

Thank you for telling me rather than just leaving a review - it is how the
faulty batch gets caught.

{signature}""",
    },
    "wrong_item": {
        "name": "Wrong item received",
        "subject": "Wrong item on order {order_id} - fixing it today",
        "body": """Hi {name},

That is our mistake. The correct item is going out today and you do not need to
send the wrong one back - keep it or pass it on.

Tracking follows within {handling_days} business days.

{signature}""",
    },
    "return_request": {
        "name": "Return request",
        "subject": "Return for order {order_id}",
        "body": """Hi {name},

No problem at all. Here is how it works:

  - Send it back to {return_address} within {return_window} days
  - Include the order number {order_id} in the parcel
  - Once it arrives I refund {refund_amount} within 2 business days

If the item arrived damaged or was not what we described, do not send it back -
reply and tell me, and I will refund you straight away.

{signature}""",
    },
    "refund_approved": {
        "name": "Refund approved",
        "subject": "Refunded - order {order_id}",
        "body": """Hi {name},

Your refund of {refund_amount} has been processed. It goes back to the original
payment method and usually appears within 5-10 business days, depending on your
bank.

Sorry this one did not work out. If you tell me what went wrong I will actually
use it.

{signature}""",
    },
    "chargeback_rebuttal": {
        "name": "Chargeback evidence pack",
        "subject": "Dispute evidence - order {order_id}",
        "body": """Evidence for dispute on order {order_id}
(attach each item below as a separate file, in this order)

1. Order confirmation with timestamp, IP address and billing/shipping addresses
2. Proof of delivery: carrier tracking showing DELIVERED plus the delivery date
3. Terms accepted at checkout, with the timestamp of acceptance
4. The published refund and shipping policy as displayed on the product page
5. The full support thread showing every response and how fast it was sent
6. The AVS/CVV result from the original authorisation
7. Product page screenshot showing the delivery estimate the customer saw

Summary for the reviewer:
The customer placed order {order_id} on {order_date} for {total}. The item was
delivered on {delivered_date}, confirmed by carrier tracking {tracking_number}.
The delivery estimate of {promised_days} days was displayed before purchase and
was met. Our refund policy was available at checkout, and no refund request was
received through any support channel before this dispute was filed.

Note: submit inside the deadline even if the evidence is thin. A missed
deadline is an automatic loss; weak evidence sometimes wins.""",
    },
    "review_request": {
        "name": "Review request",
        "subject": "How is the {product_name} working out?",
        "body": """Hi {name},

Your {product_name} arrived a few days ago - how is it going?

If it is doing the job, a short review with a photo genuinely helps other
people decide: {review_url}

And if it is not doing the job, reply to this email instead of leaving a
review and I will make it right.

{signature}""",
    },
    "stock_delay": {
        "name": "Out of stock",
        "subject": "Order {order_id} - a choice to make",
        "body": """Hi {name},

The {product_name} sold faster than we restocked, and yours is affected.

Next batch ships {restock_date}. Your options:
  1. Wait - I will add {incentive} to the order for the trouble
  2. Full refund today, no need to explain

Reply with 1 or 2. No reply by {deadline} and I will refund you automatically.

{signature}""",
    },
}


def render_macro(key: str, **fields) -> str:
    """Fill a macro. Unfilled slots stay visible as {slot} on purpose."""
    macro = MACROS.get(key)
    if not macro:
        raise KeyError(f"unknown macro '{key}'. Options: {', '.join(sorted(MACROS))}")

    class _Keep(dict):
        def __missing__(self, k):
            return "{" + k + "}"

    subject = macro["subject"].format_map(_Keep(fields))
    body = macro["body"].format_map(_Keep(fields))
    return f"Subject: {subject}\n\n{body}"
