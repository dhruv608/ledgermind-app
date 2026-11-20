"""Balance tabs (each account from its opening balance through its journal lines to the closing balance), fixed assets
and the tax computation."""

import re
from typing import Any, Dict, List, Optional

from openpyxl.utils import get_column_letter as L

from backend.app.services.review.setup_checks import ASSET_CLASS_CODES
from backend.app.services.bank_only.books_tabs.common import BOLD, ITALIC, NAMED_FROM_LAST_YEAR, SheetHelpers, ref


class BalanceTabs(SheetHelpers):
    """Balance tabs (each account from its opening balance through its journal lines to the closing balance), fixed
    assets and the tax computation. Mixed into BooksWorkbook (its state: self.eng, self.wb, self.ledger ...)."""

    # ------------------------------------------------------------------------------------------------- balance tabs
    def balance_tab(self, name: str, title: str, codes: List[int]) -> Optional[Dict[str, Any]]:
        """Opening balance, each journal line on the account, closing balance; checked against the Trial Balance."""
        codes = [c for c in codes if c in self.tb_row]
        if not codes:
            return None
        ws = self.sheet(name, title)
        self.heading(ws, 6, {1: "Particulars", 3: "Debit", 4: "Credit"})
        r = first = 8
        ws.cell(row=r, column=1, value="Opening balance")
        tb = [self.tb_row[c] for c in codes]
        self.money(ws, r, 3, "=" + "+".join(ref("Trial Balance", f"E{x}") for x in tb))
        self.money(ws, r, 4, "=-(" + "+".join(ref("Trial Balance", f"F{x}") for x in tb) + ")")
        r += 1
        for code in codes:
            for row, side, what in self.journal_lines.get(code, []):
                particulars = self.sheets["Journals"].cell(row=row, column=2).value
                ws.cell(row=r, column=1, value=f"{what} ({particulars})")
                self.money(ws, r, 3 if side == "F" else 4, f"=Journals!{side}{row}")
                r += 1
        moved = r - 1
        ws.cell(row=r, column=1, value="Closing balance").font = BOLD
        self.money(ws, r, 3, f"=MAX(SUM(D{first}:D{moved})-SUM(C{first}:C{moved}),0)", bold=True)
        self.money(ws, r, 4, f"=MAX(SUM(C{first}:C{moved})-SUM(D{first}:D{moved}),0)", bold=True)
        closing = r
        self.total(ws, r + 1, 3, first, r)
        self.total(ws, r + 1, 4, first, r)
        ws.cell(row=r + 2, column=1, value="Difference to the Trial Balance (should be nil)")
        self.money(ws, r + 2, 4, f"=SUM(C{first}:C{moved})-SUM(D{first}:D{moved})-(" +
                   "+".join(ref("Trial Balance", f"N{x}") for x in tb) + ")")
        self.widths(ws, A=70, B=2, C=14, D=14, E=14, F=14)
        # The closing balance is the balancing figure, on the opposite side to the balance (as in the accountant's
        # sheets): a debit balance (debtors, bank) shows under Credit
        return {"ws": ws, "next": r + 4, "debit": f"(D{closing}-C{closing})", "credit": f"(C{closing}-D{closing})"}

    def reconcile(self, tab, label: str, value, against: str) -> None:
        ws, r = tab["ws"], tab["next"]
        ws.cell(row=r, column=1, value="Reconciliation").font = BOLD
        ws.cell(row=r + 1, column=1, value=label)
        self.money(ws, r + 1, 4, value)
        ws.cell(row=r + 1, column=5, value="Difference")
        self.money(ws, r + 1, 6, f"=ROUND(D{r + 1}-{against},2)")
        tab["next"] = r + 3

    def balance_name(self, name: str, codes: List[int]) -> str:
        """Loans, HP, PAYE and pension tabs take the name of the account in last year's TB when the client has one
        (the firm names them differently per client: 'PAYE & NI' on 5352, 'Pensions Payable' on 5351); the other tabs
        keep the accountant's usual names."""
        if name not in NAMED_FROM_LAST_YEAR:
            return name
        used = [c for c in codes if c in self.tb_row]
        last = self.raw.opening_names.get(used[0]) if len(used) == 1 else None
        if not last:
            return name
        title = re.sub(r"[\[\]:*?/\\']", "", last).strip()[:31] or name
        self.renamed[title] = name
        return title

    def opening_variance(self, tab, account) -> None:
        """The statement opens at a different balance than last year's TB carries: shown as its own line, as the
        accountant does, so the reconciling difference above is explained."""
        if account is None or account.opening is None or account.code not in self.raw.opening_tb:
            return
        in_tb = self.raw.opening_tb[account.code]
        if abs(in_tb - account.opening) < 0.005:
            return
        ws, r = tab["ws"], tab["next"]
        sign = -1 if account.is_card else 1          # a card: amounts owed
        ws.cell(row=r, column=1, value="Opening balance variance").font = BOLD
        ws.cell(row=r + 1, column=1, value="Opening balance per statement")
        self.money(ws, r + 1, 4, round(sign * account.opening, 2))
        ws.cell(row=r + 2, column=1, value="Opening balance per last year's TB")
        self.money(ws, r + 2, 4, round(sign * in_tb, 2))
        ws.cell(row=r + 3, column=1, value="Variance to explain (last year's figure or the statement)")
        self.money(ws, r + 3, 4, f"=D{r + 1}-D{r + 2}", bold=True)
        tab["next"] = r + 5

    def fixed_assets(self) -> None:
        classes = [(k, v) for k, v in ASSET_CLASS_CODES.items()
                   if any(c in self.tb_row for c in v["cost"] + v["acc"])]
        if not classes:
            return
        ws = self.sheet("FAR", "Fixed Assets Register")
        self.heading(ws, 6, {1: "Asset class", 3: "Cost B/Fwd", 4: "Additions", 5: "Disposals", 6: "Cost C/Fwd",
                             8: "Depreciation B/Fwd", 9: "Charge", 10: "Eliminated", 11: "Depreciation C/Fwd",
                             13: "NBV this year", 14: "NBV last year"})

        def moved(codes, col: str) -> str:
            present = [c for c in codes if c in self.tb_row]
            return "+".join(f"SUMIF(Journals!$E:$E,{c},Journals!${col}:${col})" for c in present) or "0"

        def opening(codes) -> float:
            return round(sum(self.raw.opening_tb.get(c, 0.0) for c in codes), 2)

        r = first = 7
        rows = {}
        for label, v in classes:
            ws.cell(row=r, column=1, value=label)
            self.money(ws, r, 3, opening(v["cost"]))
            self.money(ws, r, 4, f"={moved(v['cost'], 'F')}")
            self.money(ws, r, 5, f"={moved(v['cost'], 'G')}")
            self.money(ws, r, 6, f"=C{r}+D{r}-E{r}")
            self.money(ws, r, 8, -opening(v["acc"]))
            self.money(ws, r, 9, f"={moved(v['acc'], 'G')}")
            self.money(ws, r, 10, f"={moved(v['acc'], 'F')}")
            self.money(ws, r, 11, f"=H{r}+I{r}-J{r}")
            self.money(ws, r, 13, f"=F{r}-K{r}")
            self.money(ws, r, 14, f"=C{r}-H{r}")
            rows[label] = r
            r += 1
        tot = r + 1
        ws.cell(row=tot, column=1, value="Total").font = BOLD
        for c in (3, 4, 5, 6, 8, 9, 10, 11, 13, 14):
            self.total(ws, tot, c, first, r - 1)
        fa_rows = [self.tb_row[c] for _, v in classes for c in v["cost"] + v["acc"] if c in self.tb_row]
        ws.cell(row=tot + 2, column=12, value="Check")
        self.money(ws, tot + 2, 13, f"=M{tot}-(" + "+".join(ref("Trial Balance", f"N{x}") for x in fa_rows) + ")")
        ws.cell(row=tot + 4, column=1, value="The charge for the year comes from the approved depreciation journal "
                                                "(Journals tab).").font = ITALIC
        self.widths(ws, A=24, B=2, **{L(c): 13 for c in range(3, 15)})

        fa = self.sheet("Fixed Assets", "Fixed Assets")
        self.heading(fa, 6, {1: "Particulars", **{3 + i: label for i, (label, _) in enumerate(classes)},
                             3 + len(classes): "Total"})
        lines = [("Cost brought forward", "C"), ("Additions", "D"), ("Disposals", "E"), ("Cost carried forward", "F"),
                 None, ("Depreciation brought forward", "H"), ("Charge for the year", "I"), ("Eliminated", "J"),
                 ("Depreciation carried forward", "K"), None, ("Net book value this year", "M"),
                 ("Net book value last year", "N")]
        r = 8
        for line in lines:
            if line is None:
                r += 1
                continue
            text, col = line
            fa.cell(row=r, column=1, value=text)
            for i, (label, _) in enumerate(classes):
                self.money(fa, r, 3 + i, "=" + ref("FAR", f"{col}{rows[label]}"))
            self.money(fa, r, 3 + len(classes), f"=SUM(C{r}:{L(2 + len(classes))}{r})", bold=True)
            r += 1
        self.widths(fa, A=32, B=2, **{L(3 + i): 18 for i in range(len(classes) + 1)})

    def tax_computation(self, tab, profit: str) -> None:
        ws, r = tab["ws"], tab["next"]
        ws.cell(row=r, column=1, value="Tax Computation (estimate: check against the CT600)").font = BOLD

        def tb_sum(lo: int, hi: int) -> str:
            rows = [x for c, x in self.tb_row.items() if lo <= c <= hi]
            return "+".join(ref("Trial Balance", f"N{x}") for x in rows) or "0"

        lines = [("Profit for the year", f"={profit}"),
                 ("Add: Corporation tax charged", f"={tb_sum(3800, 3899)}"),
                 ("Add: Depreciation", f"={tb_sum(3400, 3405)}+{tb_sum(1800, 1805)}"),
                 ("Less: Losses brought forward", 0)]
        first = r + 1
        for i, (text, value) in enumerate(lines, first):
            ws.cell(row=i, column=1, value=text)
            self.money(ws, i, 3, value)
        taxable = first + len(lines) + 1
        ws.cell(row=taxable, column=1, value="Taxable profit").font = BOLD
        self.money(ws, taxable, 3, f"=MAX(C{first}+C{first + 1}+C{first + 2}-C{first + 3},0)", bold=True)
        # The £50,000 / £250,000 limits cut for a short period and shared with associated companies (CTA 2010 s18D)
        days, associates = self._ct_period()
        lo_row, hi_row = taxable + 2, taxable + 3
        ws.cell(row=lo_row, column=1, value=f"Lower limit (£50,000 x {days}/365 / {associates + 1})")
        self.money(ws, lo_row, 3, f"=ROUND(50000*{days}/365/{associates + 1},2)")
        ws.cell(row=hi_row, column=1, value=f"Upper limit (£250,000 x {days}/365 / {associates + 1})")
        self.money(ws, hi_row, 3, f"=ROUND(250000*{days}/365/{associates + 1},2)")
        out = taxable + 5
        ws.cell(row=out, column=1, value="Tax liability (19% to the lower limit; marginal relief to the upper; 25% above)").font = BOLD
        t, lo, hi = f"C{taxable}", f"C{lo_row}", f"C{hi_row}"
        self.money(ws, out, 3, f"=ROUND(IF({t}<={lo},{t}*0.19,IF({t}>={hi},{t}*0.25,"
                               f"{t}*0.25-({hi}-{t})*3/200)),2)", bold=True)
        tab["next"] = out + 2

    def _ct_period(self) -> tuple:
        """(days in the period, associated companies) for the CT limits: the period from last year's end (a year when
        unknown), and the associated companies entered in the client's tax setup (none when not entered)."""
        import json
        ye, prior = self.ye, self.eng.prior_period_end_date
        days = (ye - prior).days if ye and prior else 365
        try:
            inputs = json.loads(self.eng.profile.tax_inputs or "{}") if self.eng.profile is not None else {}
        except (ValueError, TypeError, AttributeError):
            inputs = {}
        try:
            associates = max(0, int(inputs.get("associated_companies") or 0))
        except (ValueError, TypeError):
            associates = 0
        return max(1, min(days, 366)), associates
