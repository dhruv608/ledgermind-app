"""Bank statements read into their lines (the raw data route): date, description, money in, money out
and the running balance. A PDF page with a text layer is read from its own text (exact digits, fast); a scan as a
picture (vision.py); code then proves the reading with the balance column, in either order (oldest or newest first).

  read_pages   each page: its lines, and the balance brought / carried forward printed on it; a page whose lines do
               not chain (balance = the one before + in - out) is read again by the second model
  assemble     an account's statements together, from every file sent: a month sent twice (the same brought and
               carried forward balances and first date) is kept once; months in date order (banks often print the
               newest first); each page must carry on from the page before, and a break is a page to check; the
               period the statements cover, so a month missing at either end shows"""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract import vision

PROMPT = """This is one page of a UK bank statement. Read every transaction line on it, in the order printed.
Reply with one JSON object only:
{"bank": "bank name or null", "account_last4": "last 4 digits of the account number or null",
 "account_name": "the account's name or type as printed (e.g. 'Joint Account', 'Cash ISA') or null",
 "holders": ["each account holder's name as printed"],
 "postcode": "the account holder's postcode as printed (e.g. CV21 2ER) or null",
 "currency": "the account's currency code (GBP, EUR, USD...) from its money signs, IBAN or heading, or null",
 "brought_forward": number or null (the balance brought forward / opening balance printed on this page),
 "lines": [{"date": "YYYY-MM-DD", "description": "the payee and reference as printed", "in": number or null,
            "out": number or null, "balance": number or null}],
 "carried_forward": number or null}
Money as plain numbers with pence (no £ or commas). A banking app often prints the pence smaller, just after the
pounds ('-£400.00' with a small '.00'): that is 400.00, never 40000. Use the year from the statement period for every date. A line with
no amount (a balance line, a heading) is not a transaction: leave it out. A card statement's summary box (previous
balance, amount spent on purchases, total amount you repaid, new balance, minimum payment) is not a transaction either. An overdrawn balance is negative: a balance
printed with D, DR or OD after it ('116.61D'), or in brackets, is overdrawn (-116.61)."""


@dataclass
class StatementLine:
    on: Optional[str]
    description: str
    money_in: float
    money_out: float
    balance: Optional[float]
    page: int = 0
    doc_id: Optional[int] = None


@dataclass
class PageRead:
    page: int
    lines: List[StatementLine]
    brought_forward: Optional[float]
    carried_forward: Optional[float]
    bank: Optional[str] = None
    account_last4: Optional[str] = None
    chains: bool = True
    account_name: Optional[str] = None
    holders: List[str] = field(default_factory=list)
    postcode: Optional[str] = None
    currency: Optional[str] = None
    read_by: str = vision.READER
    skipped: bool = False              # not read: the document's time ran out (TIME_LIMIT)


@dataclass
class Account:
    """An account's statements put together."""
    lines: List[StatementLine] = field(default_factory=list)
    opening: Optional[float] = None
    closing: Optional[float] = None
    first: Optional[str] = None
    last: Optional[str] = None
    duplicates: int = 0
    checks: List[str] = field(default_factory=list)

    @property
    def money_in(self) -> float:
        return round(sum(l.money_in for l in self.lines), 2)

    @property
    def money_out(self) -> float:
        return round(sum(l.money_out for l in self.lines), 2)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return None


# A statement's own summary box given back as a line: a card statement's 'Amount spent on purchases' and 'Total
# amount you repaid' are not a cost and takings; a balance carried forward is not a line either
# ('previous / new balance' only with a figure or nothing after it: New Balance is also a shop)
SUMMARY_BOX = re.compile(r"^\s*(total amount you (re)?paid|amount spent on purchases|total (amount )?spent\b"
                         r"|(previous|new) balance\s*($|[\d£:(-])|minimum (amount|payment)|balance (brought|carried) forward"
                         r"|(opening|closing) balance|(brought|carried) forward)", re.I)


def _lines(answer: Optional[Dict[str, Any]], page: int) -> List[StatementLine]:
    out = []
    for l in (answer or {}).get("lines") or []:
        i, o = _num(l.get("in")) or 0.0, _num(l.get("out")) or 0.0
        if not i and not o:
            continue
        if SUMMARY_BOX.search(str(l.get("description") or "")):
            continue
        out.append(StatementLine(l.get("date"), str(l.get("description") or "").strip(), abs(i), abs(o), _num(l.get("balance")), page))
    return out


