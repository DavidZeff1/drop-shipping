# Repository guidance

A dropshipping operating system: a stdlib-only Python package (`dropship/`)
plus written playbooks (`playbooks/`).

## Constraints

- **Python 3.10+, standard library only.** No numpy, scipy, pandas, requests or
  pytest. Anything needed is implemented in `dropship/stats.py`. This is the
  point: the tool must run anywhere, immediately, with no install step.
- **Every number carries its threshold.** A metric shown without the figure it
  should be judged against is not finished. `2.1x ROAS` means nothing;
  `2.1x against a 2.4x breakeven` is a decision.
- **Every problem carries its fix.** Output that reports a failure states the
  command or action that addresses it.

## Layout

| Module | Responsibility |
|---|---|
| `models.py` | Dataclasses, JSON round-trip, lifecycle states |
| `store.py` | JSON persistence, lookups by id/sku/name-prefix |
| `stats.py` | Incomplete gamma, chi-square inverse, Poisson and Wilson intervals |
| `economics.py` | Contribution margin, breakeven CPA/ROAS, price ladder, sensitivity |
| `research.py` | Hard gates, then a weighted opportunity score |
| `testing.py` | Kill/iterate/hold/scale decisions, funnel diagnosis, scale ladder |
| `cashflow.py` | Day-by-day simulation, max safe daily spend |
| `suppliers.py` | Vetting scorecard, sample checklist |
| `listings.py` | Listing copy, ad angles, UGC brief, email flow |
| `ops.py` | Order SLAs, action queue, support macros |
| `kpis.py` | Rollups and threshold-aware alerts |
| `daily.py` | The `today` briefing and the portfolio view |
| `importers.py` | CSV import with fuzzy column matching |
| `dashboard.py` | Offline single-file HTML |
| `ui.py` | Local web interface on `http.server`: pages and forms over the engine |
| `storefront.py` | Customer-facing pages: one product page, or the whole shop |
| `cli.py` | Argparse entry point |
| `demo.py` | Seed data |

Dependency direction is one-way: `stats` → `economics` → everything else.
`cli`, `ui`, `dashboard` and `storefront` sit on top: they import from the rest,
and the engine never imports them.

State changes that both front ends make live in the engine, not in a command
or a page handler: `research.apply_score`, `testing.apply_decision`,
`ops.update_order`. Add new ones there too, so the CLI and the UI cannot drift.

## Changing the economics

`UnitEconomics.contribution_margin` is the root of every downstream number.
Changing it changes breakeven, test budgets, kill thresholds, scale ladders and
cash limits at once. It is tested against a hand calculation and against the
identity `breakeven_roas x contribution_margin == aov`; keep both passing.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The helper inside `TestCLI` is named `cli`, not `run` — `run` collides with
`unittest.TestCase.run` and fails in a confusing way.

## Dashboard

The palette is validated for colour-vision deficiency and contrast in both
light and dark modes. If you change a chart colour, re-validate rather than
eyeballing it, and keep the table view under each chart — it is the
accessibility fallback, not decoration.

## UI

The admin screens are generated, not written: `ENTITIES` in `ui.py` holds one
`Entity` per record type and one `Field` per column, and the list, the form,
the save and the delete all come from that. A new field on a model is a line
there, not a new page. `after_save` is where a record's engine hook goes —
products re-score through `research.apply_score` on every save.

`ui.py` layers its styles on the dashboard's `_CSS`, so its controls reuse the
validated tokens; the same re-validation rule applies. It binds to 127.0.0.1
with no login, and refuses requests whose `Host` or `Origin` is not its own —
that is what stops any other web page from posting to it while it runs. Keep
both checks. Every page reads the store fresh; every write loads, changes and
saves under one lock.

## Storefront

The only output a customer ever sees, so the rules are different from the rest
of the system and they are not stylistic:

- No invented reviews, no fake scarcity, no countdown timers. They raise
  disputes faster than they raise conversion, and a fabricated review is the
  first thing a card network looks at.
- Unfilled `{slots}` stay visible and highlighted, and `Page.issues` names each
  one rather than letting a draft go live.
- The delivery estimate, the returns policy and a contact address belong on the
  page, not behind checkout. They are also the evidence in a chargeback.
- Money never passes through the file: the buy button hands over to the
  operator's own payment link, and orders return via `import orders`.
- Light mode only, unlike the dashboard: photos shot on white do not survive an
  inverted palette.
- The policy pages are mostly slots on purpose. They are answers only the
  operator has, and an invented refund policy is worse than none: it is the
  document a bank reads in a dispute.
- `build_site` only shows products in `SELLING`. A killed or unscored product
  has no business in a shop window.

## Tone

The playbooks and the CLI copy are deliberately direct about the odds and about
what each failure costs. Keep that. Softening it removes the only thing that
makes an operator act on a kill decision.
