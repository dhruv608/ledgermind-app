"""A register class the books keep under another class's codes (fixtures inside plant) is worked with that class,
asset by asset at each asset's own rate, instead of the whole pool at the firm default."""
from types import SimpleNamespace as NS

from backend.app.services.review.yearend_journals import _far_class, merged_classes, register_unreliable_classes


def asset(category, cost_bwd, rate="25% RBM"):
    return NS(category=category, cost_bwd=cost_bwd, depr_rate_method=rate, additions=0, disposals=0)


def tb(code, opening):
    return NS(std_code=code, opening_amount=opening)


FAR = [asset("Plant & Machinery", 18847.97), asset("Fixtures & Fittings", 776.00),
       asset("Fixtures & Fittings", 7336.94, "20% RBM"), asset("Motor Vehicle", 168933.50)]


def test_fixtures_kept_in_plant_codes_merge_into_plant():
    tbs = [tb(4120, 26960.91), tb(4130, 168933.50)]
    after = {4120: 26960.91, 4121: 1224.70, 4130: 168933.50}
    merged = merged_classes(FAR, tbs, after)
    assert merged == {"Fixtures and fittings": "Plant and machinery"}
    # So the register is reliable for plant again (each asset keeps its own rate) and nothing is unreliable
    assert register_unreliable_classes(FAR, tbs, after, merged) == set()
    held = {"Plant and machinery": 28185.61}
    assert _far_class("Fixtures & Fittings", held, merged) == "Plant and machinery"
    # Without the merge both classes would fall back to the books at the firm default
    assert register_unreliable_classes(FAR, tbs, after) == {"Plant and machinery", "Fixtures and fittings"}


def test_no_merge_when_the_sum_does_not_fill_the_gap():
    tbs = [tb(4120, 30000.00), tb(4130, 168933.50)]
    after = {4120: 30000.00, 4130: 168933.50}
    assert merged_classes(FAR, tbs, after) == {}


def test_no_merge_when_the_books_hold_the_class():
    tbs = [tb(4120, 26960.91), tb(4140, 8112.94), tb(4130, 168933.50)]
    after = {4120: 26960.91, 4140: 8112.94, 4130: 168933.50}
    assert merged_classes(FAR, tbs, after) == {}


def test_no_merge_when_the_register_already_agrees():
    far = [asset("Plant & Machinery", 26960.91), asset("Fixtures & Fittings", 8112.94)]
    tbs = [tb(4120, 26960.91)]
    assert merged_classes(far, tbs, {4120: 26960.91}) == {}