def chain_break(lines: List[StatementLine], start: Optional[float]) -> Optional[int]:
    """The first line whose balance does not follow from the one before (None: it chains). Lines with no balance
    printed (several on one day) are carried to the next printed balance."""
    running = start
    for k, l in enumerate(lines):
        if running is not None:
            running = round(running + l.money_in - l.money_out, 2)
        if l.balance is not None:
            if running is not None and abs(running - l.balance) > 0.005:
                return k
            running = l.balance
    return None


def _ask(image: bytes, model: str) -> Optional[Dict[str, Any]]:
    try:
        return vision.ask(model, image, PROMPT, max_tokens=8000)
    except Exception as e:
        vision.logger.warning("SA statement reader %s failed: %s: %s", model, type(e).__name__, str(e)[:200])
        return None


def _ask_text(text: str, model: str) -> Optional[Dict[str, Any]]:
    try:
        return vision.ask_text(model, text, PROMPT, max_tokens=8000)
    except Exception as e:
        vision.logger.warning("SA statement reader %s failed: %s: %s", model, type(e).__name__, str(e)[:200])
        return None


def opening_of(lines: List[StatementLine]) -> Optional[float]:
    """The balance before the page's first line, worked back from the first printed balance."""
    for k, l in enumerate(lines):
        if l.balance is not None:
            return round(l.balance - sum(x.money_in - x.money_out for x in lines[:k + 1]), 2)
    return None


def currency_of(v: Any) -> Optional[str]:
    """A currency as its three-letter code ('£' and 'Sterling' are GBP, '€' EUR), else None."""
    c = str(v or "").strip().upper()
    c = {"£": "GBP", "STERLING": "GBP", "POUNDS": "GBP", "€": "EUR", "EURO": "EUR", "EUROS": "EUR", "$": "USD"}.get(c, c)
    return c if re.fullmatch(r"[A-Z]{3}", c) else None


def overdrawn_signs(lines: List[StatementLine], start: Optional[float]) -> int:
    """Balances read without their overdrawn sign ('116.61D' read as 116.61): walking the page, a balance that is the
    exact negative of what the lines before make it is turned round. Returns how many were. Only an exact match is
    changed, so nothing is invented."""
    running, fixed = start, 0
    for l in lines:
        if running is not None:
            running = round(running + l.money_in - l.money_out, 2)
        if l.balance is not None:
            if running is not None and abs(running - l.balance) > 0.005 and abs(running + l.balance) <= 0.005:
                l.balance = -l.balance
                fixed += 1
            running = l.balance
    return fixed


def _page(n: int, ans: Optional[Dict[str, Any]], model: str) -> PageRead:
    lines = _lines(ans, n)
    bf, cf = _num((ans or {}).get("brought_forward")), _num((ans or {}).get("carried_forward"))
    chains = chain_break(lines, bf) is None
    if not chains and overdrawn_signs(lines, bf):
        chains = chain_break(lines, bf) is None
    # Every line adds up and only an overdrawn brought forward was read without its minus (£658.95 for -£658.95):
    # the page is right, the brought forward is the overdrawn balance
    if not chains and bf and chain_break(lines, None) is None and abs(bf + (opening_of(lines) or 0)) < 0.005:
        bf, chains = -bf, True
    # Online banking often prints the newest line first: when the balances only add up read from the bottom, the
    # page is turned into date order (its brought / carried forward are not trusted then)
    if not chains and len(lines) > 1 and chain_break(lines[::-1], None) is None:
        lines, bf, cf, chains = lines[::-1], None, None, True
    return PageRead(n, lines, bf, cf, bank=(ans or {}).get("bank"), account_last4=(ans or {}).get("account_last4"),
                    chains=chains, read_by=model, account_name=(ans or {}).get("account_name"),
                    holders=[h for h in (ans or {}).get("holders") or [] if isinstance(h, str) and h],
                    postcode=((ans or {}).get("postcode") or None), currency=currency_of((ans or {}).get("currency")))


