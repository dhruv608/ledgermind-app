"""A Self Assessment job's documents: each file sent goes through intake (intake.py), is classified and, for the kinds
with a reader (P60, P45, payslip, bank statement, savings, letting, pension and mortgage statements, DWP letters,
dividend vouchers, last year's working paper), read and checked; every file is kept with what was found and why it may need a person."""

import hashlib
import json
from typing import List, Tuple

from sqlalchemy.orm import Session

from backend.app.sa.extract.lastyear import is_sheet, previous_year
from backend.app.sa import foster
from backend.app.sa.extract import cis, dividend, donations, foreign_tax, invoice, sa302, sa_statement, interest, letting, mortgage, p11d, p45, p60, pension, vat_return, vision
from backend.app.sa.extract.classify import classify, tax_year_of, working_paper_year
from backend.app.sa.intake import intake, page_png, page_texts
from backend.app.sa.models import SADocument, SAJob


def _masked(ni: str) -> str:
    return "•" * max(len(ni) - 3, 0) + ni[-3:] if ni else ni


def _read_p60(item, job: SAJob, text_fields):
    """(fields, status, notes, read_by) for a P60: by code from its text when the layout allows, else two AI reads."""
    if text_fields and text_fields.get("pay_this") is not None:
        status, notes = p60.checks(text_fields, job.tax_year, job.ni_number, person=job.person_name)
        return text_fields, status, notes, "text"
    image = page_png(item)
    first, second = vision.read_twice(image, p60.PROMPT)
    if first is None and second is None:
        return {}, "CHECK", ["The P60 could not be read: enter its figures by hand."], vision.READER
    fields = p60.clean(first or second)
    printed = p60.printed_year(item.text)
    if printed:
        fields["tax_year"] = printed
    status, notes = p60.checks(fields, job.tax_year, job.ni_number, second if first else None, job.person_name)
    return fields, status, notes, f"{vision.READER} + {vision.CHECKER}"


# The documents read into figures by an AI model with code checking the answer: a text layer from its text, a scan
# by two models (their totals must agree)
READERS = {"INTEREST_STATEMENT": interest, "LETTING_STATEMENT": letting, "PENSION_STATEMENT": pension,
           "DWP_LETTER": pension, "MORTGAGE_INTEREST": mortgage, "DIVIDEND_VOUCHER": dividend, "CIS_STATEMENT": cis,
           "FOSTER_LETTER": foster, "TAX_CALCULATION": sa302,
           "FOREIGN_TAX": foreign_tax, "DONATIONS": donations, "VAT_RETURN": vat_return, "HMRC_STATEMENT": sa_statement}


def readable(text: str) -> bool:
    """A text layer that is words and figures, not a font's codes (a building society's PDF gives control codes for
    its text, more than half of it: read as a picture instead). Any printable text counts, a sheet's | included."""
    import unicodedata
    t = (text or "").strip()
    codes = sum(1 for ch in t if unicodedata.category(ch)[0] == "C" and ch not in "\n\r\t")
    return len(t) >= 80 and codes <= 0.1 * len(t)


def _read_money_doc(item, job: SAJob, reader):
    """(fields, status, notes, read_by) for a savings or letting statement."""
    text = item.text
    # A long tax report: its consolidated tax certificate is the page read (it may be past the first 20 pages)
    if hasattr(reader, "certificate_text") and item.name.lower().endswith(".pdf"):
        text = reader.certificate_text(page_texts(item)) or text
    if not item.image and readable(text):
        try:
            ans = vision.ask_text(vision.READER, text[:16000], reader.PROMPT, max_tokens=6000)
        except Exception:
            ans = None
        fields = reader.clean(ans)
        if hasattr(reader, "with_text"):
            fields = reader.with_text(fields, text)           # the reading held to the page's own text
        status, notes = reader.checks(fields, job.tax_year, job.person_name)
        return fields, status, notes, f"{vision.READER} (text)"
    image = page_png(item)
    # As long an answer as the text path allows: a statement of many lines cut off at 1,200 tokens is unreadable JSON
    first, second = vision.read_twice(image, reader.PROMPT, max_tokens=6000)
    if first is None and second is None:
        return {}, "CHECK", ["The statement could not be read: enter its figures by hand."], vision.READER
    fields = reader.clean(first or second)
    status, notes = reader.checks(fields, job.tax_year, job.person_name, second if first else None)
    return fields, status, notes, f"{vision.READER} + {vision.CHECKER}"


