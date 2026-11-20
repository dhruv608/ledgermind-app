"""Balance sheet tabs: F bank (the NL tab and F2) and G2 trade creditors."""



def step_bank(ctx, shared) -> None:
    """5. Bank Accounts (Section F)"""
    client_name, engagement = shared.client_name, shared.engagement
    rebuild_control_subledger, wb, ye_str = shared.rebuild_control_subledger, shared.wb, shared.ye_str
    # 5. Bank Accounts (Section F)
    bank_codes = {str(c) for c in range(4800, 4831)}  # every current, deposit and reserve account, and cash
    if "F2.1-NL Transaction" in wb.sheetnames:
        rebuild_control_subledger("F2.1-NL Transaction", bank_codes, "bank", "Bank Account")
    if "F2-Bank" in wb.sheetnames:
        ws_f2 = wb["F2-Bank"]
        ws_f2["A1"] = client_name
        ws_f2["A2"] = ye_str
        ws_f2["B18"] = f"as on {engagement.period_end_date:%d.%m.%Y}"     # the template had another year end


def step_creditors(ctx, shared) -> None:
    """6. Trade Creditors (Section G2)"""
    ageing, ageing_under, client_name = shared.ageing, shared.ageing_under, shared.client_name
    rebuild_control_subledger, remove_sheet = shared.rebuild_control_subledger, shared.remove_sheet
    tb_codes_present, wb, write_account_lead = shared.tb_codes_present, shared.wb, shared.write_account_lead
    write_ageing_report, ye_str = shared.write_ageing_report, shared.ye_str
    # 6. Trade Creditors (Section G2)
    has_creditors = any(c in tb_codes_present for c in {"5200", "2100"})
    if not has_creditors:
        for s in ["G2 - Trade creditors", "G2.1- Creditors NL", "G2.2 - A P Ageing Details"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D9"] = 0.0
    else:
        rebuild_control_subledger("G2.1- Creditors NL", {"5200", "5600"}, "creditor", "Trade Creditors")
        if "G2 - Trade creditors" in wb.sheetnames:
            ws_g2 = wb["G2 - Trade creditors"]
            ws_g2["A1"] = client_name
            ws_g2["A2"] = ye_str
            # Credit balance: c/fwd on the debit side (G1 reads C12); G1's last-year column reads the net b/fwd
            lead = write_account_lead(ws_g2, 5200, "C", "D", {"bf": 8, "ttb": 10, "jnl": 11, "cf": 12, "total": 14}, "C",
                                      nl="G2.1- Creditors NL", t_only=True)
            if "G1 (LEAD)" in wb.sheetnames:
                wb["G1 (LEAD)"]["E9"] = "='G2 - Trade creditors'!D8-'G2 - Trade creditors'!C8"
                if lead:
                    wb["G1 (LEAD)"]["D9"] = f"={lead['cf_link']}"
                    wb["G1 (LEAD)"]["E9"] = f"={lead['bf_link']}"
            ageing_under(ws_g2, lead, ageing.get("AP"), "payables", 5200, "G2.2", owed=True)
        write_ageing_report("G2.2 - A P Ageing Details", ageing.get("AP"), "Aged Payables", "G2.2")
