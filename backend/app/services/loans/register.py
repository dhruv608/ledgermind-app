"""The loans register (the "Loans register" sheet of the firm's schedule template): one row per agreement under a heading
row with Lender / agreement, Amount financed, Term, Payments per year, Interest rate, Total finance charge, Regular
payment, Balloon and Interest method. The template's own example rows ('EXAMPLE ...') and the TOTAL row are left out.
"""

import re
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from backend.app.services.loans.schedule import Agreement

# Heading words -> field; the first column that matches is used (the calculated columns repeat some words)
FIELDS = [
    ("lender", re.compile(r"^lender")),
    ("kind", re.compile(r"^type$")),
    ("drawdown", re.compile(r"agreement|drawdown")),
    ("first_payment", re.compile(r"first payment")),
    ("amount", re.compile(r"amount financed|cash price|loan amount")),
    ("deposit", re.compile(r"deposit|part.?exchange")),
    ("payments", re.compile(r"number of payments|^term")),
    ("per_year", re.compile(r"payments per year")),
    ("rate", re.compile(r"interest rate")),
    ("charge", re.compile(r"finance charge")),
    ("payment", re.compile(r"regular payment|monthly payment|instalment")),
    ("balloon", re.compile(r"balloon|final payment")),
    ("method", re.compile(r"interest method|^method$")),
    ("books_balance", re.compile(r"balance per books")),
    ("books_interest", re.compile(r"interest per books")),
]


def header_row(rows: List[List[str]]) -> Optional[int]:
    for i, row in enumerate(rows[:30]):
        text = " | ".join(str(c).lower() for c in row)
        if "lender" in text and ("amount financed" in text or "number of payments" in text):
            return i
    return None


def _columns(row: List[str]) -> Dict[str, int]:
    cols: Dict[str, int] = {}
    for i, cell in enumerate(row):
        h = re.sub(r"\s+", " ", str(cell or "").strip().lower())
        if not h:
            continue
        for name, pattern in FIELDS:
            if name not in cols and pattern.search(h):
                # 'Agreement / drawdown date' is the date, not 'Lender / agreement'
                if name == "drawdown" and "lender" in h:
                    continue
                if name == "balloon" and "date" in h:
                    continue
                cols[name] = i
                break
    return cols


def _number(text) -> Optional[float]:
    t = str(text or "").replace("£", "").replace(",", "").replace("%", "").strip()
    if not t or t.lower() in ("nan", "none"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _date(text) -> Optional[date]:
    t = str(text or "").strip()
    if not t or t.lower() in ("nan", "none"):
        return None
    try:
        d = pd.to_datetime(t, dayfirst=not re.match(r"^\d{4}-", t))
    except (ValueError, TypeError):
        return None
    return None if pd.isna(d) else d.date()


def read(rows: List[List[str]]) -> List[Agreement]:
    h = header_row(rows)
    if h is None:
        return []
    cols = _columns(rows[h])
    cell = lambda row, name: row[cols[name]] if name in cols and cols[name] < len(row) else ""
    out: List[Agreement] = []
    for row in rows[h + 1:]:
        lender = str(cell(row, "lender") or "").strip()
        if not lender or lender.lower() in ("nan", "total") or lender.upper().startswith("EXAMPLE"):
            continue
        amount, payments = _number(cell(row, "amount")), _number(cell(row, "payments"))
        if not amount or not payments:
            continue
        rate = _number(cell(row, "rate"))
        if rate is not None and rate > 1:          # typed as 2.5 rather than 2.5% / 0.025
            rate = rate / 100
        out.append(Agreement(
            lender=lender[:255], kind=str(cell(row, "kind") or "").strip()[:50],
            drawdown=_date(cell(row, "drawdown")), first_payment=_date(cell(row, "first_payment")),
            amount=amount, deposit=_number(cell(row, "deposit")) or 0.0, payments=int(payments),
            per_year=int(_number(cell(row, "per_year")) or 12), rate=rate, charge=_number(cell(row, "charge")),
            payment=_number(cell(row, "payment")), balloon=_number(cell(row, "balloon")) or 0.0,
            method=str(cell(row, "method") or "").strip() or "Actuarial",
            books_balance=_number(cell(row, "books_balance")), books_interest=_number(cell(row, "books_interest"))))
    return out