def _final_by_name(f, name: str):
    """A payslip whose file is named as the final one ('Final Payslip.pdf') is the final one."""
    if f.get("kind") == "PAYSLIP" and "final" in name.lower().split("/")[-1]:
        f["final"] = True
    return f


NAMED_P60 = "\nThe file is named as a P60: if it is one, give its figures."


def _tie_break(item, prompt, clean, first, second, keys=("pay_this", "tax_this")):
    """When the two readers disagree on pay or tax, the page is read a third time at a higher resolution: the reading
    two of the three agree on is kept, with the agreeing one as its check (None: no third reading settled it)."""
    if not first or not second:
        return None
    a, b = clean(first), clean(second)
    same = lambda x, y: all(x.get(k) is not None and y.get(k) is not None and abs(x[k] - y[k]) <= 0.005 for k in keys)
    if same(a, b):
        return None
    try:
        third = vision.ask(vision.READER, page_png(item, dpi=300), prompt)
    except Exception:
        return None
    c = clean(third)
    if same(a, c):
        return first, third
    if same(b, c):
        return second, third
    return None


def _read_employment_doc(item, job: SAJob, reader=p45):
    """(fields, status, notes, read_by) for a P45, payslip or P11D: a text layer read from its text, a scan by two
    models (the checks also take the person's NI number)."""
    if not item.image and len((item.text or "").strip()) >= 80:
        try:
            ans = vision.ask_text(vision.READER, item.text[:12000], reader.PROMPT, max_tokens=2000)
        except Exception:
            ans = None
        f = _final_by_name(reader.clean(ans), item.name)
        status, notes = reader.checks(f, job.tax_year, job.ni_number, job.person_name)
        return f, status, notes, f"{vision.READER} (text)"
    first, second = vision.read_twice(page_png(item), reader.PROMPT)
    if first is None and second is None:
        return {}, "CHECK", ["The document could not be read: enter its figures by hand."], vision.READER
    settled = _tie_break(item, reader.PROMPT, reader.clean, first, second) if reader is not p11d else None
    if settled:
        first, second = settled
    f = _final_by_name(reader.clean(first or second), item.name)
    status, notes = reader.checks(f, job.tax_year, job.ni_number, job.person_name, second if first else None)
    return f, status, notes, f"{vision.READER} + {vision.CHECKER}" + (" (3 reads)" if settled else "")


def _read_client_sheet(item):
    """(fields, status, notes, read_by) for the client's own income and expenses sheet: read by code."""
    from backend.app.sa.extract import client_sheet
    try:
        fields = client_sheet.read(item.data)
    except Exception:
        fields = {"rows": []}             # not an .xlsx the code can open (an old .xls): the model reads its text
    if not fields["rows"]:
        # Not the firm's template: the client's own layout, read by the model from the sheet's text (own_sheet.py)
        from backend.app.sa.extract import own_sheet
        try:
            ans = vision.ask_text(vision.READER, (item.text or "")[:24000], own_sheet.PROMPT, max_tokens=8000)
        except Exception:
            ans = None
        f = own_sheet.clean(ans)
        if not f["is_business_sheet"]:
            return f, "FILED", ["No business income or costs on this sheet: filed (its other figures have their own "
                                "pages)."], f"{vision.READER} (text)"
        return f, "CHECK", [f"The client's own sheet, read by the AI: {len(f['rows'])} business rows. Check them against "
                            f"the sheet on Self-employment."], f"{vision.READER} (text)"
    return fields, "READ", [], "code"


