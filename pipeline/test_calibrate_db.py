"""--from-db calibration — coercion and the shared code path.

The transport is the Supabase CLI and is not tested here; what is tested is
everything between its JSON and the engine, because a coercion bug here
would silently score every ZIP as insufficient_data and the calibration
would read as "the market went quiet" rather than "the parser dropped the
numbers".

Run: python3 -m pytest pipeline/test_calibrate_db.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from calibrate_v2 import DB_SQL, _num, parse_db_rows

HIST = {f"2025-{m:02d}": {} for m in range(8, 13)}
HIST.update({f"2026-{m:02d}": {} for m in range(1, 9)})
HIST["2025-08"] = {"medianPrice": 500000, "averageDaysOnMarket": 40,
                   "totalListings": 200, "medianPricePerSquareFoot": 250,
                   "newListings": 60}

ROW = {"zip": "77494", "as_of_month": "2026-08",
       # numerics arrive as STRINGS from db query — seen live, not assumed
       "list_median_price": "489296", "active_dom": "52.29",
       "total_listings": "979", "list_median_ppsf": "241.5",
       "new_listings": "180", "history": HIST}


def test_num_coerces_the_strings_db_query_actually_returns():
    assert _num("489296") == 489296.0
    assert _num("52.29") == 52.29
    assert _num(None) is None and _num("") is None and _num("n/a") is None


def test_rows_flow_through_the_real_from_market_stats_path():
    m = parse_db_rows([ROW])[0]
    assert m.zip_code == "77494"
    assert m.list_price_yoy == (489296 - 500000) / 500000
    assert m.active_dom_yoy == (52.29 - 40) / 40
    assert m.listings_yoy == (979 - 200) / 200


def test_history_arriving_as_a_json_string_is_handled():
    m = parse_db_rows([dict(ROW, history=json.dumps(HIST))])[0]
    assert m.listings_yoy is not None


def test_missing_history_yields_insufficient_not_a_crash():
    import verdict_v2 as v2
    m = parse_db_rows([dict(ROW, history=None)])[0]
    assert v2.evaluate(m).reasons[0][0] == "insufficient_data"


def test_sql_strips_history_to_the_fields_the_engine_reads():
    """The whole reason the transport is the CLI: the ~180KB payloads are
    stripped server-side. If the SQL stops selecting a field the engine
    needs, YoY for it silently dies — pin the list."""
    for f in ("medianPrice", "averageDaysOnMarket", "totalListings",
              "medianPricePerSquareFoot", "newListings"):
        assert f in DB_SQL
    assert "raw_json->'saleData'->'history'" in DB_SQL
    assert "{source}" in DB_SQL
