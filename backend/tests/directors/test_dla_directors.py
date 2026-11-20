"""The director's loan accounts put to their director, a control each when two or more."""
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.workbook.dla_directors import NOT_NAMED, director_groups, person_of


def _t(name, code=5400):
    return N(raw_account_name=name, std_code=code)


def test_person_of():
    assert person_of("5400 - Director Loan account R Fowler") == "R Fowler"
    assert person_of("5400 - Directors Loan - Carl") == "Carl"
    assert person_of("Directors loan account (Current liabilities - creditors < 1 year)") is None
    assert person_of("5400 - Directors loan account - drawings") is None


def test_two_directors_split():
    tb = [_t("Director Loan account R Fowler"), _t("Director Loan account S Lawman"), _t("Bank", 4800)]
    assert director_groups(tb, []) == {"R Fowler": {"Director Loan account R Fowler"},
                                       "S Lawman": {"Director Loan account S Lawman"}}


def test_named_by_client_details_and_unnamed_kept():
    tb = [_t("5400 - Directors Loan - Carl"), _t("Directors Loan - Martin", 5401), _t("Directors loan account - drawings")]
    groups = director_groups(tb, ["Carl Smith", "Martin Jones"])
    assert set(groups) == {"Carl Smith", "Martin Jones", NOT_NAMED}


def test_one_director_no_split():
    tb = [_t("Directors loan account (Current liabilities)"), _t("Directors loan account - drawings"),
          _t("Director Loan account R Fowler")]
    assert director_groups(tb, []) == {}