def _read_statement(item):
    """(fields, status, notes, read_by) for a bank statement: every page read as a picture and chained."""
    from backend.app.sa.extract.statement import PageRead, StatementLine, chain_break, read_pages
    if item.name.lower().endswith(".csv"):
        # A bank's own export: read by code, as printed (bank_csv.py); oldest first, as the PDF pages are put
        from backend.app.sa.extract import bank_csv
        r = bank_csv.read(item.data, item.name)
        lines = [StatementLine(*l, page=1) for l in r["lines"]]
        if len(lines) > 1 and (lines[0].on or "") > (lines[-1].on or ""):
            lines = lines[::-1]
        has_bal = any(l.balance is not None for l in lines)
        reads = [PageRead(1, lines, None, None, account_last4=r["account_last4"], account_name=r["account_name"],
                          chains=(not has_bal) or chain_break(lines, None) is None, read_by="code (bank export)")]
    elif item.name.lower().endswith(".pdf"):
        # Each page's text (a text layer is read as text) and its picture, made only when the text is not enough
        n_pages = item.pages or 1
        texts = page_texts(item)
        reads = read_pages([(lambda n=n: page_png(item, n, dpi=160)) for n in range(n_pages)], texts=texts)
        from backend.app.sa.extract.statement import into_period, period_of
        into_period(reads, period_of(texts or []))
    else:
        reads = read_pages([item.data])
    lines = [l for p in reads for l in p.lines]
    fields = {
        "bank": next((p.bank for p in reads if p.bank), None),
        "account_last4": next((p.account_last4 for p in reads if p.account_last4), None),
        "account_name": next((p.account_name for p in reads if p.account_name), None),
        "holders": next((p.holders for p in reads if p.holders), []),
        "postcode": next((p.postcode for p in reads if p.postcode), None),
        "currency": next((p.currency for p in reads if getattr(p, "currency", None)), None),
        "lines": len(lines), "money_in": round(sum(l.money_in for l in lines), 2),
        "money_out": round(sum(l.money_out for l in lines), 2),
        "first": min((l.on for l in lines if l.on), default=None), "last": max((l.on for l in lines if l.on), default=None),
        "pages": [{"page": p.page, "bf": p.brought_forward, "cf": p.carried_forward, "chains": p.chains, "read_by": p.read_by,
                   "lines": [[l.on, l.description, l.money_in, l.money_out, l.balance] for l in p.lines]} for p in reads],
    }
    broken = [p.page for p in reads if p.lines and not p.chains]
    notes = [f"Page{'s' if len(broken) > 1 else ''} {', '.join(map(str, broken))}: the balances do not add up line by line; check the amounts."] if broken else []
    skipped = [p.page for p in reads if p.skipped]
    if skipped:
        # The AI service was too slow for the whole statement: what was read is kept, the rest is marked to check
        notes.append(f"Page{'s' if len(skipped) > 1 else ''} {', '.join(map(str, skipped))} not read: the reading took too "
                     f"long (the AI service was slow). Read them again later, or enter those lines by hand.")
        broken += skipped
    if not lines:
        if not skipped and fields.get("bank"):
            # The bank was read but the page has no transaction on it (a cover, notes or terms page, a blank page sent
            # with the statements): filed, not held as unread
            return fields, "FILED", [f"A {fields['bank']} page with no transactions on it (a cover, notes or blank page): "
                                     f"filed."], vision.READER
        return fields, "CHECK", (notes if skipped else ["No transactions could be read from this statement."]), vision.READER
    return fields, ("CHECK" if broken else "READ"), notes, " + ".join(sorted({p.read_by for p in reads}))


def read_last_year(data: bytes, name: str):
    """(fields, status, notes, read_by) for last year's working paper: its sources, this year's checklist."""
    from backend.app.sa.extract import lastyear
    try:
        out = lastyear.read(data, name)
    except Exception:
        return {}, "CHECK", ["Last year's working paper could not be read: add last year's sources by hand."], None
    fields = {"last_year": True, "lines": out["lines"], "answers": out["answers"], "total_income": out["total_income"]}
    return fields, ("CHECK" if out["checks"] else "READ"), out["checks"], out.get("model")


# A page's kind, asked page by page of a scanned bundle (the kinds the readers know)
KIND_PROMPT = """This is one page of a document sent for a UK Self Assessment tax return. Say what the page is, as "kind",
one of: P60, P45, PAYSLIP, P11D, BANK_STATEMENT, MORTGAGE_INTEREST, LETTING_STATEMENT, INTEREST_STATEMENT,
DIVIDEND_VOUCHER, PENSION_STATEMENT, DWP_LETTER, CIS_STATEMENT, FOSTER_LETTER, TAX_CALCULATION, FOREIGN_TAX (a
foreign country's tax assessment or return), TAX_CODE_NOTICE (an HMRC coding notice), VAT_RETURN (a VAT return or
its VAT 100 boxes), HMRC_STATEMENT (HMRC's Self Assessment statement, SA300), INVOICE (a bill, an
invoice or a receipt), OTHER (the person's own notes or summary sheet, a list, a letter, anything else).
Reply with one JSON object only, for example {"kind": "BANK_STATEMENT"}."""
PAGE_KINDS = {"P60", "P45", "PAYSLIP", "P11D", "BANK_STATEMENT", "MORTGAGE_INTEREST", "LETTING_STATEMENT",
              "INTEREST_STATEMENT", "DIVIDEND_VOUCHER", "PENSION_STATEMENT", "DWP_LETTER", "CIS_STATEMENT",
              "FOSTER_LETTER", "TAX_CALCULATION", "FOREIGN_TAX", "TAX_CODE_NOTICE", "VAT_RETURN", "HMRC_STATEMENT", "INVOICE", "OTHER"}
