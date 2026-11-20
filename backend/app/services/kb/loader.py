"""Loads the public sources (rules/kb_sources.json) into the knowledge base through the gov.uk Content API: clean
page bodies with their titles, section references and the date the publisher last changed them (not the web pages,
whose menus, banners and links would be indexed too).

  manuals  walked section by section (child_section_groups); index-only sections (no text) are skipped
  pages    a notice or long guide is split at its numbered sections (h2), each its own page with a link to it;
           a guide in parts gives one page per part; a short page stays whole; a path with {tax_year} (yearly
           rates) is loaded for the two years before this tax year, this one and next once it is published
  collections  a gov.uk collection of helpsheets: each one's newest yearly HTML versions (Self Assessment HS...)
  rulebooks  a LedgerMind rulebook (JSON under data/): one page per rule, with its standard section, and one for the
           thresholds

Every request that fails is logged (path, status), never skipped silently. Pages already loaded with the same text
are not embedded again."""

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.services.kb.acts import ActSource, act_pages
from backend.app.services.kb.chunker import Chunk, chunk_page, html_blocks, page_text
from backend.app.services.kb.store import Page, ensure_schema, save_pages

API = "https://www.gov.uk/api/content"
SITE = "https://www.gov.uk"
SOURCES_FILE = Path(__file__).resolve().parents[2] / "rules" / "kb_sources.json"
ROOT = Path(__file__).resolve().parents[4]          # the project folder (Act PDFs are under data/)
THREADS = 12
BATCH = 400                     # pages saved (and embedded) together
SPLIT_TOKENS = 3000             # a page longer than this is split at its numbered sections
HEADERS = {"User-Agent": "LedgerMind knowledge base loader"}


@dataclass
class LoadLog:
    pages: Dict[str, int] = field(default_factory=lambda: {"added": 0, "updated": 0, "unchanged": 0, "placeholder": 0})
    index_only: int = 0
    removed: int = 0
    chunks: int = 0
    words: int = 0
    failed: List[Tuple[str, str]] = field(default_factory=list)
    by_source: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def note(self, source: str, items: List[Tuple[Page, List[Chunk]]], counts: Dict[str, int]) -> None:
        for k, v in counts.items():
            self.pages[k] += v
        s = self.by_source.setdefault(source, {"pages": 0, "chunks": 0, "words": 0})
        for page, chunks in items:
            words = len(page.page_text.split())
            s["pages"] += 1
            s["chunks"] += len(chunks)
            s["words"] += words
            self.chunks += len(chunks)
            self.words += words


class Fetcher:
    def __init__(self, log: LoadLog):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.log = log

    def get(self, path: str, optional: bool = False) -> Optional[dict]:
        """The page's content; None if it fails (logged), or quietly for an optional page not published yet (404)."""
        for attempt in range(5):
            try:
                r = self.session.get(API + path, timeout=45)
            except requests.RequestException as e:
                err = type(e).__name__
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                err = str(r.status_code)
                time.sleep(2 ** attempt * 2)          # slow down and try again
                continue
            if not (optional and r.status_code == 404):
                self.log.failed.append((path, str(r.status_code)))
            return None
        self.log.failed.append((path, f"gave up after retries ({err})"))
        return None


def _updated(d: dict) -> Optional[datetime]:
    value = d.get("public_updated_at") or d.get("updated_at")
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _children(d: dict) -> List[str]:
    return [c["base_path"] for g in (d.get("details") or {}).get("child_section_groups") or []
            for c in g.get("child_sections") or [] if c.get("base_path")]


def _page(source: str, document: str, ref: Optional[str], title: str, url: str, topic: str,
          updated: Optional[datetime], html: str) -> Tuple[Page, List[Chunk]]:
    blocks = html_blocks(html)
    path = f"{document} > {ref}: {title}" if ref and ref != title else f"{document} > {title}"
    return (Page(source, document, ref, title, url, topic, updated, page_text(blocks)), chunk_page(path, blocks))


def load_manual(engine: Engine, fetch: Fetcher, slug: str, document: str, topic: str, log: LoadLog,
                sections: Optional[List[str]] = None) -> None:
    """Every section of an HMRC manual with text (or only under the top sections listed: 'NIM01000CO'), saved in
    batches as they arrive."""
    root = fetch.get(f"/hmrc-internal-manuals/{slug}")
    if root is None:
        return
    frontier = _children(root)
    if sections:
        frontier = [p for p in frontier if p.rsplit("/", 1)[-1].upper() in sections]
    seen, batch = set(), []
    with ThreadPoolExecutor(THREADS) as pool:
        while frontier:
            todo = [p for p in dict.fromkeys(frontier) if p not in seen]     # a section listed under two parents once
            seen.update(todo)
            frontier = []
            for d in pool.map(fetch.get, todo):
                if not d:
                    continue
                frontier += _children(d)
                body = (d.get("details") or {}).get("body") or ""
                if not BeautifulSoup(body, "html.parser").get_text(strip=True):
                    log.index_only += 1
                    continue
                ref = (d.get("details") or {}).get("section_id") or d["base_path"].rsplit("/", 1)[-1].upper()
                batch.append(_page("HMRC_MANUAL", document, ref, d.get("title", ""), SITE + d["base_path"], topic,
                                   _updated(d), body))
                if len(batch) >= BATCH:
                    log.note(document, batch, save_pages(engine, batch))
                    batch = []
    if batch:
        log.note(document, batch, save_pages(engine, batch))


