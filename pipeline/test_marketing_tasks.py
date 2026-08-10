"""Contract tests for the marketing queue generator (schema-v23 layer).

Fixtures are hand-built from the documented shapes — research.py's records
block, the velocity gathering rows, the marketing_demotions view — the clock
is always frozen, and the HTTP seam (marketing_tasks._http) is monkeypatched
to record instead of send. Nothing in here touches the network, Supabase, or
the wall clock."""

import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import marketing_config as MC
import marketing_tasks as MT
import utm

SCHEMA = (Path(__file__).resolve().parents[1] / "supabase" / "schema-v23.sql").read_text()

NOW = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)   # Monday 10:00 ET
PERIOD = "2026-08"


def mkrep(wsi=14.2, prev_wsi=13.4, delta=0.8, highest="2023-03", run=3,
          direction="up"):
    return {"month": PERIOD, "pretty_month": "August 2026",
            "records": {"wsi": wsi, "prev_wsi": prev_wsi, "delta": delta,
                        "highest_since": highest, "lowest_since": None,
                        "run_length": run, "run_direction": direction,
                        "basis_since": "2024-09", "basis_months": 23,
                        "month": PERIOD}}


AUSTIN = {"cbsa": "12420", "name": "Austin-Round Rock-San Marcos, TX",
          "zips": 61, "share_det": 28.3, "hold_share": 72.0, "median_mtl": 0.0,
          "sig": {"mos": {"near": 19, "median_mtl": 0.0},
                  "spy": {"near": 7, "median_mtl": 2.1}}}
VEL = {"period": PERIOD, "gathering": [AUSTIN]}
VEL_PREV = {"metros": {"12420": {"share_det": 22.4}}}

RECEIPT_UUID = "8b6f2c1a-3d4e-4f5a-9b8c-7d6e5f4a3b2c"
RECEIPT = {"id": RECEIPT_UUID, "outlet": "Idaho Statesman",
           "headline": "Boise home sellers face longest waits since 2022",
           "published_on": "2026-07-31", "flag_date": "2026-06-20",
           "metro_cbsa": "14260", "zip": None, "corroborates": "first_watch"}

CASES = [{"id": "boise-2021", "name": "Boise City, ID",
          "first_signal": "2021-11", "lead_months": 12,
          "peak_to_trough": -0.1786},
         {"id": "cape-coral-2022", "name": "Cape Coral-Fort Myers, FL",
          "first_signal": "2022-08", "lead_months": 10,
          "peak_to_trough": -0.1775},
         {"id": "miss-39500", "kind": "miss", "name": "Quincy, IL-MO",
          "first_signal": "2022-01", "lead_months": 6,
          "peak_to_trough": -0.0287}]

GEO_ANGLES = ["Homes in 20904 (Silver Spring, MD) are taking 12 days longer "
              "to sell than a year ago (34 days now).",
              "55912 (Austin, MN) has just 1.2 months of supply — at that "
              "pace every home listed there sells in under 5 weeks."]
GEO_CBSA = {"20904": "47900", "55912": "40340"}
GEO_NAMES = {"47900": "Washington-Arlington-Alexandria, DC-VA-MD-WV",
             "40340": "Rochester, MN"}


def full_candidates():
    cands = [MT.cand_record(mkrep())]
    cands += MT.cand_receipts([RECEIPT], MT.et_date(NOW), {"14260": "Boise City, ID"},
                              {}, PERIOD)
    cands += MT.cand_flips(VEL, VEL_PREV, PERIOD)
    cands += MT.cand_geo(GEO_ANGLES, PERIOD, GEO_CBSA, GEO_NAMES)
    return [c for c in cands if c]


def rows_for(plan):
    return [MT.row_from_placement(c, when, ch, PERIOD)
            for c, when, ch in plan.placed]


def all_strings(rows):
    return " ".join(str(v) for r in rows for v in r.values() if isinstance(v, str))


# ————— the checklist —————