MAX_SPLIT_PAGES = 40


def page_kinds(item) -> List[str]:
    """Each page's kind, read as a small picture (four at a time)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(n: int) -> str:
        try:
            ans = vision.ask(vision.READER, page_png(item, n, dpi=110), KIND_PROMPT, max_tokens=60, grow=False)
        except Exception:
            ans = None
        kind = str((ans or {}).get("kind") or "OTHER").upper()
        return kind if kind in PAGE_KINDS else "OTHER"
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, range(item.pages)))


def split_mixed(item) -> list:
    """A scanned PDF that is a bundle of different documents (a client's monthly pack: their own sheet, a bank
    statement, the letting agent's statement, bills) cut into its parts, each read by its own reader. Split only when
    two or more real kinds are found; an odd page inside one kind stays with it, so a statement's balance chain holds."""
    import fitz
    from backend.app.sa.intake import Item
    if not (item.image and item.name.lower().endswith(".pdf") and 2 <= (item.pages or 0) <= MAX_SPLIT_PAGES):
        return [item]
    kinds = page_kinds(item)
    if len({k for k in kinds if k != "OTHER"}) < 2:
        return [item]
    # An OTHER page between two pages of the same kind belongs to that kind
    for n in range(1, len(kinds) - 1):
        if kinds[n] == "OTHER" and kinds[n - 1] == kinds[n + 1] != "OTHER":
            kinds[n] = kinds[n - 1]
    src = fitz.open(stream=item.data, filetype="pdf")
    src.authenticate("")
    parts, start = [], 0
    for n in range(1, len(kinds) + 1):
        if n == len(kinds) or kinds[n] != kinds[start]:
            out = fitz.open()
            out.insert_pdf(src, from_page=start, to_page=n - 1)
            data = out.tobytes()
            pages = f"page {start + 1}" if n - 1 == start else f"pages {start + 1}-{n}"
            # 'August 2025 (pages 2-4).pdf': the name still ends in .pdf, so each reader opens it as a PDF
            part = Item(f"{item.name[:-4]} ({pages}).pdf", data, hashlib.sha256(data).hexdigest(), pages=n - start,
                        image=True, saved=item.saved)
            part.kind_hint = kinds[start]
            parts.append(part)
            start = n
    return parts


def add_documents(db: Session, job: SAJob, files: List[Tuple[str, bytes]]) -> List[SADocument]:
    from backend.app.core.s3 import s3_service
    seen = dict(db.query(SADocument.sha256, SADocument.kind).filter(SADocument.job_id == job.id).all())
    added = []
    # A bundle is cut into its parts first; the whole file is remembered, so the same bundle sent again is a duplicate
    items, wholes = [], set()
    for it in intake(files):
        # The whole file is checked before any split: the same bundle sent twice is a duplicate even when the AI
        # would cut the two copies at different pages
        if it.sha256 in seen or it.sha256 in wholes:
            items.append(it)
            continue
        wholes.add(it.sha256)
        parts = split_mixed(it)
        if len(parts) > 1:
            # The whole bundle is kept as a record of its own, so the same file sent later is a duplicate too
            seen[it.sha256] = "BUNDLE"
            bundle = SADocument(job_id=job.id, filename=it.name[:500], sha256=it.sha256, size=len(it.data), kind="BUNDLE",
                                status="FILED", note=f"A bundle of documents: cut into its {len(parts)} parts, each read on its own.")
            db.add(bundle)
            added.append(bundle)
        items.extend(parts)
    later = []                                     # receipts and invoices: read together at the end
    for item in items:
        doc = SADocument(job_id=job.id, filename=item.name[:500], sha256=item.sha256, size=len(item.data))
        if item.sha256 in seen:
            doc.kind, doc.status, doc.note = seen[item.sha256], "DUPLICATE", "The same file was sent before: kept once."
            db.add(doc)
            added.append(doc)
            continue
        ext = "." + item.name.rsplit(".", 1)[-1].lower() if "." in item.name.split("/")[-1] else ""
        if item.data:
            doc.storage_key = s3_service.upload_file_bytes(item.data, f"sa_uploads/{job.id}/{item.sha256}{ext}")
        fields, notes = {}, []
        if item.unreadable:
            doc.status, notes = "UNREADABLE", [item.unreadable]
        elif item.image:
            # A scan or photo: the reader says what it is; a P60 is then read again by the checker
            hint = getattr(item, "kind_hint", None)     # a part of a bundle: its kind is known already
            first = None
            if not hint or hint == "P60":
                try:
                    first = vision.ask(vision.READER, page_png(item), p60.PROMPT)
                except Exception:
                    first = None
            doc.kind = hint or (first or {}).get("kind") or "OTHER"
            # The reader could not say what the scan is, but its file name does ('P60.pdf', 'Letter from french
            # authorities.pdf'): read it as that kind (R-IN-01: every document is read)
            if doc.kind == "OTHER" and not hint:
                by_name = classify("", item.name)
                if by_name in ("P60", "BANK_STATEMENT") or by_name in READERS or by_name in ("P45", "PAYSLIP", "P11D"):
                    doc.kind = by_name
                # A P60 by its name only: the reader's answer has no P60 figures, so it reads the picture once more,
                # told what the file is (a P60 picture taken for 'OTHER' on one read is often read right on the next)
                if doc.kind == "P60" and (first or {}).get("kind") != "P60":
                    try:
                        first = vision.ask(vision.READER, page_png(item), p60.PROMPT + NAMED_P60)
                    except Exception:
                        first = None
            if doc.kind == "P60":
                second = None
                try:
                    second = vision.ask(vision.CHECKER, page_png(item), p60.PROMPT)
                except Exception:
                    pass
                settled = _tie_break(item, p60.PROMPT, p60.clean, first, second)
                if settled:
                    first, second = settled
                fields = p60.clean(first)
                doc.status, notes = p60.checks(fields, job.tax_year, job.ni_number, second, job.person_name)
                doc.read_by = f"{vision.READER} + {vision.CHECKER}" + (" (3 reads)" if settled else "")
            elif doc.kind == "BANK_STATEMENT":
                fields, doc.status, notes, doc.read_by = _read_statement(item)
            elif doc.kind == "INVOICE":
                later.append((doc, item))
            elif doc.kind in READERS:
                fields, doc.status, notes, doc.read_by = _read_money_doc(item, job, READERS[doc.kind])
            elif doc.kind in ("P45", "PAYSLIP", "P11D"):
                fields, doc.status, notes, doc.read_by = _read_employment_doc(item, job, p11d if doc.kind == "P11D" else p45)
            else:
                doc.status, doc.read_by = "FILED", vision.READER
        else:
            doc.kind = classify(item.text, item.name)
            # A bank's own export (a CSV with a date, description and amount header): a bank statement, read by code
            csv_bank = False
            sipp = None
            if item.name.lower().endswith(".csv") and item.data:
                from backend.app.sa.extract import bank_csv, sipp_csv
                if sipp_csv.looks_like(item.name, item.data):
                    # A SIPP's activity export: its top-ups are pension contributions (R-SAV-07); the rest stays out
                    from backend.app.sa.income import tax_year_dates
                    start, end = (x.isoformat() for x in tax_year_dates(job.tax_year))
                    sipp = sipp_csv.as_pension(item.name, item.data, start, end)
                    doc.kind = "PENSION_STATEMENT"
                else:
                    csv_bank = bank_csv.looks_like(bank_csv._text(item.data[:4000]))
                    if csv_bank:
                        doc.kind = "BANK_STATEMENT"
            if sipp is not None or (doc.kind == "PENSION_STATEMENT" and item.name.lower().endswith(".csv")):
                fields = sipp or {}
                doc.status, doc.read_by = ("CHECK", "code (SIPP export)") if sipp else ("FILED", "code (SIPP export)")
                notes = ([f"SIPP top-ups of £{sipp['items'][0]['amount']:,.2f} in {job.tax_year}: a relief at source "
                          f"contribution, entered as paid (grossed up in the calculation). Confirm they are the person's own "
                          f"payments, not the employer's. The SIPP's own dividends and interest are not taxable (R-SAV-05, "
                          f"-07)."] if sipp else ["A SIPP export with no top-ups in the year: filed."])
            elif doc.kind == "P60":
                fields, doc.status, notes, doc.read_by = _read_p60(item, job, p60.from_text(item.text))
            elif doc.kind == "BANK_STATEMENT" and (item.name.lower().endswith(".pdf") or csv_bank):
                fields, doc.status, notes, doc.read_by = _read_statement(item)
            elif doc.kind == "INVOICE":
                later.append((doc, item))
            elif doc.kind in READERS:
                fields, doc.status, notes, doc.read_by = _read_money_doc(item, job, READERS[doc.kind])
            elif doc.kind in ("P45", "PAYSLIP", "P11D"):
                fields, doc.status, notes, doc.read_by = _read_employment_doc(item, job, p11d if doc.kind == "P11D" else p45)
            elif doc.kind == "CLIENT_ACCOUNTS":
                fields, doc.status, notes, doc.read_by = _read_client_sheet(item)
            else:
                doc.status = "FILED"
                doc.tax_year = working_paper_year(item.text, item.name) if doc.kind == "WORKING_PAPER" else tax_year_of(item.text)
                if doc.kind == "WORKING_PAPER" and doc.tax_year == previous_year(job.tax_year) and is_sheet(item.name):
                    fields, doc.status, notes, doc.read_by = read_last_year(item.data, item.name)
                    if fields:
                        fields["saved"] = item.saved        # the newest version by its own date wins (R-IN-08)
        if fields:
            doc.tax_year = fields.get("tax_year") or doc.tax_year
            if fields.get("ni_number"):
                fields["ni_number"] = _masked(fields["ni_number"])
            doc.fields = json.dumps(fields)
        doc.note = " ".join(notes) or None
        seen[item.sha256] = doc.kind
        db.add(doc)
        added.append(doc)
    _read_receipts(later, job)
    db.commit()
    return added


# A scanned receipt is read by the second model only when the first reading needs a look or its total is at least this
# (a second reading of every receipt is a large part of the AI cost; a misread small bill moves the return by pence)
RECEIPT_SECOND_READ = 100.0


def _read_receipt_scan(item, job: SAJob, reader):
    """(fields, status, notes, read_by) for a scanned receipt or bill: one reading, a second only when it matters."""
    image = page_png(item)
    try:
        first = vision.ask(vision.READER, image, reader.PROMPT, max_tokens=6000)
    except Exception:
        first = None                                # the second model still reads it
    fields = reader.clean(first)
    status, notes = reader.checks(fields, job.tax_year, job.person_name)
    total = sum(abs(b.get("total") or 0) for b in fields.get("bills") or [])
    if first is not None and status in ("READ", "FILED", "OTHER_YEAR") and total < RECEIPT_SECOND_READ:
        return fields, status, notes, vision.READER
    try:
        second = vision.ask(vision.CHECKER, image, reader.PROMPT, max_tokens=6000)
    except Exception:
        second = None
    if first is None and second is None:
        return {}, "CHECK", ["The bill could not be read: enter its figures by hand."], vision.READER
    fields = reader.clean(first or second)
    status, notes = reader.checks(fields, job.tax_year, job.person_name, second if first else None)
    return fields, status, notes, f"{vision.READER} + {vision.CHECKER}"


def _read_receipts(later, job: SAJob) -> None:
    """The receipts and invoices sent, read four at a time (a client may send two hundred: one by one, two readers
    each, they held the upload for most of an hour); each is read as a money document (two readers for a scan)."""
    if not later:
        return
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    reader = SimpleNamespace(PROMPT=invoice.prompt_for(job.person_name), clean=invoice.clean, checks=invoice.checks)

    def one(pair):
        try:
            if pair[1].image:
                return _read_receipt_scan(pair[1], job, reader)
            return _read_money_doc(pair[1], job, reader)
        except Exception as e:                      # one bad file never stops the others
            return {}, "CHECK", [f"The bill could not be read ({type(e).__name__}): look at it."], vision.READER

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, later))
    for (doc, _), (fields, status, notes, read_by) in zip(later, results):
        doc.status, doc.read_by = status, read_by
        if fields:
            doc.fields = json.dumps(fields)
        doc.note = " ".join(notes) or None


def doc_out(doc: SADocument) -> dict:
    return {"id": doc.id, "filename": doc.filename, "kind": doc.kind, "status": doc.status, "tax_year": doc.tax_year,
            "fields": json.loads(doc.fields) if doc.fields else None, "note": doc.note, "read_by": doc.read_by,
            "size": doc.size, "created_at": doc.created_at.isoformat() if doc.created_at else None}
