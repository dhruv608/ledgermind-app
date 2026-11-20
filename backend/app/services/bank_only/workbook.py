"""
Workbook for a client with no accounting software (bank statement + Dext), in the accountant's own working-paper
layout. The Xero/QuickBooks workbook (excel_service) is not used or changed:
only its finishing steps (page footer, recalculation, storage) are called.

How the figures flow: the bank, sales and bills tabs list every line with its head and spread it into
one column per account; the Journals tab posts each tab's column totals (and the approved year-end journals); the
Trial Balance is last year's closing balances plus a SUMIF of the Journals tab; each balance tab (debtors, creditors,
bank, director's loan ...) walks from the opening balance through the journal lines on its account to the closing
balance and checks it against the Trial Balance. All formulas, so a head changed in Excel flows through.

The tab writers are in bank_only/books_tabs (bank, party, ledger, balance and notes tabs), mixed into
BooksWorkbook; formats and sheet helpers in books_tabs/common.py.
"""

import re
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook
from sqlalchemy.orm import Session

from backend.app.core.s3 import s3_service
from backend.app.models.database import ClientEngagement, GeneratedWorkpaper, MasterCOA, ProposedJournal, TBRecord
from backend.app.services.bank_only.books import work_out
from backend.app.services.bank_only.ledger import BANK, NAMES, SUSPENSE
from backend.app.services.workbook.recalc import recalculate_with_excel_com, recalculate_with_libreoffice
from backend.app.services.workbook.tidy import tidy_workbook

from backend.app.services.bank_only.books_tabs.bank_tabs import BankTabs
from backend.app.services.bank_only.books_tabs.party_tabs import PartyTabs
from backend.app.services.bank_only.books_tabs.ledger_tabs import LedgerTabs
from backend.app.services.bank_only.books_tabs.balance_tabs import BalanceTabs
from backend.app.services.bank_only.books_tabs.notes_tabs import NotesTabs
from backend.app.services.bank_only.books_tabs.common import BALANCE_TABS, BOLD, BooksChanged, SHEET_ORDER, TITLE

__all__ = ["BooksWorkbook", "build_books_workbook", "BooksChanged"]


