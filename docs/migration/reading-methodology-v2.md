# reading-methodology-v2 — the frozen spec

Status: **provisional.** The logic is frozen; the numbers are not. Retiring
`SPEC["provisional"]` requires `calibrate_v2.py --archive` against real
RentCast responses, and a commit that says so.

Implemented in `pipeline/verdict_v2.py`. Not yet wired into the site — Phase
4 switches the pipeline over, per tranche.

## The basis changed, and that is the whole story

v1 scored Redfin statistics computed largely from **closed sales**. v2 scores
RentCast `/markets` statistics computed from **active listings**. Two of v1's
five danger signals have no equivalent on the new basis:

| v1 signal | fate |
|---|---|
| Months of supply > 4 / 6 | **gone** — `inventory / homes_sold`, and active-listing statistics cannot see closings. This was v1's highest-weighted check. |
| Price-drop share > 35% | **gone** — no equivalent field. |
| Median sale price YoY < −2% / −5% | survives as median **list** price YoY |
| Median DOM YoY > +40% | survives as **active** DOM YoY |
| Inventory YoY > +50% | survives as total listings YoY |

Which three survived is not luck. **Every survivor was already a
year-over-year ratio; both casualties were levels.** Active DOM sits higher
than sold DOM, and a list-price median sits higher than a sale-price median —
a level ported across that gap is simply wrong, while the direction and
magnitude of a year-over-year change stay comparable. That is why the three
survivors keep their v1 thresholds unchanged.

## The reading

Danger signals, scored:

| signal | condition | points |
|---|---|---|
| `price_falling_fast` | list price YoY < −5% | 3 |
| `price_falling` | list price YoY < −2% | 2 |
| `dom_stretching` | active DOM YoY > +40% | 1 |
| `inventory_surge` | total listings YoY > +50% | 1 |

Bands: **ACT at ≥ 3**, WATCH at ≥ 1, HOLD at 0. Fewer than two known signals
yields no reading at all (`insufficient_data`).

Seller's-market reading (renders as ACT), only when **zero** danger lines are
crossed and **all three** hold: list price YoY ≥ +5%, active DOM YoY ≤ −15%,
total listings YoY ≤ −15%.

Recorded on every reading but deliberately **unscored**: price-per-square-foot
YoY and new-listings YoY. Neither has a v1 counterpart to calibrate against,
so scoring them now would be inventing a threshold rather than porting one.
Both are candidates for the first real calibration — PPSF especially, since a
median list price moves whenever the mix of listed homes changes and PPSF
largely controls for that.

## What was tuned

**One number: the ACT band, from 4 to 3.** The two lost checks could
contribute 4 of v1's 9 possible points; at an unchanged band of 4, ACT became
nearly unreachable. Every surviving check keeps its v1 weight and threshold.

The strong path moved from "3 of 4" to "all 3 of 3" because two of those four
signals died with the metrics behind them. A strong reading tells somebody to
sell into a hot market, so the conservative error is the correct one.

## What the distribution says

`python3 pipeline/calibrate_v2.py --compare-naive`, over all 33,426 scored ZIPs:

| | HOLD | WATCH | ACT | strong | ACT total |
|---|---|---|---|---|---|
| **v1 baseline**, five signals | 46.4% | 21.3% | 28.3% | 4.1% | 32.4% |
| **naive port** — v1 bands, two signals removed | 71.0% | 19.4% | 9.7% | 0.0% | 9.7% |
| **v2** | 53.5% | 20.6% | 22.8% | 3.1% | 25.9% |

The naive port is what the plan's warning looks like in practice — "if most of
the country flips category, the thresholds are wrong, not the country." It
moves HOLD by **+24.6 points** and makes a strong reading literally
unreachable, since that path needed 3 of 4 signals and only 2 survive. v2
moves HOLD by +7.1.

**The remaining drop is deliberate and is not tuned away.** ACT falls from
32.4% to 25.9%. With two of five danger signals genuinely gone the engine has
less evidence, so it should call fewer ACTs; adjusting thresholds until the
old distribution reappeared would manufacture confidence the data no longer
supports. The comparison is a smoke alarm, not a target.

## Why the numbers are provisional

They were fitted in **proxy mode** — v2's logic fed the three surviving
metrics as *Redfin* measured them. Those are the same kind of number (all
three are YoY ratios) but not identical in behaviour: active DOM carries stale
inventory that a sold-DOM series never sees, so its year-over-year swings are
damped, and a `dom_stretching` threshold of +40% may prove too strict on the
new basis. Nothing about that can be settled without real responses.

The re-fit costs nothing. Lever 2 puts every payload on disk, so
`calibrate_v2.py --archive` re-runs against Tier A as many times as needed
without another request.

## Open, and owned elsewhere

- **The public methodology page is deliberately not yet updated.** It would
  describe a basis the live site is not using — the site is paused and serving
  no readings at all. It lands with Tranche 1, alongside the ToS update naming
  the new sources and the per-tier refresh cadence.
- **Attorney question 2** — whether displaying readings derived from RentCast
  data is permitted under its ToU — is upstream of publishing any of this.
- Phase 4 wires v2 into `fetch_data.py`/`build_pages.py` behind the tranche
  allowlist, and must suppress subscriber alerts across the cutover: the first
  run diffs v2 readings against v1-era stored verdicts and would mail
  subscribers about a source change (correction 6).
