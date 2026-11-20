"""Pieces of a law page cut by its own structure, not by character count.

A page (an HMRC manual section, a notice, an Act's section) is the natural unit: most are short (median ~240
words), so the whole page is one piece and needs no overlap. A long page is split at its headings, then its
paragraphs / list items / table rows, then its sentences, and packed up to TARGET tokens. Only pieces of the same
split page overlap (OVERLAP tokens carried from the end of one piece into the next); a tail under MIN is joined to
the piece before. A table is never cut mid-row: each row carries its column headings, so a piece of a big table
still reads on its own. Every piece starts with its heading path (document > section > sub-heading), embedded with
it, so a short piece keeps its context.

Sizes are settings (tuned with the test questions), in tokens estimated as characters / 4."""

import re
from dataclasses import dataclass
from typing import List, Tuple

from bs4 import BeautifulSoup, NavigableString, Tag

TARGET = 450
MAX = 600
OVERLAP = 60
MIN = 80
SENTENCE = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z(\"'])")
BLOCK_TAGS = {"p", "li", "pre", "blockquote", "dd", "dt"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Block:
    heading: str          # the sub-heading it sits under ('' before the first)
    text: str
    is_heading: bool = False


@dataclass
class Chunk:
    heading: str          # the full heading path, embedded with the text
    text: str
    tokens: int


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _table_rows(table: Tag) -> List[str]:
    """Each row as 'Heading: value | Heading: value' (the header row's labels), so a row reads on its own."""
    rows = table.find_all("tr")
    if not rows:
        return []
    head = [_clean(c.get_text(" ")) for c in rows[0].find_all(["th", "td"])]
    has_head = bool(rows[0].find("th")) or len(rows) > 1
    out = []
    for r in rows[1:] if has_head else rows:
        cells = [_clean(c.get_text(" ")) for c in r.find_all(["th", "td"])]
        if not any(cells):
            continue
        if has_head and len(head) == len(cells):
            out.append(" | ".join(f"{h}: {c}" if h else c for h, c in zip(head, cells) if c))
        else:
            out.append(" | ".join(c for c in cells if c))
    return out


def html_blocks(html: str) -> List[Block]:
    """The page body as blocks in reading order: headings, paragraphs, list items (with their marker) and table
    rows. Navigation and empty elements are left out."""
    soup = BeautifulSoup(html or "", "html.parser")
    blocks: List[Block] = []
    current = ""

    def walk(node: Tag):
        nonlocal current
        for child in node.children:
            if isinstance(child, NavigableString):
                text = _clean(str(child))
                if text and node.name in ("div", "section", "body", "[document]"):
                    blocks.append(Block(current, text))
                continue
            if not isinstance(child, Tag) or child.name in ("script", "style", "nav", "footer"):
                continue
            if child.name in HEADINGS:
                current = _clean(child.get_text(" "))
                if current:
                    blocks.append(Block(current, current, is_heading=True))
            elif child.name == "table":
                blocks.extend(Block(current, row) for row in _table_rows(child))
            elif child.name == "li":
                nested = child.find(["ul", "ol"])
                if nested:
                    nested.extract()
                text = _clean(child.get_text(" "))
                if text:
                    blocks.append(Block(current, f"- {text}"))
                if nested:
                    walk(nested)
            elif child.name in BLOCK_TAGS:
                text = _clean(child.get_text(" "))
                if text:
                    blocks.append(Block(current, text))
            else:
                walk(child)

    walk(soup)
    return blocks


def _sentences(text: str) -> List[str]:
    """A block too long for one piece, in sentences (a very long sentence in fixed slices as a last resort)."""
    parts: List[str] = []
    for s in SENTENCE.split(text):
        while tokens(s) > MAX:
            cut = s.rfind(" ", 0, MAX * 4)
            cut = cut if cut > 0 else MAX * 4
            parts.append(s[:cut])
            s = s[cut:].strip()
        if s:
            parts.append(s)
    return parts


def _tail(text: str) -> str:
    """The last OVERLAP tokens of a piece, from a sentence start where possible, to begin the next one."""
    if tokens(text) <= OVERLAP:
        return text
    start = len(text) - OVERLAP * 4
    nxt = SENTENCE.search(text, start)
    return text[nxt.end():] if nxt and nxt.end() < len(text) else text[text.find(" ", start) + 1:]


def chunk_page(path: str, blocks: List[Block]) -> List[Chunk]:
    """The page's pieces. path: 'Company Taxation Manual > Loans to participators > CTM61505: Charge to tax'."""
    body = [b for b in blocks if b.text]
    if not body:
        return []
    whole = "\n".join(b.text for b in body)
    if tokens(whole) <= MAX:
        return [Chunk(path, whole, tokens(whole))]

    pieces: List[Tuple[str, str]] = []          # (sub-heading, text)
    cur: List[str] = []
    cur_heading = body[0].heading

    def close(carry: bool) -> None:
        nonlocal cur
        if not cur:
            return
        text = "\n".join(cur)
        pieces.append((cur_heading, text))
        cur = [_tail(text)] if carry else []

    for b in body:
        if b.is_heading:
            # A new section of the page: start a fresh piece once the current one is worth keeping
            if sum(tokens(t) for t in cur) >= MIN:
                close(carry=False)
            cur_heading = b.heading
            cur.append(b.text)
            continue
        units = [b.text] if tokens(b.text) <= MAX else _sentences(b.text)
        for u in units:
            if cur and sum(tokens(t) for t in cur) + tokens(u) > TARGET:
                close(carry=True)
                cur_heading = b.heading
            cur.append(u)
    if cur:
        text = "\n".join(cur)
        if tokens(text) < MIN and pieces:
            heading, prev = pieces[-1]
            pieces[-1] = (heading, prev + "\n" + text)          # a short tail joins the piece before
        else:
            pieces.append((cur_heading, text))

    out = []
    for heading, text in pieces:
        full = f"{path} > {heading}" if heading and heading not in path else path
        out.append(Chunk(full, text, tokens(text)))
    return out


def embed_text(chunk: Chunk) -> str:
    """What is embedded for a piece: its heading path, then its text."""
    return f"{chunk.heading}\n\n{chunk.text}"


def page_text(blocks: List[Block]) -> str:
    """The whole page as plain text (sent to the model in full when it is short: small-to-big)."""
    return "\n".join(b.text for b in blocks if b.text)

