"""Last year's working paper read into its sources (last year's return is this year's checklist).

The firm's working papers are spreadsheets whose layout differs client to client (a PAYE sheet listing employers,
pensions and interest with a 'Total income' line; a Property sheet per address; a Self emp or Expense analysis sheet;
Queries with the client's answers), so the AI reads the sheets as text and lists every source, and code checks the
list: the income sources must add up to the 'Total income' the sheet prints, when it prints one.

What is read (R-EX-02, R-SA102-02):
  sources        each employment (PAYE ref, pay, tax, leaving date), pension, State Pension, benefit, interest per
                 account, dividends per payer, property per address, self-employment, foreign income, other income
  carry forward  losses, unused finance costs, receipts or items deferred to next year (R-EX-02: lines to match)
  reliefs        Gift Aid, pension contributions (relief at source)
  exempt         money treated as not taxable (R-SP-03: evidence and an accountant decision each year)
  answers        what the Queries sheet says on Child Benefit, student loan, Marriage Allowance, pension method"""

import io
import json
import re
from typing import Any, Dict, Optional

SHEET_ROWS = 150            # rows of a sheet sent (monthly grids and long bank lists are cut)
MAX_CHARS = 40000
# Bank reconciliations and ledgers say nothing about sources: left out
SKIP_SHEETS = re.compile(r"^(bank( \d+)?|deposit acc|credit card|bank (payment|receipt)s?|vat control|etb|journal"
                         r"|last year vs this year|evidence map)$", re.I)        # our own pack: the year before, the files

SOURCES = {
    "EMPLOYMENT": ("P60", "BENEFIT", "EXPENSES"), "PENSIONS": ("PENSION", "STATE_PENSION", "BENEFIT"), "SAVINGS": ("INTEREST",),
    "DIVIDENDS": ("DIVIDEND",), "PROPERTY": ("PROFIT",), "SELF_EMPLOYMENT": ("PROFIT",), "FOREIGN": ("INCOME",),
    "OTHER": ("INCOME", "EXEMPT"), "RELIEFS": ("GIFT_AID", "PENSION_RAS"),
    "CARRY_FORWARD": ("LOSS", "FINANCE_COSTS", "DEFERRED", "CA_POOL", "USE_OF_HOME", "OTHER"),
}
ANSWERS = ("child_benefit", "student_loan", "marriage_allowance", "director", "capital_gains")

PROMPT = """This is a UK accountancy firm's working paper for one person's Self Assessment return, last tax year.
Each sheet is given as rows of cells. List every source of income on it, what is carried forward to this year, the
reliefs, and the answers the client gave in the Queries sheet.

Reply with one JSON object only:
{"total_income": number or null (the total taxable income the working paper prints: 'Total taxable income' when it
                 shows one, else 'Total income'; null if it prints neither),
 "lines": [{"source": one of SOURCE, "kind": one of KIND for that source, "name": "employer / payer / bank /
            property address / business, as written", "ref": "PAYE reference, account or null",
            "amount": number or null (the year's gross income; for property and self-employment the profit;
            jointly owned or shared: the person's own share, with the share in note; for a carry-forward the
            amount carried), "tax": number or null (tax deducted at source),
            "ended": "the date it ended (left the job, sold, stopped) or null", "note": "one short line or null"}],
 "answers": {"child_benefit": true/false/null, "student_loan": true/false/null, "marriage_allowance": true/false/null,
             "director": true/false/null, "capital_gains": true/false/null}}
SOURCE and KIND: EMPLOYMENT (P60 the pay; BENEFIT benefits in kind from a P11D, one line per employer; EXPENSES
employment expenses claimed, such as professional fees or travel) · PENSIONS (PENSION a private or overseas pension, STATE_PENSION, BENEFIT a taxable
state benefit) · SAVINGS (INTEREST, one line per account) · DIVIDENDS (DIVIDEND, one per company) · PROPERTY (PROFIT,
one per address) · SELF_EMPLOYMENT (PROFIT) · FOREIGN (INCOME) · OTHER (INCOME: other income, casual work; EXEMPT:
money the paper treats as not taxable, such as UN pay, an inheritance or gifts, one line each) · RELIEFS
(GIFT_AID, PENSION_RAS) · CARRY_FORWARD (LOSS, FINANCE_COSTS unused finance costs, DEFERRED a receipt or item left
to next year, CA_POOL a capital allowances pool's written-down value carried forward: name the pool (main, special
rate, a car) and the assets in note, only when the paper shows a tax pool, not the accounts' net book value,
USE_OF_HOME the use of home amount claimed for the business (the hours a month in note when shown), OTHER).
Numbers as plain numbers (no £ or commas). A heading with no figure for the person is not a source: leave it out.
Do not invent: if the paper does not show it, leave it out or use null."""


def previous_year(tax_year: str) -> str:
    start = int(tax_year[:4]) - 1
    return f"{start}-{str(start + 1)[2:]}"


def is_sheet(name: str) -> bool:
    return name.lower().endswith((".xls", ".xlsx", ".xlsm", ".ods"))


