// ShouldISellYet — the one address module.
//
// The problem this exists to solve: the address used to be asked for as a
// single freeform line, then again by Stripe in a different format, and the
// report tried to recover the ZIP by regexing the last 5-digit group out of
// whatever the user typed. Three formats, one of them guessed. The ZIP is the
// key to every verdict on this site, so it can't be a parse result — it has to
// be a validated field.
//
// So: ONE structured shape, captured ONCE (subscribe.html, immediately before
// checkout), stored in ONE place, read by every surface through this file.
//
//   { street, unit, city, state, zip }
//
// Those names are the Supabase columns too (prefixed address_*, except zip
// which already existed) — see toRow()/fromRow(). Keeping them identical is
// deliberate: a rename in one place should break loudly, not silently map a
// field onto the wrong column.
//
// Storage is two-tier and the tiers are NOT equals:
//   * Supabase subscribers row, keyed by email — canonical. Survives devices.
//   * localStorage `sisy_address` — a mirror, for the pre-account session
//     (someone filling the form before they've paid) and for offline reads.
// The server wins on conflict; see ADDRESS.adopt().

const ADDRESS = (function () {
  const KEY = "sisy_address";
  const FIELDS = ["street", "unit", "city", "state", "zip"];

  // US states + DC. Used for the <select> and to reject a typo'd state that
  // would otherwise reach Supabase and sit there unqueryable.
  const STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME " +
    "MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX " +
    "UT VT VA WA WV WI WY").split(" ");

  const clean = (s) => String(s == null ? "" : s).trim().replace(/\s+/g, " ");

  function blank() {
    return { street: "", unit: "", city: "", state: "", zip: "" };
  }

  function normalize(a) {
    const o = blank();
    if (!a) return o;
    FIELDS.forEach((f) => { o[f] = clean(a[f]); });
    o.state = o.state.toUpperCase().slice(0, 2);
    o.zip = o.zip.replace(/\D/g, "").slice(0, 5);
    return o;
  }

  // ————— storage (mirror) —————

  function load() {
    try { return normalize(JSON.parse(localStorage.getItem(KEY) || "null")); }
    catch (e) { return blank(); }
  }

  function save(a) {
    const o = normalize(a);
    try { localStorage.setItem(KEY, JSON.stringify(o)); } catch (e) {}
    return o;
  }

  // Server row wins over the local mirror, field by field — but only where the
  // server actually has something. A subscriber who fills in a unit number on
  // this device and hasn't re-synced shouldn't lose it to an older blank row.
  function adopt(row) {
    const server = fromRow(row);
    const local = load();
    const merged = blank();
    FIELDS.forEach((f) => { merged[f] = server[f] || local[f]; });
    return save(merged);
  }

  function clear() { try { localStorage.removeItem(KEY); } catch (e) {} }

  // ————— Supabase mapping —————

  function toRow(a) {
    const o = normalize(a);
    return {
      address_street: o.street || null,
      address_unit: o.unit || null,
      address_city: o.city || null,
      address_state: o.state || null,
      zip: o.zip,
    };
  }

  function fromRow(row) {
    if (!row) return blank();
    return normalize({
      street: row.address_street, unit: row.address_unit,
      city: row.address_city, state: row.address_state, zip: row.zip,
    });
  }

  // ————— validation —————
  // Returns { ok, field, msg }. `field` is the id suffix the caller focuses,
  // so one shared validator can drive two different forms.

  function validate(a) {
    const o = normalize(a);
    if (!o.street) return { ok: false, field: "street", msg: "Please enter the street address." };
    if (!/^\d{5}$/.test(o.zip)) return { ok: false, field: "zip", msg: "Please enter the home's 5-digit ZIP code." };
    if (!o.city) return { ok: false, field: "city", msg: "Please enter the city." };
    if (STATES.indexOf(o.state) === -1) return { ok: false, field: "state", msg: "Please choose the state." };
    return { ok: true, field: "", msg: "" };
  }

  // ————— ZIP → { known, state, city } —————
  // Two independent questions, answered by two sources:
  //
  //   known + state — OUR data. data/index.json maps the 3-digit prefix to a
  //     state (9 KB, always worth loading); the state shard confirms the exact
  //     ZIP is one we actually score. A ZIP we can't score is a ZIP whose
  //     report would be empty, so this must be checked at capture, not at
  //     render — after payment is far too late to find out.
  //
  //   city — Zippopotam (free, keyless), best-effort, cached in the same
  //     `sisy_city_*` keys the homepage and report already use, so a ZIP
  //     checked on the homepage costs nothing here. City is a SUGGESTION: it
  //     prefills a field the user can overwrite, and a failed lookup just
  //     means they type it themselves. It never blocks.

  let _index = null;
  const _shards = {};

  // null on failure, never {} — the caller has to be able to tell "no such
  // ZIP" from "couldn't look it up", because one of those may block a
  // purchase and the other must not.
  async function index() {
    if (_index) return _index;
    try {
      const r = await fetch("data/index.json");
      if (r.ok) _index = await r.json();
    } catch (e) {}
    return _index;
  }

  async function shard(st) {
    if (_shards[st]) return _shards[st];
    try {
      const r = await fetch("data/zips/" + st + ".json");
      if (r.ok) _shards[st] = await r.json();
    } catch (e) {}
    return _shards[st] || null;
  }

  function cityCache(zip) {
    try { return localStorage.getItem("sisy_city_" + zip) || ""; } catch (e) { return ""; }
  }

  async function cityFor(zip) {
    const hit = cityCache(zip);
    if (hit) return hit;
    try {
      const r = await fetch("https://api.zippopotam.us/us/" + zip);
      if (!r.ok) return "";
      const j = await r.json();
      const names = [...new Set((j.places || []).map((p) => p["place name"]).filter(Boolean))];
      const city = names.join(" / ");
      if (city) { try { localStorage.setItem("sisy_city_" + zip, city); } catch (e) {} }
      return city;
    } catch (e) { return ""; }
  }

  // `checked` says whether the answer is trustworthy. If the data files
  // didn't load, `known` is false but `checked` is false too — callers must
  // fail OPEN on that combination. Blocking a paying customer because a JSON
  // fetch blipped is a worse failure than letting one uncovered ZIP through.
  async function resolve(zip) {
    const z = String(zip || "").replace(/\D/g, "").slice(0, 5);
    const out = { zip: z, known: false, checked: false, state: "", city: "" };
    if (!/^\d{5}$/.test(z)) return out;

    const idx = await index();
    if (!idx) { out.city = await cityFor(z); return out; }

    const st = idx[z.slice(0, 3)];
    // No prefix entry means no state has this ZIP block — a typo, almost
    // always. That IS a checked answer; skip the shard, there's nothing to
    // look in.
    if (!st) { out.checked = true; out.city = await cityFor(z); return out; }

    out.state = st;
    const s = await shard(st);
    if (s) {
      out.checked = true;
      const row = s[z];
      if (row) {
        out.known = true;
        if (row.st) out.state = row.st;  // shard is authoritative over the prefix map
      }
    }
    out.city = await cityFor(z);
    return out;
  }

  // ————— formatting —————

  function streetLine(a) {
    const o = normalize(a);
    return [o.street, o.unit].filter(Boolean).join(", ");
  }

  function placeLine(a) {
    const o = normalize(a);
    const cityState = [o.city, o.state].filter(Boolean).join(", ");
    return [cityState, o.zip].filter(Boolean).join(" ");
  }

  function oneLine(a) {
    return [streetLine(a), placeLine(a)].filter(Boolean).join(", ");
  }

  function isEmpty(a) {
    const o = normalize(a);
    return !FIELDS.some((f) => o[f]);
  }

  return {
    FIELDS, STATES,
    blank, normalize, load, save, adopt, clear,
    toRow, fromRow, validate, resolve, cityFor, cityCache,
    streetLine, placeLine, oneLine, isEmpty,
  };
})();