# A page with this much text has a text layer: its own text is read (exact digits, much faster than a picture)
TEXT_PAGE = 200


def _printed(a: float, text: str) -> bool:
    """The amount on the page as banks print it: 1234.56, 1,234.56 or 1 234.56 (Revolut)."""
    s = f"{a:,.2f}"
    if any(x in text for x in (f"{a:.2f}", s, s.replace(",", " "), s.replace(",", " "), s.replace(",", " "))):
        return True
    # A whole amount printed without pence ('1000', '1,000')
    if a == int(a):
        w = f"{int(a):,}"
        return any(re.search(rf"(?<![\d.,]){re.escape(x)}(?![\d]|[.,]\d)", text) for x in {str(int(a)), w, w.replace(",", " ")})
    return False


PERIOD = re.compile(r"from\W{0,4}(\d{1,2})/(\d{1,2})/(\d{4})\W{0,10}to\W{0,4}(\d{1,2})/(\d{1,2})/(\d{4})", re.I)


def period_of(texts: List[Optional[str]]) -> Optional[Tuple[str, str]]:
    """The period a statement says it covers ('From 01/04/2025 To 31/03/2026'), from any page's text."""
    for t in texts:
        m = PERIOD.search(t or "")
        if m:
            d1, m1, y1, d2, m2, y2 = m.groups()
            return f"{y1}-{int(m1):02d}-{int(d1):02d}", f"{y2}-{int(m2):02d}-{int(d2):02d}"
    return None


def into_period(reads: List[PageRead], period: Optional[Tuple[str, str]]) -> int:
    """Lines dated outside the statement's own period put in it when their day and month fit only one year of it (an
    online download prints '31 Mar' with no year: a page read alone guesses the year). Returns how many moved."""
    if not period:
        return 0
    a, b = period
    moved = 0
    for p in reads:
        for l in p.lines:
            if not l.on or len(l.on) != 10 or a <= l.on <= b:
                continue
            fits = [f"{y}{l.on[4:]}" for y in range(int(a[:4]), int(b[:4]) + 1) if a <= f"{y}{l.on[4:]}" <= b]
            if len(fits) == 1:
                l.on = fits[0]
                moved += 1
    return moved


def as_printed(p: PageRead, text: str) -> PageRead:
    """A text page's amounts held to its own text: an amount not printed on the page whose hundredth is (the reader
    dropped the pence point: '500.00' read as 50000) is put back to what is printed."""
    for l in p.lines:
        for attr in ("money_in", "money_out"):
            a = getattr(l, attr)
            if a and not _printed(a, text) and _printed(round(a / 100, 2), text):
                setattr(l, attr, round(a / 100, 2))
    return p


# A document's reading stops starting new pages after this long (seconds): when the AI service is slow, one scanned
# statement must not hold up the whole return. Pages not read are marked to check, the rest carries on
TIME_LIMIT = 600


def read_pages(pages: List[Any], threads: int = 4, texts: Optional[List[Optional[str]]] = None,
               time_limit: float = TIME_LIMIT) -> List[PageRead]:
    """Every page read. A page with a text layer is read from its text first; a scan, or a text reading that does not
    chain, is read as a picture; a picture reading that does not chain is read again by the second model (the reading
    that chains is kept). A page's picture may be given as a function, made only when it is needed. Past the time
    limit no new page is started (PageRead.skipped)."""
    import time
    texts = texts or [None] * len(pages)
    picture = lambda i: pages[i]() if callable(pages[i]) else pages[i]
    deadline = time.monotonic() + time_limit
    late = lambda: time.monotonic() > deadline

    def first(i: int) -> PageRead:
        if late():
            return PageRead(i + 1, [], None, None, skipped=True)
        t = texts[i] if i < len(texts) else None
        if t and len(t.strip()) >= TEXT_PAGE:
            p = as_printed(_page(i + 1, _ask_text(t, vision.READER), f"{vision.READER} (text)"), t)
            if p.lines and p.chains:
                return p
        img = picture(i)
        return _page(i + 1, _ask(img, vision.READER) if img else None, vision.READER)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        out = list(pool.map(first, range(len(pages))))
    for k, p in enumerate(out):
        if p.lines and not p.chains and not late():
            img = picture(k)
            again = _page(p.page, _ask(img, vision.CHECKER), vision.CHECKER) if img else None
            if again and again.lines and again.chains:
                out[k] = again
    misread_brought_forward(out)
    return out


