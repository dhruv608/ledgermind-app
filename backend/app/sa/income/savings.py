"""Savings, dividends, Gift Aid and pension lines from the documents and the bank, and a director's dividends."""

import json
import re
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.sa.models import SADocument, SAJob, SALine
from backend.app.sa.income.common import DIVIDEND_CODES, tax_year_dates


BANK_INTEREST_NOTE = "Interest credited on the bank statements"


def sync_savings_lines(db: Session, job: SAJob) -> None:
    """Savings lines from the documents (R-SAV-01 to 03): each account on an interest statement (an ISA kept but left
    out, a joint account at half), then the interest credited on each account's bank statements in the tax year (the
    same tags from the account's name and holders), unless an interest statement already gives that account. A bank line is kept up to date as statements are added;
    the accountant's share or include on it is kept."""
    from backend.app.sa.extract import interest
    start, end = (d.isoformat() for d in tax_year_dates(job.tax_year))
    lines = db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "SAVINGS").all()
    have = {l.doc_id for l in lines if l.doc_id is not None and l.note != BANK_INTEREST_NOTE}
    covered = set()
    docs = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "INTEREST_STATEMENT",
                                       SADocument.status.in_(("READ", "CHECK"))).all()
    # An account with a certificate or statement for the whole tax year: that is the provider's tax-year figure
    # (R-SAV-02), so its monthly statements are not added to it again (one money, one place)
    whole_year = {d.id: interest.whole_year(f, start, end) and not f.get("other_person")
                  for d in docs for f in [json.loads(d.fields) if d.fields else {}]}
    year_accounts = {a["account_last4"] for d in docs if whole_year[d.id]
                     for a in (json.loads(d.fields) if d.fields else {}).get("accounts") or [] if a.get("account_last4")}
    # A page with no dates giving to the penny the interest of an account on a whole-year certificate is that
    # certificate again (another page of it)
    year_amounts = [float(a.get("interest_gross") or 0) for d in docs if whole_year[d.id]
                    for a in (json.loads(d.fields) if d.fields else {}).get("accounts") or [] if a.get("interest_gross")]
    # The words naming each account on a whole-year certificate ('HL Active Savings Account': hl, active): a bank page
    # with no account number whose interest line names one is a payment the certificate already counts ('Interest paid
    # Active Savings')
    generic = {"account", "accounts", "savings", "saving", "saver", "interest", "bank", "paid", "gross", "certificate",
               "statement", "from", "after", "with", "limited", "plc", "the", "and", "your"}
    year_words = {w for d in docs if whole_year[d.id] for f in [json.loads(d.fields) if d.fields else {}]
                  for a in f.get("accounts") or [] for w in re.findall(r"[a-z]{4,}", f"{a.get('account_name') or ''}".lower())
                  if w not in generic}
    dated_seen: set = set()
    for doc in sorted(docs, key=lambda d: (d.id not in have, d.id)):     # files with lines already first
        f = json.loads(doc.fields) if doc.fields else {}
        if f.get("other_person"):
            continue                       # another person's account: off the return until confirmed (R-IN-07)
        for a in f.get("accounts") or []:
            if a.get("account_last4"):
                covered.add(a["account_last4"])
            # The same dated period and the same interest on two files (two pages of one statement, the provider read
            # differently): one statement, counted once
            same = (f.get("period_from"), f.get("period_to"), round(float(a.get("interest_gross") or 0), 2))
            again = bool(same[0] and same[1] and same[2]) and same in dated_seen
            dated_seen.add(same)
            if doc.id in have or again:
                continue
            if not whole_year[doc.id] and a.get("account_last4") in year_accounts:
                continue                   # the year's certificate for this account gives its interest
            if (not whole_year[doc.id] and not f.get("period_from") and not f.get("period_to") and a.get("interest_gross")
                    and any(abs(float(a["interest_gross"]) - y) < 0.005 for y in year_amounts)):
                continue                   # the same certificate's figure on an undated page
            name = " ".join(x for x in (f.get("provider"), a.get("account_name")) if x) or "Savings account"
            db.add(SALine(job_id=job.id, source="SAVINGS", kind="ISA" if a.get("isa") else "INTEREST", label=name[:255],
                          amount=a["interest_gross"], tax_paid=a.get("tax_deducted") or 0,
                          share=0.5 if a.get("joint") else 1, doc_id=doc.id, auto=1,
                          note="Joint account: half each unless evidence says otherwise (R-SAV-01)" if a.get("joint") else None))
    # The bank statements, account by account (the same account over several files added together)
    by_account: Dict[str, Dict] = {}
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "BANK_STATEMENT",
                                           SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all():
        f = json.loads(doc.fields) if doc.fields else {}
        total, n = interest.from_statement(f.get("pages") or [], start, end)
        if not n:
            continue
        said = {w for p in f.get("pages") or [] for l in p.get("lines") or [] if l[2] and interest.INTEREST_IN.search(l[1] or "")
                for w in re.findall(r"[a-z]{4,}", (l[1] or "").lower())}
        if not f.get("account_last4") and said & year_words:
            continue                       # the interest the year's certificate for that account gives
        acct = f.get("account_last4") or f"file {doc.id}"
        named = " ".join(x for x in (f.get("account_name"), doc.filename) if x)
        # A joint account (its name or the file's says so, or two holders printed): half each unless evidence says
        # otherwise
        joint = bool(interest.JOINT_WORDS.search(named)) or len(f.get("holders") or []) > 1
        row = by_account.setdefault(acct, {"amount": 0.0, "doc_id": doc.id, "bank": f.get("bank"), "joint": joint,
                                           "isa": bool(interest.ISA_WORDS.search(named))})
        row["amount"] = round(row["amount"] + total, 2)
    old = {l.label: l for l in lines if l.note == BANK_INTEREST_NOTE}
    for acct, row in by_account.items():
        if acct in covered:
            continue
        label = f"{row['bank'] or 'Bank'} account {acct}"[:255]
        if label in old:
            old[label].amount = row["amount"]
        else:
            db.add(SALine(job_id=job.id, source="SAVINGS", kind="ISA" if row["isa"] else "INTEREST", label=label,
                          amount=row["amount"], share=0.5 if row["joint"] else 1, doc_id=row["doc_id"], auto=1,
                          note=BANK_INTEREST_NOTE))
    db.commit()


