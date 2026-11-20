"""
Compare the app's result for a client with the accountant's own finished working papers (the answer key).

    python backend/scripts/compare_with_answer_key.py "<client>" "data/clients/<client>/accountant/<workbook>.xlsx"

Reads the accountant's TTB (code per client account), B1-ETB (balance per code before / after the journals) and H1
(corporation tax), and the app's mappings (database) and latest workbook (storage). Writes an Excel report to
data/outputs/compare_reports/ and prints a summary. Read-only: nothing in the app changes.
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.core.database import SessionLocal  # noqa: E402
from backend.app.models.database import ClientEngagement, GeneratedWorkpaper, MasterCOA, TBRecord  # noqa: E402

TOLERANCE = 1.0                      # pounds
DETAIL_SHEETS = re.compile(r"NL|Transaction|Ledger|Detail|COA|Re-analysis|TTB|ETB", re.I)
RED = PatternFill("solid", fgColor="FDE2E1")
GREEN = PatternFill("solid", fgColor="E3F4E8")
BOLD = Font(bold=True)


def num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def key(name: str) -> str:
    """'1100-1 - Casting Consumables' and '1100-1 Casting Consumables ' compare equal."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split())


def header_row(ws, first_cell: str, max_rows: int = 15) -> int:
    for r, row in enumerate(ws.iter_rows(min_row=1, max_row=max_rows, values_only=True), 1):
        if row and isinstance(row[0], str) and row[0].strip().lower() == first_cell:
            return r
    return 0


def read_ttb(wb) -> list:
    """(code, net balance, name) per client account from the TTB tab: code A, name B, debit F, credit G."""
    ws = wb["TTB"]
    start = header_row(ws, "tc code") or 6
    out = []
    for row in ws.iter_rows(min_row=start + 1, values_only=True):
        if not row or row[1] in (None, "") or not isinstance(row[0], (int, float)):
            continue
        name = str(row[1]).strip()
        out.append((int(row[0]), num(row[5]) - num(row[6]), name))
    return out


def read_etb(wb) -> dict:
    """Code -> {name, tb, final} from B1-ETB: TB H-I, journals J-K, final L-M (debit positive)."""
    ws = wb["B1-ETB"]
    start = header_row(ws, "nc") or 7
    out = {}
    for row in ws.iter_rows(min_row=start + 2, values_only=True):
        if not row or not isinstance(row[0], (int, float)):
            continue
        code = int(row[0])
        e = out.setdefault(code, {"name": str(row[1] or ""), "tb": 0.0, "final": 0.0})
        e["tb"] += num(row[7]) - num(row[8])
        e["final"] += num(row[11]) - num(row[12])
    return out


def read_tax(wb):
    """The corporation tax for the year from H1: the amount on the 'CT liability for Current year' line."""
    for name in ("H1-Taxation", "H1 - Taxation"):
        if name in wb.sheetnames:
            for row in wb[name].iter_rows(values_only=True):
                if any(isinstance(c, str) and "ct liability for current year" in c.lower() for c in row):
                    vals = [c for c in row if isinstance(c, (int, float))]
                    return round(vals[-1], 2) if vals else None
    return None


