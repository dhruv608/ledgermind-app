"""
Account mapping review report: for each client with the accountant's finished workbook, every account with the code
the app gives it and the accountant's code (and, where the file has it, last year's code), plus the
differences across all clients, the accounts coded differently from client to client, and the app's remembered
choices and account rules. Columns to fill in during the review are yellow.

    PYTHONPATH=. python backend/scripts/compare_with_answer_key.py "<client>" "<accountant's workbook>"   (once per client)
    PYTHONPATH=. python backend/scripts/mapping_review_report.py

Writes data/outputs/reports/Account_mapping_review_<date>.xlsx (data/ is not in git: it holds client data).
"""

import glob
import json
import os
import re
from collections import defaultdict
from datetime import date

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from backend.app.core.database import SessionLocal
from backend.app.models.database import ClientEngagement, FirmMappingRule, MappingMemory, MasterCOA, TBRecord, User

# Clients with the accountant's finished workbook, kept outside the repository (client data):
# data/answer_keys.json = {"owner_email": "...", "answer_keys": [["client name in the app", "path to the workbook"], ...]}
_KEYS = json.load(open("data/answer_keys.json", encoding="utf-8")) if os.path.exists("data/answer_keys.json") else {}
ANSWER_KEYS = [tuple(k) for k in _KEYS.get("answer_keys", [])]
OWNER_EMAIL = _KEYS.get("owner_email", "")

SOURCE_TEXT = {
    "LAST_YEAR": "Same as last year", "MEMORY": "Confirmed before (remembered)", "MANUAL": "Set by accountant",
    "CONFIRMED": "Confirmed by accountant", "CODE_AND_NAME": "Client's own code and name", "CLIENT_FIRM_CODE": "Client's own code",
    "COA_NAME": "Exact firm account name", "RULE": "Built-in naming rule", "FIRM_DEFAULT": "Firm account rule",
    "PARENT": "Parent account", "AI": "AI suggestion", "ROLL_FORWARD": "Carried from last year's balance",
}

FONT = "Arial"
HEAD = PatternFill("solid", fgColor="1F2937")
INPUT = PatternFill("solid", fgColor="FFF2CC")
DIFF = PatternFill("solid", fgColor="FDE2E1")
SAME = PatternFill("solid", fgColor="E2F0D9")
THIN = Border(bottom=Side(style="thin", color="D9D9D9"))


def leaf(name: str) -> str:
    return (name or "").split(":")[-1].strip().lower()


def concept(name: str) -> str:
    """An account name reduced to words, to find the same kind of account across clients."""
    n = re.sub(r"\(.*?\)", " ", (name or "").lower())
    n = re.sub(r"^\d+(-\d+)?\s*[-:]?\s*", "", n.split(":")[-1])
    n = re.sub(r"[^a-z& ]+", " ", n)
    return " ".join(w for w in n.split() if w not in ("and", "the", "of", "costs", "cost", "expenses", "expense"))