def _sections(html: str) -> List[Tuple[str, Optional[str], str]]:
    """A page's numbered sections: (heading, anchor, html) at each h2, with any text before the first one."""
    root = BeautifulSoup(html, "html.parser")
    # The body inside a wrapper ('<div class="govspeak">...'): its sections are the wrapper's children
    while True:
        tags = [n for n in root.contents if getattr(n, "name", None)]
        if len(tags) == 1 and tags[0].name == "div" and tags[0].find("h2"):
            root = tags[0]
        else:
            break
    out: List[Tuple[str, Optional[str], List[str]]] = [("", None, [])]
    for node in root.contents:
        if getattr(node, "name", None) == "h2":
            out.append((re.sub(r"\s+", " ", node.get_text(" ")).strip(), node.get("id"), [str(node)]))
        else:
            out[-1][2].append(str(node))
    return [(h, a, "".join(parts)) for h, a, parts in out if BeautifulSoup("".join(parts), "html.parser").get_text(strip=True)]


def tax_year_pages(p: dict, today: Optional[date] = None) -> List[Tuple[str, str, bool]]:
    """A page with {tax_year} in its path (rates for one tax year): (path, ref, optional) for the two years before
    this tax year, this one and next (next is optional: HMRC publishes it shortly before 6 April). Others as given."""
    if "{tax_year}" not in p["path"]:
        return [(p["path"], p["ref"], False)]
    today = today or date.today()
    current = today.year if (today.month, today.day) >= (4, 6) else today.year - 1
    return [(p["path"].replace("{tax_year}", f"{y}-to-{y + 1}"),
             p["ref"].replace("{tax_year}", f"{y}-{str(y + 1)[2:]}"), y > current)
            for y in range(current - 2, current + 2)]


def load_page(engine: Engine, fetch: Fetcher, path: str, ref: str, topic: str, log: LoadLog,
              optional: bool = False) -> None:
    """A notice or guide: split at its numbered sections when long, one page per part for a guide in parts."""
    d = fetch.get(path, optional)
    if d is None:
        return
    if d.get("document_type") == "redirect":
        target = ((d.get("redirects") or [{}])[0]).get("destination")
        log.failed.append((path, f"redirects to {target}: update kb_sources.json"))
        return
    title, updated, details = d.get("title", ""), _updated(d), d.get("details") or {}
    source = "VAT_NOTICE" if "Notice" in ref else "GUIDANCE"
    items: List[Tuple[Page, List[Chunk]]] = []
    if details.get("parts"):
        for part in details["parts"]:
            items.append(_page(source, title, ref, part.get("title", ""), f"{SITE}{path}/{part.get('slug', '')}", topic,
                               updated, part.get("body", "")))
    else:
        body = details.get("body") or ""
        if len(BeautifulSoup(body, "html.parser").get_text(" ")) // 4 <= SPLIT_TOKENS:
            items.append(_page(source, title, ref, title, SITE + path, topic, updated, body))
        else:
            for heading, anchor, html in _sections(body):
                section_ref = (f"{ref} s{m.group(1)}" if (m := re.match(r"^(\d+(?:\.\d+)*)\b", heading)) else ref)
                url = f"{SITE}{path}#{anchor}" if anchor else f"{SITE}{path}"
                items.append(_page(source, title, section_ref, heading or title, url, topic, updated, html))
    for i in range(0, len(items), BATCH):
        log.note(title, items[i:i + BATCH], save_pages(engine, items[i:i + BATCH]))
    # Pages of this source no longer produced (a section HMRC removed, or the whole page now split into sections)
    keep = [page.url for page, _ in items]
    with engine.begin() as c:
        gone = c.execute(text("DELETE FROM law_documents WHERE (url = :base OR url LIKE :parts OR url LIKE :anchors) "
                              "AND NOT (url = ANY(:keep))"),
                         {"base": SITE + path, "parts": SITE + path + "/%", "anchors": SITE + path + "#%", "keep": keep})
        log.removed += gone.rowcount or 0


def load_collection(engine: Engine, fetch: Fetcher, src: dict, log: LoadLog, done: set) -> None:
    """A gov.uk collection of helpsheets: each publication whose title matches `match` (HS222...), its newest `years`
    HTML versions ('HS222 How to calculate your taxable profits (2026)', for the 2025-26 return), each as a page."""
    d = fetch.get(src["path"])
    if d is None:
        return
    for doc in (d.get("links") or {}).get("documents") or []:
        found = re.search(src["match"], doc.get("title", ""))
        path = doc.get("base_path")
        if not found or not path or path in done:
            continue
        done.add(path)
        pub = fetch.get(path)
        if pub is None:
            continue
        versions = [a for a in (pub.get("details") or {}).get("attachments") or []
                    if a.get("attachment_type") == "html" and a.get("url")][:src.get("years", 2)]
        for a in versions:
            year = re.search(r"\((\d{4})\)\s*$", a.get("title", ""))
            ref = f"{found.group(0)} ({year.group(1)})" if year else found.group(0)
            load_page(engine, fetch, a["url"].replace(SITE, ""), ref, src["topic"], log)


