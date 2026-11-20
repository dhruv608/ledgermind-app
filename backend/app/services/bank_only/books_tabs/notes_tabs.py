"""The notes (preparation and questions) and the checks tab."""

from typing import Any, Dict, List

from openpyxl.styles import Font

from backend.app.models.database import AuditFinding
from backend.app.services.bank_only.ledger import SUSPENSE
from backend.app.services.bank_only.books_tabs.common import BOLD, ITALIC, SheetHelpers, TITLE, WRAP


class NotesTabs(SheetHelpers):
    """The notes (preparation and questions) and the checks tab. Mixed into BooksWorkbook (its state: self.eng,
    self.wb, self.ledger ...)."""

    def preparation_text(self) -> str:
        """How the accounts were prepared, from the files actually used (a job with only a bank statement and an
        uncoded TB makes no mention of sales invoices or Dext bills)."""
        n = len(self.raw.accounts)
        used = [f"the bank statements for {n} accounts" if n > 1 else "the bank statement"]
        if self.raw.sales:
            used.append(f"the {len(self.raw.sales)} sales invoices")
        if self.raw.purchases:
            used.append(f"the {len(self.raw.purchases)} purchase bills (Dext)")
        text = "We have prepared the annual accounts from " + (", ".join(used[:-1]) + " and " + used[-1]
                                                               if len(used) > 1 else used[0]) + " provided"
        if not self.raw.opening_tb:
            return text + ". No closing balances from last year were provided, so the accounts start from nil."
        if self.raw.opening_lines:
            return text + (", with last year's closing balances brought forward. Last year's trial balance had no "
                           "account codes: its lines were matched to our accounts by name.")
        return text + ", with last year's closing balances brought forward."

    def notes_tab(self, questions: List[Dict[str, Any]], expected: Dict[int, float]) -> None:
        ws = self.sheet("Notes", "Notes & Queries :-")
        ws["J4"] = "Client Comments"
        ws["J4"].font = TITLE
        debtors = self.sales.debtors()
        creditors = self.bills.creditors()
        dla = round(sum(v for c, v in expected.items() if 5400 <= c < 5410), 2)
        sales_total = round(sum(i.gross for i in self.raw.sales), 2)
        bills_total = round(sum(b.gross for b in self.raw.purchases), 2)
        direct = self.direct_count
        notes = [
            ("Preparation:-", None, self.preparation_text()),
            ("Trade Debtors:-", "Trade Debtors", f"We have recorded sales of £{sales_total:,.2f} through "
             f"{len(self.raw.sales)} sales invoices. £{debtors:,.2f} is unpaid at the year end (Debtor Listing): "
             "please confirm these amounts are still due from your customers."),
            ("Trade Creditors:-", "Trade Creditors", f"We have recorded expenses of £{bills_total:,.2f} from "
             f"{len(self.raw.purchases)} purchase bills. £{creditors:,.2f} is unpaid at the year end: please confirm."),
            ("Director's Loan Account:-", "Director Loan Account",
             (f"The director owes the company £{dla:,.2f} at the year end. If not repaid within nine months of the "
              "year end, tax under s455 applies." if dla > 0.005 else
              f"The company owes the director £{-dla:,.2f} at the year end." if dla < -0.005 else
              "The director's loan account is clear at the year end.")),
            ("Personally Paid Expenses:-", None, "Please confirm or provide details of any business expenses paid "
             "personally by the director during the year."),
            ("Transactions:-", "Transactions", f"{direct} bank transactions have no invoice or bill and were recorded "
             "directly by their nature (Transactions tab): please confirm."),
        ]
        suspense = expected.get(SUSPENSE, 0.0)
        if abs(suspense) >= 0.005:
            notes.append(("Suspense:-", None, f"£{abs(suspense):,.2f} is held in suspense until the questions below "
                                              "are answered."))
        r = 6
        for n, (head, tab, text) in enumerate(notes, 1):
            ws.cell(row=r, column=1, value=n)
            ws.cell(row=r, column=2, value=head).font = BOLD
            if tab and tab in self.wb.sheetnames:
                link = ws.cell(row=r, column=5, value=tab)
                link.hyperlink = f"#'{tab}'!A1"
                link.font = Font(name="Calibri", color="0563C1", underline="single")
            ws.cell(row=r + 1, column=2, value=text).alignment = WRAP
            ws.merge_cells(start_row=r + 1, start_column=2, end_row=r + 1, end_column=8)
            ws.row_dimensions[r + 1].height = 15 * max(1, len(text) // 95 + 1)
            r += 3
        if questions:
            ws.cell(row=r, column=1, value="Questions for the client").font = TITLE
            r += 2
            groups = [("explain", "Please explain"), ("documents", "Please send"), ("confirm", "Please confirm")]
            n = 0
            for group, title in groups:
                rows = [q for q in questions if q["group"] == group]
                if not rows:
                    continue
                ws.cell(row=r, column=2, value=title).font = BOLD
                r += 1
                for q in rows:
                    n += 1
                    ws.cell(row=r, column=1, value=n)
                    ws.cell(row=r, column=2, value=q["text"]).alignment = WRAP
                    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
                    ws.row_dimensions[r].height = 15 * max(1, len(q["text"]) // 95 + 1)
                    if q.get("answer"):
                        ws.cell(row=r, column=10, value=q["answer"]).alignment = WRAP
                    r += 1
                r += 1
        self.widths(ws, A=6, B=14, C=14, D=14, E=22, F=14, G=14, H=14, I=2, J=50)

    def checks_tab(self) -> None:
        findings = self.db.query(AuditFinding).filter(AuditFinding.engagement_id == self.eng.id) \
            .order_by(AuditFinding.id.asc()).all()
        ws = self.sheet("App checks", "What the app checked")
        ws["A5"] = "The review's findings on these books. Journals approved in the app are on the Journals tab."
        ws["A5"].font = ITALIC
        self.heading(ws, 7, {1: "Ref", 2: "Check", 3: "Severity", 4: "Finding", 5: "Details", 6: "Amount",
                             7: "Status", 8: "Accountant's note"})
        r = 8
        for f in findings:
            ws.cell(row=r, column=1, value=f.procedure_ref)
            ws.cell(row=r, column=2, value=f.procedure_name).alignment = WRAP
            ws.cell(row=r, column=3, value=f.severity)
            ws.cell(row=r, column=4, value=f.finding_title).alignment = WRAP
            ws.cell(row=r, column=5, value=f.finding_details).alignment = WRAP
            if f.quantified_amount:
                self.money(ws, r, 6, float(f.quantified_amount))
            ws.cell(row=r, column=7, value={"OPEN": "Open", "CLEARED": "Cleared"}.get(f.status, f.status))
            ws.cell(row=r, column=8, value=f.cleared_note).alignment = WRAP
            r += 1
        if not findings:
            ws.cell(row=r, column=1, value="The review found nothing to raise.")
        self.widths(ws, A=8, B=24, C=10, D=36, E=60, F=13, G=13, H=36)
