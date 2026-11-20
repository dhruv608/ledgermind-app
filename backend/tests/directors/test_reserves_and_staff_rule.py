"""Reserves brought forward never move in the year (FRS 102 10.21), and a firm rule's
two-word phrase matches whatever the order ('Entertainment - Staff' is staff entertaining, BIM45033 / CTA 2009 s1299)."""
from types import SimpleNamespace as N

from backend.app.services.mapping.firm_rules import SEED_RULES, first_rule
from backend.app.services.review import opening_balances as ob

RULES = [N(words=r["words"], except_words=r.get("except_words"), std_code=r["std_code"]) for r in SEED_RULES]


def test_staff_entertaining_named_either_way_round():
    assert first_rule(RULES, "7404 - Entertainment - Staff").std_code == 3070
    assert first_rule(RULES, "Staff Entertainment").std_code == 3070
    assert first_rule(RULES, "Entertainment & Gifts - Client").std_code == 3385
    assert first_rule(RULES, "Meeting - Client").std_code == 3385
    assert first_rule(RULES, "Software - cost") is None              # 'except' words still rule a name out


class Chart:
    def name(self, code, default=""):
        return {8000: "Balance b/fwd"}.get(code, default)


def _rec(name, code, net, opening):
    return N(raw_account_name=name, std_code=code, net_amount=net, opening_amount=opening)


def test_reserves_posted_to_in_the_year_raise_a_point(monkeypatch):
    import backend.app.services.bank_only.books as books
    monkeypatch.setattr(books, "is_books_client", lambda e: False)
    eng = N(id="e1")
    moved = [_rec("3200 - Profit and Loss Account", 8000, -383377.35, -1143555.16), _rec("4800 - Bank", 4800, 10.0, 0.0)]
    out = ob.reserves_moved(eng, moved, Chart(), None)
    assert len(out) == 1 and out[0].procedure_ref == "U-OB-003" and out[0].severity == "HIGH"
    assert "760,177.81" in out[0].finding_title
    still = [_rec("Reserves b/f", 8000, -1143555.16, -1143555.16), _rec("4800 - Bank", 4800, 10.0, 0.0)]
    assert ob.reserves_moved(eng, still, Chart(), None) == []