def test_refresh_populates_queue():
    """Priorities land as ints on the documented tiers, the whys carry the
    real numbers, and every slot obeys the fetched windows and the caps."""
    cands = full_candidates()
    plan = MT.plan_schedule(cands, [], MC.FALLBACK_WINDOWS, NOW)
    rows = rows_for(plan)

    tiers = {r["priority_score"] for r in rows}
    assert all(isinstance(r["priority_score"], int) for r in rows)
    assert {1, 2, 3, 4} <= tiers

    rec = next(r for r in rows if r["dedupe_key"] == f"mq-{PERIOD}-record-us")
    assert "14.2%" in rec["why_headline"]
    assert "since March 2023" in rec["why_headline"]
    flip = next(r for r in rows if r["type"] == "post" and r["metro_cbsa"] == "12420")
    assert "28% of its 61 scored ZIPs" in flip["why_headline"]
    assert "supply" in flip["why_detail"]          # the dial that moved

    # every scheduled_for sits on a window instant the calendar offers
    slot_set = {(when, ch) for slots in
                MT.build_slots(MC.FALLBACK_WINDOWS, NOW).values()
                for when, ch, _ in slots}
    counts = {}
    for r in rows:
        if r["channel"]:
            when = MT.parse_ts(r["scheduled_for"])
            assert (when, r["channel"]) in slot_set
            wk = MT.week_start(MT.et_date(when))
            counts[(wk, r["channel"])] = counts.get((wk, r["channel"]), 0) + 1
    assert counts and all(n <= MC.MAX_WEEKLY_PER_CHANNEL for n in counts.values())


def test_third_weekly_post_refused(monkeypatch):
    """The Python layer refuses the third same-channel post in a week —
    printed, returned in the plan, and never among the rows to write. (The
    v23 trigger is the live backstop; see the (LIVE) checklist item.)"""
    monkeypatch.setattr(MC, "HORIZON_WEEKS", 1)
    sunday = datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc)   # Sun 10:00 ET
    cands = [{"key": f"mq-2026-08-geo-2000{i}", "type": "post", "tier": 4,
              "channel": "ig", "why_headline": f"headline {i}"}
             for i in range(3)]
    plan = MT.plan_schedule(cands, [], MC.FALLBACK_WINDOWS, sunday)
    assert len(plan.placed) == 2
    assert len(plan.refused) == 1
    refused_cand, reason = plan.refused[0]
    assert reason.startswith("refused:weekly_cap:ig:")
    assert refused_cand["key"] not in {r["dedupe_key"] for r in rows_for(plan)}


def test_burst_within_48h_priority0(monkeypatch):
    frozen = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)    # Fri 14:00 ET
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    written = []
    monkeypatch.setattr(MT, "post_task_row",
                        lambda url, key, row: (written.append(row), (True, None))[1])

    tok = MT.insert_burst_task(6.12, 6.43, "2026-07", now_utc=frozen)
    assert tok == "mq-burst-2026-07-2026-08-02"      # Sunday-start ET week
    row = written[-1]
    assert row["priority_score"] == 0
    assert row["channel"] is None
    when = MT.parse_ts(row["scheduled_for"])
    assert timedelta(0) < when - frozen <= timedelta(hours=MC.BURST_WINDOW_HOURS)
    local = when.astimezone(MT._ET)
    assert f"{local.hour:02d}:{local.minute:02d}" in MC.BURST_SLOT_TIMES_ET
    assert "dropped 0.31 points" in row["why_headline"]
    assert "utm_source=x" in row["utm_url"] and tok in row["utm_url"]

    # same-week rerun mints the same key — the upsert makes it a no-op
    assert MT.insert_burst_task(6.12, 6.43, "2026-07", now_utc=frozen) == tok

    # an insert failure returns None and never raises past its print
    monkeypatch.setattr(MT, "post_task_row", lambda *a: (False, "boom"))
    assert MT.insert_burst_task(6.12, 6.43, "2026-07", now_utc=frozen) is None


