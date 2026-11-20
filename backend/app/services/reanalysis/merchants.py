"""
The merchant behind a ledger or bank line: the bank's wording, card text,
store numbers, towns and references taken off, then matched to the merchant dictionary (rules/merchants.json: aliases
-> merchant -> category). 'CARD PAYMENT TO AMZN MKTP UK*2X4 LONDON' -> Amazon, marketplace. A name not in the
dictionary is kept as its first words (the client's own payee), with 'person' as the category when it reads as a
person's name. The dictionary is firm data: new merchants are added there, never in this code.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

MERCHANTS_FILE = Path(__file__).resolve().parents[2] / "rules" / "merchants.json"
# Ledger contact names that are not a payee (Xero 'Spend Money', QuickBooks 'Expense')
NOT_A_CONTACT = re.compile(r"^(spend|receive) money\b|^expense$|^bill$|^payable invoice$|^journal\b", re.I)
TITLES = {"mr", "mrs", "miss", "ms", "dr", "mx"}
# How it was paid, not who was paid ('CLASSIC CANTON (VIA GOOGLE PAY)')
PAID_WITH = re.compile(r"\(?\s*via\s+(apple|google|samsung)\s+pay\s*\)?|\b(apple|google|samsung)\s+pay\b", re.I)
# Card acquirers written before the real merchant ('SQ *THE COFFEE HOUSE', 'SUMUP *JOES', 'ZTL*BAKERY')
ACQUIRER = re.compile(r"\b(sq|sumup|ztl|izettle|paypal|pp)\s*\*\s*", re.I)


@dataclass
class Merchant:
    name: str                   # display name: 'Amazon', or the payee's own words 'John Smith'
    key: str                    # lower-case key for memory: 'amazon', 'john smith'
    category: Optional[str]     # dictionary category, 'person', or None
    known: bool                 # found in the dictionary


@lru_cache(maxsize=1)
def _dictionary() -> Tuple[List[Tuple[str, str, str]], str]:
    """(alias words, merchant, category), longest alias first, and the dictionary version."""
    from backend.app.services.shared import rules_store
    data = rules_store.load("merchants")
    rows = [(" ".join(_words(alias)), m["merchant"], m["category"]) for m in data["merchants"] for alias in m["aliases"]]
    rows = [r for r in rows if r[0]]
    rows.sort(key=lambda r: -len(r[0]))
    return rows, data.get("version", "")


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9&]+", (text or "").lower().replace("'", ""))


def _payee_text(description: str) -> str:
    """The part of the line naming the payee: the contact before ' - ' (Xero and QuickBooks write 'Contact - memo'),
    unless that contact is a generic word ('Spend Money'); card acquirer prefixes taken off."""
    text = description or ""
    if " - " in text:
        contact, rest = text.split(" - ", 1)
        text = rest if NOT_A_CONTACT.search(contact.strip()) else contact
    return ACQUIRER.sub(" ", text)


def merchant_of(description: str) -> Merchant:
    from backend.app.services.bank_only.books import payee_key
    from backend.app.services.review.subcontractors import is_person
    description = PAID_WITH.sub(" ", description or "")
    text = _payee_text(description)
    words = " " + " ".join(_words(text)) + " "
    whole = " " + " ".join(_words(description)) + " "
    rows, _ = _dictionary()
    for alias, name, category in rows:
        if f" {alias} " in words or f" {alias} " in whole:
            return Merchant(name, name.lower(), category, True)
    key = payee_key(text)
    if not key:
        return Merchant("", "", None, False)
    key = " ".join([w for w in key.split() if w not in TITLES][:3])
    display = key.title()
    return Merchant(display, key, "person" if is_person(display) else None, False)

