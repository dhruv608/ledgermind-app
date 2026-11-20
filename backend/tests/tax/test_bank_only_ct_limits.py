"""Bank-only jobs' CT estimate: the £50,000 / £250,000 limits cut for a short period and shared with associated
companies (CTA 2010 s18D), as the main CT computation does."""
import json
from datetime import date
from types import SimpleNamespace as N

from openpyxl import Workbook

from backend.app.services.bank_only.books_tabs.balance_tabs import BalanceTabs


class _Books(BalanceTabs):
    def __init__(self, prior, associates):
        self.ye, self.tb_row = date(2025, 12, 31), {}
        self.eng = N(prior_period_end_date=prior,
                     profile=N(tax_inputs=json.dumps({"associated_companies": associates}) if associates is not None else None))


def _sheet(prior, associates):
    ws = Workbook().active
    _Books(prior, associates).tax_computation({"ws": ws, "next": 1}, "100000")
    return {ws.cell(row=r, column=1).value: ws.cell(row=r, column=3).value for r in range(1, ws.max_row + 1)}


def test_full_year_no_associates_keeps_50k_and_250k():
    cells = _sheet(date(2024, 12, 31), None)
    assert cells["Lower limit (£50,000 x 365/365 / 1)"] == "=ROUND(50000*365/365/1,2)"
    assert cells["Upper limit (£250,000 x 365/365 / 1)"] == "=ROUND(250000*365/365/1,2)"


def test_short_period_and_associates_cut_the_limits():
    cells = _sheet(date(2025, 6, 30), 1)                       # 184 days, one associated company
    assert cells["Lower limit (£50,000 x 184/365 / 2)"] == "=ROUND(50000*184/365/2,2)"
    tax = next(v for k, v in cells.items() if k and k.startswith("Tax liability"))
    assert "C" in tax and "50000" not in tax and "250000" not in tax   # the formula uses the limit cells