def test_skip_demotion_applied_and_disclosed():
    demo = [{"metro_cbsa": "12420",
             "metro_name": "Austin-Round Rock-San Marcos, TX", "skips": 2,
             "last_skip_at": "2026-08-09T14:00:00Z",
             "expires_at": "2026-10-08T14:00:00Z"}]
    cands = MT.cand_geo(["Homes in 78701 (Austin, TX) are taking 12 days "
                         "longer to sell than a year ago (34 days now)."],
                        PERIOD, {"78701": "12420"},
                        {"12420": "Austin-Round Rock-San Marcos, TX"})
    MT.apply_demotions(cands, demo)
    c = cands[0]
    assert c["tier"] == 5 and isinstance(c["tier"], int)     # 4 + 1, int tier
    assert c["why_detail"].endswith(
        "- Heads-up: Austin-Round Rock-San Marcos, TX is running one priority "
        "tier lower until Oct 8, 2026 — skipped as not newsworthy twice in "
        "the last 60 days (most recently Aug 9).")

    # one skip, or two skips more than 60 days apart, never reach Python:
    # the VIEW owns that arithmetic — pin its two clauses against drift.
    assert "having count(*) >= 2" in SCHEMA
    assert "interval '60 days'" in SCHEMA
    fresh = MT.cand_geo(["Homes in 78701 (Austin, TX) are taking 12 days "
                         "longer to sell than a year ago (34 days now)."],
                        PERIOD, {"78701": "12420"}, {})
    MT.apply_demotions(fresh, [])                  # empty view = no demotion
    assert fresh[0]["tier"] == 4

    # never demoted below the floor, and never a fixed-time (pitch/burst) row
    ever = [{"key": "k", "type": "evergreen", "tier": 5, "metro_cbsa": "12420",
             "why_detail": "- x."}]
    MT.apply_demotions(ever, demo)
    assert ever[0]["tier"] == 5
    pitch = [{"key": "p", "type": "press_pitch", "tier": 1,
              "metro_cbsa": "12420", "fixed_time": NOW, "why_detail": "- x."}]
    MT.apply_demotions(pitch, demo)
    assert pitch[0]["tier"] == 1 and "Heads-up" not in pitch[0]["why_detail"]


def test_naomi_never_generated():
    """With the v23 seed (zero nextdoor_naomi windows) the channel string
    cannot appear in any generated row — the windows table IS the off
    switch. A fixture window row (the dated-migration shape) makes DMV geo
    candidates eligible, and only DMV ones."""
    plan = MT.plan_schedule(full_candidates(), [], MC.FALLBACK_WINDOWS, NOW)
    assert "nextdoor_naomi" not in json.dumps(rows_for(plan))

    naomi = [{"channel": "nextdoor_naomi", "dow": 2, "at_time": "08:30",
              "label": "Tuesday morning", "anchor": False}]
    dmv = MT.cand_geo(GEO_ANGLES[:1], PERIOD, GEO_CBSA, GEO_NAMES)   # 20904
    plan = MT.plan_schedule(dmv, [], naomi, NOW)
    assert [ch for _, _, ch in plan.placed] == ["nextdoor_naomi"]

    non_dmv = MT.cand_geo(GEO_ANGLES[1:], PERIOD, GEO_CBSA, GEO_NAMES)  # 55912
    plan = MT.plan_schedule(non_dmv, [], naomi, NOW)
    assert not plan.placed and plan.refused[0][1] == "refused:no_slot"


def test_never_prints_zero_months():
    """The mtlProse contract, enforced repo-wide for the queue: a 0.0 median
    renders 'already at its danger line', never '0.0 months'."""
    plan = MT.plan_schedule(full_candidates(), [], MC.FALLBACK_WINDOWS, NOW)
    text = all_strings(rows_for(plan))
    assert not re.search(r"\b0(\.0)? months?\b", text)
    assert "already at its danger line" in text
    flip = next(r for r in rows_for(plan) if r["metro_cbsa"] == "12420")
    assert "already at its danger line" in flip["why_detail"]
    assert "already at its danger line" in flip["caption"]


