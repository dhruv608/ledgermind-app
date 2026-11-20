"""Sales and bills tabs, the duplicates tab and the debtor / creditor listings."""

import re
from typing import Any, Dict, List

from openpyxl.utils import get_column_letter as L

from backend.app.services.bank_only.bank_sort import HEAD_CODES, UNSORTED
from backend.app.services.bank_only.categories import paid_by_director
from backend.app.services.bank_only.ledger import SUSPENSE
from backend.app.services.bank_only.books_tabs.common import BOLD, Columns, SheetHelpers, TOTAL_BORDER, ref


class PartyTabs(SheetHelpers):
    """Sales and bills tabs, the duplicates tab and the debtor / creditor listings. Mixed into BooksWorkbook (its
    state: self.eng, self.wb, self.ledger ...)."""

    # ------------------------------------------------------------------------------------------------- sales / bills
    def sales_tab(self) -> Dict[str, str]:
        ws = self.sheet("Sales Invoices", "Sales Invoices")
        self.heading(ws, 6, {1: "Date", 2: "Due Date", 3: "Invoice Number", 4: "Customer", 5: "Description",
                             6: "Total (GBP)", 7: "VAT", 8: "Net", 9: "Category", 10: "Received Amount",
                             11: "Received Date", 12: "Outstanding", 13: "Link"})
        item_of = {id(it.invoice): it for it in self.sales.items}
        first = r = 7
        for inv in sorted(self.raw.sales, key=lambda i: (i.party.lower(), i.when)):
            it = item_of.get(id(inv))
            self.date(ws, r, 1, inv.when)
            if inv.due:
                self.date(ws, r, 2, inv.due)
            ws.cell(row=r, column=3, value=inv.number)
            ws.cell(row=r, column=4, value=inv.party)
            ws.cell(row=r, column=5, value=inv.description or None)
            self.money(ws, r, 6, inv.gross)
            self.money(ws, r, 7, inv.vat if self.vat else 0)
            self.money(ws, r, 8, f"=F{r}-G{r}")
            ws.cell(row=r, column=9, value="Sales")
            self.money(ws, r, 10, round(it.paid, 2) if it else 0)
            if it and it.allocations:
                ws.cell(row=r, column=11, value=", ".join(sorted({f"{l.when:%d/%m/%Y}" for l, _, _ in it.allocations})))
            self.money(ws, r, 12, f"=F{r}-J{r}")
            if inv.link:
                ws.cell(row=r, column=13, value=f'=HYPERLINK("{inv.link}","Link")')
            r += 1
        last, tot = r - 1, r + 1
        ws.cell(row=tot, column=4, value="Total").font = BOLD
        for c in (6, 7, 8, 10, 12):
            self.total(ws, tot, c, first, last)
        self.widths(ws, A=11, B=11, C=15, D=28, E=30, F=13, G=11, H=13, I=10, J=13, K=22, L=13, M=8)
        ws.freeze_panes = "A7"
        return {"gross": ref("Sales Invoices", f"F{tot}"), "vat": ref("Sales Invoices", f"G{tot}"),
                "net": ref("Sales Invoices", f"H{tot}"), "outstanding": ref("Sales Invoices", f"L{tot}")}

    def bills_tab(self) -> Dict[str, Any]:
        name = "Purchase Bills"
        ws = self.sheet(name, "Purchase Bills")
        cols = Columns(10)
        heads = {}
        for b in self.raw.purchases:
            head, code = self.ledger.bill_heads.get(b.row, (UNSORTED, SUSPENSE))
            label = "Suspense" if code == SUSPENSE else (head if HEAD_CODES.get(head) == code else self.name(code))
            label = "Purchases" if label == "Purchases (no bill)" else label
            cols.add(("code", code), label, code)
            heads[b.row] = cols.label[("code", code)]
        paid_col = cols.last + 1
        self.heading(ws, 6, {1: "Date", 2: "Due Date", 3: "Invoice Number", 4: "Supplier", 5: "Description",
                             6: "Gross Amount", 7: "Tax", 8: "Net Amount", 9: "Heads",
                             **{cols.col(k): cols.label[k] for k in cols.keys},
                             paid_col: "Paid through Bank", paid_col + 1: "Paid by Director", paid_col + 2: "Paid Date",
                             paid_col + 3: "Outstanding", paid_col + 4: "Link"})
        item_of = {id(it.invoice): it for it in self.bills.items}
        spread = "$H" if self.vat else "$F"
        first = r = 7
        for b in sorted(self.raw.purchases, key=lambda i: (i.party.lower(), i.when)):
            it = item_of.get(id(b))
            self.date(ws, r, 1, b.when)
            if b.due:
                self.date(ws, r, 2, b.due)
            ws.cell(row=r, column=3, value=b.number or None)
            ws.cell(row=r, column=4, value=b.party)
            ws.cell(row=r, column=5, value=b.description or None)
            self.money(ws, r, 6, b.gross)
            self.money(ws, r, 7, b.vat if self.vat else 0)
            self.money(ws, r, 8, f"=F{r}-G{r}")
            ws.cell(row=r, column=9, value=heads[b.row])
            for k in cols.keys:
                c = cols.col(k)
                self.money(ws, r, c, f"=IF($I{r}={L(c)}$6,{spread}{r},0)")
            # Dext 'Directors Current Account': paid by the director personally (owed to him, not a creditor)
            director = b.gross if paid_by_director(b.category) else 0.0
            self.money(ws, r, paid_col, round(it.paid - director, 2) if it else 0)
            self.money(ws, r, paid_col + 1, director)
            if it and it.allocations:
                ws.cell(row=r, column=paid_col + 2, value=", ".join(sorted({f"{l.when:%d/%m/%Y}" for l, _, _ in it.allocations})))
            self.money(ws, r, paid_col + 3, f"=F{r}-{L(paid_col)}{r}-{L(paid_col + 1)}{r}")
            if b.link:
                ws.cell(row=r, column=paid_col + 4, value=f'=HYPERLINK("{b.link}","Link")')
            r += 1
        last, tot = r - 1, r + 1
        ws.cell(row=tot, column=4, value="Total").font = BOLD
        for c in [6, 7, 8] + [cols.col(k) for k in cols.keys] + [paid_col, paid_col + 1, paid_col + 3]:
            self.total(ws, tot, c, first, last)
        self.widths(ws, A=11, B=11, C=15, D=28, E=30, F=13, G=11, H=13, I=22)
        for c in range(cols.first, paid_col + 4):
            ws.column_dimensions[L(c)].width = 14
        ws.freeze_panes = "A7"
        return {"cols": cols, "gross": ref(name, f"F{tot}"), "vat": ref(name, f"G{tot}"),
                "outstanding": ref(name, f"{L(paid_col + 3)}{tot}"), "director": ref(name, f"{L(paid_col + 1)}{tot}"),
                "col_total": {k: ref(name, f"{L(cols.col(k))}{tot}") for k in cols.keys}}

    def duplicates_tab(self) -> None:
        """Duplicates check for a Bank + Dext client: bills / invoices entered twice (from the Dext lists), and those
        still outstanding at the year end with a bank payment / receipt of the same amount to the same party that is
        not linked to them (paid but outstanding: the payment was recorded directly)."""
        ws = self.sheet("Duplicates Review", "Duplicates review")
        ws["A5"] = "Review only: nothing is posted. Each line is a question for the client."
        self.heading(ws, 7, {1: "Side", 2: "Check", 3: "Party", 4: "Date", 5: "Number", 6: "Amount", 7: "Finding"})
        rows = []
        for p in self.raw.problems:
            text, where = p.text, p.where
            if re.search(r"appears twice|possible duplicate|used for two customers", text, re.I):
                rows.append(("Customer" if where == "Sales" else "Supplier", "Entered twice", "", None, "", None, text))
        words = lambda t: {w for w in re.findall(r"[a-z]{3,}", (t or "").lower())
                           if w not in {"ltd", "limited", "the", "and", "payment", "card", "transfer", "direct", "debit"}}
        for side, match, unlinked in (
                ("Supplier", self.bills, [x for x in self.bills.no_bill]),
                ("Customer", self.sales, [r for r in self.sales.receipts if not r.customer or r.allocated < r.amount - 0.005])):
            for item in match.outstanding():
                inv = item.invoice
                for u in unlinked:
                    line = u.line
                    amount = line.money_out if side == "Supplier" else line.money_in
                    if abs(amount - item.outstanding) < 0.01 and words(inv.party) & words(line.description)                             and (self.ye is None or line.when <= self.ye):
                        rows.append((side, "Paid but outstanding", inv.party, inv.when, inv.number, item.outstanding,
                                     f"Outstanding at the year end, but {'paid' if side == 'Supplier' else 'received'} "
                                     f"£{amount:,.2f} on {line.when:%d/%m/%Y} ('{line.description[:60]}') with no "
                                     f"link to it: entered twice, or the payment belongs to this "
                                     f"{'bill' if side == 'Supplier' else 'invoice'}?"))
                        break
        r = 8
        for row in rows:
            for c, v in enumerate(row, 1):
                if c == 4 and v is not None:
                    self.date(ws, r, c, v)
                elif c == 6 and v is not None:
                    self.money(ws, r, c, v)
                else:
                    ws.cell(row=r, column=c, value=v or None)
            r += 1
        if not rows:
            ws["A8"] = "No duplicate or unallocated items found."
        self.widths(ws, A=10, B=20, C=30, D=12, E=14, F=12, G=90)

    def debtor_listing(self) -> str:
        ws = self.sheet("Debtor Listing", "Debtors Listing")
        self.heading(ws, 6, {1: "Date", 2: "Customer", 3: "Invoice", 4: "Total (GBP)", 5: "Received Date",
                             6: "Received Amount", 7: "O/S"})
        r = 7
        subtotals = []
        for title, items in (("Opening Debtors (last year's unpaid invoices)",
                              [it for it in self.sales.items if it.brought_forward]),
                             ("Current Year Debtors (unpaid at the year end)",
                              [it for it in self.sales.items if not it.brought_forward and it.outstanding > 0.005])):
            ws.cell(row=r, column=1, value=title).font = BOLD
            r += 1
            first = r
            for it in sorted(items, key=lambda i: (i.invoice.party.lower(), i.invoice.when)):
                self.date(ws, r, 1, it.invoice.when)
                ws.cell(row=r, column=2, value=it.invoice.party)
                ws.cell(row=r, column=3, value=it.invoice.number or None)
                self.money(ws, r, 4, it.invoice.gross)
                if it.allocations:
                    ws.cell(row=r, column=5, value=", ".join(sorted({f"{l.when:%d/%m/%Y}" for l, _, _ in it.allocations})))
                self.money(ws, r, 6, round(it.paid, 2))
                self.money(ws, r, 7, f"=D{r}-F{r}")
                r += 1
            for c in (4, 6, 7):
                self.total(ws, r, c, first, r - 1)
            subtotals.append(f"G{r}")
            r += 2
        ws.cell(row=r, column=6, value="Total outstanding").font = BOLD
        self.money(ws, r, 7, "=" + "+".join(subtotals), bold=True).border = TOTAL_BORDER
        self.widths(ws, A=11, B=30, C=14, D=13, E=24, F=15, G=13)
        return ref("Debtor Listing", f"G{r}")

    def listing(self, tab, title: str, rows: List[List[Any]], money_cols=(4,)) -> None:
        ws, r = tab["ws"], tab["next"]
        ws.cell(row=r, column=1, value=title).font = BOLD
        heads, rows = rows[0], rows[1:]
        self.heading(ws, r + 1, {i + 1: h for i, h in enumerate(heads)})
        r += 2
        for row in rows:
            for i, v in enumerate(row, 1):
                if hasattr(v, "year"):
                    self.date(ws, r, i, v)
                elif i in money_cols:
                    self.money(ws, r, i, v)
                else:
                    ws.cell(row=r, column=i, value=v)
            r += 1
        tab["next"] = r + 1
