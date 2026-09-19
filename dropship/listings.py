"""Listing and ad copy generation.

Deterministic, template-driven, and structured around the angle - because the
angle, not the wording, is what makes a dropshipping ad work. Ten angles for
the same product beat ten rewrites of the same angle every time.

Output is a working draft you edit, not copy you paste unread. Every claim you
keep is a claim you are legally responsible for (see playbooks/compliance.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .economics import UnitEconomics
from .models import Product

# The ten angles that carry most dropshipping winners. Test angles against each
# other first; only once an angle wins do variations of it matter.
ANGLES = {
    "problem_agitate": {
        "name": "Problem / Agitate / Solve",
        "hook": "If {problem}, you already know how {consequence}.",
        "use_when": "The pain is obvious and the audience already feels it.",
        "body": "Most people put up with {problem} because the alternatives are "
                "expensive or awkward. {product} fixes it in {timeframe} "
                "without {objection}.",
    },
    "before_after": {
        "name": "Before / After",
        "hook": "This took {timeframe}. Watch.",
        "use_when": "The result is visible on camera. The single strongest "
                    "format on paid social.",
        "body": "No edits, no tricks - just {product} doing the thing it was "
                "built for.",
    },
    "us_vs_them": {
        "name": "Us vs Them",
        "hook": "Why pay {competitor_price} for something that does less?",
        "use_when": "A well-known, more expensive alternative exists.",
        "body": "{product} does the same job for {price}, and you get it in "
                "{delivery_days} days.",
    },
    "social_proof": {
        "name": "Social proof",
        "hook": "{review_count} people bought this last month. Here is why.",
        "use_when": "You have real reviews. Never fabricate this one - it is "
                    "both illegal and the easiest claim to disprove.",
        "body": "Rated {rating} by verified buyers who had the same {problem}.",
    },
    "curiosity": {
        "name": "Curiosity gap",
        "hook": "I did not expect this to actually work.",
        "use_when": "The mechanism is unusual or surprising.",
        "body": "Here is what happens when {mechanism}.",
    },
    "demonstration": {
        "name": "Silent demonstration",
        "hook": "(no words - the product does the talking in 3 seconds)",
        "use_when": "Wow factor is high. Works with sound off, which is how "
                    "most people scroll.",
        "body": "One continuous shot. No cuts until the result lands.",
    },
    "founder": {
        "name": "Founder story",
        "hook": "I built this because {problem} and nothing on the market fixed it.",
        "use_when": "You want a brand, not a one-off sale.",
        "body": "Honest, unpolished, filmed on a phone. Polish lowers trust here.",
    },
    "objection": {
        "name": "Objection handling",
        "hook": "\"Does it actually work?\" - fair question.",
        "use_when": "Retargeting warm traffic that did not buy.",
        "body": "{guarantee}. If it does not do what we say, you are covered.",
    },
    "use_case": {
        "name": "Specific use case",
        "hook": "If you {situation}, this was made for you.",
        "use_when": "Broad targeting is too expensive; you need a narrow hook.",
        "body": "Built for exactly one job: {job}.",
    },
    "seasonal": {
        "name": "Occasion / gift",
        "hook": "The one gift they will not put in a drawer.",
        "use_when": "Q4, or a gifting-shaped product.",
        "body": "Order by {cutoff_date} to arrive in time.",
    },
}

UGC_BRIEF = """UGC brief - {product_name}

Length: 20-30 seconds. Vertical 9:16. Filmed on a phone, not a camera.

0-3s   HOOK. {hook}
       Face on camera or the product already in motion. No logos, no intro.
3-8s   PROBLEM. Name the annoyance in the viewer's own words.
8-18s  DEMONSTRATION. One continuous shot of it working. This is the ad.
18-25s PROOF. A number, a review, or a visible result.
25-30s CTA. "{cta}" - said plainly, once.

Rules
  - Sound off by default: the video must sell with subtitles alone.
  - No stock footage. It reads as an ad in under a second.
  - Shoot 3 hooks for every 1 body. Hooks are what you actually test.
  - Do not claim what you cannot prove. See playbooks/compliance.md.
"""


@dataclass
class Listing:
    product_name: str
    titles: list[str] = field(default_factory=list)
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)
    description: str = ""
    faq: list[tuple[str, str]] = field(default_factory=list)
    trust_blocks: list[str] = field(default_factory=list)
    shipping_note: str = ""
    upsell_ideas: list[str] = field(default_factory=list)
    ad_hooks: list[dict] = field(default_factory=list)
    ugc_brief: str = ""
    email_flow: list[dict] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)


def _placeholder(field_name: str) -> str:
    return "{" + field_name + "}"


def generate(product: Product, ue: UnitEconomics,
             problem: str = "", outcome: str = "") -> Listing:
    """Build a full listing draft plus an angle test matrix.

    Anything in {braces} is a slot you must fill. They are left visible on
    purpose: a placeholder you can see is better than a guess you cannot.
    """
    name = product.name
    problem = problem or _placeholder("the problem it solves")
    outcome = outcome or _placeholder("the outcome the customer wants")
    delivery = f"{product.delivery_days:.0f}"

    listing = Listing(product_name=name)

    listing.titles = [
        f"{name} - {outcome}",
        f"{name}: {problem}, Solved",
        f"The {name} That Actually Works",
        f"{name} | Ships in {delivery} Days",
    ]
    listing.subtitle = f"{outcome} without {_placeholder('the usual trade-off')}."

    listing.bullets = [
        f"Fixes {problem} in {_placeholder('timeframe')} - no {_placeholder('common hassle')}",
        f"Built for {_placeholder('specific situation')}, not a generic one-size version",
        f"{_placeholder('material or mechanism')} - the part cheaper versions skip",
        f"Arrives in {delivery} days with tracking from the moment it ships",
        f"{_placeholder('guarantee, e.g. 30-day returns')} - if it does not work, you are covered",
    ]

    listing.description = f"""## {outcome}

