// Generates the hero map's topographic contour layer as a static SVG.
//
//   npm install && npm run topo
//
// Build-time only — this never runs in the browser. Output is written to
// web/img/topo-contours.svg and inlined into web/index.html by hand.
//
// The contours are decorative terrain texture, not real elevation: a seeded
// fBm noise field biased by a few gaussian "ranges" so density reads highest
// over the Mountain West and, more softly, the Appalachians.
//
// The projection here MUST stay identical to the one in index.html's initMap()
// (geoAlbersUsa fitted to [[20,8],[W-20,H-40]] over the *states* collection at
// 560x360) — the SVG is stacked directly over that canvas, so any drift in
// fitExtent shows up as contours sliding off the coastline.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { geoAlbersUsa, geoPath } from "d3-geo";
import { contours } from "d3-contour";
import { feature, merge } from "topojson-client";
import { createNoise2D } from "simplex-noise";
import { optimize } from "svgo";

const require = createRequire(import.meta.url);
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../web/img/topo-contours.svg");

// —————— must mirror index.html ——————
const W = 560, H = 360;
const FIT = [[20, 8], [W - 20, H - 40]];

// —————— texture knobs ——————
// Overridable from the environment so the size/detail trade can be swept
// without editing this file: CELL=4 MIN_SEG=1.3 npm run topo
const num = (k, d) => (process.env[k] ? Number(process.env[k]) : d);
const CELL = num("CELL", 4);            // noise sample spacing, px. Smaller = finer, larger file.
const LEVELS = num("LEVELS", 10);       // total contour levels; every other one is hidden < 640px
const INDEX_EVERY = num("INDEX_EVERY", 4); // every Nth contour is an "index line" (heavier)
const SMOOTH_PASSES = num("SMOOTH_PASSES", 2); // Chaikin corner-cutting iterations
const MIN_SEG = num("MIN_SEG", 1.3);    // drop points closer together than this, px
const MIN_RING = num("MIN_RING", 24);   // drop rings shorter than this perimeter, px
const PRECISION = num("PRECISION", 2);  // decimal places in path data

// Deterministic PRNG so re-running the generator reproduces byte-identical art.
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Gaussian bumps that push contour density where mountains belong. Purely
// impressionistic — x/y are screen coords in the 560x360 projected space.
// Amplitudes are deliberately of the same order as the fBm term below, not
// larger: the thresholds are evenly spaced across the whole field's range, so
// a range that towers over the noise swallows most of the levels and leaves
// the rest of the country blank. These modulate the noise, they don't replace it.
const RANGES = [
  { x: 92,  y: 108, sx: 34, sy: 72, amp: 0.46 },  // Cascades / Sierra
  { x: 168, y: 132, sx: 52, sy: 62, amp: 0.52 },  // Northern Rockies
  { x: 196, y: 196, sx: 46, sy: 50, amp: 0.40 },  // Colorado Plateau / Southern Rockies
  { x: 132, y: 196, sx: 40, sy: 44, amp: 0.28 },  // Great Basin
  { x: 428, y: 148, sx: 30, sy: 42, amp: 0.30 },  // Appalachians, north
  { x: 452, y: 200, sx: 26, sy: 40, amp: 0.27 },  // Appalachians, south
];

function ranges(x, y) {
  let v = 0;
  for (const r of RANGES) {
    const dx = (x - r.x) / r.sx, dy = (y - r.y) / r.sy;
    v += r.amp * Math.exp(-(dx * dx + dy * dy) / 2);
  }
  return v;
}

// —————— geometry ——————
const topo = JSON.parse(readFileSync(require.resolve("us-atlas/states-10m.json"), "utf8"));
const states = feature(topo, topo.objects.states);
const outline = merge(topo, topo.objects.states.geometries);
const proj = geoAlbersUsa().fitExtent(FIT, states);
const toPath = geoPath(proj);

// —————— noise field ——————
const nx = Math.ceil(W / CELL) + 1;
const ny = Math.ceil(H / CELL) + 1;
const noise2D = createNoise2D(mulberry32(20874));
const field = new Float64Array(nx * ny);

for (let j = 0; j < ny; j++) {
  for (let i = 0; i < nx; i++) {
    const x = i * CELL, y = j * CELL;
    // fBm — four octaves, halving amplitude, doubling frequency
    let amp = 1, freq = 1 / 128, sum = 0, norm = 0;
    for (let o = 0; o < 4; o++) {
      sum += amp * noise2D(x * freq, y * freq);
      norm += amp;
      amp *= 0.5; freq *= 2;
    }
    field[j * nx + i] = (sum / norm) * 1.0 + ranges(x, y);
  }
}

let lo = Infinity, hi = -Infinity;
for (const v of field) { if (v < lo) lo = v; if (v > hi) hi = v; }

// Evenly spaced thresholds, inset from the extremes so the outermost contour
// isn't a single degenerate speck at the field's max.
const thresholds = Array.from({ length: LEVELS }, (_, i) =>
  lo + ((i + 0.5) / LEVELS) * (hi - lo));

const bands = contours().size([nx, ny]).thresholds(thresholds)(field);

