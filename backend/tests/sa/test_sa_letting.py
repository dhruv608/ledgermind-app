"""Letting agent statements read (made-up figures): headings, lines outside the tax year, money paid to the landlord
left out, the owner check and the same property under two spellings (R-SA105-01 to 11)."""

from backend.app.sa.extract import letting as T


def statement(**kw):
    base = {"agent": "A Lettings Ltd", "landlords": ["Kay Writer"], "period_from": "2025-07-01", "period_to": "2025-07-31",
            "properties": [{"address": "8, Elm Close, Townley TW1 2AB", "lines": [
                {"date": "2025-07-01", "description": "Rent received", "amount": "1,000.00", "heading": "RENT"},
                {"date": "2025-07-01", "description": "Management fee 12%", "amount": 120, "heading": "PROFESSIONAL"},
                {"date": "2025-07-10", "description": "Boiler repair", "amount": 85.5, "heading": "unknown"},
                {"date": "2025-07-31", "description": "Paid to landlord", "amount": 794.5, "heading": "NOT_INCOME"},
                {"date": "2025-03-31", "description": "Rent received", "amount": 1000, "heading": "RENT"}]}]}
    base.update(kw)
    return base


def test_lines_under_their_headings_in_the_year():
    f = T.clean(statement())
    status, notes = T.checks(f, "2025-26", "Kay Writer")
    heads = [(l["heading"], l["amount"]) for l in f["properties"][0]["lines"]]
    assert heads == [("RENT", 1000.0), ("PROFESSIONAL", 120.0), ("REPAIRS", 85.5), ("NOT_INCOME", 794.5)]
    assert status == "CHECK" and "1 line dated outside 2025-26" in notes[0]     # the March 2025 rent left out
    assert T.rent(f) == 1000.0


def test_another_year_or_another_landlord():
    f = T.clean(statement(period_from="2024-05-01", period_to="2024-05-31", properties=[{"address": "8 Elm Close", "lines": [
        {"date": "2024-05-01", "description": "Rent", "amount": 900, "heading": "RENT"}]}]))
    assert T.checks(f, "2025-26")[0] == "OTHER_YEAR"
    g = T.clean(statement(landlords=["Alex Other"]))
    assert T.checks(g, "2025-26", "Kay Writer")[0] == "CHECK" and g["other_person"]


def test_the_same_property_under_two_spellings():
    assert T.same_property("8, Elm Close - Rent for the month", "8 Elm Close Rental Income")
    assert T.same_property("56 Bennett St CV21 2ER", "56 Bennett St")
    assert not T.same_property("8 Elm Close", "10 Elm Close")


def test_two_readers_must_agree_on_the_rent():
    f = T.clean(statement())
    second = statement()
    second["properties"][0]["lines"][0]["amount"] = 100
    status, notes = T.checks(f, "2025-26", "Kay Writer", second)
    assert any("disagree on the rent" in n for n in notes)


def test_not_a_rent_statement_or_overseas():
    f = T.clean({"is_rent_statement": False, "properties": [{"address": "8 Elm Close", "lines": [
        {"date": "2025-05-01", "description": "Fuel", "amount": 40, "heading": "OTHER"}]}]})
    assert T.checks(f, "2025-26", "Kay Writer")[0] == "FILED" and f["properties"] == []
    g = T.clean(statement(currency="NZD", properties=[{"address": "2/11 Some Street, Napier", "country": "NZL", "lines": [
        {"date": "2025-06-01", "description": "Rent", "amount": 1500, "heading": "RENT"}]}]))
    status, notes = T.checks(g, "2025-26", "Kay Writer")
    assert T.overseas(g) and status == "CHECK" and "SA106" in notes[0]


def test_no_agent_named_waits_for_a_confirm():
    f = T.clean(statement(agent=None))
    status, notes = T.checks(f, "2025-26", "Kay Writer")
    assert status == "CHECK" and f["unconfirmed"] and any("No letting agent" in n for n in notes)
    g = T.clean(statement())
    T.checks(g, "2025-26", "Kay Writer")
    assert not g.get("unconfirmed")


def test_a_short_forename_is_the_landlord():
    # A short forename and a misspelt surname on the agent's statement: counted, the spelling noted (R-IN-07)
    from backend.app.sa.extract import p60
    assert p60.owner("Andy Fletchour", "Andrew Fletchour") is None
    assert p60.owner("Andy Fletcher", "Andrew Fletchour") == "NAME"
    assert p60.owner("Bob Smith", "Andrew Smith") == "OTHER"


def test_initials_run_together():
    from backend.app.sa.extract import p60
    assert p60.owner("CJ BEATTIE", "Chris Beattie") is None
    assert p60.owner("PK SMITH", "John Smith") == "OTHER"


def test_a_year_to_31_march_is_the_tax_year():
    # The client's own sheet, 1 April to 31 March: its 1 April rent is in the year (ITTOIA s275A, PIM1015)
    from backend.app.sa.extract import letting
    f = {"is_rent_statement": True, "agent": None, "landlords": [], "currency": "GBP", "period_from": "2025-04-01",
         "period_to": "2026-03-01", "properties": [{"address": "1 Test Road", "country": "GBR", "lines": [
             {"on": "2025-04-01", "description": "Rent", "heading": "RENT", "amount": 900.0},
             {"on": "2026-03-01", "description": "Rent", "heading": "RENT", "amount": 900.0}]}]}
    letting.checks(f, "2025-26", "Pat Test")
    assert letting.rent(f) == 1800.0
    monthly = {"period_from": "2025-04-01", "period_to": "2025-04-30"}
    assert not letting.march_basis(monthly)


def test_surname_first_names_and_depreciation():
    # A tax office prints 'Pollard, Philip' (made-up use); depreciation is never a cost (R-SA105-08)
    from backend.app.sa.extract import letting, p60
    assert p60.owner("Testman, Philip", "Philip Testman") is None and p60.owner("Testman, Ann", "Philip Testman") == "OTHER"
    f = letting.clean({"is_rent_statement": True, "agent": "An Agent", "currency": "NZD", "properties": [{"address": "1 Test St",
        "country": "NZL", "lines": [{"date": "2026-03-31", "description": "Rent", "heading": "RENT", "amount": 27040},
                                    {"date": "2026-03-31", "description": "Depreciation", "heading": "OTHER", "amount": 924.59}]}]})
    status, notes = letting.checks(f, "2025-26", "Philip Testman")
    assert [l["heading"] for l in f["properties"][0]["lines"]] == ["RENT", "NOT_INCOME"]
    assert status == "CHECK" and any("Depreciation of 924.59" in n for n in notes)


def test_a_dash_in_this_years_column_is_nothing_this_year():
    from backend.app.sa.extract import letting
    text = "2026\nper partner\n2025\nRent\n27,040.00\n$\n13,520.00\n$\n27,560.00\nTennant Gift\n-\n$\n-\n$\n52.00\n$"
    f = {"properties": [{"lines": [{"description": "Rent", "amount": 27040.0}, {"description": "Tennant Gift", "amount": 52.0}]}]}
    assert [l["description"] for l in letting.with_text(f, text)["properties"][0]["lines"]] == ["Rent"]
    one = {"properties": [{"lines": [{"description": "Rent Received", "amount": 725.0}]}]}
    assert len(letting.with_text(one, "Rent Received\n-\n725.00")["properties"][0]["lines"]) == 1   # one column: untouched
