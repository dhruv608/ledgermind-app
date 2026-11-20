"""The kinds of line each source of income has, the dividend codes and the dates of a tax year."""

from datetime import date
from typing import Tuple


KINDS = {
    "EMPLOYMENT": ("P60", "PAY", "BENEFIT"),
    "SELF_EMPLOYMENT": ("PROFIT",),
    "PROPERTY": ("PROFIT",),
    "SAVINGS": ("INTEREST", "ISA"),
    "DIVIDENDS": ("DIVIDEND",),
    "PENSIONS": ("STATE_PENSION", "PENSION", "BENEFIT"),
    "FOREIGN": ("INCOME",),
    "RELIEFS": ("GIFT_AID", "PENSION_RAS", "SALARY_SACRIFICE", "VCT", "EIS", "SEIS", "LOAN_INTEREST"),
}
DIVIDEND_CODES = (8010, 8011)


def tax_year_dates(tax_year: str) -> Tuple[date, date]:
    start = int(tax_year[:4])
    return date(start, 4, 6), date(start + 1, 4, 5)
