"""Last year's corporation tax over / under provision is only worked from the CT account when the client posted no
charge of its own this year (last year's provision v the CT600 / HMRC account); and income a
client already defers itself is not deferred again."""
from types import SimpleNamespace as N

from backend.app.services.review import yearend_journals as yj
from backend.app.services.review.yearend_journals import corporation_tax as ct_module
from backend.app.services.review.accrual_journals import DEFERRED_INCOME_NAME


class Chart:
    def name(self, code, default=""):
        return {5310: "Corporation tax", 3800: "Corporation tax charge", 3810: "Prior year adjustment"}.get(code, default)


def _run(after, lines):
    return yj.ct_prior_year(N(id="e1"), Chart(), [0], after, lines)


def test_client_posted_its_own_charge_so_ask_for_the_hmrc_account():
    lines = [N(code=5310, debit=252718.91, credit=0.0), N(code=5310, debit=0.0, credit=186051.33)]
    findings, journals = _run({5310: -163854.95, 3800: 170647.91}, lines)
    assert journals == [] and findings[0].procedure_ref == "U-CT-002"
    assert "HMRC CT account" in findings[0].finding_title and "230,522.53" in findings[0].finding_title


def test_no_charge_in_the_books_still_works_last_years_difference(monkeypatch):
    monkeypatch.setattr(ct_module, "_journal", lambda *a, **k: "journal")
    monkeypatch.setattr(ct_module, "_entry", lambda *a, **k: "entry")
    lines = [N(code=5310, debit=1014.84, credit=0.0)]           # paid £1,014.84 against £1,000 provided
    findings, journals = _run({5310: 14.84, 3800: 0.0}, lines)
    assert journals == ["journal"] and "under provided by £14.84" in findings[0].finding_title


def test_the_clients_own_deferred_income_account_is_recognised():
    for name in ("2109 - Accruals - Deferred Income", "Income in advance", "Deferred revenue"):
        assert DEFERRED_INCOME_NAME.search(name), name
    assert not DEFERRED_INCOME_NAME.search("Accruals")