// —————— polyline cleanup ——————
// Chaikin corner-cutting: replaces each corner with two points at 1/4 and 3/4
// along its adjacent edges, which rounds the marching-squares staircase.
function chaikin(ring) {
  let pts = ring;
  for (let pass = 0; pass < SMOOTH_PASSES; pass++) {
    const out = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
      out.push([x0 + (x1 - x0) * 0.25, y0 + (y1 - y0) * 0.25]);
      out.push([x0 + (x1 - x0) * 0.75, y0 + (y1 - y0) * 0.75]);
    }
    out.push(out[0]);
    pts = out;
  }
  return pts;
}

function thin(ring) {
  const out = [ring[0]];
  for (let i = 1; i < ring.length; i++) {
    const [px, py] = out[out.length - 1], [x, y] = ring[i];
    if (Math.hypot(x - px, y - py) >= MIN_SEG) out.push([x, y]);
  }
  if (out.length > 1) out.push(out[0]);
  return out;
}

const perimeter = (r) => r.reduce((s, p, i) =>
  i ? s + Math.hypot(p[0] - r[i - 1][0], p[1] - r[i - 1][1]) : 0, 0);

const round = (n) => {
  const v = Number(n.toFixed(PRECISION));
  return Object.is(v, -0) ? 0 : v;
};

function ringToPath(ring) {
  let d = "";
  for (let i = 0; i < ring.length; i++) {
    d += (i ? "L" : "M") + round(ring[i][0]) + " " + round(ring[i][1]);
  }
  return d + "Z";
}

// —————— build the layer ——————
const layers = bands.map((band, li) => {
  const ds = [];
  for (const poly of band.coordinates) {
    for (const ring of poly) {
      // grid space -> screen space
      const scaled = ring.map(([x, y]) => [x * CELL, y * CELL]);
      if (scaled.length < 4) continue;
      const smooth = thin(chaikin(scaled));
      if (smooth.length < 4 || perimeter(smooth) < MIN_RING) continue;
      ds.push(ringToPath(smooth));
    }
  }
  return { li, d: ds.join("") };
}).filter((l) => l.d);

// The clip outline is the single biggest contributor to file size — the 10m
// coastline carries hundreds of islands only a few pixels across. Rendered at
// ~500px wide under a 14%-opacity hairline, none of them can hold a visible
// contour, so subpaths below MIN_ISLAND px² are dropped and the rest are
// emitted at 1 decimal (0.1px at this scale is far below a device pixel).
//
// Subpaths are filtered on the *projected path string* rather than by
// reprojecting rings by hand: geoAlbersUsa is a composite of three
// sub-projections, and points near their seams return null individually.
const MIN_ISLAND = num("MIN_ISLAND", 25);

function slimClip(d) {
  return d.split("M").filter(Boolean).map((sub) => {
    const n = sub.match(/-?\d+(?:\.\d+)?/g);
    if (!n || n.length < 6) return "";
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i + 1 < n.length; i += 2) {
      const x = +n[i], y = +n[i + 1];
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    if ((x1 - x0) * (y1 - y0) < MIN_ISLAND) return "";
    let out = "M";
    for (let i = 0; i + 1 < n.length; i += 2) {
      out += (i ? "L" : "") + (+n[i]).toFixed(1) + " " + (+n[i + 1]).toFixed(1);
    }
    return out + "Z";
  }).join("");
}

const rawClip = toPath(outline);
const clipD = slimClip(rawClip);

// Two axes of grouping:
//   index vs. regular  -> stroke weight (the topo-map convention)
//   coarse vs. fine    -> odd levels drop out below 640px, where 14 levels of
//                         1px stroke moire against each other
const group = (pred, cls, width, opacity) => {
  const d = layers.filter((l) => pred(l.li)).map((l) => l.d).join("");
  return d ? `<path class="${cls}" d="${d}" stroke-width="${width}" stroke-opacity="${opacity}"/>` : "";
};

const svg = `<svg class="topo" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
<defs><clipPath id="topoClip"><path d="${clipD}"/></clipPath></defs>
<g clip-path="url(#topoClip)" fill="none" stroke="#8a7a55" stroke-linejoin="round" stroke-linecap="round">
${group((i) => i % 2 === 0 && i % INDEX_EVERY !== 0, "tc", 0.85, 0.14)}
${group((i) => i % 2 === 0 && i % INDEX_EVERY === 0, "tc ti", 1.15, 0.2)}
${group((i) => i % 2 === 1, "tc tf", 0.85, 0.14)}
</g>
</svg>`;

const out = optimize(svg, {
  multipass: true,
  plugins: [
    { name: "preset-default", params: { overrides: { removeViewBox: false, cleanupIds: false } } },
  ],
}).data;

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, out);

const kb = (Buffer.byteLength(out) / 1024).toFixed(1);
const clipKb = (Buffer.byteLength(clipD) / 1024).toFixed(1);
const rawKb = (Buffer.byteLength(rawClip) / 1024).toFixed(1);
console.log(`levels: ${layers.length}/${LEVELS}  grid: ${nx}x${ny}  ` +
            `clip: ${rawKb} -> ${clipKb} KB  |  total ${kb} KB  ->  ${OUT}`);
if (Buffer.byteLength(out) > 120 * 1024) {
  console.error(`!! over the 120 KB budget — raise CELL or MIN_SEG, or drop LEVELS`);
  process.exit(1);
}
