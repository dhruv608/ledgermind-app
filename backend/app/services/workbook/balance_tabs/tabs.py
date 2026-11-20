"""Which balance sheet tabs a client gets, in order."""

from typing import List

from backend.app.services.workbook.balance_tabs.bank import bank_tabs
from backend.app.services.workbook.balance_tabs.cards import card_tabs
from backend.app.services.workbook.balance_tabs.common import Context
from backend.app.services.workbook.balance_tabs.debtors import _debtors_lead, deposit_tab, s455_tab
from backend.app.services.workbook.balance_tabs.loans import loan_tabs
from backend.app.services.workbook.balance_tabs.others import other_creditors_tab, other_debtors_tab
from backend.app.services.workbook.balance_tabs.reserves import dividend_tab, share_capital_tab
from backend.app.services.workbook.balance_tabs.suspense import suspense_tab


# ------------------------------------------------------------------------------------------------------------------
def add_balance_tabs(ctx: Context) -> List[str]:
    banks = bank_tabs(ctx)
    made = banks + card_tabs(ctx, banks[-1:] or ["F2.1-NL Transaction", "F2-Bank", "F1 (LEAD)"]) + loan_tabs(ctx)
    deposit, s455 = deposit_tab(ctx), s455_tab(ctx)
    _debtors_lead(ctx, deposit, s455)
    share_capital_tab(ctx)
    dividends = dividend_tab(ctx)
    suspense = suspense_tab(ctx)
    debtors, creditors = other_debtors_tab(ctx), other_creditors_tab(ctx)
    return made + [t for t in (deposit, s455, dividends, suspense, debtors, creditors) if t]