def director_dividends(db: Session, job: SAJob) -> List[Dict]:
    """Dividend payments in the company's books dated in the tax year (every year of the company the firm has)."""
    from backend.app.models.database import ClientEngagement, GLTransaction, TBRecord
    if not job.company_engagement_id:
        return []
    linked = db.get(ClientEngagement, job.company_engagement_id)
    if linked is None:
        return []
    start, end = tax_year_dates(job.tax_year)
    years = db.query(ClientEngagement).filter(ClientEngagement.owner_user_id == linked.owner_user_id,
                                              ClientEngagement.client_name == linked.client_name).all()
    out, seen = [], set()
    for eng in years:
        names = {r.raw_account_name for r in db.query(TBRecord).filter(TBRecord.engagement_id == eng.id,
                                                                        TBRecord.std_code.in_(DIVIDEND_CODES)).all()}
        if not names:
            continue
        for t in db.query(GLTransaction).filter(GLTransaction.engagement_id == eng.id,
                                                GLTransaction.raw_account_name.in_(names)).all():
            when = t.transaction_date
            amount = float(t.debit_amount or 0) - float(t.credit_amount or 0)
            if when is None or not (start <= when <= end) or amount <= 0:
                continue
            key = (when, round(amount, 2), (t.description or "")[:60])
            if key in seen:                       # the same payment in two years' ledgers
                continue
            seen.add(key)
            out.append({"date": when.isoformat(), "amount": round(amount, 2), "description": t.description or "",
                        "company": eng.client_name, "year_end": eng.period_end_date.isoformat() if eng.period_end_date else None})
    return sorted(out, key=lambda d: d["date"])


