# tools/

Build-time asset generators. **Nothing here ships to the browser.**

## gen-topo.mjs — hero map topographic texture

Generates `web/img/topo-contours.svg`, the contour texture layered inside the
homepage hero map. Output is a static asset; the browser never runs the
generator or evaluates noise at runtime.

```bash
cd tools && npm install && npm run topo
```

Then re-inline the result into `web/index.html` (search for
`<!-- Decorative terrain texture` inside `.mapstack`) — the SVG is inlined
rather than linked so the page-level `@media (max-width:640px)` rule can
drop the fine contour levels.

Knobs are env-overridable for sweeping the detail/size trade:

```bash
CELL=3 MIN_SEG=1.1 LEVELS=12 npm run topo
```

| var | default | effect |
| --- | --- | --- |
| `CELL` | 4 | noise sample spacing, px. Lower = finer, bigger file |
| `LEVELS` | 10 | contour levels. Odd ones are hidden below 640px |
| `INDEX_EVERY` | 4 | every Nth contour is a heavier "index line" |
| `MIN_SEG` | 1.3 | drop points closer together than this |
| `MIN_RING` | 24 | drop rings with a shorter perimeter than this |
| `MIN_ISLAND` | 25 | drop clip-path subpaths below this bbox area, px² |

The script fails loudly if the result exceeds the 120 KB budget.

**The projection must stay in sync with `initMap()` in `web/index.html`** —
`geoAlbersUsa().fitExtent([[20,8],[540,320]])` over the *states* collection at
560×360. The SVG is stacked directly over that canvas, so any drift shows up as
contours sliding off the coastline.
