"""
One page for the accountant: for each kind of account where the default code is a choice, the codes the accountant used in
finished workbooks (and in which clients) and what the app uses now; the accountant writes the default for new clients.

    PYTHONPATH=. python backend/scripts/code_choices_sheet.py

Writes data/outputs/reports/Default_codes_for_new_clients_<date>.xlsx. Uses the latest compare reports (run
compare_with_answer_key.py for each client first).
"""

import os
import re
from collections import defaultdict
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from backend.app.core.database import SessionLocal
from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord, User
from backend.scripts.mapping_review_report import ANSWER_KEYS, OWNER_EMAIL, find_his, his_codes
from backend.app.services.mapping.firm_rules import first_rule, load_rules
from backend.app.services.mapping.mapping_service import MappingService

# The kinds of account where firms choose between close codes: (label, words in the account name, words that exclude)
KINDS = [
    ("Software, hosting, subscriptions", r"software|hosting|domain|subscription|saas|microsoft|adobe|google|zoom|slack|quickbooks|xero", r"cost|addition|sales|income|depreciation"),
    ("Vehicle fuel and running costs", r"fuel|petrol|diesel|vehicle running|car running|vehicle expenses|motor expenses|company vehicle", r"insurance|repair|parking|lease|hire|depreciation|cost b|addition"),
    ("Vehicle repairs and parking", r"vehicle repair|parking|tolls|congestion", r""),
    ("Postage and printing", r"postage|printing|stationery|courier|carriage", r""),
    ("Training", r"training|seminar|workshop|course|cpd|conference", r""),
    ("Staff party and entertaining", r"christmas|party|staff entertain|team (lunch|building|event)", r"client"),
    ("Client entertaining / meetings", r"client (meeting|entertain|lunch|dinner)|entertainment|entertaining", r"staff"),
    ("Insurance", r"insurance", r"national insurance|\bni\b"),
    ("Legal and professional fees", r"legal|professional fee|solicitor", r""),
    ("Accountancy fees", r"accountancy|accounting fee|bookkeeping|payroll fee", r"software|subscription"),
    ("Telephone and internet", r"telephone|mobile|phone|internet|broadband", r""),
    ("Travel", r"travel|subsistence|hotel|accommodation|train|taxi|uber|flight", r"income|sales"),
    ("Pensions (staff and directors)", r"pension", r"payable|liabilit|creditor"),
    ("Credit cards", r"credit card|capital on tap|barclaycard|amex|american express", r"fee|charge|interest"),
]

FONT = "Arial"
INPUT = PatternFill("solid", fgColor="FFF2CC")
HEAD = PatternFill("solid", fgColor="1F2937")


def main():
    db = SessionLocal()
    owner = db.query(User).filter(User.email == OWNER_EMAIL).first()
    coa_rows = {c.std_code: c for c in db.query(MasterCOA)}
    coa = {k: c.std_name for k, c in coa_rows.items()}
    rules = load_rules(db, owner.id)

    used = defaultdict(lambda: defaultdict(set))      # kind -> the accountant's code -> {client}
    examples = defaultdict(set)                       # kind -> account names
    for client, _ in ANSWER_KEYS:
        eng = (db.query(ClientEngagement).filter(ClientEngagement.client_name == client,
                                                ClientEngagement.owner_user_id == owner.id)
               .order_by(ClientEngagement.period_end_date.desc()).first())
        if eng is None:
            continue
        his = his_codes(client)
        short = client.replace(" Limited", "").replace(" Ltd", "").replace(" and Security", "")
        for t in db.query(TBRecord).filter(TBRecord.engagement_id == eng.id).all():
            h = find_his(his, t.raw_account_name, float(t.net_amount or 0))
            if not h or h[2] is None:
                continue
            name = t.raw_account_name.split(":")[-1].lower()
            for label, words, excl in KINDS:
                if re.search(words, name) and not (excl and re.search(excl, name)):
                    used[label][int(h[2])].add(short)
                    examples[label].add(t.raw_account_name.split(":")[-1].strip())
                    break

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Default codes"
    ws["A1"] = "Default codes for new clients"
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    ws["A2"] = ("For a client already done, the app keeps last year's code. These defaults are only for a new client "
                "(or a new account). Please write the code you want in the yellow column.")
    ws["A2"].font = Font(name=FONT, italic=True, size=9, color="595959")
    headers = ["Kind of account", "Codes you used (clients)", "App uses now", "Your default code", "Notes"]
    widths = [32, 70, 34, 14, 30]
    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = HEAD
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[chr(64 + i)].width = w
    r = 5
    for label, _, _ in KINDS:
        codes = used.get(label)
        if not codes:
            continue
        lines = [f"{code} {coa.get(code, '')} - {', '.join(sorted(cl))}"
                 for code, cl in sorted(codes.items(), key=lambda kv: -len(kv[1]))]
        # What the app does for a new client: built-in naming rules / exact firm names, then the account rules, then AI
        sample = sorted(examples[label], key=len)[0]
        built_in = MappingService._resolve_by_rules(sample, coa_rows, {}, False)
        rule = first_rule(rules, sample)
        if built_in:
            app_now = f"{built_in['std_code']} {coa.get(built_in['std_code'], '')} (built-in rule)"
        elif rule:
            app_now = f"{rule.std_code} {coa.get(rule.std_code, '')} (account rule)"
        else:
            app_now = "AI decides (no rule)"
        app_now += f" (e.g. '{sample}')"
        row = [label, "\n".join(lines), app_now, None, None]
        for j, v in enumerate(row, 1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = Font(name=FONT, size=10, bold=(j == 1))
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for j in (4, 5):
            ws.cell(row=r, column=j).fill = INPUT
        ws.cell(row=r, column=1).font = Font(name=FONT, size=10, bold=True)
        ws.cell(row=r, column=2).border = Border(bottom=Side(style="thin", color="D9D9D9"))
        ws.row_dimensions[r].height = max(18, 15 * len(lines))
        r += 1
    ws.freeze_panes = "A5"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    os.makedirs("data/outputs/reports", exist_ok=True)
    out = f"data/outputs/reports/Default_codes_for_new_clients_{date.today():%Y-%m-%d}.xlsx"
    wb.save(out)
    print(out, "| rows:", r - 5)


if __name__ == "__main__":
    main()