def sync_donation_lines(db: Session, job: SAJob) -> None:
    """A donations list or a charity's receipt on Reliefs as Gift Aid: the tax year's donations, as paid (the engine grosses
    them up). One line per document; a document already on the return is not added again."""
    from backend.app.sa.extract.donations import in_year
    have = {l.doc_id for l in db.query(SALine).filter(SALine.job_id == job.id, SALine.doc_id.isnot(None))}
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "DONATIONS",
                                           SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in have or f.get("other_person"):
            continue
        total = round(sum(r["amount"] for r in in_year(f, job.tax_year)), 2)
        if total:
            db.add(SALine(job_id=job.id, source="RELIEFS", kind="GIFT_AID", amount=total, doc_id=doc.id, auto=1,
                          label=f"Gift Aid ({doc.filename.replace(chr(92), '/').split('/')[-1][:60]})"[:255],
                          note="Donations as paid, from the client's list or receipts: confirm the Gift Aid declarations"))
    db.commit()


def sync_pension_lines(db: Session, job: SAJob) -> None:
    """Pension statements and DWP letters on the return (R-SAV-06, R-SAV-07, R-SP-02): the State Pension and taxable
    benefits at the DWP's figure, a pension paid with its tax, a relief at source contribution as paid (net). A pension
    a P60 from the same payer already gives is not added again ('never bank credits when a P60 exists')."""
    from backend.app.sa.extract.pension import same_payer
    lines = db.query(SALine).filter(SALine.job_id == job.id).all()
    have = {l.doc_id for l in lines if l.doc_id is not None}
    p60_ids = {d for (d,) in db.query(SADocument.id).filter(SADocument.job_id == job.id, SADocument.kind == "P60").all()}
    p60_payers = [l.label for l in lines if l.source == "PENSIONS" and l.doc_id in p60_ids]
    p60_amounts = [float(l.amount) for l in lines if l.source == "PENSIONS" and l.doc_id in p60_ids and l.amount]
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind.in_(("PENSION_STATEMENT", "DWP_LETTER")),
                                           SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in have or f.get("other_person"):
            continue
        for it in f.get("items") or []:
            amount = it.get("amount")
            if amount is None:
                continue
            label = (it.get("name") or it.get("payer") or it["kind"].replace("_", " ").title())[:255]
            if it["kind"] == "CONTRIBUTION":
                if it.get("basis") == "RELIEF_AT_SOURCE":
                    db.add(SALine(job_id=job.id, source="RELIEFS", kind="PENSION_RAS", label=label, amount=amount,
                                  doc_id=doc.id, auto=1, note="Paid net: grossed up for the bands (R-SAV-07)"))
                continue
            # (the administrator may be the payer printed, 'CAPITA', with the scheme as the name: either names the P60's)
            names = {n for n in (it.get("payer"), it.get("name"), label) if n}
            if it["kind"] in ("PENSION", "LUMP_SUM") and (any(same_payer(n, p) for n in names for p in p60_payers)
                                                          or any(abs(float(amount) - a) < 0.005 for a in p60_amounts)):
                continue                   # the P60 gives this pension already (its payer, or the same money)
            if it["kind"] == "LUMP_SUM":
                # The taxable part only, as pension income (a tax-free lump sum has none)
                if not amount:
                    continue
                whole = it.get("year_amount")
                db.add(SALine(job_id=job.id, source="PENSIONS", kind="PENSION", label=f"{label}: lump sum, taxable part"[:255],
                              amount=amount, tax_paid=it.get("tax_deducted") or 0, doc_id=doc.id, auto=1,
                              note=(f"Taxable part of a £{whole:,.2f} lump sum" if whole else "Taxable part of a lump sum")
                                   + " (PN4-PN6): if the provider's P45 or P60 includes it, remove one"))
                continue
            db.add(SALine(job_id=job.id, source="PENSIONS", kind=it["kind"], label=label, amount=amount,
                          tax_paid=it.get("tax_deducted") or 0, doc_id=doc.id, auto=1))
    db.flush()
    # Taxable benefits credited on the bank statements, when no DWP letter gives them ('DWP letter or bank credits');
    # kept up to date as statements are added
    from backend.app.sa.extract.pension import bank_benefits
    start, end = (d.isoformat() for d in tax_year_dates(job.tax_year))
    benefits: Dict[str, Tuple[float, int]] = {}
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "BANK_STATEMENT",
                                           SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all():
        f = json.loads(doc.fields) if doc.fields else {}
        for name, amount in bank_benefits(f.get("pages") or [], start, end).items():
            total, first = benefits.get(name, (0.0, doc.id))
            benefits[name] = (round(total + amount, 2), first)
    now = db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "PENSIONS").all()
    for name, (amount, doc_id) in benefits.items():
        if any(l.kind == "BENEFIT" and name.split()[0].lower() in (l.label or "").lower() and l.note != BANK_BENEFIT_NOTE for l in now):
            continue                       # a DWP letter (or the accountant) gives it
        line = next((l for l in now if l.note == BANK_BENEFIT_NOTE and l.label == name), None)
        if line is not None:
            line.amount = amount
        else:
            db.add(SALine(job_id=job.id, source="PENSIONS", kind="BENEFIT", label=name, amount=amount, doc_id=doc_id,
                          auto=1, note=BANK_BENEFIT_NOTE))
    db.commit()


