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
| `cli.py` | Argparse entry point |
| `demo.py` | Seed data |

Dependency direction is one-way: `stats` → `economics` → everything else.
`cli` and `dashboard` import from the rest and are imported by nothing.

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

## Tone

The playbooks and the CLI copy are deliberately direct about the odds and about
what each failure costs. Keep that. Softening it removes the only thing that
makes an operator act on a kill decision.