class BooksWorkbook(BankTabs, PartyTabs, LedgerTabs, BalanceTabs, NotesTabs):
    def __init__(self, engagement: ClientEngagement, db: Session):
        self.eng, self.db = engagement, db
        self.raw, self.bank, self.sales, self.bills, self.ledger, self.choices = work_out(engagement, db)
        self.vat = bool(engagement.profile.is_vat_registered) if engagement.profile else False
        self.chart = {c.std_code: c.std_name for c in db.query(MasterCOA).all()}
        self.client = engagement.client_name or self.raw.client_name
        ye = engagement.period_end_date or self.raw.year_end
        self.ye = ye
        self.ye_str = ye.strftime("%d.%m.%Y") if ye else ""
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.sheets: Dict[str, Any] = {}
        # Journals tab: firm code -> [(row, 'F' debit / 'G' credit, what)]
        self.journal_lines: Dict[int, List[Tuple[int, str, str]]] = defaultdict(list)
        self.tb_row: Dict[int, int] = {}
        self.approved = self.db.query(ProposedJournal).filter(
            ProposedJournal.engagement_id == engagement.id, ProposedJournal.status == "APPROVED"
        ).order_by(ProposedJournal.id.asc()).all()
        # Several bank accounts: a set of bank tabs each, kept together
        self.several = len(self.raw.accounts) > 1
        self.bank_order: Dict[str, Tuple[str, int, int]] = {}      # tab -> (place in SHEET_ORDER, account, kind)
        self.renamed: Dict[str, str] = {}      # a tab named from last year's TB -> its usual name (for the order)

    # ------------------------------------------------------------------------------------------------- helpers
    def name(self, code: int) -> str:
        account = next((a for a in self.raw.accounts if a.code == code), None)
        if account is not None and account.is_card:
            return f"{account.name} - credit card"
        if self.several and account is not None:
            return f"Bank - {account.name}"
        return self.raw.opening_names.get(code) or self.chart.get(code) or NAMES.get(code) or f"Account {code}"

    def bank_tab_name(self, base: str, account, n: int, kind: int) -> str:
        """'Bank Receipts' for one account; 'Bank Receipts (Tide Saving)' with several (Excel: 31 characters). A
        credit card is named as the accountant does: 'Capital on Tap - CC', 'Capital on Tap Receipts' ..."""
        label = re.sub(r"[\[\]:*?/\\']", "", account.name) if account is not None else ""
        def fit(before: str, after: str) -> str:
            # The account's name is shortened, never the tab's own word: cut to 31, 'Natwest Card Receipts' and
            # 'Natwest Card Payments' would be the same tab
            return f"{before}{label[:31 - len(before) - len(after)].rstrip()}{after}"
        if account is not None and account.is_card:
            name = {"Bank Account": fit("", " - CC"), "Bank Receipts": fit("", " Receipts"),
                    "Bank Payments": fit("", " Payments"), "Bank Statement": fit("", " Statement")}[base]
        elif not self.several or account is None:
            name = base
        else:
            name = fit("Bank - ", "") if base == "Bank Account" else fit(f"{base} (", ")")
        self.bank_order[name] = (base if base == "Bank Statement" else "Bank Account", n, kind)
        return name

    def sheet(self, name: str, title: str):
        ws = self.wb.create_sheet(name)
        self.sheets[name] = ws
        if name == "Notes":
            ws["A1"], ws["A2"] = f"Client: {self.client}", f"Year End: {self.ye_str}"
        else:
            ws["A1"], ws["A2"] = "=Notes!A1", "=Notes!A2"
        ws["A1"].font = ws["A2"].font = BOLD
        ws["A4"] = title
        ws["A4"].font = TITLE
        ws.sheet_view.showGridLines = False
        return ws

    # ------------------------------------------------------------------------------------------------- build
    def build(self) -> Tuple[Workbook, List[str]]:
        if self.ledger.out_of_balance():
            raise BooksChanged(f"The books do not balance (difference £{self.ledger.out_of_balance():,.2f})")
        made = {r.std_code: float(r.net_amount or 0) for r in
                self.db.query(TBRecord).filter(TBRecord.engagement_id == self.eng.id).all()}
        books = self.ledger.trial_balance()
        if any(abs(made.get(c, 0.0) - books.get(c, 0.0)) >= 0.005 for c in set(made) | set(books)):
            raise BooksChanged("The Books tab has changed since the trial balance was made: press 'Make trial "
                               "balance' on the Books tab, run the review, then build the workbook.")

        receipts, payments = self.bank_parts()
        from backend.app.services.bank_only.books import books as books_screen
        questions = books_screen(self.eng, self.db)["questions"]
        expected = self.expected_tb()

        self.transactions_tab(receipts, payments)
        self.opening_tab()
        accounts = sorted(self.raw.accounts, key=lambda a: a.code) or [None]      # by code: 4800, 4801 ...
        banks = []
        for n, a in enumerate(accounts):
            mine = (lambda x: a is None or x[0].account == a.name)
            which = f" - {a.name}" if self.several else ""
            card = a is not None and a.is_card
            rec = self.bank_tab(self.bank_tab_name("Bank Receipts", a, n, 1),
                                f"{a.name} - credit card receipts (repayments, refunds)" if card else "Bank Receipts" + which,
                                [x for x in receipts if mine(x)])
            pay = self.bank_tab(self.bank_tab_name("Bank Payments", a, n, 2),
                                f"{a.name} - credit card payments" if card else "Bank Payments" + which,
                                [x for x in payments if mine(x)])
            banks.append((a, rec, pay))
        # A bank-only client has no Dext invoice or bill lists: no (empty) sales, debtor listing or bills tabs
        bank_only = self.raw.bank_only
        sales = None if bank_only else self.sales_tab()
        listing_total = None if bank_only else self.debtor_listing()
        bills = None if bank_only else self.bills_tab()
        if not bank_only:
            self.duplicates_tab()
        self.journals_tab(banks, sales, bills)
        profit = self.trial_balance_tab()
        self.fixed_assets()

        tabs = {}
        for name, title, codes in BALANCE_TABS:
            sheet = self.balance_name(name, codes)
            tabs[name] = self.balance_tab(sheet, sheet if sheet != name else title, codes)
        if tabs["Trade Debtors"] and listing_total is not None:
            self.reconcile(tabs["Trade Debtors"], "Balance as per Debtor Listing", f"={listing_total}",
                           tabs["Trade Debtors"]["debit"])
        for n, a in enumerate(accounts):
            code = a.code if a is not None else BANK
            card = a is not None and a.is_card
            tab = self.balance_tab(self.bank_tab_name("Bank Account", a, n, 0),
                                   f"{a.name} - credit card" if card else
                                   f"Bank - {a.name}" if self.several else "Bank current account", [code])
            if tab:
                closing = a.closing if a is not None else self.raw.closing_bank
                closing = closing if closing is not None else 0
                if card:      # what the card statement says is owed, against the credit balance
                    self.reconcile(tab, f"Balance owed as per card statement on {self.ye_str}", -closing, tab["credit"])
                else:
                    self.reconcile(tab, f"Balance as per statement on {self.ye_str}", closing, tab["debit"])
                self.opening_variance(tab, a)
        if tabs["Trade Creditors"]:
            t = tabs["Trade Creditors"]
            open_bills = [it for it in self.bills.items if it.outstanding > 0.005]
            self.reconcile(t, "Balance as per listing below", round(sum(i.outstanding for i in open_bills), 2),
                           t["credit"])
            self.listing(t, "Unpaid bills at the year end", [["Date", "Invoice Number", "Supplier", "Outstanding"]] +
                         [[i.invoice.when, i.invoice.number or None, i.invoice.party, i.outstanding] for i in open_bills])
        if tabs["Director Loan Account"]:
            dla_lines = [(b, parts[0][3] if b.money_in else -parts[0][3]) for b, _, parts, _ in receipts + payments
                         if any(5400 <= p[2] < 5410 for p in parts)]
            self.listing(tabs["Director Loan Account"], "DLA Analysis (bank)",
                         [["Date", "Description", "", "Paid in (£)", "Paid out (£)"]] +
                         [[b.when, b.description, None, a if a > 0 else None, -a if a < 0 else None]
                          for b, a in sorted(dla_lines, key=lambda x: x[0].when)], money_cols=(4, 5))
        if tabs["Corporation Tax"]:
            self.tax_computation(tabs["Corporation Tax"], profit)
        for n, a in enumerate(accounts):
            self.statement_tab(a, n)
        self.checks_tab()

        # The Notes tab last (it reports on the other tabs), then every tab in the accountant's order: each bank
        # account's tabs together (account, receipts, payments), the statements at the end
        self.notes_tab(questions, expected)
        order = {n: i for i, n in enumerate(SHEET_ORDER)}

        def place(title: str):
            if title in self.bank_order:
                base, n, kind = self.bank_order[title]
                return order[base], n, kind
            return order.get("TB" if title.startswith("TB-") else self.renamed.get(title, title), 99), 0, 0
        self.wb._sheets.sort(key=lambda ws: place(ws.title))

        issues = []
        if abs(expected.get(SUSPENSE, 0.0)) >= 0.005:
            issues.append(f"Suspense £{abs(expected[SUSPENSE]):,.2f} (client questions)")
        open_q = sum(1 for q in questions if not q["answered"])
        if open_q:
            issues.append(f"{open_q} client question(s) not answered")
        return self.wb, issues


