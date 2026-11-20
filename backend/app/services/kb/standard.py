"""An accounting standard from its PDF (FRS 102, the FRC's edition) into the knowledge base: every numbered paragraph
(17.32, 1AC.30) under its section ('Section 17 Property, Plant and Equipment'), a page for every few paragraphs so an
answer can cite them ('FRS 102 17.23-17.31'). The page headers ('Financial Reporting Council 37', '38 FRS 102
(September 2024)') are dropped; text before the first paragraph and after the last section (the basis for
conclusions, the appendices) is not a paragraph and is left out."""

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from pypdf import PdfReader

PARA = re.compile(r"^([1-9]\d?[A-Z]{0,2})\.(\d{1,3}[A-Z]{0,2})\s+(.*)$")      # sections 1 to 35
SECTION = re.compile(r"^Section\s+(\d{1,2}[A-Z]?)$")
HEADER = re.compile(r"^(Financial Reporting Council\s+\d+|\d+\s+FRS \d+ \(.*\))$")
PER_PAGE = 12                 # paragraphs on one knowledge base page


@dataclass
class StandardSource:
    file: str
    document: str            # 'FRS 102 The Financial Reporting Standard applicable in the UK and Republic of Ireland'
    short: str               # 'FRS 102'
    url: str
    topic: str


def _lines(texts: Iterable[str]) -> Iterable[str]:
    for text in texts:
        for line in (text or "").split("\n"):
            s = re.sub(r"\s+", " ", line).strip()
            if s and not HEADER.match(s):
                yield s


def paragraphs(texts: Iterable[str]) -> Tuple[Dict[str, str], List[Tuple[str, str, str]]]:
    """({section: title}, [(section, paragraph number, text)]) from the standard's page texts, in order."""
    titles: Dict[str, str] = {}
    out: List[Tuple[str, str, str]] = []
    pending: Optional[str] = None
    for line in _lines(texts):
        if pending is not None:
            titles.setdefault(pending, line[:120])
            pending = None
            continue
        m = SECTION.match(line)
        if m:
            pending = m.group(1)
            continue
        p = PARA.match(line)
        num = f"{p.group(1)}.{p.group(2)}" if p else ""
        if p and not any(s == p.group(1) and n == num for s, n, _t in out):
            out.append((p.group(1), num, p.group(3)))
        elif out:
            sec, num, text = out[-1]
            out[-1] = (sec, num, f"{text} {line}")
    return titles, out


def standard_pages(src: StandardSource) -> List[Tuple[str, str, str, str]]:
    """(ref, title, url, html) for each page: a section's paragraphs, PER_PAGE at a time."""
    reader = PdfReader(src.file)
    titles, paras = paragraphs(p.extract_text() or "" for p in reader.pages)
    by_section: Dict[str, List[Tuple[str, str]]] = {}
    for sec, num, text in paras:
        by_section.setdefault(sec, []).append((num, text))
    pages = []
    for sec, items in by_section.items():
        title = titles.get(sec, "")
        for i in range(0, len(items), PER_PAGE):
            part = items[i:i + PER_PAGE]
            first, last = part[0][0], part[-1][0]
            ref = f"{src.short} {first}" if first == last else f"{src.short} {first}-{last}"
            heading = f"Section {sec} {title}".strip()
            body = "".join(f"<p>{num} {_escape(text)}</p>" for num, text in part)
            # One address per page (pages are stored by address): the section's first page keeps '#section-17',
            # the next ones '#section-17-2', '#section-17-3'
            anchor = f"#section-{sec}" + (f"-{i // PER_PAGE + 1}" if i else "")
            pages.append((ref, heading, f"{src.url}{anchor}", f"<p>{_escape(heading)}</p>{body}"))
    return pages


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
