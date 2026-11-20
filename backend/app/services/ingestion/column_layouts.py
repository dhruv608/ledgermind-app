"""
Reading a trial balance or ledger from any software by its columns (Sage, or any Excel the Xero/QuickBooks readers do
not know). At upload the app finds the heading row, guesses which column is what (Description, Debit, Credit; for the
ledger also Account, Date, Type, VAT), the accountant checks it once, and the layout is saved for the firm: the next
file with the same headings is read the same way without asking.

The readers return the same tables the Xero/QuickBooks readers do, so everything after the upload (movement-only TB
with the openings from the ledger, mapping, review, workbook) is unchanged.
"""

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from backend.app.core.database import Base, create_table
from backend.app.services.ingestion.ledger_files.common import firm_code_of

# The columns each report needs. (id, label, required); a TB needs Debit and Credit, or one Balance; a ledger needs
# Debit and Credit, or one Amount
FIELDS: Dict[str, List[Tuple[str, str, bool]]] = {
    "TB": [("name", "Account name", True), ("code", "Account code", False), ("debit", "Debit", False),
           ("credit", "Credit", False), ("balance", "Balance (+ debit, - credit)", False),
           ("firm_code", "Firm code (Taxcalc / final code)", False)],
    "GL": [("account", "Account", True), ("date", "Date", True), ("type", "Type", False),
           ("name", "Customer / supplier", False), ("reference", "Reference", False),
           ("description", "Description", False), ("debit", "Debit", False), ("credit", "Credit", False),
           ("amount", "Amount (+ debit, - credit)", False), ("vat", "VAT amount", False)],
}

# Heading words for each column (lower case, spaces collapsed), most likely first
SYNONYMS: Dict[str, Dict[str, List[str]]] = {
    "TB": {
        "name": ["account name", "account", "nominal name", "ledger account", "description", "name", "details"],
        "code": ["account code", "nominal code", "code", "n/c", "a/c", "nc", "ref"],
        "debit": ["debit", "dr", "debit amount", "debits", "debit - year to date", "debit ytd"],
        "credit": ["credit", "cr", "credit amount", "credits", "credit - year to date", "credit ytd"],
        "balance": ["balance", "net", "closing balance", "ytd", "net balance", "amount"],
        "firm_code": ["taxcalc code", "taxcalc", "tax calc code", "final code", "firm code", "tc code"],
    },
    "GL": {
        "account": ["account", "ledger account", "account name", "nominal", "nominal account", "distribution account"],
        "date": ["date", "transaction date", "trx date", "posting date", "txn date", "posted dt.", "posted dt",
                 "posted date", "post date", "gl date", "doc dt.", "doc date"],
        "type": ["type", "transaction type", "source", "trx type"],
        "name": ["name", "contact", "customer", "supplier", "payee", "customer/supplier"],
        "reference": ["reference", "ref", "invoice number", "no.", "number", "num", "invoice no"],
        "description": ["description", "details", "memo", "narrative", "memo/description"],
        "debit": ["debit", "dr", "debit amount", "debits"],
        "credit": ["credit", "cr", "credit amount", "credits"],
        "amount": ["amount", "value", "net"],
        "vat": ["vat", "vat amount", "tax", "tax amount"],
    },
}

OPENING = re.compile(r"^\s*opening balance:?\s*$", re.I)
TOTAL = re.compile(r"^\s*(grand\s+)?totals?\b", re.I)
BALANCE_FORWARD = re.compile(r"\s*\(balance forward as of [^)]*\)\s*$", re.I)
# Words that only Sage's reports use: the client is marked as a Sage client
SAGE_WORDS = re.compile(r"nominal ledger|qe invoice|sales tax control account|purchase tax control account|debtors control account|creditors control account", re.I)


class UploadLayout(Base):
    """A column layout the accountant confirmed: the same headings are read the same way next time, for any client."""
    __tablename__ = "upload_layouts"
    __table_args__ = (UniqueConstraint("owner_user_id", "role", "signature", name="uq_upload_layout"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, nullable=True, index=True)
    role = Column(String(10), nullable=False)               # TB / GL
    signature = Column(String(1000), nullable=False)        # the headings, in order
    header_row = Column(Integer, nullable=False)
    mapping = Column(Text, nullable=False)                  # JSON {field: column index}
    software = Column(String(30), nullable=True)            # SAGE / OTHER
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(UploadLayout.__table__)


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v).strip().lower()) if v is not None and not (isinstance(v, float) and v != v) else ""


def _rows(raw: pd.DataFrame) -> List[List[Any]]:
    return [[None if (isinstance(v, float) and v != v) else v for v in r] for r in raw.values.tolist()]