{problem.capitalize()} is one of those things you stop noticing because you have
worked around it for so long. {name} removes the workaround.

### How it works
{_placeholder('One short paragraph on the mechanism. Be concrete and specific - '
              'mechanism is what separates a product page from an ad.')}

### What you get
{_placeholder('Exactly what is in the box. List it. Ambiguity here becomes a refund later.')}

### Who it is for
{_placeholder('Name the person. A page written for everybody converts for nobody.')}

### Delivery
Ships within {_placeholder('handling days')} business days and arrives in about
{delivery} days. You get a tracking number the moment it leaves the warehouse.
"""

    listing.faq = [
        ("How long does delivery take?",
         f"About {delivery} days, with tracking from dispatch. We show the "
         f"estimate before you pay, not after."),
        ("What if it does not work for me?",
         _placeholder("Your returns window and who pays return shipping. "
                      "State it plainly - vagueness here causes chargebacks.")),
        ("Is this the same as the cheaper ones?",
         _placeholder("The specific difference. If there is not one, lower "
                      "your price rather than overstate the product.")),
        ("How do I use it?",
         _placeholder("Three steps, maximum.")),
        ("Can I track my order?",
         "Yes. A tracking link is emailed automatically as soon as it ships."),
    ]

    listing.trust_blocks = [
        f"Delivery estimate shown before checkout ({delivery} days)",
        "Tracking on every order",
        _placeholder("Returns policy - state the number of days"),
        _placeholder("Support response time you can actually hit"),
        "Secure checkout",
    ]

    listing.shipping_note = (
        f"Set expectations at {product.delivery_days:.0f} days on the product "
        f"page, the cart and the confirmation email. Under-promising on delivery "
        f"is the cheapest refund-prevention there is: the refund rate you assume "
        f"({_placeholder('your config refund_rate')}) is mostly a function of "
        f"this one number."
    )

    # AOV is the cheapest lever on target ROAS - more effective than bid tuning.
    listing.upsell_ideas = [
        f"Quantity bundle: 2 for {product.price * 1.75:,.2f} (saves them "
        f"{product.price * 0.25:,.2f}, adds {ue.contribution_margin * 0.7:,.2f} to your margin)",
        f"Post-purchase one-click offer at {product.price * 0.5:,.2f} - no new "
        f"ad spend, pure margin",
        "Shipping protection add-on (covers loss claims and raises AOV)",
        f"Free shipping threshold just above {product.price * 1.3:,.0f} to pull "
        f"single orders up into bundles",
    ]

    ctx = {
        "problem": problem,
        "consequence": _placeholder("what it costs them"),
        "product": name,
        "timeframe": _placeholder("timeframe"),
        "objection": _placeholder("the usual downside"),
        "competitor_price": _placeholder("competitor price"),
        "price": f"{product.price:,.2f}",
        "delivery_days": delivery,
        "review_count": _placeholder("real review count"),
        "rating": _placeholder("real rating"),
        "mechanism": _placeholder("the surprising mechanism"),
        "guarantee": _placeholder("your guarantee"),
        "situation": _placeholder("specific situation"),
        "job": _placeholder("the one job"),
        "cutoff_date": _placeholder("cutoff date"),
    }
    for key, angle in ANGLES.items():
        listing.ad_hooks.append({
            "angle": key,
            "name": angle["name"],
            "hook": angle["hook"].format(**ctx),
            "body": angle["body"].format(**ctx),
            "use_when": angle["use_when"],
        })

    listing.ugc_brief = UGC_BRIEF.format(
        product_name=name,
        hook=ANGLES["problem_agitate"]["hook"].format(**ctx),
        cta=_placeholder("your call to action"),
    )

    listing.email_flow = [
        {"trigger": "Abandoned checkout", "delay": "1 hour",
         "goal": "Remove the friction that stopped them",
         "content": "Restate the delivery estimate and the returns policy. "
                    "No discount yet - discounting hour one trains people to wait."},
        {"trigger": "Abandoned checkout", "delay": "24 hours",
         "goal": "Last chance",
         "content": f"Now a modest incentive. Keep it under "
                    f"{ue.contribution_margin * 0.2:,.2f} or it eats the margin "
                    f"you are trying to protect."},
        {"trigger": "Order confirmed", "delay": "immediate",
         "goal": "Prevent the WISMO ticket before it exists",
         "content": f"Confirm the {delivery}-day estimate in plain language and "
                    f"explain what happens next. Most support volume is created here."},
        {"trigger": "Shipped", "delay": "on tracking issue",
         "goal": "Reassure",
         "content": "Tracking link plus a realistic arrival window."},
        {"trigger": "Delivered", "delay": "3 days after",
         "goal": "Reviews and repeat purchase",
         "content": "Ask for a photo review. Photo reviews raise conversion "
                    "more than any copy change you will make."},
        {"trigger": "Delivered", "delay": "21 days after",
         "goal": "Second order",
         "content": "Cross-sell. A repeat customer costs nothing to acquire, "
                    "which is the only reliable way out of rising ad costs."},
    ]

    listing.todo = [
        "Replace every {placeholder} - unfilled slots are the fastest way to look like a scam",
        "Delete any claim you cannot evidence if a regulator asks",
        "Add at least 15 real reviews before spending on traffic",
        "Compress images: the product page must load in under 2.5s on 4G",
        "Show the delivery estimate above the fold, not at checkout",
    ]
    return listing