def build_books_workbook(engagement: ClientEngagement, db: Session) -> GeneratedWorkpaper:
    """Build, work out the formulas, store and record the workbook (as the Xero/QuickBooks workbook is stored)."""
    from backend.app.services.workbook import memlog
    builder = BooksWorkbook(engagement, db)
    memlog.step(builder.client, "start")
    wb, issues = builder.build()
    memlog.step(builder.client, "all tabs written")
    tidy_workbook(wb, builder.client, builder.ye_str)
    clean_name = "".join(c for c in builder.client if c.isalnum() or c in (" ", "_", "-")).strip()
    filename = f"WP_{clean_name}_YE_{builder.ye_str}.xlsx"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        wb.save(str(path))
        memlog.step(builder.client, "file saved")
        if not recalculate_with_excel_com(path):
            recalculate_with_libreoffice(path)
        memlog.step(builder.client, "formulas worked out")
        file_bytes = path.read_bytes()
    storage_path = s3_service.upload_file_bytes(
        file_bytes=file_bytes, s3_key=f"engagements/{engagement.id}/{datetime.utcnow():%Y%m%d-%H%M%S}_{filename}",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    workpaper = GeneratedWorkpaper(
        engagement_id=engagement.id, filename=filename, storage_path=storage_path, file_size_bytes=len(file_bytes),
        diagnostics_score="PASS" if not issues else f"{len(issues)} issue(s) found", generated_at=datetime.utcnow())
    db.add(workpaper)
    db.commit()
    db.refresh(workpaper)
    return workpaper