def _fake_http(recorded, existing_rows, posted_keys):
    """A PostgREST double behind the one HTTP seam. GETs answer from the
    fixtures; POSTs are recorded and succeed."""
    windows = [dict(w, at_time=w["at_time"] + ":00") for w in MC.FALLBACK_WINDOWS]

    def fake(req):
        url = req.full_url
        if req.get_method() == "POST":
            recorded.append(req)
            return 201, ""
        if "marketing_windows" in url:
            return 200, json.dumps(windows)
        if "marketing_demotions" in url or "press_corroboration" in url:
            return 200, "[]"
        if "dedupe_key=in." in url:
            return 200, json.dumps([{"dedupe_key": k} for k in posted_keys
                                    if k in url])
        return 200, json.dumps(existing_rows)     # the horizon fetch
    return fake


def _run_main(tmp_path, monkeypatch, recorded, existing_rows=(), posted_keys=()):
    data = tmp_path / "data"
    (data / "zips").mkdir(parents=True, exist_ok=True)
    (data / "meta.json").write_text(json.dumps({"period": PERIOD}))
    (data / "velocity-aggregates.json").write_text(
        json.dumps({"period": PERIOD, "gathering": []}))
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(MT, "PACK_DIR", tmp_path / "pack")
    monkeypatch.setattr(MT, "_http",
                        _fake_http(recorded, list(existing_rows), list(posted_keys)))
    rc = MT.main(["--data", str(data), "--now", "2026-08-10T14:00:00Z"])
    assert rc == 0


def test_idempotent_rerun(tmp_path, monkeypatch):
    """Same data, same clock → the same dedupe-key multiset, one row per
    POST, ignore-duplicates on every one, and a status the operator set
    between runs is never touched (no write shape but POST exists)."""
    run1, run2 = [], []
    _run_main(tmp_path, monkeypatch, run1)
    _run_main(tmp_path, monkeypatch, run2)

    def keys(reqs):
        return sorted(json.loads(r.data.decode())[0]["dedupe_key"] for r in reqs)
    assert keys(run1) and keys(run1) == keys(run2)
    for req in run1 + run2:
        body = json.loads(req.data.decode())
        assert isinstance(body, list) and len(body) == 1        # one row per POST
        assert "on_conflict=dedupe_key" in req.full_url
        assert req.get_header("Prefer") == "resolution=ignore-duplicates,return=minimal"
        assert req.get_method() == "POST"                       # never UPDATE-shaped

    # the pack manifest is byte-deterministic across the two runs
    pack = (tmp_path / "pack" / f"pack-{PERIOD}.json").read_bytes()
    _run_main(tmp_path, monkeypatch, [])
    assert (tmp_path / "pack" / f"pack-{PERIOD}.json").read_bytes() == pack

    # a row the operator posted between runs is skipped, not re-planned
    first = json.loads(run1[0].data.decode())[0]
    posted = dict(first, status="posted")
    run3 = []
    _run_main(tmp_path, monkeypatch, run3,
              existing_rows=[posted], posted_keys=[first["dedupe_key"]])
    assert first["dedupe_key"] not in keys(run3)


def test_narrative_unset_degrades(monkeypatch, capsys):
    monkeypatch.setattr(MC, "NARRATIVE", {"text": "", "period": ""})
    assert MT.cand_contrarian(mkrep(), PERIOD) is None
    assert "NARRATIVE unset/stale" in capsys.readouterr().out

    # set but pointing the same way as the data = no gap, no card
    monkeypatch.setattr(MC, "NARRATIVE",
                        {"text": "crash headlines dominating", "period": PERIOD})
    assert MT.cand_contrarian(mkrep(wsi=32.0, delta=1.1), PERIOD) is None
    assert "no gap" in capsys.readouterr().out

    # a real gap renders the §5.2 sentence with the actual numbers
    c = MT.cand_contrarian(mkrep(wsi=14.2, delta=-0.3), PERIOD)
    assert c["why_headline"] == (
        'The narrative says "crash headlines dominating" — the data says '
        "85.8% of scored ZIP markets still rate HOLD or better, and the "
        "warning share fell 0.3 pts this month.")
    assert c["tier"] == 2
    # the caption never quotes operator prose (HYPE guard checks captions)
    assert "crash" not in c["caption"]
    assert not MT.guard(c)


