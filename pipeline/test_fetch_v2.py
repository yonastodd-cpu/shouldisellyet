"""The v2 (data-center hub) schema adapter.

The dangerous part of the 2026-06 source migration is silent unit drift:
the new columns LOOK like the old ones but three of them changed meaning
(price/inventory YoY became true percents; the DOM YoY column claims "(%)"
but actually holds Δdays × 100 — both verified against the national file,
see _V2_MAP in fetch_data.py). A wrong mapping here doesn't crash — it
quietly mis-scores every ZIP in the country. So these tests pin the exact
numbers end to end.

Run: python3 -m pytest pipeline/test_fetch_v2.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_data
from fetch_data import load_price_drops, load_rows, load_zip_states, row_to_metrics

V2_HEADER = (
    '"LAST UPDATED","FREQUENCY","PERIOD BEGIN","PERIOD END","REGION ID",'
    '"REGION TYPE","REGION NAME","METRO","HOMES SOLD","HOMES SOLD MOM (%)",'
    '"HOMES SOLD YOY (%)","MEDIAN SALE PRICE NSA ($)","MEDIAN SALE PRICE NSA MOM (%)",'
    '"MEDIAN SALE PRICE NSA YOY (%)","MEDIAN DAYS ON MARKET (DAYS)",'
    '"MEDIAN DAYS ON MARKET MOM (%)","MEDIAN DAYS ON MARKET YOY (%)",'
    '"INVENTORY","INVENTORY MOM (%)","INVENTORY YOY (%)","MONTHS OF SUPPLY",'
    '"MONTHS OF SUPPLY MOM (%)","MONTHS OF SUPPLY YOY (%)"'
)

# 07002: price +3.98% · DOM 34, column 752.25 (= +7.52 days) · inventory
# −7.45% · months of supply 4 — real values from the live file's first row,
# minus columns this slice doesn't carry.
V2_ROWS = [
    '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30",2509,"Zip","07002",'
    '"New York, NY metro area",80,NA,-13.75,649853,NA,3.98,34,NA,752.25,106,NA,-7.45,4,NA,27.4',
    # a metro row that must be filtered out
    '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30",1,"Metro","Bayonne, NJ",'
    '"New York, NY metro area",999,NA,1,1,NA,1,1,NA,1,1,NA,1,1,NA,1',
    # NA-heavy thin ZIP: mapped fields must come back empty, not crash
    '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30",2510,"Zip","07003",'
    '"New York, NY metro area",2,NA,NA,150000,NA,NA,NA,NA,NA,NA,NA,NA,NA,NA,NA',
]


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _use_states(monkeypatch, tmp_path, mapping):
    """Point the adapter's zip→state lookup at a known tiny committed map."""
    fetch_data._ZIP_STATES = None
    (tmp_path / "zip_states.csv").write_text(
        "zip,state\n" + "\n".join(f"{z},{s}" for z, s in mapping.items()) + "\n")
    real = load_zip_states
    monkeypatch.setattr(fetch_data, "load_zip_states", lambda base=None: real(tmp_path))


def test_v2_rows_translate_to_legacy_keys(tmp_path, monkeypatch):
    _use_states(monkeypatch, tmp_path, {"07002": "NJ"})
    src = _write(tmp_path, "v2.csv", V2_HEADER + "\n" + "\n".join(V2_ROWS) + "\n")
    rows = list(load_rows(src))

    assert len(rows) == 2, "metro row must be filtered out"
    r = rows[0]
    assert r["region"] == "07002"          # bare ZIP, leading zero intact
    assert r["state_code"] == "NJ"         # from the committed mapping
    assert r["period_end"] == "2026-06-30"
    assert r["median_sale_price"] == "649853"
    # ——— the three unit conversions this file exists to pin ———
    assert float(r["median_sale_price_yoy"]) == 0.0398   # percent → fraction
    assert float(r["inventory_yoy"]) == -0.0745          # percent → fraction
    assert float(r["median_dom_yoy"]) == 7.5225          # Δdays×100 → days
    assert r["months_of_supply"] == "4"

    thin = rows[1]
    assert thin["median_sale_price_yoy"] == ""           # NA → empty, not crash
    assert thin["median_dom"] == ""


