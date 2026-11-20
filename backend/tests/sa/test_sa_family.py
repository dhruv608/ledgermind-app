"""Child Benefit charge, Marriage Allowance and student loans (made-up figures; no database)."""

from types import SimpleNamespace as N

from backend.app.sa import boxes, family
from backend.app.sa.engine.calc import Income, calculate


def fam(**kw):
    base = dict(child_benefit=None, children=None, cb_stopped=None, higher_income=None, marriage=None, spouse_name=None,
                loan_plans=None, postgraduate=0, studying=0, sl_deducted=None, pgl_deducted=None)
    return N(**{**base, **kw})


def test_student_loan_plan_threshold_and_paye():
    inc = Income(employment=40000, savings=1500)                       # interest under £2,000: left out
    loan = family.student_loan(inc, fam(loan_plans="PLAN_2", sl_deducted=1000), "2025-26")
    assert (loan["income"], loan["threshold"], loan["due"], loan["charge"]) == (40000, 28470, 1037, 37)


def test_unearned_over_2000_counts_in_full():
    loan = family.student_loan(Income(employment=27000, savings=2100), fam(loan_plans="PLAN_2"), "2025-26")
    assert (loan["unearned_counted"], loan["income"], loan["due"]) == (True, 29100, 56)


def test_two_plans_lowest_threshold_and_postgraduate():
    loan = family.student_loan(Income(employment=40000), fam(loan_plans="PLAN_1,PLAN_2", postgraduate=1), "2025-26")
    assert (loan["threshold"], loan["due"], loan["pgl_due"], loan["charge"]) == (26065, 1254, 1140, 2394)
    assert family.student_loan(Income(employment=40000), fam(loan_plans="PLAN_2", studying=1), "2025-26")["charge"] == 0
    assert family.student_loan(Income(employment=40000), fam(loan_plans="PLAN_1"), "2024-25")["threshold"] == 24990


def test_child_benefit_charge_only_for_the_higher_income():
    inc = Income(employment=70000)
    family.apply(inc, fam(child_benefit=2000, higher_income="ME"), "2025-26")
    assert calculate(inc).hicbc == 1000                                  # 1% per £200 over £60,000: 50%
    inc = Income(employment=70000)
    family.apply(inc, fam(child_benefit=2000, higher_income="PARTNER"), "2025-26")
    assert calculate(inc).hicbc == 0


def test_issues_block_until_known():
    calc = calculate(Income(employment=70000)).as_dict()
    got = family.issues(fam(), calc, {"child_benefit": "YES", "student_loan": "YES"}, "2025-26")
    assert [(i["key"], i["block"]) for i in got] == [("cb_amount", True), ("cb_higher", True), ("sl_plan", True)]
    got = family.issues(fam(marriage="RECEIVED"), calc, {}, "2025-26")
    assert [i["key"] for i in got] == ["ma_rate"]                        # taxed at the higher rate: not allowed
    low = calculate(Income(employment=20000)).as_dict()
    assert family.issues(fam(marriage="RECEIVED"), low, {"child_benefit": "YES"}, "2025-26") == []


def test_marriage_allowance_in_the_engine():
    gives = calculate(Income(employment=20000, marriage_allowance="transferred"))
    gets = calculate(Income(employment=20000, marriage_allowance="received"))
    assert gives.personal_allowance == 11310 and gets.reductions["marriage_allowance"] == 252


def test_tr5_boxes():
    calc = {"adjusted_net_income": 70000.0}
    page = boxes.family_page(fam(loan_plans="PLAN_2", sl_deducted=1000, child_benefit=2000, children=2, higher_income="ME",
                                 marriage="TRANSFERRED", spouse_name="Alex Example"), calc, "2025-26")[0]
    got = {r["box"]: r["value"] for r in page["rows"]}
    assert got == {"SL 1": "X", "SL 2": 1000, "CB 1": 2000, "CB 2": "2", "MA 1": "Alex", "MA 2": "Example"}
    partner = boxes.family_page(fam(child_benefit=2000, higher_income="PARTNER"), calc, "2025-26")
    assert partner == []


def test_investment_reliefs_and_loan_interest():
    from backend.app.sa.engine.calc import Income, calculate
    c = calculate(Income(employment=60000, investments={"EIS": 10000, "SEIS": 4000, "VCT": 300000}))
    # VCT 30% of the £200,000 limit, but only as far as the income tax goes; nothing left for EIS and SEIS
    assert c.reductions["vct"] == c.income_tax and "eis" not in c.reductions and c.income_tax_due == 0
    c = calculate(Income(employment=60000, investments={"EIS": 10000, "SEIS": 4000}))
    assert (c.reductions["eis"], c.reductions["seis"]) == (3000, 2000)
    capped = calculate(Income(employment=300000, loan_interest=100000))     # 25% of £300,000 = £75,000
    plain = calculate(Income(employment=225000))
    assert capped.net_income == plain.net_income == 225000


def test_sa101_boxes():
    from types import SimpleNamespace as N
    line = lambda kind, amount: N(source="RELIEFS", kind=kind, amount=amount, include=1, share=1, tax_paid=0, label="", note=None, doc_id=None)
    pages = boxes.main_return([line("EIS", 10000), line("SEIS", 4000), line("LOAN_INTEREST", 900)])
    ai2 = next(p for p in pages if p["form"] == "SA101 Ai2")
    assert {r["box"]: r["value"] for r in ai2["rows"]} == {"2": 10000, "5": 900, "10": 4000}


def test_the_allowance_taper_is_a_planning_point():
    from backend.app.sa.family import issues
    calc = {"adjusted_net_income": 110000.0, "lines": []}
    pts = [i for i in issues(None, calc, {}, "2025-26") if i["key"] == "pa_taper"]
    assert pts and "£5,000 of the personal allowance is lost" in pts[0]["text"] and not pts[0]["block"]
    assert not [i for i in issues(None, {"adjusted_net_income": 90000.0, "lines": []}, {}, "2025-26") if i["key"] == "pa_taper"]