def misread_brought_forward(out: List[PageRead]) -> int:
    """A page whose lines all add up but whose brought forward does not, when the page opens at the page before's
    closing balance: the brought forward was misread, not a line lost (nothing is missing between the two pages), so
    the page is not held. Returns how many pages were put right."""
    fixed, closing = 0, None
    for p in out:
        if p.lines and not p.chains and chain_break(p.lines, None) is None:
            opening = opening_of(p.lines)
            if closing is not None and opening is not None and abs(opening - closing) < 0.005:
                p.brought_forward, p.chains = opening, True
                fixed += 1
        printed = [l.balance for l in p.lines if l.balance is not None]
        closing = printed[-1] if printed else (p.carried_forward if p.carried_forward is not None else closing)
    return fixed


def assemble(reads: List[Tuple[Optional[int], PageRead]]) -> Account:
    """An account's pages from every file, (doc_id, page): duplicates dropped, in date order, chained across pages."""
    acc = Account()
    seen, pages = set(), []
    for doc_id, p in reads:
        if not p.lines:
            continue
        key = (p.brought_forward, p.carried_forward, p.lines[0].on)
        # The same page in two files (a report saved twice under two names, with no balances printed to tell them by):
        # every line the same is a copy, counted once
        same = ("lines",) + tuple((l.on, round(l.money_in, 2), round(l.money_out, 2), (l.description or "").strip().lower())
                                  for l in p.lines)
        if (p.brought_forward is not None and key in seen) or (len(p.lines) >= 2 and same in seen):
            acc.duplicates += 1
            continue
        seen.add(key)
        seen.add(same)
        for l in p.lines:
            l.doc_id, l.page = doc_id, p.page
        pages.append((p.lines[0].on or "", doc_id or 0, p.page, p))
    pages.sort(key=lambda x: (x[0], x[1], x[2]))
    running: Optional[float] = None
    # A line already counted: the same day, amount and printed balance (the same weeks printed twice in two layouts
    # in one file: two different payments never leave the same balance on the same day)
    counted: set = set()
    line_key = lambda l: (l.on, round(l.money_in or 0, 2), round(l.money_out or 0, 2), round(l.balance, 2))
    for first, doc_id, n, p in pages:
        with_balance = [l for l in p.lines if l.balance is not None]
        again = [l for l in with_balance if line_key(l) in counted]
        if with_balance and len(again) == len(p.lines):
            acc.duplicates += 1                             # the whole page counted already
            continue
        if again:
            p.lines = [l for l in p.lines if l.balance is None or line_key(l) not in counted]
        counted.update(line_key(l) for l in p.lines if l.balance is not None)
        if not p.lines:
            continue
        bf = p.brought_forward
        if running is None:
            acc.opening = bf if bf is not None else (
                round(p.lines[0].balance - p.lines[0].money_in + p.lines[0].money_out, 2) if p.lines[0].balance is not None else None)
        elif bf is not None and abs(bf - running) > 0.005:
            acc.checks.append(f"Page {n} ({first}) starts at £{bf:,.2f} but the page before ends at £{running:,.2f}: "
                              f"a line missing or a balance misread between them.")
        if not p.chains:
            acc.checks.append(f"Page {n} ({first}): the balances do not add up line by line; check its amounts.")
        printed = [l.balance for l in p.lines if l.balance is not None]
        running = printed[-1] if printed else (p.carried_forward if p.carried_forward is not None else running)
        acc.lines.extend(p.lines)
    acc.closing = running
    dates = [l.on for l in acc.lines if l.on]
    acc.first, acc.last = (min(dates), max(dates)) if dates else (None, None)
    return acc


def covers(acc: Account, start: str, end: str) -> List[str]:
    """What is missing at either end of the period (the first statement starts late, the last ends early)."""
    out = []
    if acc.first and acc.first > start:
        out.append(f"The statements start on {acc.first}, after the period starts ({start}): ask for the statement before.")
    if acc.last and acc.last < end:
        out.append(f"The statements end on {acc.last}, before the period ends ({end}): ask for the statement after.")
    return out
