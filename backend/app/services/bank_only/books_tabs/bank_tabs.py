"""The bank tabs: one set per account (statement, lines spread by head), the transactions list."""

from collections import defaultdict
from typing import Any, Dict, List

from openpyxl.utils import get_column_letter as L

from backend.app.services.bank_only.bank_sort import CUSTOMER, HEAD_CODES, SUPPLIER, UNSORTED
from backend.app.services.bank_only.ledger import BANK, CREDITORS, DEBTORS, EXCHANGE, SUSPENSE, _bank_code
from backend.app.services.bank_only.books_tabs.common import BOLD, Columns, SheetHelpers, ref


class BankTabs(SheetHelpers):
    """The bank tabs: one set per account (statement, lines spread by head), the transactions list. Mixed into
    BooksWorkbook (its state: self.eng, self.wb, self.ledger ...)."""

    # ------------------------------------------------------------------------------------------------- bank
    def bank_parts(self):
        """Each bank line as the ledger records it: (line, [(column key, label, code, amount)], note), receipts and
        payments apart. Matched receipts and payments split between last year's and this year's invoices/bills, the
        part with no invoice/bill in suspense; every other line to its head."""
        receipt_of = {id(r.line): r for r in self.sales.receipts}
        payment_of = {id(p.line): p for p in self.bills.payments}
        opening_part: Dict[int, float] = defaultdict(float)
        matched: Dict[int, List[str]] = defaultdict(list)
        for m in (self.sales, self.bills):
            for it in m.items:
                for line, amount, _ in it.allocations:
                    if it.brought_forward:
                        opening_part[id(line)] += amount
                    matched[id(line)].append(f"{it.invoice.number or it.invoice.party} £{amount:,.2f}")
        receipts, payments = [], []
        for s in self.bank.lines:
            b = s.line
            note = ("For " + ", ".join(matched[id(b)][:4])) if matched.get(id(b)) else s.how
            if b.money_in > 0 and id(b) in receipt_of:
                rc = receipt_of[id(b)]
                old = round(opening_part[id(b)], 2)
                parts = [(("debtors", "opening"), "Opening Trade Debtors", DEBTORS, old),
                         (("debtors", ""), "Trade Debtors", DEBTORS, round(rc.allocated - old, 2)),
                         (("code", SUSPENSE), "Suspense", SUSPENSE, rc.unallocated)]
                receipts.append((b, b.money_in, [p for p in parts if abs(p[3]) >= 0.005], note))
                continue
            if b.money_out > 0 and id(b) in payment_of:
                p = payment_of[id(b)]
                old = round(opening_part[id(b)], 2)
                parts = [(("creditors", "opening"), "Opening Creditors", CREDITORS, old),
                         (("creditors", ""), "Trade Creditors", CREDITORS, round(p.allocated - old, 2)),
                         (("code", EXCHANGE), "Exchange difference", EXCHANGE, p.fx),
                         (("code", SUSPENSE), "Suspense", SUSPENSE, p.unallocated)]
                payments.append((b, b.money_out, [x for x in parts if abs(x[3]) >= 0.005], note))
                continue
            code = _bank_code(s, self.raw.no_bill_code)
            amount = round(b.money_in - b.money_out, 2)
            if code == SUSPENSE:
                label = "Suspense"
            elif s.head not in (CUSTOMER, SUPPLIER, UNSORTED) and HEAD_CODES.get(s.head) == code:
                label = s.head
            else:
                label = self.name(code)
            parts = [(("code", code), label, code, abs(amount))]
            (receipts if amount > 0 else payments).append((b, abs(amount), parts, note))
        return receipts, payments

    def bank_tab(self, name: str, title: str, lines) -> Dict[str, Any]:
        """Bank Receipts / Bank Payments: one row a line, its head, spread into one column per account."""
        ws = self.sheet(name, title)
        amount_head = "Bank Receipts (£)" if "Receipts" in name else "Bank Payments (£)"
        cols = Columns(7)
        for _, _, parts, _ in lines:
            for key, label, code, _ in parts:
                cols.add(key, label, code)
        check_col, note_col = cols.last + 1, cols.last + 2
        self.heading(ws, 6, {1: "Date", 2: "Description", 4: amount_head, 5: "Heads",
                             **{cols.col(k): cols.label[k] for k in cols.keys}, check_col: "Check", note_col: "Matched to / why"})
        first = r = 7
        for b, amount, parts, note in sorted(lines, key=lambda x: (x[0].when, x[0].row)):
            self.date(ws, r, 1, b.when)
            ws.cell(row=r, column=2, value=b.description)
            self.money(ws, r, 4, amount)
            single = len(parts) == 1
            ws.cell(row=r, column=5, value=cols.label[parts[0][0]] if single else "Split")
            for k in cols.keys:
                c = cols.col(k)
                if single:
                    self.money(ws, r, c, f"=IF($E{r}={L(c)}$6,$D{r},0)")
            if not single:
                for key, _, _, part in parts:
                    self.money(ws, r, cols.col(key), part)
            self.money(ws, r, check_col, f"=D{r}-SUM({L(cols.first)}{r}:{L(cols.last)}{r})")
            ws.cell(row=r, column=note_col, value=note)
            r += 1
        last, tot = r - 1, r + 1
        ws.cell(row=tot, column=2, value="Total").font = BOLD
        for c in [4] + [cols.col(k) for k in cols.keys] + [check_col]:
            self.total(ws, tot, c, first, last)
        self.widths(ws, A=11, B=46, C=2, D=14, E=24, F=2)
        for k in cols.keys:
            ws.column_dimensions[L(cols.col(k))].width = 15
        ws.column_dimensions[L(note_col)].width = 40
        ws.freeze_panes = "C7"
        return {"total": ref(name, f"D{tot}"), "cols": cols, "tot_row": tot,
                "col_total": {k: ref(name, f"{L(cols.col(k))}{tot}") for k in cols.keys}}

    def transactions_tab(self, receipts, payments) -> None:
        ws = self.sheet("Transactions", "Directly Coded Transactions")
        self.direct_count = 0
        r = 6
        for title, lines, head in (("Bank Receipts", receipts, "Bank Receipts (£)"),
                                   ("Bank Payments", payments, "Bank Payments (£)")):
            direct = [(b, amount, parts) for b, amount, parts, _ in lines
                      if len(parts) == 1 and parts[0][0][0] == "code" and parts[0][2] != SUSPENSE]
            self.direct_count += len(direct)
            ws.cell(row=r, column=1, value=title).font = BOLD
            self.heading(ws, r + 1, {1: "Date", 2: "Description", 5: head, 6: "Heads"})
            r += 2
            first = r
            for b, amount, parts in sorted(direct, key=lambda x: (x[2][0][1], x[0].when)):
                self.date(ws, r, 1, b.when)
                ws.cell(row=r, column=2, value=b.description)
                self.money(ws, r, 5, amount)
                ws.cell(row=r, column=6, value=parts[0][1])
                r += 1
            self.total(ws, r, 5, first, r - 1)
            r += 3
        self.widths(ws, A=11, B=50, C=2, D=2, E=14, F=26)

    def statement_tab(self, account, n: int) -> None:
        name = self.bank_tab_name("Bank Statement", account, n, 0)
        ws = self.sheet(name, f"{account.name} - credit card statement (balance owed shown as minus)"
                        if account is not None and account.is_card else
                        "Bank Statement" + (f" - {account.name}" if self.several else ""))
        self.heading(ws, 5, {1: "Date", 2: "Description", 3: "Debit", 4: "Credit", 5: "Balance", 6: "Per statement"})
        code = account.code if account is not None else BANK
        opening = account.opening if account is not None and account.opening is not None \
            else self.raw.opening_tb.get(code, 0.0)
        ws.cell(row=6, column=2, value="Opening balance")
        self.money(ws, 6, 5, opening)
        r = 7
        for b in (account.lines if account is not None else self.raw.bank):
            self.date(ws, r, 1, b.when)
            ws.cell(row=r, column=2, value=b.description)
            if b.money_out:
                self.money(ws, r, 3, b.money_out)
            if b.money_in:
                self.money(ws, r, 4, b.money_in)
            self.money(ws, r, 5, f"=E{r - 1}-C{r}+D{r}")
            if b.balance is not None:
                self.money(ws, r, 6, b.balance)
            r += 1
        ws.cell(row=r + 1, column=2, value="Total").font = BOLD
        self.total(ws, r + 1, 3, 7, r - 1)
        self.total(ws, r + 1, 4, 7, r - 1)
        self.widths(ws, A=11, B=54, C=13, D=13, E=13, F=14)
        ws.freeze_panes = "A6"
