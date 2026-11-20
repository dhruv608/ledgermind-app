"""An Act of Parliament from its legislation.gov.uk PDF (the revised text, as downloaded), read into the knowledge
base one section at a time. Used where legislation.gov.uk refuses automated requests.

Each PDF page starts with a header (the Act, 'Part 15 – Accounts and reports' or 'SCHEDULE 8 – Zero-rating', the
date generated, the 'Changes to legislation' notice): it is dropped, and its Part / Schedule tells where the page
belongs (so only the Parts wanted are kept). Sections start '24 Input tax and output tax.'; a number is taken as a
new section only when it follows the one before (a wrapped line beginning '28 days...' is not a section). In a
Schedule the units are its Parts / Groups and numbered paragraphs.

The editors' notes are not law and are left out: 'Textual Amendments', 'Commencement Information' and the like, with
their F1 / C2 / I3 lines, and the F-markers and brackets in the text ('[F2(c) on the importation...]'). Omitted text
('F1(b) . . . . .') is dropped. The table of derivations at the end is not read."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from pypdf import PdfReader

from backend.app.services.kb.chunker import Block, Chunk, chunk_page, page_text
from backend.app.services.kb.store import Page

ACT_HEADER = re.compile(r"\(c\.\s*\d+\)\s*$")
PLACE = re.compile(r"^(Part|PART|SCHEDULE|Schedule)\s+([0-9A-Z]+[A-Z]?)\s+–\s+(.*)$")
CHAPTER = re.compile(r"^Chapter\s+(\S+)\s+–\s+(.*)$")
GENERATED = re.compile(r"^Document Generated:\s*(\d{4}-\d{2}-\d{2})")
NOTICE_START = re.compile(r"^(Changes to legislation:|Status:)")
NOTICE_END = re.compile(r"View outstanding changes\s*$")
NOTE_HEADINGS = {"Textual Amendments", "Modifications etc. (not altering text)", "Commencement Information",
                 "Marginal Citations", "Extent Information", "Editorial Information", "Subordinate Legislation Made",
                 "Prospective", "Annotations:"}
NOTE_LINE = re.compile(r"^[FCIMEXP]\d{1,4}\s")
SECTION = re.compile(r"^(\d{1,4}[A-Z]{0,3})\s+([A-Z“\"'\[].{1,200})$")
SUBSECTION = re.compile(r"^\(\d+[A-Z]*\)\s")
SCHEDULE_PART = re.compile(r"^(PART\s+[IVXLC\d]+[A-Z]?|Group\s+\d+[A-Z]?\b.*)$")
GLUED = re.compile(r"^\[?F(\d{2,7})([A-Z]{0,3})\s+([A-Z“\"'].{1,200})$")
# An editor's note, not a heading: 'Words in s. 2(1)(c) omitted (31.12.2020) by ...', 'S. 3A omitted ...'
NOTE_TEXT = re.compile(r"^(Words?|S{1,2}\.|Sch\.|Schs\.|Pt\.|Pts\.|Para|Definitions?|Cross-heading|Table|Entr(y|ies)|"
                       r"Art\.|Reg\.|Ch\.|Heading)\b|\b(inserted|substituted|omitted|repealed|amended|added|"
                       r"modified|applied|excluded|extended|restricted)\b\s*\(")
FMARK = re.compile(r"\[?F\d{1,4}(?=[\s(\[.,;:“\"'A-Za-z—]|$)")
DOTS = re.compile(r"^[\s(\w)]{0,6}(\.\s?){4,}\s*$")


@dataclass
class ActSource:
    file: str
    document: str            # 'Value Added Tax Act 1994'
    short: str               # 'VATA 1994'
    url: str                 # 'https://www.legislation.gov.uk/ukpga/1994/23'
    topic: str
    parts: Optional[Sequence[str]] = None     # only these Parts ('15', '16'...); None: every Part and Schedule


def _clean(line: str) -> str:
    line = FMARK.sub("", line).replace("[", "").replace("]", "")
    return re.sub(r"\s+", " ", line).strip()


def _lines(path: str) -> Iterator[Tuple[str, str, Optional[str], str]]:
    """(place, chapter, generated date, line) for every line of law text: the page headers dropped, each line with
    the Part / Schedule its page is in. Stops at the table of derivations."""
    reader = PdfReader(path)
    generated = None
    for page in reader.pages[1:]:
        raw = (page.extract_text() or "").split("\n")
        place, chapter, body, in_notice = "", "", [], False
        for i, line in enumerate(raw):
            s = line.strip()
            if i < 8 and not body:
                m = PLACE.match(s)
                if m:
                    place = f"{'Schedule' if m.group(1).lower() == 'schedule' else 'Part'} {m.group(2)}|{m.group(3).strip()}"
                    continue
                if s.startswith("– TABLE OF DERIVATIONS") or "TABLE OF DERIVATIONS" in s:
                    return
                if CHAPTER.match(s):
                    chapter = s
                    continue
                g = GENERATED.match(s)
                if g:
                    generated = g.group(1)
                    continue
                if ACT_HEADER.search(s) or re.fullmatch(r"\d{1,4}", s):
                    continue
                if NOTICE_START.match(s):
                    in_notice = not NOTICE_END.search(s)
                    continue
                if in_notice:
                    in_notice = not NOTICE_END.search(s)
                    continue
            body.append(s)
        for s in body:
            if s:
                yield place, chapter, generated, s


@dataclass
class Unit:
    place: str               # 'Part 15|Accounts and reports' / 'Schedule 8|Zero-rating'
    number: str              # section or schedule paragraph number; '' for a schedule Part / Group heading
    title: str
    lines: List[str]


def _number(n: str) -> int:
    return int(re.match(r"\d+", n).group(0))


def read_units(path: str) -> Tuple[List[Unit], Optional[str]]:
    """The Act's sections (and schedule parts / paragraphs) in order, without the editors' notes."""
    units: List[Unit] = []
    in_note = False
    current: Optional[Unit] = None
    last_section = 0
    last_place = None
    generated = None
    items = list(_lines(path))
    section_at = None                                 # the Part / Chapter of the last section
    for k, (place, chapter, gen, s) in enumerate(items):
        generated = gen or generated
        if place != last_place:
            last_place = place
            if place.startswith("Schedule"):
                last_section = 0                      # paragraphs start again in each Schedule
        nxt = items[k + 1][3] if k + 1 < len(items) else ""
        # A section heading with an editor's marker stuck to its number ('[F8015 Meaning of ...' = F80 + section 15;
        # a note always has a space after its marker): the split that follows on from the section before
        glued = GLUED.match(s)
        if glued and not NOTE_TEXT.search(glued.group(3)):
            digits, suffix, rest = glued.groups()
            options = [int(digits[j:]) for j in range(1, len(digits)) if digits[j] != "0"]
            fits = [n for n in options if last_section <= n <= last_section + 25]
            if fits:
                s = f"{min(fits)}{suffix} {rest}"
        m = SECTION.match(s)
        # A section follows on from the one before; a bigger jump only where a new Chapter or Part starts (the
        # sections between were repealed: CTA 2009 Part 13 goes from s1062 to s1112A)
        # and a step back only where a new Part starts (a Part inserted after repealed ones: CTA 2010 Part 3 s18-34
        # repealed, then Part 3A s18A)
        new_part = section_at is not None and place != section_at[0]
        is_section = bool(m) and not s.rstrip().endswith((",", ";")) and (
            last_section <= _number(m.group(1)) <= last_section + 25
            or (not NOTE_TEXT.search(m.group(2)) and (
                (last_section <= _number(m.group(1)) <= last_section + 1000 and (place, chapter) != section_at)
                or (new_part and last_section - 40 <= _number(m.group(1)) < last_section))))
        if s in NOTE_HEADINGS or NOTE_LINE.match(s):
            in_note = True
            continue
        if in_note:
            # The notes run on until the law text starts again: a section, a subsection, a schedule Part / Group, or
            # a cross-heading over a section
            if not (is_section or SUBSECTION.match(s) or SCHEDULE_PART.match(s)
                    or (SECTION.match(nxt) and not s.endswith((",", ";", ")")) and len(s) < 100)):
                continue
            in_note = False
        if is_section:
            last_section, section_at = _number(m.group(1)), (place, chapter)
            current = Unit(place, m.group(1), _clean(m.group(2)).rstrip("."), [])
            units.append(current)
            continue
        if place.startswith("Schedule") and SCHEDULE_PART.match(s):
            current = Unit(place, "", _clean(s) + (f" {_clean(nxt)}" if nxt.isupper() and len(nxt) < 80 else ""), [])
            units.append(current)
            continue
        if SECTION.match(nxt) and len(s) < 100 and not s.endswith((",", ";")) and not SUBSECTION.match(s):
            continue                                # a cross-heading ('Payment of VAT by taxable persons')
        if current is None or s.isupper() and len(s) < 80:
            continue                                # 'PART I' / 'THE CHARGE TO TAX' titles: in the page header too
        text = _clean(s)
        if text and not DOTS.match(text):
            current.lines.append(text)
    return [u for u in units if u.lines], generated


def _blocks(lines: List[str]) -> List[Block]:
    """Lines joined into the section's subsections and paragraphs: a new block at '(1)', '(a)' and the like."""
    blocks: List[str] = []
    for s in lines:
        if not blocks or re.match(r"^\((\d+[A-Z]*|[a-z]{1,3}|[ivx]+)\)\s", s) or re.match(r"^“[^”]{1,60}”\s", s):
            blocks.append(s)
        else:
            blocks[-1] += " " + s
    return [Block("", b) for b in blocks]