BANK_BENEFIT_NOTE = "Credited on the bank statements: check against the DWP's figure for the year (R-SP-02)"


def sync_dividend_lines(db: Session, job: SAJob) -> None:
    """A dividends line for each dividend on a voucher (R-SAV-04), with its payment date; one held in an ISA kept but
    left out (R-SAV-05). The person's own company's dividends come from its books (director_dividends), not vouchers."""
    from backend.app.models.database import ClientEngagement
    from backend.app.sa.extract.pension import same_payer
    have = {d for (d,) in db.query(SALine.doc_id).filter(SALine.job_id == job.id, SALine.doc_id.isnot(None)).all()}
    company = db.get(ClientEngagement, job.company_engagement_id) if job.company_engagement_id else None
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "DIVIDEND_VOUCHER",
                                           SADocument.status.in_(("READ", "CHECK"))).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in have or f.get("other_person"):
            continue
        for d in f.get("dividends") or []:
            if company is not None and same_payer(d["company"], company.client_name):
                continue                   # the director module takes it from the company's books
            db.add(SALine(job_id=job.id, source="DIVIDENDS", kind="DIVIDEND", label=d["company"][:255], amount=d["amount"],
                          paid_on=d.get("pay_date"), doc_id=doc.id, auto=1, include=0 if f.get("isa") else 1,
                          note="Held in an ISA: left out (R-SAV-05)" if f.get("isa") else None))
    # A broker's tax certificate read as a savings document gives its dividends too; an
    # overseas fund's or company's dividend is foreign income, noted for the SA106
    with_dividends = {d for (d,) in db.query(SALine.doc_id).filter(SALine.job_id == job.id, SALine.source == "DIVIDENDS",
                                                                   SALine.doc_id.isnot(None)).all()}
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "INTEREST_STATEMENT",
                                           SADocument.status.in_(("READ", "CHECK"))).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in with_dividends or f.get("other_person") or not f.get("dividends"):
            continue
        name = f.get("provider") or "Broker"
        for d in f["dividends"]:
            db.add(SALine(job_id=job.id, source="DIVIDENDS", kind="DIVIDEND", label=f"{name}: {d['company']}"[:255],
                          amount=d["amount"], doc_id=doc.id, auto=1,
                          note="Overseas: foreign dividends, for the SA106 (any foreign tax there)" if d.get("overseas") else None))
    db.commit()