def test_v2_row_feeds_the_verdict_engine(tmp_path, monkeypatch):
    _use_states(monkeypatch, tmp_path, {"07002": "NJ"})
    src = _write(tmp_path, "v2.csv", V2_HEADER + "\n" + V2_ROWS[0] + "\n")
    row = next(iter(load_rows(src)))
    m = row_to_metrics("07002", row["period_end"], row["state_code"], row)
    assert m.months_of_supply == 4.0        # direct column, not the inv/sold proxy
    assert m.median_sale_price_yoy == 0.0398
    assert m.median_dom == 34.0
    assert m.median_dom_yoy == 7.5225       # days — what verdict.py documents
    assert m.inventory_yoy == -0.0745


def test_legacy_tsv_still_parses(tmp_path):
    """seed.tsv is the old schema; archived copies must keep working."""
    rows = list(load_rows(str(Path(__file__).parent / "seed.tsv")))
    assert len(rows) == 2
    assert rows[0]["region"] == "Zip Code: 20874"
    assert rows[0]["state_code"] == "MD"
    assert "_schema" not in rows[0]          # v1 passes through untranslated


def test_price_drops_newest_period_wins(tmp_path):
    src = _write(tmp_path, "pd.csv",
        '"LAST UPDATED","FREQUENCY","PERIOD BEGIN","PERIOD END","REGION TYPE",'
        '"REGION NAME","METRO","PRICE DROPS","PRICE DROPS MOM (%)","PRICE DROPS YOY (%)",'
        '"AVERAGE SIZE OF PRICE DROP (%)","AVERAGE SIZE OF PRICE DROP MOM (PPTS)",'
        '"AVERAGE SIZE OF PRICE DROP YOY (PPTS)","PERCENT ACTIVE WITH PRICE DROPS (%)",'
        '"PERCENT ACTIVE WITH PRICE DROPS MOM (PPTS)","PERCENT ACTIVE WITH PRICE DROPS YOY (PPTS)",'
        '"HOMES SOLD WITH PRICE DROPS","HOMES SOLD WITH PRICE DROPS MOM (%)","HOMES SOLD WITH PRICE DROPS YOY (%)"\n'
        '"2026-07-03","Rolling 3 Months","2026-03-01","2026-05-31","Zip","07002","m",30,NA,1,4,NA,1,12.5,NA,1,9,NA,1\n'
        '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30","Zip","07002","m",37,NA,1,4.28,NA,1,15.08,NA,1,11,NA,1\n'
        '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30","Metro","x","m",1,NA,1,1,NA,1,99,NA,1,1,NA,1\n'
        '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30","Zip","07003","m",1,NA,1,1,NA,1,NA,NA,1,1,NA,1\n')
    out = load_price_drops(src)
    assert out["07002"] == ("2026-06", 0.1508)   # newest period, percent → fraction
    assert "07003" not in out                    # NA share → absent, not zero


def test_zip_states_prefix_fallback(tmp_path, monkeypatch):
    fetch_data._ZIP_STATES = None
    (tmp_path / "zip_states.csv").write_text(
        "zip,state\n20874,MD\n20876,MD\n20901,MD\n")
    zs = load_zip_states(tmp_path)
    assert zs.get("20874") == "MD"     # exact
    assert zs.get("20899") == "MD"     # unseen ZIP → 3-digit-prefix majority
    assert zs.get("99999") == ""       # unknown prefix → honest empty
    fetch_data._ZIP_STATES = None      # don't leak the tiny map to other tests


def test_metro_state_is_the_last_resort(tmp_path, monkeypatch):
    """A ZIP absent from the committed map (a v1-era coverage gap like all of
    Albuquerque) takes its state from the metro name; a mapped ZIP must NOT —
    07002 is NJ inside the "New York, NY" metro."""
    _use_states(monkeypatch, tmp_path, {"07002": "NJ"})
    rows_txt = V2_HEADER + "\n" + V2_ROWS[0] + "\n" + (
        '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30",9,"Zip","87102",'
        '"Albuquerque, NM metro area",50,NA,1,300000,NA,1,30,NA,100,90,NA,1,3,NA,1\n'
        # metro "NA" → no state to derive; must stay empty, not crash
        '"2026-07-03","Rolling 3 Months","2026-04-01","2026-06-30",10,"Zip","96799",'
        '"NA",5,NA,1,400000,NA,1,40,NA,100,20,NA,1,4,NA,1\n')
    src = _write(tmp_path, "v2.csv", rows_txt)
    by_zip = {r["region"]: r for r in load_rows(src)}
    assert by_zip["07002"]["state_code"] == "NJ"   # committed map wins over metro
    assert by_zip["87102"]["state_code"] == "NM"   # metro fills the gap
    assert by_zip["96799"]["state_code"] == ""     # no metro → honest empty