def act_pages(src: ActSource) -> List[Tuple[Page, List[Chunk]]]:
    """The knowledge base pages for an Act: one per section (or schedule part / paragraph), with its link."""
    units, generated = read_units(src.file)
    updated = datetime.fromisoformat(generated) if generated else None
    out = []
    seen: Dict[str, int] = {}
    for u in units:
        kind, number = u.place.split("|")[0].split(" ") if u.place else ("Part", "")
        place_title = u.place.split("|")[1] if "|" in u.place else ""
        if kind == "Part" and src.parts is not None and number not in src.parts:
            continue
        if kind == "Schedule" and src.parts is not None:
            continue                                # with chosen Parts, their schedules are not wanted either
        if kind == "Schedule":
            ref = f"{src.short} Sch {number}" + (f" para {u.number}" if u.number else f" {u.title.split(' ')[0]} {u.title.split(' ')[1]}" if u.title else "")
            url = f"{src.url}/schedule/{number}" + (f"/paragraph/{u.number}" if u.number else "")
        else:
            ref = f"{src.short} s{u.number}"
            url = f"{src.url}/section/{u.number}"
        # A number met twice (a Group's items inside a Schedule): kept apart, each with its own address
        seen[ref] = seen.get(ref, 0) + 1
        if seen[ref] > 1:
            ref = f"{ref} ({seen[ref]})"
        seen[url] = seen.get(url, 0) + 1
        if seen[url] > 1:
            url = f"{url}#{seen[url]}"
        title = u.title or place_title
        blocks = _blocks(u.lines)
        path = f"{src.document} > {kind} {number} ({place_title}) > {ref}: {title}"
        out.append((Page("LEGISLATION", src.document, ref, title, url, src.topic, updated, page_text(blocks)),
                    chunk_page(path, blocks)))
    return out


def summary(pages: List[Tuple[Page, List[Chunk]]]) -> Dict[str, int]:
    return {"pages": len(pages), "chunks": sum(len(c) for _, c in pages),
            "words": sum(len(p.page_text.split()) for p, _ in pages)}