def _match(role: str, heading: str) -> Optional[str]:
    """The field a heading names exactly ('Debit' -> debit), else None."""
    if not heading:
        return None
    for field, words in SYNONYMS[role].items():
        if heading in words:
            return field
    return None


def find_header(role: str, rows: List[List[Any]]) -> int:
    """The heading row: the row in the first 30 that names the most fields."""
    best, best_score = 0, -1
    for i, r in enumerate(rows[:30]):
        fields = {_match(role, _norm(v)) for v in r} - {None}
        score = len(fields)
        if score > best_score:
            best, best_score = i, score
    return best


def signature(role: str, rows: List[List[Any]], header_row: int) -> str:
    heads = [_norm(v) for v in rows[header_row]] if header_row < len(rows) else []
    while heads and not heads[-1]:
        heads.pop()
    return f"{role}|" + "|".join(heads)


def _is_date(v: Any) -> bool:
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return True
    if isinstance(v, str) and re.match(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", v.strip()):
        return True
    return False


def guess(role: str, rows: List[List[Any]]) -> Tuple[int, Dict[str, int]]:
    """(heading row, {field: column}) from the heading words; a ledger's account may sit in a column with no heading
    (Sage): the text column on the left that is filled on most lines."""
    header_row = find_header(role, rows)
    heads = [_norm(v) for v in rows[header_row]] if rows else []
    mapping: Dict[str, int] = {}
    # Exact words first, in each field's order of likelihood (a TB's 'Description' is the account name only when
    # no column is called 'Account name' or 'Account')
    for field, words in SYNONYMS[role].items():
        for w in words:
            col = next((i for i, h in enumerate(heads) if h == w and i not in mapping.values()), None)
            if col is not None:
                mapping[field] = col
                break
    if role == "GL" and "account" not in mapping:
        data = rows[header_row + 1: header_row + 200]
        for i, h in enumerate(heads):
            # no heading, or a number standing for one ('0' over Sage Intacct's account column)
            if (h and not h.replace(".", "").isdigit()) or i in mapping.values():
                continue
            filled = [r[i] for r in data if i < len(r) and r[i] not in (None, "")]
            if len(filled) >= max(5, len(data) // 2) and all(isinstance(v, str) for v in filled[:50]):
                mapping["account"] = i
                break
    if role == "GL":
        _account_not_contact(rows, header_row, mapping)
        _snap_to_data(rows, header_row, mapping)
    if role == "TB":
        _tb_codes_and_dates(rows, header_row, mapping)
    return header_row, mapping


def _heading_date(v: Any) -> Optional[date]:
    """A column heading that is a date: a date, a date text, or Excel's date number (TaxCalc's comparative TB heads
    its balance columns 45688 and 45322: 31/01/2025 and 31/01/2024)."""
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date()
    if isinstance(v, date):
        return v
    text = str(v).strip() if v is not None else ""
    if re.fullmatch(r"\d{5}(\.0)?", text) and 30000 <= float(text) <= 60000:
        return (datetime(1899, 12, 30) + pd.Timedelta(days=int(float(text)))).date()
    if _is_date(text):
        try:
            return pd.to_datetime(text, dayfirst=True).date()
        except (ValueError, TypeError):
            return None
    return None


def _tb_codes_and_dates(rows: List[List[Any]], header_row: int, mapping: Dict[str, int]) -> None:
    """A TB whose 'Account' column holds the codes and 'Account Description' the names (TaxCalc): the codes are the
    code, the description the name. With no Debit / Credit or Balance heading, a column headed by a date is a balance
    column, the latest date this year's (TaxCalc's comparative TB: this year, last year, variance)."""
    heads = rows[header_row] if header_row < len(rows) else []
    data = rows[header_row + 1: header_row + 300]
    col = mapping.get("name")
    if col is not None and "code" not in mapping:
        values = [r[col] for r in data if col < len(r) and r[col] not in (None, "")]
        numeric = [v for v in values if re.fullmatch(r"\d{1,6}(\.0)?", str(v).replace(",", "").strip())]
        if values and len(numeric) >= 0.6 * len(values):
            described = next((i for i, h in enumerate(heads) if i != col and "description" in _norm(h)
                              and i not in mapping.values()), None)
            if described is not None:
                mapping["code"], mapping["name"] = col, described
    if {"debit", "credit"} <= set(mapping) or "balance" in mapping:
        return
    dated = [(d, i) for i, h in enumerate(heads) if i not in mapping.values() and (d := _heading_date(h))]
    if dated:
        mapping["balance"] = max(dated)[1]


def _account_not_contact(rows: List[List[Any]], header_row: int, mapping: Dict[str, int]) -> None:
    """Sage's Nominal Activity report heads its customer / supplier code 'Account' (e.g. ABC01) and writes the ledger
    account's name, without a heading, in the first column of every line: that one is the account."""
    col = mapping.get("account")
    if col is None or col == 0:
        return
    dated = [r for r in rows[header_row + 1: header_row + 300] if "date" in mapping and mapping["date"] < len(r)
             and _is_date(r[mapping["date"]])]
    if len(dated) < 5:
        return
    codes = [str(r[col]).strip() for r in dated if col < len(r) and r[col] not in (None, "")]
    first = [r[0] for r in dated if r and isinstance(r[0], str) and r[0].strip()]
    code_like = codes and sum(1 for v in codes if " " not in v and len(v) <= 12) >= 0.8 * len(codes)
    if code_like and len(first) >= 0.9 * len(dated) and sum(1 for v in first if " " in v) >= 0.5 * len(first):
        if "name" not in mapping:
            mapping["name"] = col
        mapping["account"] = 0


def _snap_to_data(rows: List[List[Any]], header_row: int, mapping: Dict[str, int]) -> None:
    """Some reports (Sage) write a column's figures one cell left or right of its heading: a money or date column
    with nothing under its heading moves to the next column that has them."""
    data = rows[header_row + 1: header_row + 300]
    is_number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) or (
        isinstance(v, str) and re.fullmatch(r"-?[\d,]+\.?\d*", v.strip() or "x") is not None)
    for field, test in (("date", _is_date), ("debit", is_number), ("credit", is_number), ("amount", is_number)):
        col = mapping.get(field)
        if col is None:
            continue
        count = lambda c: sum(1 for r in data if c < len(r) and r[c] not in (None, "") and test(r[c]))
        if count(col) >= 3:
            continue
        taken = {c for f, c in mapping.items() if f != field}
        best = max((c for c in (col - 1, col + 1) if c >= 0 and c not in taken), key=count, default=None)
        if best is not None and count(best) >= 3:
            mapping[field] = best


def missing(role: str, mapping: Dict[str, int]) -> List[str]:
    """What a layout still needs before the file can be read (labels), [] when it is complete."""
    need = []
    if "name" not in mapping and role == "TB":
        need.append("Account name")
    if role == "GL":
        need += [label for f, label in (("account", "Account"), ("date", "Date")) if f not in mapping]
        if not ({"debit", "credit"} <= set(mapping) or "amount" in mapping):
            need.append("Debit and Credit (or Amount)")
    elif not ({"debit", "credit"} <= set(mapping) or "balance" in mapping):
        need.append("Debit and Credit (or Balance)")
    return need


def _amount(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("£", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    for suffix, sign in ((" dr", 1), (" cr", -1)):
        if s.lower().endswith(suffix):
            s, neg = s[: -len(suffix)], sign < 0
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return 0.0


def _cell(r: List[Any], mapping: Dict[str, int], field: str) -> Any:
    i = mapping.get(field)
    return r[i] if i is not None and i < len(r) else None


def read_tb(raw: pd.DataFrame, header_row: int, mapping: Dict[str, int]) -> pd.DataFrame:
    """A trial balance by its columns: one row an account (total and blank lines left out)."""
    out = []
    for r in _rows(raw)[header_row + 1:]:
        name = str(_cell(r, mapping, "name") or "").strip()
        code = str(_cell(r, mapping, "code") or "").strip()
        if code.endswith(".0"):
            code = code[:-2]
        if not name and not code:
            continue
        if TOTAL.match(name) or name.lower().startswith(("profit/(loss)", "profit (loss)", "net profit")):
            continue
        if "debit" in mapping or "credit" in mapping:
            debit, credit = _amount(_cell(r, mapping, "debit")), _amount(_cell(r, mapping, "credit"))
            net = round(debit - credit, 2)
        else:
            net = round(_amount(_cell(r, mapping, "balance")), 2)
            debit, credit = max(net, 0.0), max(-net, 0.0)
        out.append({"raw_account_name": f"{code} - {name}" if code and name else name or code,
                    "account_type": None, "debit": debit, "credit": credit, "net": net,
                    "firm_code": firm_code_of(_cell(r, mapping, "firm_code")) if "firm_code" in mapping else None})
    return pd.DataFrame(out, columns=["raw_account_name", "account_type", "debit", "credit", "net", "firm_code"])


def read_gl(raw: pd.DataFrame, header_row: int, mapping: Dict[str, int]) -> pd.DataFrame:
    """A ledger by its columns: a line is a row with a date and an amount; a row reading 'Opening Balance' gives the
    account's opening balance; total, closing and blank rows are left out. An account written only on a heading row
    (no amounts) applies to the lines below it."""
    rows = _rows(raw)
    lines, opening = [], {}
    current = ""
    for r in rows[header_row + 1:]:
        # Sage Intacct adds '(Balance forward As of 01/01/2026)' to the account on every line
        account = BALANCE_FORWARD.sub("", str(_cell(r, mapping, "account") or "")).strip()
        when = _cell(r, mapping, "date")
        if "amount" in mapping and not ({"debit", "credit"} <= set(mapping)):
            amt = _amount(_cell(r, mapping, "amount"))
            debit, credit = max(amt, 0.0), max(-amt, 0.0)
        else:
            debit, credit = _amount(_cell(r, mapping, "debit")), _amount(_cell(r, mapping, "credit"))
        if any(isinstance(v, str) and OPENING.match(v) for v in r):
            name = account or current
            if name:
                opening[name] = round(opening.get(name, 0.0) + debit - credit, 2)
            continue
        if not _is_date(when):
            # A heading row naming the account for the lines below (no date, no amounts)
            if account and not debit and not credit:
                current = account
            continue
        if not debit and not credit:
            continue
        text = lambda f: str(_cell(r, mapping, f)).strip() if _cell(r, mapping, f) not in (None, "") else ""
        vat = _cell(r, mapping, "vat")
        lines.append({
            "Date": pd.to_datetime(when, dayfirst=True, errors="coerce") if isinstance(when, str) else when,
            "Source": text("type") or "GL",
            "Description": " - ".join(p for p in (text("name"), text("description")) if p),
            "Reference": text("reference"),
            "VAT": _amount(vat) if vat not in (None, "") else None,
            "Debit": round(debit, 2),
            "Credit": round(credit, 2),
            "Parent_Account": account or current,
        })
    df = pd.DataFrame(lines)
    df.attrs["opening_balances"] = opening
    df.attrs["explicit_sides"] = True
    return df


def software_of(raw_frames: List[pd.DataFrame]) -> str:
    """SAGE when the reports carry Sage's own words, else OTHER."""
    for raw in raw_frames:
        text = " ".join(str(v) for v in raw.head(400).values.flatten() if v is not None and not (isinstance(v, float) and v != v))
        if SAGE_WORDS.search(text):
            return "SAGE"
    return "OTHER"


def saved_layout(db: Session, owner_user_id: Optional[int], role: str, sig: str) -> Optional[UploadLayout]:
    return db.query(UploadLayout).filter_by(owner_user_id=owner_user_id, role=role, signature=sig).first()


def save_layout(db: Session, owner_user_id: Optional[int], role: str, sig: str, header_row: int,
                mapping: Dict[str, int], software: str) -> None:
    row = saved_layout(db, owner_user_id, role, sig)
    if row is None:
        db.add(UploadLayout(owner_user_id=owner_user_id, role=role, signature=sig[:1000], header_row=header_row,
                            mapping=json.dumps(mapping), software=software))
    else:
        row.header_row, row.mapping, row.software = header_row, json.dumps(mapping), software


def proposal(role: str, raw: pd.DataFrame, db: Session, owner_user_id: Optional[int]) -> Dict[str, Any]:
    """What the upload screen shows for a file the usual readers do not know: the headings, a few lines, and which
    column is what (a saved layout when the headings were seen before, else the app's guess)."""
    rows = _rows(raw.head(250))
    header_row, mapping = guess(role, rows)
    sig = signature(role, rows, header_row)
    known = saved_layout(db, owner_user_id, role, sig)
    if known is not None:
        header_row, mapping = known.header_row, {k: int(v) for k, v in json.loads(known.mapping).items()}
    width = max((len(r) for r in rows[header_row: header_row + 12]), default=0)
    heads = [str(v).strip() if v not in (None, "") else "" for v in (rows[header_row] + [None] * width)[:width]]
    def shown(v: Any) -> Any:
        if v is None or (not isinstance(v, str) and pd.isna(v)):       # blank cells, empty dates (NaT) included
            return None
        return v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else v

    preview = [[shown(v) for v in (r + [None] * width)[:width]]
               for r in rows[header_row + 1:] if any(v not in (None, "") for v in r)][:5]
    return {"role": role, "known": known is not None, "header_row": header_row, "headers": heads, "preview": preview,
            "mapping": mapping, "fields": [{"id": f, "label": label, "required": req} for f, label, req in FIELDS[role]],
            "missing": missing(role, mapping), "software": software_of([raw])}
