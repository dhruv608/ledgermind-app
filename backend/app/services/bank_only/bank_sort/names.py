"""Reading names on a bank line: customer and supplier names, the directors, the payer of money in, and the
bank's own channel words."""

import re
from typing import List, Tuple

# Words that do not identify a customer or supplier
_COMMON = {"ltd", "limited", "plc", "llp", "the", "and", "co", "uk", "group", "services", "service", "housing",
           "bank", "transfer", "card", "purchase", "direct", "debit", "credit", "payment", "scheduled", "invoice",
           "london", "gbr", "pay", "solutions", "company", "properties", "property", "trading", "ctr", "centre"}

def _words(text: str) -> List[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _COMMON and not w.isdigit()]
    long = [w for w in words if len(w) >= 3]
    return long or [w for w in words if len(w) == 2]     # 'AB Housing': the short word is all there is


def _name_matches(name: str, description: str) -> bool:
    """A customer or supplier name appears on the bank line: its first distinctive word (bank lines cut names short:
    'Example Housi', 'Example Trading L')."""
    words = _words(name)
    desc = description.lower()
    if not words:
        return False
    w = words[0]
    return re.search(rf"\b{re.escape(w)}\b" if len(w) < 3 else rf"\b{re.escape(w)}", desc) is not None


def _director_words(directors: List[str]) -> List[Tuple[str, str, Tuple[str, ...]]]:
    """(first name, surname, all the names) of the directors (bank lines write 'Matt Smith' for Matthew Smith)."""
    out = []
    for d in directors:
        parts = [p for p in re.findall(r"[a-z]+", d.lower()) if p not in ("mr", "mrs", "ms", "miss", "dr")]
        if parts and len(parts[-1]) >= 3:
            out.append((parts[0] if len(parts) > 1 else "", parts[-1], tuple(parts)))
    return out


def _is_name(word: str, name: str) -> bool:
    """A word on the line is the name, or the name cut short or run on ('Rakesh' for Rakeshkumar, 'Rakeshkumar' for
    Rakesh): five letters at least, so 'Ali' is never 'Alison'."""
    if word == name:
        return True
    short, long = sorted((word, name), key=len)
    return len(short) >= 5 and long.startswith(short)


def _names_director(description: str, directors: List[Tuple[str, str, Tuple[str, ...]]]) -> bool:
    """The director on the line: the surname with no initial beside it that is none of his names ('R Smith' or
    'Smith L' paying an invoice is a customer who shares the surname of John Smith; 'MR J D SMITH' is John David
    Smith), or his first name with another of his names (the surname misspelt on the line)."""
    words = re.findall(r"[a-z]+", description.lower())
    for first, surname, names in directors:
        initials = {n[0] for n in names}
        for i, w in enumerate(words):
            if w != surname:
                continue
            beside = [x for x in (words[j] for j in (i - 2, i - 1, i + 1) if 0 <= j < len(words)) if len(x) == 1]
            if first and beside and not any(x in initials for x in beside):
                continue
            return True
        if first and len(names) > 1:
            for i, w in enumerate(words):
                if _is_name(w, first) and any(len(x) >= 3 and _is_name(x, n) for x in words[i + 1:i + 4]
                                              for n in names[1:]):
                    return True
    return False


# The bank's own words on the line, not the payee: 'MOBILE-CHANNEL' is how the payment was made, not a phone bill
CHANNEL_WORDS = re.compile(r"\bmobile[- ]?channel\b|\bvia (mobile|online|internet)( (banking|app|-? ?pymt))?\b|"
                           r"\b(on-?line|internet|mobile|telephone) banking\b|\bmobile app\b", re.I)
# Money in from the client itself ('Self Transfer', 'Transfer funds'): its own money moved, not a sale
OWN_MONEY = re.compile(r"self[- ]?transfer|transfer(ring)? funds|own funds|\bown money\b|from (my|our) (other )?account",
                       re.I)
# The bank's words before the payer's name ('Direct Credit From', 'Automated Credit', 'FPI')
PAYER_PREFIX = re.compile(r"^\s*((direct|automated|bank giro|giro) credit|bgc|fpi|faster payments?( receipt)?|"
                          r"bill payment|credit|transfer|from|received|payment)\b[\s:.-]*", re.I)


def _payer_words(text: str) -> List[str]:
    """The first words of the line once the bank's own words are taken off: the payer of money in."""
    while True:
        cut = PAYER_PREFIX.sub("", text, count=1)
        if cut == text:
            break
        text = cut
    return [w for w in re.findall(r"[a-z0-9]+", text.lower())][:3]