def test_press_pitch_batches_and_gap(monkeypatch, capsys):
    monkeypatch.setattr(MC, "PRESS_OUTLET_BATCHES",
                        [{"slug": "national", "name": "National desks"},
                         {"slug": "regional", "name": "Regional desks"}])
    cands = MT.cand_pitches(mkrep(), NOW, PERIOD)
    assert [c["key"] for c in cands] == [f"mq-{PERIOD}-pitch-national",
                                         f"mq-{PERIOD}-pitch-regional"]
    for c in cands:
        assert c["tier"] == 1
        assert c["caption"].startswith("Warning signs in 14.2%")   # subject first
        # third business day after Mon Aug 10 = Thu Aug 13, 09:00 ET (EDT)
        assert c["fixed_time"] == datetime(2026, 8, 13, 13, 0, tzinfo=timezone.utc)
        # the bare release link was swapped for the tracked one
        assert f"utm_campaign={c['key']}" in c["why_detail"]
        assert "utm_source=press" in c["why_detail"]
        assert "utm_medium=email" in c["why_detail"]
    plan = MT.plan_schedule(cands, [], MC.FALLBACK_WINDOWS, NOW)
    assert all(ch is None for _, _, ch in plan.placed)             # channel NULL

    monkeypatch.setattr(MC, "PRESS_OUTLET_BATCHES", [])
    monkeypatch.delenv("PRESS_LIST", raising=False)
    assert MT.cand_pitches(mkrep(), NOW, PERIOD) == []
    assert "no outlet batches configured" in capsys.readouterr().out


def test_receipt_rules(capsys):
    today = MT.et_date(NOW)
    fresh = MT.cand_receipts([RECEIPT], today, {"14260": "Boise City, ID"}, {}, PERIOD)
    assert len(fresh) == 1
    c = fresh[0]
    assert c["key"] == f"mq-receipt-{RECEIPT_UUID}" and c["tier"] == 2
    assert c["why_headline"] == ("Receipt: Idaho Statesman reported what our "
                                 "index flagged in Boise City, ID 41 days earlier.")
    assert "41-day head start" in c["caption"]
    assert c["source_id"] == RECEIPT_UUID

    behind = dict(RECEIPT, published_on="2026-06-01", flag_date="2026-06-20")
    assert MT.cand_receipts([behind], today, {}, {}, PERIOD) == []   # lead <= 0
    stale = dict(RECEIPT, published_on="2026-06-01", flag_date="2026-04-01")
    assert MT.cand_receipts([stale], today, {}, {}, PERIOD) == []    # > 35 days

    # a GET failure is a labelled gap, never a crash — other rules unaffected
    rows = MT.load_receipts("u", "k", getter=lambda *a, **kw: (None, "boom"))
    assert rows == []
    assert "receipts unreadable — boom" in capsys.readouterr().out


def test_evergreen_only_when_empty():
    plan = MT.plan_schedule([], [], MC.FALLBACK_WINDOWS, NOW)
    MT.evergreen_pass(plan, [], MC.FALLBACK_WINDOWS, CASES, PERIOD, NOW)
    assert len(plan.placed) == MC.HORIZON_WEEKS          # both weeks were empty
    for c, when, ch in plan.placed:
        ws = MT.week_start(MT.et_date(when))
        cid = c["render"]["case_id"]
        assert cid != "miss-39500"                       # miss never selected
        assert c["key"] == f"mq-{ws}-ever-{cid}"
        assert "months before" in c["why_headline"]
        assert "would otherwise be empty" in c["why_detail"]
    boise = MT.cand_evergreen(CASES[:1], date(2026, 8, 9), PERIOD)
    assert "12 months before" in boise["why_headline"]
    assert "18%" in boise["why_headline"]
    assert "-17.9%" in boise["why_detail"]

    # a week with a live placement stays evergreen-free
    live = MT.plan_schedule(full_candidates(), [], MC.FALLBACK_WINDOWS, NOW)
    ws_busy = {MT.week_start(MT.et_date(w)) for _, w, ch in live.placed if ch}
    n_before = len(live.placed)
    MT.evergreen_pass(live, [], MC.FALLBACK_WINDOWS, CASES, PERIOD, NOW)
    for c, when, ch in live.placed[n_before:]:
        assert MT.week_start(MT.et_date(when)) not in ws_busy

    # kind != "miss" is the selection universe, whatever the rotation says
    for k in range(8):
        c = MT.cand_evergreen(CASES, date(2026, 8, 9) + timedelta(days=7 * k), PERIOD)
        assert c["render"]["case_id"] != "miss-39500"


