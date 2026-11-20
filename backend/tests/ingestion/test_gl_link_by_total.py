"""A ledger account whose name matches no TB account is linked to the TB account with exactly the same total (a
client's 2025 ledger '404 Net Salary Expense' v TB 'Wages', £14,886.30 both). One to one only."""
import tempfile
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.database import GLTransaction, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.sop.common import code_matcher

# Its own database: other test files set up the shared one first
engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/link.db")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)


def _setup(eid, tb, gl):
    db = SessionLocal()
    for name, code, amount in tb:
        db.add(TBRecord(engagement_id=eid, raw_account_name=name, std_code=code, net_amount=amount))
    for name, dr, cr in gl:
        db.add(GLTransaction(engagement_id=eid, raw_account_name=name, transaction_date=date(2025, 1, 1),
                             debit_amount=dr, credit_amount=cr))
    db.commit()
    return db, db.query(TBRecord).filter(TBRecord.engagement_id == eid).all()


def test_links_by_exact_total():
    db, tb = _setup("L1", [("Wages", 3000, 14886.30), ("Staff - Employer's NI", 3001, 5502.55), ("Sales", 0, -45368.5)],
                    [("404 Net Salary Expense", 10000.0, 0), ("404 Net Salary Expense", 4886.30, 0),
                     ("405 PAYE/NI Expense", 5502.55, 0), ("Sales", 0, 45368.5)])
    code_of = code_matcher(ChartLookup.gl_account_codes(tb))
    assert code_of("404 Net Salary Expense") == 3000
    assert code_of("405 PAYE/NI Expense") == 3001
    assert code_of("Sales") == 0
    db.close()


def test_not_when_two_tb_accounts_share_the_total():
    db, tb = _setup("L2", [("Wages", 3000, 500.0), ("Rent", 3100, 500.0)], [("Net Salary Expense", 500.0, 0)])
    assert code_matcher(ChartLookup.gl_account_codes(tb))("Net Salary Expense") is None
    db.close()


def test_not_to_a_tb_account_the_ledger_already_names():
    db, tb = _setup("L3", [("Wages", 3000, 700.0)], [("Wages", 700.0, 0), ("Other wages", 700.0, 0)])
    code_of = code_matcher(ChartLookup.gl_account_codes(tb))
    assert code_of("Wages") == 3000 and code_of("Other wages") is None
    db.close()
