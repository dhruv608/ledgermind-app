"""Sales and purchase invoices (Dext) read and checked."""

from typing import Any, Dict, List
import re
from datetime import timedelta

from backend.app.services.bank_only.input_files.common import (
    DAMAGED_NUMBER, Invoice, PARTY_WORDS, Problem, RawInput, _amount, _col, _date, _header)


def _read_invoices(ws, out: RawInput, where: str) -> List[Invoice]:
    # A date and an amount are enough: 'Date | Amount' or 'Date | Description | Gross' lists have no Customer /
    # Supplier column
    hr, heads = _header(ws, ["date", PARTY_WORDS[where] + ("total", "gross", "amount", "net")])
    if hr is None:
        out.problems.append(Problem(where, "HIGH", f"{where}: headings not found (a date column and an amount "
                                                   f"column are needed)."))
        return []
    c = {k: _col(heads, *w) for k, w in {
        "date": ("date",), "due": ("due",), "number": ("invoice number", "invoice no", "inv no", "number", "ref"),
        "party": PARTY_WORDS[where], "desc": ("description", "details", "narrative", "item"),
        # Dext exports the amount in the bill's own currency and again in pounds: the pounds first
        "gross": ("total (gbp)", "total", "gross"), "vat": ("tax (gbp)", "vat (gbp)", "tax", "vat"), "net": ("net",),
        "category": ("category",)}.items()}
    if c["gross"] is None:
        # 'Amount' alone is the gross; 'VAT amount' / 'Net amount' are not
        c["gross"] = next((i for h, i in heads.items() if "amount" in h and not re.search(r"vat|tax|net", h)), None)
    if c["gross"] is None and c["net"] is not None:
        c["gross"] = c["net"] if c["vat"] is None else None
    if c["gross"] is None and c["net"] is None:
        out.problems.append(Problem(where, "HIGH", f"{where}: no amount column (Total, Gross or Amount)."))
        return []
    link_cols = [i for h, i in heads.items() if "link" in h or "image" in h]
    # 'Date' also matches 'Due Date' and 'Received date': the invoice date is the first date column
    c["date"] = min((i for h, i in heads.items() if "date" in h and "due" not in h and "received" not in h),
                    default=c["date"])
    c["received"] = next((i for h, i in heads.items() if "received" in h and "date" not in h), None)
    items, damaged = [], 0
    for r_idx, row in enumerate(ws.iter_rows(min_row=hr + 1, values_only=True), hr + 1):
        when = _date(row[c["date"]]) if c["date"] < len(row) else None
        if when is None:
            continue
        get = lambda k: row[c[k]] if c[k] is not None and c[k] < len(row) else None
        vat = _amount(get("vat"))
        net = _amount(get("net")) if c["net"] is not None else None
        gross = _amount(get("gross")) if c["gross"] is not None else round(net + vat, 2)
        if net is None:
            net = round(gross - vat, 2)
        if c["party"] is None and abs(gross) < 0.005 and abs(net) < 0.005:
            continue                    # a blank or heading row with a date in it (a £0 Dext bill is kept)
        number = get("number")
        number = str(int(number)) if isinstance(number, float) and number.is_integer() else str(number or "").strip()
        if DAMAGED_NUMBER.match(number):
            number, damaged = "", damaged + 1
        link = next((str(row[i]) for i in link_cols if i < len(row) and str(row[i] or "").startswith("http")), "")
        description = str(get("desc") or "").strip()
        party = str(get("party") or "").strip()
        if c["party"] is None and description:
            # No name column: 'Wickes - Strong Flex' is Wickes; a description with no dash is taken as the name
            party = description.partition(" - ")[0].strip()
        items.append(Invoice(
            row=r_idx, when=when, due=_date(get("due")), number=number,
            party=party, description=description,
            gross=gross, vat=vat, net=net,
            received=_amount(get("received")) if where == "Sales" and get("received") not in (None, "") else None,
            link=link, category=str(get("category") or "").strip()))
    if damaged:
        out.problems.append(Problem(where, "LOW", f"{damaged} invoice number(s) were turned into rounded numbers by "
                                                  "Excel (like 1.00113E+11): taken as having no number."))
    return items


def number_key(number: str) -> str:
    """How an invoice number is found on a bank line: by its digits ('BD200576' is quoted as 'Bd200576' or '200576');
    a number of letters with a short count ('PSOCT25', '#BWAPR25') only whole, as the customer writes it."""
    digits = re.sub(r"\D", "", number or "")
    whole = re.sub(r"[^A-Za-z0-9]", "", number or "").upper()
    if re.search(r"[A-Za-z]", whole) and len(digits) < 5:
        return whole if len(whole) >= 5 else ""
    return digits


def _check_invoices(out: RawInput) -> None:
    for where, items in (("Sales", out.sales), ("Purchases", out.purchases)):
        # The same invoice twice: the same number for the same party, or the same party, date and amount where one has
        # no number. Same-day invoices with different numbers are separate jobs. One number used for two different
        # customers is the client's numbering mistake, asked about on its own.
        by_number: Dict[str, Invoice] = {}
        by_amount: Dict[Any, Invoice] = {}
        for i in items:
            if i.number:
                key = i.number.upper() if where == "Sales" else f"{i.party.lower()}|{i.number.upper()}"
                first = by_number.get(key)
                if first is None:
                    by_number[key] = i
                elif first.party.lower() == i.party.lower():
                    out.problems.append(Problem(where, "MEDIUM",
                        f"Invoice {i.number} ({i.party}) appears twice, rows {first.row} and {i.row}: keep one."))
                else:
                    out.problems.append(Problem(where, "MEDIUM",
                        f"Invoice number {i.number} is used for two customers: {first.party} (row {first.row}, "
                        f"£{first.gross:,.2f}) and {i.party} (row {i.row}, £{i.gross:,.2f}). Ask the client which is right."))
            same = (i.party.lower(), i.when, i.gross)
            first = by_amount.get(same)
            if first is not None and (not i.number or not first.number):
                out.problems.append(Problem(where, "MEDIUM",
                    f"Possible duplicate: {i.party} {i.when:%d/%m/%Y} £{i.gross:,.2f} at rows {first.row} and {i.row} "
                    f"(one has no invoice number). Keep one."))
            by_amount.setdefault(same, i)
        if out.year_end:
            start = out.year_end.replace(year=out.year_end.year - 1) + timedelta(days=1)
            outside = [i for i in items if not (start <= i.when <= out.year_end)]
            if outside:
                out.problems.append(Problem(where, "LOW", f"{len(outside)} invoice(s) dated outside the year (kept, marked outside)."))
        if where == "Sales":
            # Gaps in the invoice number sequence (numbers with the same prefix)
            nums = sorted({int(m.group(2)) for i in items for m in [re.match(r"^([A-Za-z]*)(\d+)$", i.number)] if m})
            # Counted before listed: numbers like 'WHNOV24' and '18674583770' would make a gap of billions
            missing = sum(b - a - 1 for a, b in zip(nums, nums[1:]))
            gaps = [n for a, b in zip(nums, nums[1:]) for n in range(a + 1, b)] if 0 < missing <= 50 else []
            if gaps:
                out.problems.append(Problem("Sales", "MEDIUM",
                    f"{len(gaps)} invoice number(s) missing from the sequence ({', '.join(map(str, gaps[:12]))}"
                    f"{'…' if len(gaps) > 12 else ''}): ask the client whether they were cancelled."))
        else:
            no_number = [i for i in items if not i.number]
            if no_number:
                out.problems.append(Problem("Purchases", "LOW", f"{len(no_number)} bill(s) have no invoice number."))