def sheets_text(data: bytes, name: str) -> str:
    """Every sheet as rows of its non-empty cells ('r12: Employer 1 : | Acme Ltd | 14000.00')."""
    import pandas as pd
    if name.lower().endswith(".ods"):
        # OpenDocument (LibreOffice, Google Sheets): read without extra packages, numbers kept as numbers
        from backend.app.sa.extract import ods
        def cell(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return v
        frames = {sheet: pd.DataFrame([[cell(v) for v in r] for r in rows[:SHEET_ROWS]])
                  for sheet, rows in ods.read(data).items()}
    else:
        frames = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, nrows=SHEET_ROWS)
    parts = []
    for sheet, f in frames.items():
        if SKIP_SHEETS.match(str(sheet).strip()):
            continue
        rows = []
        for i, row in enumerate(f.values.tolist()):
            cells = []
            for v in row:
                if v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "0", "0.0"):
                    continue
                cells.append(f"{round(v, 2):g}" if isinstance(v, float) else str(v).strip()[:80])
            if cells:
                rows.append(f"r{i + 1}: " + " | ".join(cells))
        if rows:
            parts.append(f"=== Sheet: {sheet}\n" + "\n".join(rows))
    return "\n".join(parts)[:MAX_CHARS]


def _num(v: Any) -> Optional[float]:
    try:
        return None if v in (None, "") else round(float(str(v).replace(",", "").replace("£", "")), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The AI's answer kept to known sources and kinds."""
    lines = []
    for l in (answer or {}).get("lines") or []:
        source, kind = str(l.get("source") or "").upper(), str(l.get("kind") or "").upper()
        if source not in SOURCES:
            continue
        if kind not in SOURCES[source]:
            kind = SOURCES[source][0]
        name = str(l.get("name") or "")
        # Use of home is a cost the business claimed, never income; a pool carried at nil carries nothing
        if re.search(r"use of home|working from home|home office", name, re.I) and source != "CARRY_FORWARD":
            source, kind = "CARRY_FORWARD", "USE_OF_HOME"
        if kind == "CA_POOL" and not _num(l.get("amount")):
            continue
        lines.append({"source": source, "kind": kind, "name": str(l.get("name") or "").strip()[:200] or source.title(),
                      "ref": (str(l["ref"]).strip()[:60] or None) if l.get("ref") else None,
                      "amount": _num(l.get("amount")), "tax": _num(l.get("tax")),
                      "ended": (str(l["ended"]).strip()[:40] or None) if l.get("ended") else None,
                      "note": (str(l["note"]).strip()[:300] or None) if l.get("note") else None})
    answers = {k: v for k, v in ((answer or {}).get("answers") or {}).items() if k in ANSWERS and isinstance(v, bool)}
    return {"lines": lines, "answers": answers, "total_income": _num((answer or {}).get("total_income")), "checks": []}


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two reads of one line: the same source and figure (a line with no figure: the same reference or first word)."""
    if a["source"] != b["source"]:
        return False
    if a["amount"] is not None and b["amount"] is not None:
        return abs(a["amount"] - b["amount"]) <= 1
    if a["amount"] is None and b["amount"] is None:
        word = lambda l: (l["name"].lower().split() or [""])[0]
        return bool(a["ref"] and a["ref"] == b["ref"]) or word(a) == word(b)
    return False


def merge(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    """The first read's lines, each marked agreed when the second read found the same line; lines only the second
    found are added, marked to check. The printed total is shown, not tested: papers print it net of expenses, for
    one business, or with money that is not taxable."""
    rest = list(second["lines"])
    lines = []
    for l in first["lines"]:
        match = next((m for m in rest if _same(l, m)), None)
        if match is not None:
            rest.remove(match)
        lines.append({**l, "agreed": match is not None})
    lines += [{**m, "agreed": False} for m in rest]
    out = {"lines": lines, "answers": {**second["answers"], **first["answers"]},
           "total_income": first["total_income"] if first["total_income"] is not None else second["total_income"], "checks": []}
    odd = sum(1 for l in lines if not l["agreed"])
    if odd:
        out["checks"].append(f"{odd} line{'s' if odd > 1 else ''} read differently by the two readers: check against the "
                             f"working paper.")
    return out


READERS = ("deepseek.v3.2", "moonshotai.kimi-k2.5")


def _ask(text: str, model: str) -> Optional[Dict[str, Any]]:
    from backend.app.core.bedrock import bedrock_ai
    try:
        raw, _ = bedrock_ai.invoke_model_reporting(PROMPT + "\n\n" + text, model_id=model, max_tokens=6000, temperature=0)
    except Exception:
        return None
    start, end = (raw.find("{"), raw.rfind("}")) if isinstance(raw, str) else (-1, -1)
    try:
        return json.loads(raw[start:end + 1]) if start != -1 else None
    except ValueError:
        return None


def read(data: bytes, name: str) -> Dict[str, Any]:
    """Last year's sources from the working paper, read by two models and compared ({lines, answers, total_income,
    checks, model})."""
    from concurrent.futures import ThreadPoolExecutor
    text = sheets_text(data, name)
    if not text.strip():
        return {"lines": [], "answers": {}, "total_income": None, "checks": ["The working paper has no sheets to read."]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda m: _ask(text, m), READERS)
    if first is None and second is None:
        out = clean(None)
        out["checks"].append("The working paper could not be read: add last year's sources by hand.")
    elif first is None or second is None:
        out = clean(first or second)
        out["lines"] = [{**l, "agreed": False} for l in out["lines"]]
        out["checks"].append("Only one reader answered: check every line against the working paper.")
    else:
        out = merge(clean(first), clean(second))
    out["model"] = " + ".join(READERS)
    return out