def load_all(engine: Engine, only: Optional[List[str]] = None, online: bool = False) -> LoadLog:
    """Every source in kb_sources.json (or only those whose slug / path contains one of `only`); online: only the gov.uk
    manuals and pages (the Acts and rulebooks are files on the machine that loads, not on the server)."""
    ensure_schema(engine)
    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    log, fetch = LoadLog(), None
    fetch = Fetcher(log)
    wanted = lambda key: not only or any(o in key for o in only)
    for m in sources["manuals"]:
        if wanted(m["slug"]):
            load_manual(engine, fetch, m["slug"], m["document"], m["topic"], log, m.get("sections"))
    for p in sources["pages"]:
        for path, ref, optional in tax_year_pages(p):
            if wanted(path):
                load_page(engine, fetch, path, ref, p["topic"], log, optional)
    done: set = set()
    for c in sources.get("collections", []):
        if wanted(c["path"]):
            load_collection(engine, fetch, c, log, done)
    for a in ([] if online else sources.get("acts", [])):
        if wanted(a["file"]) or wanted(a["short"]):
            load_act(engine, ActSource(**a), log)
    for r in ([] if online else sources.get("rulebooks", [])):
        if wanted(r["file"]) or wanted(r["short"]):
            load_rulebook(engine, r, log)
    for s in ([] if online else sources.get("standards", [])):
        if wanted(s["file"]) or wanted(s["short"]):
            load_standard(engine, s, log)
    return log


def load_standard(engine: Engine, src: dict, log: LoadLog) -> None:
    """An accounting standard from its PDF (standard.py), a few numbered paragraphs a page."""
    from backend.app.services.kb.standard import StandardSource, standard_pages
    path = ROOT / src["file"]
    if not path.exists():
        log.failed.append((src["file"], "PDF not found on this machine"))
        return
    items = [_page(src["short"], src["document"], ref, title, url, src["topic"], None, body)
             for ref, title, url, body in standard_pages(StandardSource(str(path), src["document"], src["short"],
                                                                         src["url"], src["topic"]))]
    for i in range(0, len(items), BATCH):
        log.note(src["document"], items[i:i + BATCH], save_pages(engine, items[i:i + BATCH]))


def load_rulebook(engine: Engine, src: dict, log: LoadLog) -> None:
    """A rulebook in our own words (e.g. data/reference/law/ledgermind_frs102_rules.json): each rule its own page,
    referenced by its number and the standard's section ('FA-001, FRS 102 s17'), so an answer can name both."""
    path = ROOT / src["file"]
    if not path.exists():
        log.failed.append((src["file"], "rulebook not found on this machine"))
        return
    book = json.loads(path.read_text(encoding="utf-8"))
    e = lambda v: html.escape(str(v or "").strip())
    items = []
    for r in book.get("rules", []):
        ref = f"{r['id']}, {src['short']} {r['ref']}" if r.get("ref") else r["id"]
        body = "".join(f"<p>{label}: {e(r.get(k))}</p>" for label, k in (
            ("Rule", "rule"), ("What to check", "check"), ("Data used", "data"), ("Small companies (Section 1A)", "small"),
            ("Note", "note")) if r.get(k))
        items.append(_page(src["short"], src["document"], ref, f"{r['area']}: {r['rule'][:80]}",
                           f"{src['url']}#{r['id']}", src["topic"], None,
                           f"<p>{e(src['short'])} {e(r.get('ref'))}, {e(r['area'])} ({e(book.get('basis'))})</p>{body}"))
    if book.get("thresholds"):
        rows = "".join(f"<p>{e(t.get('item'))}: {e(t.get('limit'))}. From: {e(t.get('from'))}. Source: "
                       f"{e(t.get('source'))}</p>" for t in book["thresholds"])
        items.append(_page(src["short"], src["document"], f"{src['short']} thresholds",
                           "Size limits and thresholds (small, micro, audit exemption)", f"{src['url']}#thresholds",
                           src["topic"], None, rows))
    for i in range(0, len(items), BATCH):
        log.note(src["document"], items[i:i + BATCH], save_pages(engine, items[i:i + BATCH]))


def load_act(engine: Engine, src: ActSource, log: LoadLog) -> None:
    """An Act from its PDF (acts.py), section by section."""
    path = ROOT / src.file
    if not path.exists():
        log.failed.append((src.file, "PDF not found on this machine"))
        return
    items = act_pages(ActSource(str(path), src.document, src.short, src.url, src.topic, src.parts))
    for i in range(0, len(items), BATCH):
        log.note(src.document, items[i:i + BATCH], save_pages(engine, items[i:i + BATCH]))
