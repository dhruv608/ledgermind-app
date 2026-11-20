"""G3 directors' loan account."""



def step_dla(ctx, shared) -> None:
    """7. Directors Loan Account (Section G3)"""
    ctx, rebuild_control_subledger, remove_sheet = shared.ctx, shared.rebuild_control_subledger, shared.remove_sheet
    tb_codes_present, wb, write_account_lead = shared.tb_codes_present, shared.wb, shared.write_account_lead
    # 7. Directors Loan Account (Section G3)
    has_dla = any(c in tb_codes_present for c in {"5400", "2150"})
    if not has_dla:
        for s in ["G3- DLA", "G3.1 - DLA-NL Transactions"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D11"] = 0.0
    else:
        from backend.app.services.workbook.context import DLA_TYPE_ORDER, dla_type
        rebuild_control_subledger("G3.1 - DLA-NL Transactions", {"5400", "5401", "5402", "5800"}, "director",
                                  "Directors Loan Account", type_of=dla_type)
        # The types the director's loan holds this year, each its own line of the T-account
        present = {dla_type(tx) for tx in ctx.tx_rows if tx[1] == "5400"}
        dla_types = [t for t in DLA_TYPE_ORDER if t in present] or None
        if "G3- DLA" in wb.sheetnames:
            # The template carries a leftover side working in columns G-I (a fixed 'Dividend' of 25,000 and
            # balances read from fixed cells of G3.1): it has no source in the client's data, so it is cleared
            g3 = wb["G3- DLA"]
            for row in g3.iter_rows(min_row=8, max_row=g3.max_row, min_col=7, max_col=9):
                for cell in row:
                    if cell.value is not None and type(cell).__name__ != "MergedCell":
                        cell.value = None
            g3["B15"] = None          # the template's 'Dividend' line, with no source
            # Owed to the directors (credit) as the c/fwd on the debit side; G1 shows it under creditors (an
            # overdrawn account comes out negative there)
            lead = write_account_lead(g3, 5400, "D", "E", {"bf": 9, "ttb": 12, "jnl": 13, "cf": 17, "total": 19}, "D",
                                      nl="G3.1 - DLA-NL Transactions", types=dla_types, t_only=True)
            # The c/fwd (owed to the directors +) for B1-ETB's schedule column
            ctx.schedule_cf[5400] = (lead["cf_link"] if lead else "'G3- DLA'!D17", -1)
            if lead and lead.get("end"):
                _confirmation(ctx, g3, lead["cf"], lead["end"] + 2)
                # The overdrawn-loan tests: reserves / dividend / s455, highest balance, 30-day redrawing
                from backend.app.services.workbook.dla_tests import add_dla_tests
                add_dla_tests(ctx, g3, lead["cf"], lead["end"] + 7)
                # One control per director when there are two or more
                from backend.app.services.workbook.dla_directors import add_director_tabs
                add_director_tabs(ctx, g3, lead["cf"])
            if "G1 (LEAD)" in wb.sheetnames:
                wb["G1 (LEAD)"]["D11"] = f"={lead['cf_link']}" if lead else "='G3- DLA'!D17"
                wb["G1 (LEAD)"]["E11"] = f"={lead['bf_link']}" if lead else "='G3- DLA'!E9-'G3- DLA'!D9"


def _confirmation(ctx, ws, cf: str, top: int) -> None:
    """The balance agreed to the directors' signed confirmation: typed here, or on the control
    accounts screen (key 'code:5400', debit +, so shown here owed to the directors +), and the difference."""
    from backend.app.services.reconciliation.common import entered_inputs, statement_balance
    from backend.app.services.workbook.balance_tabs.common import BOLD, _input, _money
    typed = None
    if ctx.db is not None:
        try:
            entered = entered_inputs(ctx.db, ctx.engagement.id).get("code:5400")
        except Exception:
            entered = None
        if entered and entered.get("agreed"):
            typed = f"={cf}"
        elif statement_balance(entered) is not None:
            typed = -statement_balance(entered)
    conf, diff = f"D{top + 1}", f"D{top + 2}"
    ws.cell(row=top, column=1, value="Directors' confirmation").font = BOLD
    ws.cell(row=top + 1, column=2, value=f"Balance per the directors' signed confirmation at {ctx.engagement.period_end_date:%d/%m/%Y} "
                                         f"(owed to the directors +, overdrawn -)")
    _input(ws[conf], typed)
    ws.cell(row=top + 1, column=5, value="Type this")
    ws.cell(row=top + 2, column=2, value="Difference: books less confirmation (must be nil)").font = BOLD
    _money(ws[diff], bold=True).value = f'=IF({conf}="","Confirmation not entered",ROUND(({cf})-{conf},2))'
    ws.cell(row=top + 3, column=2, value=(
        "Owed to the directors: agree it to their signed confirmation, nothing more. Overdrawn: the highest balance in "
        "the year, interest at the official rate (benefit in kind) and s455 on what is not repaid within nine months "
        "(H1)."))