def test_et_slots_dst_and_std(monkeypatch):
    """The DST pin: Sunday 19:30 ET is 23:30Z in August and 00:30Z+1d in
    January — via zoneinfo AND via the arithmetic fallback."""
    aug = (date(2026, 8, 16), datetime(2026, 8, 16, 23, 30, tzinfo=timezone.utc))
    jan = (date(2027, 1, 10), datetime(2027, 1, 11, 0, 30, tzinfo=timezone.utc))
    for d, want in (aug, jan):
        assert MT.et_to_utc(d, "19:30") == want
    monkeypatch.setattr(MT, "_ET", None)                 # tz database gone
    for d, want in (aug, jan):
        assert MT.et_to_utc(d, "19:30") == want


def test_no_supabase_exits_zero(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    (data / "zips").mkdir(parents=True)
    (data / "meta.json").write_text(json.dumps({"period": PERIOD}))
    (data / "velocity-aggregates.json").write_text(
        json.dumps({"period": PERIOD, "gathering": []}))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(MT, "PACK_DIR", tmp_path / "pack")
    rc = MT.main(["--data", str(data), "--now", "2026-08-10T14:00:00Z"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN (Supabase not configured" in out
    assert "WOULD-INSERT" in out                 # evergreen fills the horizon
    assert "marketing queue:" in out


def test_token_contract():
    toks = [utm.token("record", period=PERIOD),
            utm.token("contrarian", period=PERIOD),
            utm.token("flip", period=PERIOD, cbsa="12420"),
            utm.token("receipt", uuid=RECEIPT_UUID),
            utm.token("geo", period=PERIOD, zip="20904"),
            utm.token("evergreen", ws="2026-08-23", case_id="boise-2021"),
            utm.token("burst", rate_period="2026-07", ws="2026-08-09"),
            utm.token("pitch", period=PERIOD, batch_slug="national")]
    assert toks[3] == f"mq-receipt-{RECEIPT_UUID}" and len(toks[3]) == 47
    assert len(set(toks)) == len(toks)
    for t in toks:
        assert utm.SLUG_RE.match(t) and len(t) <= 60
        assert t not in ("zippage", "share")     # the organic utm_source labels
    try:
        utm.token("evergreen", ws="2026-08-23", case_id="x" * 70)
        assert False, "over-long token must raise, not write"
    except ValueError:
        pass


def test_windows_fallback_matches_seed():
    """The mirror drift guard: FALLBACK_WINDOWS must equal the v23 seed
    INSERT, parsed out of the SQL itself. Commented rows (the dormant Naomi
    INSERT) are stripped first — the off switch must stay off here too."""
    live = "\n".join(l for l in SCHEMA.splitlines()
                     if not l.lstrip().startswith("--"))
    m = re.search(r"insert into public\.marketing_windows\s*"
                  r"\(channel, dow, at_time, label, anchor\)\s*values(.*?)"
                  r"on conflict", live, re.S)
    assert m, "seed INSERT not found in schema-v23.sql"
    seed = {(ch, int(dow), at, label, anch == "true")
            for ch, dow, at, label, anch in re.findall(
                r"\('(\w+)',\s*(\d),\s*'(\d\d:\d\d)',\s*'([^']*)',\s*(true|false)\)",
                m.group(1))}
    ours = {(w["channel"], w["dow"], w["at_time"], w["label"], w["anchor"])
            for w in MC.FALLBACK_WINDOWS}
    assert seed == ours
    assert not any(w["channel"] == "nextdoor_naomi" for w in MC.FALLBACK_WINDOWS)
