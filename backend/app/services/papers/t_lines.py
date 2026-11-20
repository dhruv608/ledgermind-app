"""The lines of a balance sheet account's T named the way an accountant reads them ("Sales invoices raised", "Bank
receipts", "VAT paid to HMRC" ...), not "movement from TB" or the software's type. Each ledger line is named from what
the account is (bank, trade debtors, VAT ...), the kind of entry the software gave it (invoice, bill, payment,
journal ...) and its side; lines that fit no name keep the software's type."""

import re
from typing import Iterable, Optional

from backend.app.services.mapping.chart_lookup import (CT_CREDITOR, DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM,
                                                       NET_WAGES, PAYE_NIC, VAT_CONTROL)

TRADE_DEBTORS, TRADE_CREDITORS, CREDIT_CARD = 4400, 5200, 5351
BANK_CODES = range(4800, 4831)
JOURNALS = "Journals in the books"

# The kind of account, from its codes, else the words of its name (first match)
KIND_NAMES = [(re.compile(p, re.I), k) for p, k in (
    (r"\bvat\b", "vat"),
    (r"paye|national insurance|\bnic?\b", "paye"),
    (r"pension", "pension"),
    (r"net wages|wages (payable|control)|net pay|salar(y|ies) payable", "wages"),
    (r"corporation tax", "ct"),
    (r"director", "dla"),
    (r"loan|mortgage|hire purchase|finance lease|bounce", "loan"),
    (r"\bbank\b|credit card|current account|savings|deposit account|petty cash|cash in hand", "bank"),
    (r"^(trade )?debtors|receivable", "debtors"),
    (r"^(trade )?creditors|payable", "creditors"),
)]


def account_kind(codes: Iterable[int], names: Iterable[str]) -> str:
    codes = set(codes)
    if codes and all(c in BANK_CODES or c == CREDIT_CARD for c in codes):
        return "bank"
    for code_set, kind in (({TRADE_DEBTORS}, "debtors"), ({TRADE_CREDITORS}, "creditors"), ({VAT_CONTROL}, "vat"),
                           ({PAYE_NIC}, "paye"), ({NET_WAGES}, "wages"), ({CT_CREDITOR}, "ct"),
                           ({DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM}, "dla")):
        if codes and codes <= code_set:
            return kind
    text = " ".join(names)
    for pattern, kind in KIND_NAMES:
        if pattern.search(text):
            return kind
    return "other"


def entry_kind(source: Optional[str]) -> str:
    """The kind of entry from the software's type (QuickBooks, Xero, Sage words)."""
    s = (source or "").lower()
    if not s.strip() or s.strip() in ("gl", "books", "-"):
        return ""
    for words, kind in (
        (("starting value", "opening"), "opening"),
        (("refund", "overpayment"), "money"),
        (("allocation",), "allocation"),
        (("credit note", "supplier credit", "credit card credit"), "credit"),
        (("payroll",), "payroll"),
        (("journal", "adjust"), "journal"),
        (("vat payment", "sales tax payment"), "tax_paid"),
        (("payable invoice", "purchase invoice", "accpay"), "bill"),
        (("bill payment",), "money"),
        (("bill",), "bill"),
        (("invoice", "accrec"), "invoice"),
        (("sales receipt",), "cash_sale"),
        (("expense", "spend money", "cheque", "check"), "spend"),
        (("deposit", "receive money"), "receive"),
        (("payment", "transfer", "receipt"), "money"),
    ):
        if any(w in s for w in words):
            return kind
    return "?"


PAID = {"paye": "Paid to HMRC", "pension": "Paid to the pension provider", "wages": "Wages paid",
        "ct": "Paid to HMRC"}
OWED = {"paye": "PAYE and NI owed per the payroll", "pension": "Pension owed per the payroll",
        "wages": "Net wages owed per the payroll", "ct": "Corporation tax charge"}


# What a line or journal is about, by its words, for the lines the T names on its own (DLA: use of home, dividend;
# loans: interest charged)
USE_OF_HOME = re.compile(r"use of (the )?home|home office|working from home|\bwfh\b", re.I)
DIVIDEND = re.compile(r"dividend", re.I)
INTEREST = re.compile(r"interest", re.I)
# Money paid to the director (a payment the bank shows as an expense, but its words say it went to the director)
DRAWINGS = re.compile(r"drawing|director|\bdla\b|transfer to", re.I)


def named_by_words(kind: str, text: Optional[str]) -> Optional[str]:
    """A line's or journal's name from its description, where the T has a line of its own; else None."""
    t = text or ""
    if kind == "dla":
        if USE_OF_HOME.search(t):
            return "Use of home"
        if DIVIDEND.search(t):
            return "Dividend"
    if kind == "loan" and INTEREST.search(t):
        return "Interest charged"
    return None


def line_name(kind: str, source: Optional[str], debit: bool, description: Optional[str] = None) -> str:
    """One ledger line's name on the T. debit: the line debits the account."""
    by_words = named_by_words(kind, description)
    if by_words:
        return by_words
    entry = entry_kind(source)
    if entry == "opening":
        return "Opening balance in the ledger"
    if entry in ("journal", "payroll") and kind in PAID and not debit:
        return OWED[kind]           # the payroll (or tax) journal posts what is owed
    if entry == "journal" and kind != "vat":
        return JOURNALS
    if kind == "bank":
        if "transfer" in (source or "").lower():
            return "Transfers between accounts"
        return "Bank receipts" if debit else "Bank payments"
    if kind == "debtors":
        if entry == "invoice":
            return "Sales invoices raised" if debit else "Sales invoices reversed"
        if entry in ("credit", "allocation"):
            return "Credit notes" if not debit else "Credit notes reversed"
        if entry in ("money", "receive", "cash_sale", ""):
            return "Bank receipts from customers" if not debit else "Refunds to customers"
    if kind == "creditors":
        if entry == "bill":
            return "Purchase bills received" if not debit else "Purchase bills reversed"
        if entry in ("credit", "allocation"):
            return "Supplier credit notes" if debit else "Supplier credit notes reversed"
        if entry in ("money", "spend", "receive", ""):
            return "Bank payments to suppliers" if debit else "Refunds from suppliers"
    if kind == "vat":
        s = (source or "").lower()
        if entry == "tax_paid" or (entry == "money" and debit and "refund" not in s):
            return "VAT paid to HMRC" if debit else "VAT repaid by HMRC"
        if entry == "journal":
            return JOURNALS
        # By the document: sales documents (and their refunds and credit notes) carry output VAT, purchase documents
        # input VAT, whichever side the line is on (a supplier credit note takes input VAT back)
        if "payable" in s or "supplier" in s or entry in ("bill", "spend"):
            return "VAT on purchases (input VAT)"
        if "receivable" in s or "refund" in s or entry in ("invoice", "cash_sale", "receive", "credit"):
            return "VAT on sales (output VAT)"
        if entry in ("money", ""):
            return "VAT on purchases (input VAT)" if debit else "VAT on sales (output VAT)"
    if kind in PAID:
        return PAID[kind] if debit else OWED[kind]
    if kind == "dla":
        if debit and entry != "bill" and DRAWINGS.search(description or ""):
            return "Drawings"
        if entry in ("spend", "bill"):
            return "Personal paid expenses" if debit else "Company expenses paid by the director"
        if entry in ("money", "receive", ""):
            return "Drawings" if debit else "Funds introduced"
    if kind == "loan":
        if entry in ("money", "spend", "receive", ""):
            return "Instalments paid" if debit else "Loan received"
    if entry == "":
        return "Debits" if debit else "Credits"
    return (source or "").strip()
