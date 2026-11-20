"""The Journals tab, the opening balances and the Trial Balance."""

from typing import Any, Dict, List, Optional, Tuple

from openpyxl.utils import get_column_letter as L

from backend.app.services.bank_only.categories import DIRECTORS_LOAN, paid_by_director
from backend.app.services.bank_only.ledger import BANK, CREDITORS, DEBTORS, SALES, VAT
from backend.app.services.bank_only.books_tabs.common import BOLD, ITALIC, P_AND_L_END, SheetHelpers, ref


class LedgerTabs(SheetHelpers):
    """The Journals tab, the opening balances and the Trial Balance. Mixed into BooksWorkbook (its state: self.eng,
    self.wb, self.ledger ...)."""

    # ------------------------------------------------------------------------------------------------- journals
    def journals_tab(self, banks, sales, bills) -> None:
        ws = self.sheet("Journals", "Journals")
        self.heading(ws, 6, {1: "Sr No.", 2: "Particulars", 5: "Taxcalc", 6: "Debit", 7: "Credit", 8: "Check"})
        r, no = 8, 0

        def journal(lines: List[Tuple[str, int, Optional[Any], Optional[Any]]], being: str) -> None:
            nonlocal r, no
            lines = [x for x in lines if x[2] not in (None, 0) or x[3] not in (None, 0)]
            if not lines:
                return
            no += 1
            first = r
            ws.cell(row=r, column=1, value=no)
            for what, code, dr, cr in lines:
                ws.cell(row=r, column=2, value=what)
                ws.cell(row=r, column=5, value=code)
                if dr not in (None, 0):
                    self.money(ws, r, 6, dr)
                    self.journal_lines[code].append((r, "F", f"Journal {no}: {being}"))
                if cr not in (None, 0):
                    self.money(ws, r, 7, cr)
                    self.journal_lines[code].append((r, "G", f"Journal {no}: {being}"))
                r += 1
            ws.cell(row=r, column=2, value=f"(Being {being})").font = ITALIC
            self.money(ws, r, 8, f"=SUM(F{first}:F{r - 1})-SUM(G{first}:G{r - 1})")
            r += 2

        def from_tab(tab, debit_side: bool) -> List:
            cols = tab["cols"]
            return [(cols.label[k], cols.code[k], "=" + tab["col_total"][k] if debit_side else None,
                     None if debit_side else "=" + tab["col_total"][k]) for k in cols.keys]

        for account, receipts, payments in banks:
            code = account.code if account is not None else BANK
            label = self.name(code) if account is not None and account.is_card else \
                f"Bank - {account.name}" if self.several else "Bank account"
            which = f" - {account.name}" if self.several else ""
            if receipts["cols"].keys:
                journal([(label, code, "=" + receipts["total"], None)] + from_tab(receipts, False),
                        f"bank receipts recorded{which}")
            if payments["cols"].keys:
                journal(from_tab(payments, True) + [(label, code, None, "=" + payments["total"])],
                        f"bank payments recorded{which}")
        if self.raw.sales:
            journal([("Trade Debtors", DEBTORS, "=" + sales["gross"], None),
                     ("Sales", SALES, None, "=" + (sales["net"] if self.vat else sales["gross"]))] +
                    ([("VAT", VAT, None, "=" + sales["vat"])] if self.vat else []),
                    "sales recorded for the year from the sales invoices")
        if self.raw.purchases:
            journal(from_tab(bills, True) + ([("VAT", VAT, "=" + bills["vat"], None)] if self.vat else []) +
                    [("Trade creditors", CREDITORS, None, f"={bills['gross']}-{bills['director']}")] +
                    ([("Director's loan (bills paid by the director)", DIRECTORS_LOAN, None, "=" + bills["director"])]
                     if any(paid_by_director(b.category) for b in self.raw.purchases) else []),
                    "expenses recorded from the Dext purchase bills")
        for j in self.approved:
            if j.lines:
                lines = [(ln.narrative or ln.account_name or self.name(ln.account_code), ln.account_code,
                          float(ln.debit or 0) or None, float(ln.credit or 0) or None) for ln in j.lines]
            else:
                lines = [(j.debit_name, j.debit_code, float(j.amount), None),
                         (j.credit_name, j.credit_code, None, float(j.amount))]
            journal(lines, f"{j.description} - {j.journal_ref}")
        self.widths(ws, A=8, B=44, C=2, D=2, E=10, F=14, G=14, H=12)

    # ------------------------------------------------------------------------------------------------- trial balance
    def opening_tab(self) -> None:
        year = self.ye.year - 1 if self.ye else ""
        name = f"TB-{year}"
        ws = self.sheet(name, f"Trial Balance (last year's closing balances, {year})")
        self.sheets["TB"] = ws
        self.heading(ws, 6, {1: "Account", 2: "Account Description", 3: "Debit", 4: "Credit"})
        r = first = 7
        for code, amount in sorted(self.raw.opening_tb.items()):
            ws.cell(row=r, column=1, value=code)
            ws.cell(row=r, column=2, value=self.name(code))
            self.money(ws, r, 3 if amount > 0 else 4, abs(amount))
            r += 1
        ws.cell(row=r + 1, column=1, value="Total").font = BOLD
        self.total(ws, r + 1, 3, first, r - 1)
        self.total(ws, r + 1, 4, first, r - 1)
        ws.cell(row=r + 2, column=1, value="Difference")
        self.money(ws, r + 2, 4, f"=C{r + 1}-D{r + 1}")
        self.widths(ws, A=10, B=46, C=14, D=14)

    def trial_balance_tab(self) -> str:
        ws = self.sheet("Trial Balance", "Extended Trial Balance")
        for c, text in {5: "Opening Balance", 7: "Journals", 9: "Final", 10: "P&L", 12: "Balance Sheet", 14: "Closing"}.items():
            ws.cell(row=5, column=c, value=text).font = BOLD
        self.heading(ws, 6, {1: "Code", 2: "Account Name", 5: "Dr", 6: "Cr", 7: "Dr", 8: "Cr", 9: "Balance",
                             10: "Dr", 11: "Cr", 12: "Dr", 13: "Cr", 14: "Balance"})
        codes = sorted(set(self.raw.opening_tb) | set(self.journal_lines))
        r = first = 8
        pl_rows = []
        for group in ([c for c in codes if c < P_AND_L_END], [c for c in codes if c >= P_AND_L_END]):
            for code in group:
                self.tb_row[code] = r
                ws.cell(row=r, column=1, value=code)
                ws.cell(row=r, column=2, value=self.name(code))
                opening = self.raw.opening_tb.get(code, 0.0)
                if opening > 0:
                    self.money(ws, r, 5, opening)
                elif opening < 0:
                    self.money(ws, r, 6, opening)
                self.money(ws, r, 7, f"=SUMIF(Journals!$E:$E,$A{r},Journals!$F:$F)")
                self.money(ws, r, 8, f"=-SUMIF(Journals!$E:$E,$A{r},Journals!$G:$G)")
                self.money(ws, r, 9, f"=SUM(E{r}:H{r})")
                dr, cr = (10, 11) if code < P_AND_L_END else (12, 13)
                self.money(ws, r, dr, f"=IF(I{r}>0,I{r},0)")
                self.money(ws, r, cr, f"=IF(I{r}<0,I{r},0)")
                self.money(ws, r, 14, f"=SUM(J{r}:M{r})")
                if code < P_AND_L_END:
                    pl_rows.append(r)
                r += 1
            r += 1
        last, tot = r - 2, r
        for c in range(5, 15):
            self.total(ws, tot, c, first, last)
        ws.cell(row=tot + 1, column=2, value="Difference (should be nil)")
        for c in (6, 8):
            self.money(ws, tot + 1, c, f"={L(c - 1)}{tot}+{L(c)}{tot}")
        profit_row = tot + 3
        ws.cell(row=profit_row, column=2, value="Profit/(loss) for the year").font = BOLD
        profit = f"=-SUM(N{pl_rows[0]}:N{pl_rows[-1]})" if pl_rows else "=0"
        self.money(ws, profit_row, 14, profit, bold=True)
        self.widths(ws, A=8, B=46, C=2, D=2, **{L(c): 13 for c in range(5, 15)})
        ws.freeze_panes = "C7"
        return ref("Trial Balance", f"N{profit_row}")

    # ------------------------------------------------------------------------------------------------- notes
    def expected_tb(self) -> Dict[int, float]:
        """The closing balances the workbook should show: the books plus the approved journals."""
        tb = dict(self.ledger.trial_balance())
        for j in self.approved:
            pairs = [(ln.account_code, float(ln.debit or 0) - float(ln.credit or 0)) for ln in j.lines] if j.lines \
                else [(j.debit_code, float(j.amount)), (j.credit_code, -float(j.amount))]
            for code, amount in pairs:
                tb[code] = round(tb.get(code, 0.0) + amount, 2)
        return tb
