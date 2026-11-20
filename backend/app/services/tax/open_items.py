"""Invoices and bills still open at the year end, each found in the ledger with its own VAT.

Used by the VAT reconciliation (the VAT inside open items) and by the debtors / creditors items to look at (an open
invoice with no VAT while the customer's other invoices carry VAT; on cash accounting that is a query, as it changes
the VAT due when the money comes in).

A ledger document is the lines of one invoice or bill: one day, one contact (the part of the description before
' - '); an open item is matched to the document of its contact on its own date."""

from datetime import date
from typing import Dict, Iterable, List, Optional, Set, Tuple

from backend.app.services.sop.duplicates import DOCUMENT_SOURCES, _contact_key

VAT_MIN = 0.01


def ledger_documents(gl: Iterable, vat_code: int) -> Dict[Tuple[str, str, date], Dict]:
    """{(side 'AR' / 'AP', contact key, date): {"gross", "vat", "texts"}} from the ledger's invoice and bill lines."""
    docs: Dict[Tuple[str, str, date], Dict] = {}
    for line in gl:
        source = (line.source or "").strip().lower()
        side = ("AR" if source in DOCUMENT_SOURCES["customer"] else
                "AP" if source in DOCUMENT_SOURCES["supplier"] else None)
        if side is None or not line.when:
            continue
        # every line's whole text kept, so a contact named with ' - ' ('Customer - Shopify Sales') still matches
        key = (side, _contact_key((line.description or "").split(" - ")[0]), line.when)
        d = docs.setdefault(key, {"gross": 0.0, "vat": 0.0, "texts": set(), "contact": key[1]})
        d["texts"].add(_contact_key(line.description or ""))
        d["gross"] = max(d["gross"], abs(line.debit), abs(line.credit))
        if line.code == vat_code:
            d["vat"] += line.debit - line.credit
    return docs


def documents_by_day(docs: Dict[Tuple[str, str, date], Dict], side: str) -> Dict[date, List[Dict]]:
    by_day: Dict[date, List[Dict]] = {}
    for (s, _contact, when), d in docs.items():
        if s == side:
            by_day.setdefault(when, []).append(d)
    return by_day


def find_document(item, by_day: Dict[date, List[Dict]]) -> Optional[Dict]:
    """The ledger document of an open item: same date, and the contact's name at the start of a line's text."""
    name = _contact_key(item.contact)
    if not (item.when and name):
        return None
    return next((d for d in by_day.get(item.when, [])
                 if any(t == name or t.startswith(name + " ") for t in d["texts"])), None)


def contacts_with_vat(docs: Dict[Tuple[str, str, date], Dict], side: str) -> Set[str]:
    """Contacts with VAT on at least one of their invoices / bills in the year."""
    return {d["contact"] for (s, _c, _w), d in docs.items() if s == side and abs(d["vat"]) >= VAT_MIN}


def missing_vat(item, doc: Optional[Dict], with_vat: Set[str]) -> bool:
    """An open invoice / bill (owed the usual way) found in the ledger with no VAT, while the same contact's other
    documents carry VAT."""
    return (doc is not None and item.amount >= 1 and doc["gross"] >= 1 and abs(doc["vat"]) < VAT_MIN
            and doc["contact"] in with_vat)