def numbers(ws) -> dict:
    out = {}
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                out[c.coordinate] = float(c.value)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("client", help="part of the client name in the app, e.g. Acme")
    ap.add_argument("answer_key", help="the accountant's finished workbook (.xlsx)")
    ap.add_argument("--app-workbook", help="compare this app workbook instead of the latest one built")
    args = ap.parse_args()

    db = SessionLocal()
    eng = db.execute(select(ClientEngagement).where(ClientEngagement.client_name.ilike(f"%{args.client}%"))).scalars().first()
    if eng is None:
        sys.exit(f"No client like '{args.client}' in the app")
    chart = {c.std_code: c.std_name for c in db.execute(select(MasterCOA)).scalars()}
    records = db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars().all()
    wp = db.execute(select(GeneratedWorkpaper).where(GeneratedWorkpaper.engagement_id == eng.id)
                    .order_by(GeneratedWorkpaper.generated_at.desc())).scalars().first()
    app_path = Path(args.app_workbook) if args.app_workbook else (Path(wp.storage_path) if wp else None)
    db.close()

    key_wb = load_workbook(args.answer_key, data_only=True)
    app_wb = load_workbook(app_path, data_only=True) if app_path and app_path.exists() else None

    # ---- 1. Mapping: the accountant's code for each client account vs the app's
    his = read_ttb(key_wb)
    mapping_rows, agree_n, agree_amt, total_amt = [], 0, 0.0, 0.0
    ours = {key(r.raw_account_name): r for r in records}
    # QuickBooks sub-accounts are 'Parent:Child' in the app; the accountant's file names the child only
    leaves = defaultdict(list)
    for r in records:
        leaves[key(r.raw_account_name.split(":")[-1])].append(r)
    for k, rs in leaves.items():
        if len(rs) == 1:
            ours.setdefault(k, rs[0])
    is_bank = lambda c: c is not None and 4800 <= c <= 4829
    by_name = defaultdict(list)
    for r in records:
        by_name[key(r.raw_account_name)].append(r)
        by_name[key(r.raw_account_name.split(":")[-1])].append(r)

    def find(name: str, bal: float):
        """The app's account for the accountant's line: same name, or same short name ('Sales:Acme' / 'Sub-Contractors:Acme'),
        and when several share it, the one with the same balance."""
        found = by_name.get(key(name)) or by_name.get(key(re.sub(r"^\d+[\-\d]*\s*-\s*", "", name))) or []
        if len(found) > 1:
            found = [r for r in found if abs(num(r.net_amount) - bal) < TOLERANCE] or found
        return found[0] if found else None

    for code, bal, name in sorted(his, key=lambda x: -abs(x[1])):
        r = find(name, bal)
        app_code = r.std_code if r else None
        same = app_code == code or (is_bank(app_code) and is_bank(code))   # bank numbering is free
        if abs(bal) >= 0.01:
            total_amt += abs(bal)
            agree_amt += abs(bal) if same else 0.0
        agree_n += same
        mapping_rows.append([name, code, chart.get(code, ""), app_code, chart.get(app_code, "") if app_code else "not found",
                             r.mapping_status if r else "", round(bal, 2),
                             ("same" if app_code == code else "same (other bank number)") if same else "DIFFERENT"])

    # ---- 2. Balance per code: before journals (books) and final (after journals)
    etb_rows, etb_same, etb_tb_same = [], 0, 0
    app_etb = read_etb(app_wb) if app_wb and "B1-ETB" in app_wb.sheetnames else {}
    his_etb = read_etb(key_wb)
    def banks_together(etb: dict) -> dict:
        """Bank numbering is free (4800-4829): compare the banks as one line."""
        out = {}
        for code, e in etb.items():
            c = 4800 if 4800 <= code <= 4829 else code
            t = out.setdefault(c, {"name": "All bank accounts (4800-4829)" if c == 4800 else e["name"], "tb": 0.0, "final": 0.0})
            t["tb"] += e["tb"]
            t["final"] += e["final"]
        return out

    his_etb, app_etb = banks_together(his_etb), banks_together(app_etb)
    for code in sorted(set(his_etb) | set(app_etb)):
        h, a = his_etb.get(code, {"tb": 0.0, "final": 0.0, "name": ""}), app_etb.get(code, {"tb": 0.0, "final": 0.0, "name": ""})
        if abs(h["final"]) < 0.01 and abs(a["final"]) < 0.01 and abs(h["tb"]) < 0.01 and abs(a["tb"]) < 0.01:
            continue
        ok = abs(h["final"] - a["final"]) < TOLERANCE
        etb_same += ok
        etb_tb_same += abs(h["tb"] - a["tb"]) < TOLERANCE
        etb_rows.append([code, h["name"] or a["name"] or chart.get(code, ""), round(h["tb"], 2), round(a["tb"], 2),
                         round(h["final"], 2), round(a["final"], 2), round(a["final"] - h["final"], 2), "same" if ok else "DIFFERENT"])

    # ---- 3. Tax and 4. tabs
    his_tax, app_tax = read_tax(key_wb), read_tax(app_wb) if app_wb else None
    sheet_rows = []
    if app_wb:
        for name in key_wb.sheetnames:
            if name not in app_wb.sheetnames:
                sheet_rows.append([name, "only in his file", "", "", ""])
                continue
            if DETAIL_SHEETS.search(name):
                continue
            h, a = numbers(key_wb[name]), numbers(app_wb[name])
            cells = set(h) | set(a)
            same = sum(1 for c in cells if abs(h.get(c, 0.0) - a.get(c, 0.0)) < TOLERANCE)
            sheet_rows.append([name, "both", len(cells), same, round(100 * same / len(cells), 1) if cells else 100.0])
        for name in app_wb.sheetnames:
            if name not in key_wb.sheetnames:
                sheet_rows.append([name, "only in the app's file", "", "", ""])

    # ---- report
    out_dir = ROOT / "data" / "outputs" / "compare_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', eng.client_name)}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    map_pct = 100 * agree_n / len(his) if his else 0
    amt_pct = 100 * agree_amt / total_amt if total_amt else 0
    summary = [
        ["Client", eng.client_name], ["His file", str(args.answer_key)], ["App workbook", str(app_path or "none built")],
        [], ["Mapping: accounts on the same code", f"{agree_n} of {len(his)} ({map_pct:.0f}%)"],
        ["Mapping: by value (balances on the same code)", f"{amt_pct:.0f}%"],
        ["ETB codes with the same balance before journals (books + mapping)", f"{etb_tb_same} of {len(etb_rows)}"],
        ["ETB codes with the same final balance (after his / approved journals)", f"{etb_same} of {len(etb_rows)}"],
        ["Corporation tax: his", his_tax], ["Corporation tax: app", app_tax],
        ["Corporation tax: difference", round((app_tax or 0) - (his_tax or 0), 2) if his_tax is not None and app_tax is not None else ""],
        [], ["Note", "The app's ETB 'final' only includes journals approved in the app; his includes all of his journals."],
        [], ["Biggest ETB differences before journals"],
        *[[f"{r[0]} {r[1]}"[:46], f"his {r[2]:,.2f} / app {r[3]:,.2f}"] for r in sorted(etb_rows, key=lambda r: -abs(r[3] - r[2]))[:12]
          if abs(r[3] - r[2]) >= TOLERANCE],
    ]
    for r in summary:
        ws.append(r)
    for row in ws.iter_rows(min_col=1, max_col=1):
        row[0].font = BOLD
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 80

    def table(title, heads, rows, flag_col):
        t = wb.create_sheet(title)
        t.append(heads)
        for c in t[1]:
            c.font = BOLD
        for row in rows:
            t.append(row)
            if flag_col is not None:
                fill = GREEN if str(row[flag_col]).startswith("same") else RED
                for c in t[t.max_row]:
                    c.fill = fill
        for i, w in enumerate([40, 10, 34, 10, 34, 14, 14, 12], 1):
            t.column_dimensions[chr(64 + i)].width = w

    mapping_rows.sort(key=lambda r: (r[7].startswith("same"), -abs(r[6])))
    table("Mapping", ["Client account", "His code", "His code name", "App code", "App code name", "App status", "Balance", "Result"],
          mapping_rows, 7)
    etb_rows.sort(key=lambda r: (r[7] == "same", -abs(r[6])))
    table("ETB", ["Code", "Name", "His TB", "App TB", "His final", "App final", "App - his", "Result"], etb_rows, 7)
    table("Tabs", ["Tab", "Where", "Number cells", "Same", "% same"], sorted(sheet_rows, key=lambda r: (r[1] != "both", r[4] if r[4] != "" else 0)), None)
    wb.save(out)

    print(f"{eng.client_name}: report {out.relative_to(ROOT)}")
    for r in summary[4:11]:
        print(f"  {r[0]}: {r[1]}")
    diffs = [r for r in mapping_rows if not r[7].startswith("same")][:15]
    if diffs:
        print("  Biggest mapping differences:")
        for r in diffs:
            print(f"    {r[0][:38]:38} his {r[1]:>5}  app {str(r[3]):>5}  £{r[6]:>12,.2f}  ({r[5]})")


if __name__ == "__main__":
    main()
