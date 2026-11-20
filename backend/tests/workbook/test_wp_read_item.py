"""C14 on the Data check: what LM read from last year's working paper (the mapping found is shown)."""
import json
from types import SimpleNamespace as NS

from backend.app.services.setup.extraction_checks import wp_read_item


def _profile(read):
    return NS(tax_inputs=json.dumps({"_last_year_wp_read": read}))


def test_shows_what_was_read():
    item = wp_read_item(None, NS(id="x"), _profile({"year_end": "2025-03-31", "used": True, "etb_tab": "Trial Balance",
                                                     "etb_codes": 42, "accruals": 1, "prepayments": 2, "claims": 0,
                                                     "losses_cf": 1500.0, "open_queries": 3}))
    assert item.status == "OK"
    assert "31/03/2025" in item.detail and "'Trial Balance' tab (42 codes)" in item.detail
    assert "1 accrual and 2 prepayments" in item.detail and "£1,500.00" in item.detail and "3 open queries" in item.detail


def test_not_used_is_a_warning():
    item = wp_read_item(None, NS(id="x"), _profile({"year_end": None, "used": False, "etb_tab": None, "etb_codes": 0}))
    assert item.status == "WARNING" and "year end could not be found" in item.detail


def test_nothing_uploaded():
    assert wp_read_item(None, NS(id="x"), NS(tax_inputs="{}")) is None


def test_a_file_that_is_not_a_paper_does_not_replace_the_read():
    import json
    from datetime import date
    from types import SimpleNamespace as NS
    from backend.app.services.ingestion.supplementary_parser import SupplementaryParserService as S
    eng = NS(profile=NS(tax_inputs="{}"))
    db = NS(commit=lambda: None)
    paper = {"year_end": date(2024, 3, 31), "tax": {"etb_tab": "B1-ETB", "etb_final": {4000: 1.0}}, "items": []}
    S._store_wp_read(eng, paper, True, db)
    S._store_wp_read(eng, {"year_end": None, "tax": {}, "items": []}, False, db)        # a payroll file
    S._store_wp_read(eng, {"year_end": date(2020, 3, 31), "tax": {"etb_tab": "ETB"}, "items": []}, False, db)
    read = json.loads(eng.profile.tax_inputs)["_last_year_wp_read"]
    assert read["used"] and read["etb_tab"] == "B1-ETB" and read["year_end"] == "2024-03-31"
