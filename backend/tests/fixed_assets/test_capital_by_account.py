"""Capital items named only by the client's account: a one-off purchase over the limit on an account
naming the asset becomes a proposed move to additions; software / subscription accounts and repeated costs stay
questions. Made-up lines."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.review.capital_journals import SOFTWARE_ACCOUNT
from backend.app.services.sop.capital import find_capital_items
from backend.app.services.sop.common import GLLine

CHART = {3241: N(financial_class="Profit and Loss", category="Administrative expenses", std_name="Computer costs"),
         3380: N(financial_class="Profit and Loss", category="Administrative expenses", std_name="Office costs")}


def line(account, amount, desc="Amazon - AMZNMKTPLACE", code=3241, d=date(2025, 3, 1)):
    return GLLine(d, code, account, amount, 0.0, desc, "Expense")


def test_account_named_for_hardware_one_off():
    f = find_capital_items([line("Computer running costs", 1024.28), line("Computer running costs", 40.0)], CHART, 500)
    assert len(f) == 1 and f[0].by_account and f[0].one_off and f[0].suggested_code == 4151


def test_repeated_amount_is_not_one_off():
    f = find_capital_items([line("Computer hardware", 600.0, d=date(2025, m, 1)) for m in (1, 2, 3)], CHART, 500)
    assert f and not any(x.one_off for x in f)


def test_software_accounts_stay_questions():
    assert SOFTWARE_ACCOUNT.search("3241 Computer software costs") and SOFTWARE_ACCOUNT.search("Software & Tools (rebillable)")
    assert not SOFTWARE_ACCOUNT.search("Computer running costs") and not SOFTWARE_ACCOUNT.search("Photography Equipment")
