"""Capital items: a new roof or a refurbishment is the accountant's call, never a journal (PIM2025); a keyword alone
is not enough for a journal; desk, chair, tools, software licence and website build are asset words."""
from backend.app.services.review.capital_journals import REPAIR_OR_IMPROVEMENT
from backend.app.services.sop.capital import _CAPITAL_GROUPS


def _group(text):
    return [g for g, _code, pattern in _CAPITAL_GROUPS if pattern.search(text)]


def test_roof_and_refurbishment_are_questions():
    assert REPAIR_OR_IMPROVEMENT.search("ABC Roofing - roof replacement")
    assert REPAIR_OR_IMPROVEMENT.search("Office refurbishment works")
    assert not REPAIR_OR_IMPROVEMENT.search("Dell - laptop for new starter")


def test_new_asset_words():
    assert "Office furniture, fixtures & fittings" in _group("IKEA - two desks and a chair")
    assert "Plant, machinery & industrial equipment" in _group("Makita power tools")
    assert "Software & intangible assets" in _group("Website build - new shop site")


def test_revenue_items_on_asset_codes():
    from backend.app.services.review.capital_journals import REVENUE_IN_ASSETS, _revenue_target
    assert REVENUE_IN_ASSETS.search("Kwik Fit - MOT and service")
    assert not REVENUE_IN_ASSETS.search("Dell - XPS laptop")
    assert _revenue_target(4131, "MOT") == 3234
    assert _revenue_target(4151, "Microsoft 365 annual licence renewal") == 3240
    assert _revenue_target(4121, "Boiler repair") == 3250