def his_codes(client: str) -> list:
    """[(account name lower, balance, accountant's code, code name)] from the latest compare report of this client."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", client).strip("_")
    files = sorted(glob.glob(f"data/outputs/compare_reports/{stem}_*.xlsx"))
    if not files:
        return []
    out = []
    for r in openpyxl.load_workbook(files[-1], read_only=True)["Mapping"].iter_rows(min_row=2, values_only=True):
        if r and r[0] and r[1] is not None:
            out.append((str(r[0]).strip().lower(), float(r[6] or 0), r[1], r[2]))
    return out


def find_his(his: list, raw_name: str, balance: float):
    """The accountant's row for this account: by full name, else by the short name ('Sales:Acme' -> 'acme') with the
    same balance (the same short name can sit under two parents, e.g. Sales:Acme and Sub-Contractors:Acme)."""
    full = raw_name.strip().lower()
    exact = [h for h in his if h[0] == full]
    if exact:
        return exact[0]
    short = [h for h in his if h[0] == leaf(raw_name)]
    if len(short) <= 1:
        return short[0] if short else None
    return min(short, key=lambda h: abs(abs(h[1]) - abs(balance)))


def last_year_codes(workbook: str) -> dict:
    """{account name lower: code} from the 'QB-PY TB' tab (last year's trial balance with the accountant's codes), if any."""
    wb = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    tab = next((n for n in wb.sheetnames if re.match(r"QB-?\s*PY-?\s*TB", n.strip(), re.I)), None)
    if tab is None:
        return {}
    out = {}
    for r in wb[tab].iter_rows(values_only=True):
        if not r or not isinstance(r[0], str):
            continue
        # the code is the last whole number on the row (after the debit, credit and balance columns)
        nums = [v for v in r[1:] if isinstance(v, (int, float)) and float(v).is_integer() and 0 <= v < 10000]
        tail = [v for v in r[1:] if v is not None]
        if nums and tail and tail[-1] == nums[-1] and len(tail) >= 2:
            out[r[0].strip().lower()] = int(nums[-1])
    return out


def style_header(ws, row: int, headers, widths):
    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = HEAD
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=2)


def title(ws, text: str, sub: str):
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    ws["A2"] = sub
    ws["A2"].font = Font(name=FONT, italic=True, size=9, color="595959")


def body_font(ws, first_row: int):
    for row in ws.iter_rows(min_row=first_row):
        for c in row:
            if c.font is None or not c.font.bold:
                c.font = Font(name=FONT, size=10, bold=bool(c.font and c.font.bold), color=c.font.color if c.font else None)


def main():
    db = SessionLocal()
    owner = db.query(User).filter(User.email == OWNER_EMAIL).first()
    coa = {c.std_code: c for c in db.query(MasterCOA)}
    name_of = lambda code: coa[code].std_name if code in coa else ""
    section_of = lambda code: coa[code].category if code in coa else ""

    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Summary"
    diffs, patterns = [], defaultdict(list)
    sheet_info = []

    for client, workbook in ANSWER_KEYS:
        eng = (db.query(ClientEngagement)
               .filter(ClientEngagement.client_name == client, ClientEngagement.owner_user_id == owner.id)
               .order_by(ClientEngagement.period_end_date.desc()).first())
        if eng is None:
            continue
        his = his_codes(client)
        last = last_year_codes(workbook)
        sheet = re.sub(r"[\[\]:*?/\\]", "", client)[:28]
        ws = wb.create_sheet(sheet)
        title(ws, f"{client} - year end {eng.period_end_date:%d/%m/%Y}",
              "App code = what LedgerMind gives the account now. His code = the code in his finished workbook. "
              "Fill the yellow columns when going through it with him.")
        headers = ["Client account", "Balance £", "App code", "App code name", "How the app chose it", "Status",
                   "His code", "His code name", "His code last year", "Match", "Correct code (yellow)",
                   "Use for every client? (Y/N)", "Notes"]
        style_header(ws, 4, headers, [42, 13, 9, 34, 26, 14, 9, 34, 11, 11, 13, 13, 34])
        r = 5
        records = sorted(db.query(TBRecord).filter(TBRecord.engagement_id == eng.id).all(),
                         key=lambda t: (t.std_code or 99999, t.raw_account_name))
        for t in records:
            hrow = find_his(his, t.raw_account_name, float(t.net_amount or 0))
            h = (hrow[2], hrow[3]) if hrow else None
            ly = last.get(t.raw_account_name.strip().lower()) or last.get(leaf(t.raw_account_name))
            his_code = int(h[0]) if h and str(h[0]).strip().lstrip("-").isdigit() else None
            row = [t.raw_account_name, float(t.net_amount or 0), t.std_code, t.std_name or name_of(t.std_code),
                   SOURCE_TEXT.get(t.match_source or "", t.match_source or ""), (t.mapping_status or "").replace("_", " ").title(),
                   his_code, (h[1] if h else ""), ly]
            for i, v in enumerate(row, 1):
                ws.cell(row=r, column=i, value=v)
            ws.cell(row=r, column=10, value=f'=IF(G{r}="","",IF(C{r}=G{r},"Same",IF(AND(C{r}>=4800,C{r}<=4829,G{r}>=4800,G{r}<=4829),"Same (bank no.)","Different")))')
            for col in (11, 12, 13):
                ws.cell(row=r, column=col).fill = INPUT
            ws.cell(row=r, column=2).number_format = '#,##0.00;(#,##0.00);"-"'
            if his_code is not None and his_code != t.std_code and not (4800 <= (t.std_code or 0) <= 4829 and 4800 <= his_code <= 4829):
                diffs.append([client, t.raw_account_name, float(t.net_amount or 0), t.std_code, t.std_name or name_of(t.std_code),
                              SOURCE_TEXT.get(t.match_source or "", t.match_source or ""), his_code, name_of(his_code) or (h[1] if h else ""),
                              "Yes" if section_of(his_code) == section_of(t.std_code) else "No", ly])
            if his_code is not None:
                patterns[concept(t.raw_account_name)].append((client, t.raw_account_name, his_code, t.std_code))
            r += 1
        last_row = r - 1
        ws.auto_filter.ref = f"A4:M{last_row}"
        dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"L5:L{last_row}")
        sheet_info.append((client, sheet, last_row, eng.period_end_date, bool(last)))
        body_font(ws, 5)

    # ---- Differences, all clients
    ws = wb.create_sheet("Differences", 1)
    title(ws, "Accounts where the app and his workbook differ",
          "Same section = both codes are in the same part of the chart (often his preference for a broader code). "
          "Decide the right code in the yellow column; 'Y' means make it the default for every client.")
    headers = ["Client", "Client account", "Balance £", "App code", "App code name", "How the app chose it", "His code",
               "His code name", "Same section?", "His code last year", "Correct code (yellow)", "Use for every client? (Y/N)", "Notes"]
    style_header(ws, 4, headers, [24, 40, 13, 9, 32, 24, 9, 32, 10, 11, 13, 13, 34])
    for i, d in enumerate(sorted(diffs, key=lambda x: (x[0], -abs(x[2]))), 5):
        for j, v in enumerate(d, 1):
            ws.cell(row=i, column=j, value=v)
        ws.cell(row=i, column=3).number_format = '#,##0.00;(#,##0.00);"-"'
        for col in (11, 12, 13):
            ws.cell(row=i, column=col).fill = INPUT
    last_diff = 4 + len(diffs)
    if diffs:
        ws.auto_filter.ref = f"A4:M{last_diff}"
        dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"L5:L{last_diff}")
    body_font(ws, 5)

    # ---- Same kind of account, different codes from client to client
    ws = wb.create_sheet("Varies by client", 2)
    title(ws, "The same kind of account, coded differently in different clients",
          "Accounts with the same name in two or more clients where his codes differ. These need a firm rule, or "
          "'same as last year' per client.")
    headers = ["Account (simplified)", "Client", "Client account", "His code", "His code name", "App code", "Decision (yellow)"]
    style_header(ws, 4, headers, [30, 24, 40, 9, 34, 9, 40])
    r = 5
    for key, items in sorted(patterns.items()):
        clients = {c for c, *_ in items}
        codes = {"bank" if 4800 <= hc <= 4829 else hc for _, _, hc, _ in items}   # bank numbers are one group
        if len(clients) < 2 or len(codes) < 2 or not key:
            continue
        for c, acc, hc, ac in sorted(items):
            for j, v in enumerate([key, c, acc, hc, name_of(hc), ac], 1):
                ws.cell(row=r, column=j, value=v)
            ws.cell(row=r, column=7).fill = INPUT
            r += 1
        r += 1
    body_font(ws, 5)

    # ---- The app's remembered choices and account rules (the demo user's)
    ws = wb.create_sheet("Remembered choices")
    title(ws, "Codes the app remembers by account name (from accountant confirmations)",
          "Used for any client with an account of this name, after the client's own last-year code.")
    style_header(ws, 4, ["Account name", "Code", "Code name", "Confirmed on", "Keep? (yellow)"], [44, 9, 40, 14, 14])
    for i, m in enumerate(sorted(db.query(MappingMemory).filter(MappingMemory.owner_user_id == owner.id).all(),
                                 key=lambda m: m.client_account_name), 5):
        for j, v in enumerate([m.client_account_name, m.std_code, name_of(m.std_code),
                               m.confirmed_at.date() if m.confirmed_at else None], 1):
            ws.cell(row=i, column=j, value=v)
        ws.cell(row=i, column=4).number_format = "dd/mm/yyyy"
        ws.cell(row=i, column=5).fill = INPUT
    body_font(ws, 5)

    ws = wb.create_sheet("Account rules")
    title(ws, "Firm account rules (Account rules page)",
          "Used for a new client or a new account, when there is no last-year code. First matching rule wins.")
    style_header(ws, 4, ["#", "Name contains", "Except", "Code", "Code name", "Note", "On?", "Change? (yellow)"],
                 [5, 50, 30, 9, 34, 40, 6, 30])
    rules = db.query(FirmMappingRule).filter(FirmMappingRule.owner_user_id == owner.id).order_by(
        FirmMappingRule.position, FirmMappingRule.id).all()
    for i, rule in enumerate(rules, 5):
        for j, v in enumerate([i - 4, rule.words, rule.except_words, rule.std_code, name_of(rule.std_code), rule.note,
                               "Yes" if rule.active else "No"], 1):
            ws.cell(row=i, column=j, value=v)
            ws.cell(row=i, column=j).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=i, column=8).fill = INPUT
    body_font(ws, 5)

    # ---- Summary (formulas over the client tabs)
    title(summary, f"Account mapping review - {date.today():%d %B %Y}",
          "Per client: accounts, how many the app codes like his workbook, and how many differ. Clients without his "
          "finished workbook are not listed (nothing to compare with).")
    style_header(summary, 4, ["Client", "Year end", "Accounts", "Compared with his file", "Same", "Different",
                              "Same %", "His last-year codes in file?", "Tab"], [28, 12, 10, 12, 10, 11, 9, 14, 26])
    for i, (client, sheet, last_row, ye, has_last) in enumerate(sheet_info, 5):
        ref = f"'{sheet}'"
        summary.cell(row=i, column=1, value=client)
        summary.cell(row=i, column=2, value=ye).number_format = "dd/mm/yyyy"
        summary.cell(row=i, column=3, value=f"=COUNTA({ref}!A5:A{last_row})")
        summary.cell(row=i, column=4, value=f'=COUNTIF({ref}!J5:J{last_row},"Same*")+COUNTIF({ref}!J5:J{last_row},"Different")')
        summary.cell(row=i, column=5, value=f'=COUNTIF({ref}!J5:J{last_row},"Same*")')
        summary.cell(row=i, column=6, value=f'=COUNTIF({ref}!J5:J{last_row},"Different")')
        summary.cell(row=i, column=7, value=f"=IF(D{i}=0,\"-\",E{i}/D{i})").number_format = "0%"
        summary.cell(row=i, column=8, value="Yes" if has_last else "No")
        summary.cell(row=i, column=9, value=sheet)
    tot = 5 + len(sheet_info)
    summary.cell(row=tot, column=1, value="Total").font = Font(name=FONT, bold=True)
    for col in (3, 4, 5, 6):
        L = get_column_letter(col)
        summary.cell(row=tot, column=col, value=f"=SUM({L}5:{L}{tot - 1})").font = Font(name=FONT, bold=True)
    summary.cell(row=tot, column=7, value=f"=IF(D{tot}=0,\"-\",E{tot}/D{tot})").number_format = "0%"
    notes = tot + 2
    for k, text in enumerate([
        "How to use:",
        "1. 'Differences' lists every account coded differently from his workbook. Fill 'Correct code' with him; "
        "'Y' in 'Use for every client' means a firm rule, 'N' means only this client (the app then keeps it as that "
        "client's code next year).",
        "2. 'Varies by client' shows the same kind of account coded differently in different clients: decide a "
        "default, or 'same as last year'.",
        "3. 'Remembered choices' and 'Account rules' are what the app uses today; mark anything to change.",
        "Bank accounts are compared as one group (4800-4829): a different bank number is not a difference.",
    ]):
        c = summary.cell(row=notes + k, column=1, value=text)
        c.font = Font(name=FONT, size=9, bold=(k == 0))
    body_font(summary, 5)

    os.makedirs("data/outputs/reports", exist_ok=True)
    out = f"data/outputs/reports/Account_mapping_review_{date.today():%Y-%m-%d}.xlsx"
    wb.calculation.fullCalcOnLoad = True     # Excel works out the Match and Summary formulas on opening
    wb.save(out)
    print(out, "| differences:", len(diffs), "| clients:", len(sheet_info))


if __name__ == "__main__":
    main()
