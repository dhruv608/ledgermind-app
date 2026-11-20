"""An accrual or prepayment the app proposed, edited into the accountant's own line; their line wins."""
import os
import tempfile
from types import SimpleNamespace as N

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/edit.db"

from backend.app.core.database import Base, SessionLocal, engine
from backend.app.models.database import AuditFinding, ProposedJournal
from backend.app.models.yearend_adjustments import YearEndAdjustment
from backend.app.services.review.adjustment_edit import accountant_wins, edit_into_line, kind_of

Base.metadata.create_all(engine)


def _j(dr, cr, amount=600.0, status="PROPOSED", source="REVIEW", finding_id=None):
    return ProposedJournal(engagement_id="e1", journal_ref="AJ01", description="Prepayment: insurance", debit_code=dr,
                           debit_name="", credit_code=cr, credit_name="", amount=amount, status=status, source=source,
                           finding_id=finding_id)


def test_kind_of():
    assert kind_of(_j(4900, 3260)) == ("PREPAYMENT", 3260)
    assert kind_of(_j(3301, 5360)) == ("ACCRUAL", 3301)
    assert kind_of(_j(5360, 3301)) is None          # last year's accrual released: not this year's item
    assert kind_of(_j(3400, 4124)) is None


def test_edit_into_line_and_the_line_wins():
    db = SessionLocal()
    f = AuditFinding(engagement_id="e1", stage="STAGE_1_ACCOUNTING", procedure_ref="U-PRE-001", procedure_name="p",
                     finding_title="t", finding_details="d", status="OPEN")
    db.add(f)
    db.commit()
    j = _j(4900, 3260, finding_id=f.id)
    db.add(j)
    db.commit()
    line = edit_into_line(db, j, 700.0, "Insurance, policy from November", None, None)
    assert (line.kind, line.period, line.cost_code, float(line.amount)) == ("PREPAYMENT", "THIS_YEAR", 3260, 700.0)
    assert "edited from review point U-PRE-001" in line.description and j.status == "REJECTED"
    # the next run: the app's own prepayment on 3260 is not proposed again; one on another cost still is
    eng = N(id="e1")
    again, other = _j(4900, 3260), _j(4900, 3290)
    p1, p2 = N(), N()
    again._point, other._point = p1, p2
    findings, journals = accountant_wins(eng, db, [p1, p2], [again, other])
    assert journals == [other] and findings == [p2]
    db.query(YearEndAdjustment).delete()
    db.commit()
    db.close()


def test_not_editable():
    db = SessionLocal()
    for journal, word in ((_j(4900, 3260, status="APPROVED"), "approved"), (_j(4900, 3260, source="MANUAL"), "entered"),
                          (_j(3400, 4124), "Only")):
        try:
            edit_into_line(db, journal, 100.0, "", None, None)
            raise AssertionError("should refuse")
        except ValueError as e:
            assert word in str(e)
    db.close()
