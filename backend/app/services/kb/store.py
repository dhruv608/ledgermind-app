"""The knowledge base in Postgres: law_documents (one row per page, with its full text for small-to-big answers) and
law_chunks (its pieces, each with an embedding as halfvec and an English full-text index). Shared by every
firm: public law only, no client or firm data.

Search is hybrid: the nearest pieces by meaning (HNSW, cosine) and the best by exact words ('CTM61505', 's455',
'Box 6'), merged by reciprocal rank fusion. A page short enough is returned whole for the answer.

law_meta keeps the embedding model and size the vectors were made with: a different setting would put vectors from
two models side by side, so it is refused until everything is embedded again."""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

from backend.app.core.config import settings
from backend.app.services.kb.chunker import Chunk, embed_text
from backend.app.services.kb.embed import embed_documents, embed_query

CANDIDATES = 30         # from each search, before fusion
RRF_K = 60
WHOLE_PAGE_TOKENS = 1500
WRITE_RETRIES = 4
# A page's reference and title as words: a page whose title is the question's subject ('Annual Tax on Enveloped
# Dwellings', 'Homeworking expenses') ranks above busy pages that merely mention its words
TITLE_TSV = "to_tsvector('english', coalesce(ref, '') || ' ' || title)"


def _schema(dims: int) -> List[str]:
    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        """CREATE TABLE IF NOT EXISTS law_meta (key VARCHAR(50) PRIMARY KEY, value TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS law_documents (
               id SERIAL PRIMARY KEY,
               source VARCHAR(30) NOT NULL,            -- HMRC_MANUAL / VAT_NOTICE / GUIDANCE / LEGISLATION
               document VARCHAR(255) NOT NULL,         -- 'Company Taxation Manual'
               ref VARCHAR(100),                       -- 'CTM61505', 'VATA 1994 s30', 'Notice 700 para 4.2'
               title TEXT NOT NULL,
               url TEXT NOT NULL UNIQUE,
               topic VARCHAR(30),                      -- CT / VAT / PAYROLL / CIS / COMPANIES ...
               source_updated TIMESTAMP,               -- when the publisher last changed it
               fetched_at TIMESTAMP NOT NULL DEFAULT now(),
               content_hash CHAR(64) NOT NULL,
               page_text TEXT NOT NULL,
               tokens INTEGER NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS law_chunks (
               id SERIAL PRIMARY KEY,
               document_id INTEGER NOT NULL REFERENCES law_documents(id) ON DELETE CASCADE,
               seq INTEGER NOT NULL,
               heading TEXT NOT NULL,
               text TEXT NOT NULL,
               tokens INTEGER NOT NULL,
               embedding halfvec({dims}) NOT NULL,
               tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', heading || ' ' || text)) STORED)""",
        "CREATE INDEX IF NOT EXISTS law_chunks_embedding ON law_chunks USING hnsw (embedding halfvec_cosine_ops)",
        "CREATE INDEX IF NOT EXISTS law_chunks_tsv ON law_chunks USING gin (tsv)",
        "CREATE INDEX IF NOT EXISTS law_chunks_document ON law_chunks (document_id)",
        "CREATE INDEX IF NOT EXISTS law_documents_topic ON law_documents (topic)",
        f"CREATE INDEX IF NOT EXISTS law_documents_title ON law_documents USING gin ({TITLE_TSV})",
    ]


def embedding_setting() -> Dict[str, object]:
    return {"provider": settings.KB_EMBED_PROVIDER, "model": settings.KB_EMBED_MODEL, "dims": settings.KB_EMBED_DIMS}


def ensure_schema(engine: Engine) -> None:
    """The tables (Postgres only), and the embedding model they hold, checked against the settings."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The knowledge base needs PostgreSQL with pgvector")
    model = embedding_setting()
    with engine.begin() as c:
        for sql in _schema(settings.KB_EMBED_DIMS):
            c.execute(text(sql))
        saved = c.execute(text("SELECT value FROM law_meta WHERE key = 'embedding'")).scalar()
        if saved is None:
            c.execute(text("INSERT INTO law_meta (key, value) VALUES ('embedding', :v)"), {"v": json.dumps(model)})
        elif json.loads(saved) != model:
            raise RuntimeError(f"The knowledge base was embedded with {saved}, the settings say {model}: run "
                               f"backend/scripts/kb_reembed.py before switching")


def _vec(v: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


@dataclass
class Page:
    source: str
    document: str
    ref: Optional[str]
    title: str
    url: str
    topic: Optional[str]
    source_updated: Optional[datetime]
    page_text: str


GONE_PAGE = re.compile(r"\W*(this page has been archived|this is the archival message|this guidance has been withdrawn)",
                       re.I)
EMPTY_TEXT = re.compile(r"\(?this content has been withheld[^)]*\)?|\bcontents\b|"
                        r"this (section|chapter|part) contains the following:?", re.I)


def is_placeholder(page_text: str) -> bool:
    """A page with no law in it: HMRC's archived / withdrawn notices, text withheld under the Freedom of Information
    Act, or a bare contents line. Kept out of the law base, as it only crowds real answers out of a search."""
    if GONE_PAGE.match(page_text or ""):
        return True
    return len(re.sub(r"[\W_]+", "", EMPTY_TEXT.sub("", page_text or ""))) < 20


def save_pages(engine: Engine, items: List[Tuple[Page, List[Chunk]]]) -> Dict[str, int]:
    """Many pages at once: the unchanged ones skipped (same text, no new embedding), the pieces of all the others
    embedded together (100 to a request), then each page written. A page with no law in it is not kept (and taken
    out if an earlier load stored it). Counts of added / updated / unchanged / placeholder pages."""
    counts = {"added": 0, "updated": 0, "unchanged": 0, "placeholder": 0}
    items = list({page.url: (page, chunks) for page, chunks in items}.values())    # one entry per page
    empty = [page.url for page, _ in items if is_placeholder(page.page_text)]
    if empty:
        counts["placeholder"] = len(empty)
        with engine.begin() as c:
            c.execute(text("DELETE FROM law_documents WHERE url = ANY(:u)"), {"u": empty})
        items = [(page, chunks) for page, chunks in items if page.url not in set(empty)]
    if not items:
        return counts
    digests = [hashlib.sha256(p.page_text.encode("utf-8")).hexdigest() for p, _ in items]
    with engine.begin() as c:
        stored = {r.url: (r.id, r.content_hash) for r in c.execute(
            text("SELECT id, url, content_hash FROM law_documents WHERE url = ANY(:u)"), {"u": [p.url for p, _ in items]})}
    todo = []
    for (page, chunks), digest in zip(items, digests):
        if stored.get(page.url, (None, None))[1] == digest:
            counts["unchanged"] += 1
        else:
            todo.append((page, chunks, digest))
    vectors = iter(embed_documents([embed_text(ch) for _, chunks, _ in todo for ch in chunks]))
    rows = [(page, chunks, [next(vectors) for _ in chunks], digest) for page, chunks, digest in todo]
    # The whole batch in one transaction (fewer round trips to the database); a dropped connection rolls it back,
    # so it is simply written again
    for attempt in range(WRITE_RETRIES):
        try:
            with engine.begin() as c:
                ids = {r.url: r.id for r in c.execute(text("SELECT id, url FROM law_documents WHERE url = ANY(:u)"),
                                                      {"u": [page.url for page, *_ in rows]})}
                for page, chunks, vecs, digest in rows:
                    _write(c, page, chunks, vecs, digest, ids.get(page.url))
            break
        except OperationalError:
            if attempt == WRITE_RETRIES - 1:
                raise
            time.sleep(5 * (attempt + 1))
    for page, *_ in rows:
        counts["updated" if page.url in stored else "added"] += 1
    return counts


def _write(c: Connection, page: Page, chunks: List[Chunk], vectors: List[List[float]], digest: str,
           doc_id: Optional[int]) -> None:
    fields = {"s": page.source, "d": page.document, "r": page.ref, "t": page.title, "u": page.url, "tp": page.topic,
              "su": page.source_updated, "h": digest, "p": page.page_text, "k": max(1, len(page.page_text) // 4)}
    if doc_id is None:
        doc_id = c.execute(text(
            "INSERT INTO law_documents (source, document, ref, title, url, topic, source_updated, content_hash, "
            "page_text, tokens) VALUES (:s, :d, :r, :t, :u, :tp, :su, :h, :p, :k) RETURNING id"), fields).scalar()
    else:
        c.execute(text(
            "UPDATE law_documents SET source = :s, document = :d, ref = :r, title = :t, topic = :tp, "
            "source_updated = :su, content_hash = :h, page_text = :p, tokens = :k, fetched_at = now() WHERE id = :id"),
            {**fields, "id": doc_id})
        c.execute(text("DELETE FROM law_chunks WHERE document_id = :id"), {"id": doc_id})
    if chunks:
        c.execute(text(
            "INSERT INTO law_chunks (document_id, seq, heading, text, tokens, embedding) "
            f"VALUES (:id, :n, :h, :t, :k, CAST(:v AS halfvec({settings.KB_EMBED_DIMS})))"),
            [{"id": doc_id, "n": i, "h": ch.heading, "t": ch.text, "k": ch.tokens, "v": _vec(v)}
             for i, (ch, v) in enumerate(zip(chunks, vectors))])


def _any_words(question: str) -> str:
    """The question's words joined by OR for the exact-word search (a question rarely has every word of a page;
    Postgres drops the stop words): 'tax on an overdrawn DLA, s455' -> 'tax | overdrawn | dla | s455'."""
    return " | ".join(dict.fromkeys(w.lower() for w in re.findall(r"[A-Za-z0-9]+", question) if len(w) > 1))


QUESTION_WORDS = {"what", "when", "where", "which", "who", "why", "how", "does", "do", "can", "is", "are", "the", "a",
                  "an", "of", "for", "to", "in", "on", "and", "or", "it", "its", "my", "i", "be", "by", "from", "with",
                  "much", "many", "there", "this", "that", "have", "has", "after", "before", "until", "any"}


def _all_words(question: str) -> str:
    """The question's subject words joined by AND: a piece holding every one of them is very likely on point
    ('approved mileage allowance payments rates' -> EIM31240). Short numbers (the '27' of '2026-27') left out."""
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", question)]
    keep = [w for w in dict.fromkeys(words) if w not in QUESTION_WORDS and (len(w) > 2 or w.isalpha() and len(w) > 1)
            and not (w.isdigit() and len(w) < 3)]
    return " & ".join(keep) if len(keep) >= 2 else ""


DOC_YEAR = re.compile(r"\b(20\d\d) to (20\d\d)\b")
QUESTION_YEAR = re.compile(r"\b(20\d\d)\s*(?:-|/|to)\s*(?:20)?(\d\d)\b")


def tax_year_start(day: Optional[date] = None) -> int:
    day = day or date.today()
    return day.year if (day.month, day.day) >= (4, 6) else day.year - 1


def one_tax_year(ranked: List[int], documents: Dict[int, str], question: str, today: Optional[date] = None) -> List[int]:
    """Yearly pages (rates for '2025 to 2026') kept for one tax year only, so an answer never mixes years or quotes an
    old year's rates: the year the question names, else this tax year (else the latest one found before it)."""
    asked = QUESTION_YEAR.search(question)
    wanted = int(asked.group(1)) if asked and int(asked.group(2)) == (int(asked.group(1)) + 1) % 100 else None
    current = tax_year_start(today)
    years: Dict[str, set] = {}
    for cid in ranked:
        m = DOC_YEAR.search(documents.get(cid) or "")
        if m:
            years.setdefault(DOC_YEAR.sub("", documents[cid]).strip(), set()).add(int(m.group(1)))
    keep = {}
    for family, found in years.items():
        if wanted in found:
            keep[family] = wanted
        else:
            before = [y for y in found if y <= current]
            keep[family] = max(before) if before else min(found)
    out = []
    for cid in ranked:
        m = DOC_YEAR.search(documents.get(cid) or "")
        if m and keep.get(DOC_YEAR.sub("", documents[cid]).strip()) != int(m.group(1)):
            continue
        out.append(cid)
    return out


RERANK_POOL = 30          # pieces the re-ranker reads
RERANK_CHARS = 450        # of each piece


def rerank(question: str, pieces: List[Tuple[int, str, str]]) -> List[int]:
    """The pieces (id, reference and title, text) in order of how well each answers the question, as an AI model
    reading them judges; the search's own order where it gives no answer (or the model is not reachable)."""
    from backend.app.core.bedrock import bedrock_ai
    listing = "\n".join(f"[{i}] {head}: {' '.join(body.split())[:RERANK_CHARS]}" for i, (_, head, body) in enumerate(pieces))
    prompt = ("You rank UK tax and accounting law extracts for a question. Read every extract, then list the numbers "
              "of those that answer the question, best first: the extract that states the rule or figure asked for, "
              "for the current law (not an old year's table or a passing mention). Reply with the numbers only, as a "
              f"JSON list, at most 10.\n\nQuestion: {question}\n\nExtracts:\n{listing}")
    try:
        raw, _ = bedrock_ai.invoke_model_reporting(prompt, model_id=settings.ASSISTANT_MODEL, max_tokens=200,
                                                   temperature=0)
        picked = [int(n) for n in re.findall(r"\d+", raw[raw.find("["):raw.rfind("]") + 1] if "[" in raw else raw)]
    except Exception:
        picked = []
    order = [pieces[i][0] for i in dict.fromkeys(picked) if 0 <= i < len(pieces)]
    return order + [cid for cid, *_ in pieces if cid not in order]


def search(engine: Engine, question: str, k: int = 8, topics: Optional[Sequence[str]] = None,
           reranked: bool = False) -> List[Dict]:
    """The k best pieces for a question: meaning and exact words together (reciprocal rank fusion), each with its
    page; the whole page when it is short (small-to-big). reranked: an AI model reads the best 30 and orders them
    (a few seconds and a small model call: for the assistant's answers, not bulk checks)."""
    q = _vec(embed_query(question))
    where = "AND d.topic = ANY(:topics)" if topics else ""
    params = {"q": q, "n": CANDIDATES, "text": _any_words(question) or "''", "all": _all_words(question),
              "topics": list(topics or [])}
    with engine.begin() as c:
        c.execute(text("SET LOCAL hnsw.ef_search = 100"))
        by_meaning = [r.id for r in c.execute(text(
            f"SELECT ch.id FROM law_chunks ch JOIN law_documents d ON d.id = ch.document_id WHERE true {where} "
            f"ORDER BY ch.embedding <=> CAST(:q AS halfvec({settings.KB_EMBED_DIMS})) LIMIT :n"), params)]
        by_words = [r.id for r in c.execute(text(
            f"SELECT ch.id FROM law_chunks ch JOIN law_documents d ON d.id = ch.document_id "
            f"WHERE ch.tsv @@ to_tsquery('english', :text) {where} "
            f"ORDER BY ts_rank_cd(ch.tsv, to_tsquery('english', :text)) DESC LIMIT :n"), params)]
        # Every subject word in one piece
        by_all = [r.id for r in c.execute(text(
            f"SELECT ch.id FROM law_chunks ch JOIN law_documents d ON d.id = ch.document_id "
            f"WHERE ch.tsv @@ to_tsquery('english', :all) {where} "
            f"ORDER BY ts_rank_cd(ch.tsv, to_tsquery('english', :all)) DESC LIMIT :n"), params)] if params["all"] else []
        # Pages whose reference / title carry the question's words, each by its best piece for the question
        by_title = [r.id for r in c.execute(text(
            f"WITH docs AS (SELECT d.id, ts_rank_cd({TITLE_TSV.replace('ref', 'd.ref').replace('title', 'd.title')}, "
            f"to_tsquery('english', :text), 1) AS r FROM law_documents d "
            f"WHERE {TITLE_TSV.replace('ref', 'd.ref').replace('title', 'd.title')} @@ to_tsquery('english', :text) {where} "
            f"ORDER BY r DESC LIMIT :n) "
            f"SELECT best.id FROM docs JOIN LATERAL (SELECT ch.id FROM law_chunks ch WHERE ch.document_id = docs.id "
            f"ORDER BY ts_rank_cd(ch.tsv, to_tsquery('english', :text)) DESC LIMIT 1) best ON true "
            f"ORDER BY docs.r DESC"), params)]
        score: Dict[int, float] = {}
        for ranking in (by_meaning, by_words, by_all, by_title):
            for rank, cid in enumerate(ranking):
                score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        ranked = sorted(score, key=score.get, reverse=True)[:max(k * 4, RERANK_POOL if reranked else 0)]
        if not ranked:
            return []
        documents = {r.id: r.document for r in c.execute(text(
            "SELECT ch.id, d.document FROM law_chunks ch JOIN law_documents d ON d.id = ch.document_id "
            "WHERE ch.id = ANY(:ids)"), {"ids": ranked})}
        kept = one_tax_year(ranked, documents, question)
        if reranked and len(kept) > 1:
            pool = kept[:RERANK_POOL]
            heads = {r.id: (f"{r.ref or ''} {r.title}".strip(), r.text) for r in c.execute(text(
                "SELECT ch.id, ch.text, d.ref, d.title FROM law_chunks ch JOIN law_documents d ON d.id = ch.document_id "
                "WHERE ch.id = ANY(:ids)"), {"ids": pool})}
            kept = rerank(question, [(cid, *heads[cid]) for cid in pool if cid in heads]) + kept[RERANK_POOL:]
        best = kept[:k]
        rows = {r.id: r for r in c.execute(text(
            "SELECT ch.id, ch.heading, ch.text, d.document, d.ref, d.title, d.url, d.source, d.topic, "
            "d.source_updated, d.tokens AS page_tokens, d.page_text FROM law_chunks ch "
            "JOIN law_documents d ON d.id = ch.document_id WHERE ch.id = ANY(:ids)"), {"ids": best})}
    out, pages_given = [], set()
    for cid in best:
        r = rows[cid]
        whole = r.page_tokens <= WHOLE_PAGE_TOKENS
        if whole and r.url in pages_given:
            continue                                # the page is already given whole
        pages_given.add(r.url)
        out.append({"heading": r.heading, "text": r.page_text if whole else r.text,
                    "whole_page": whole, "document": r.document, "ref": r.ref,
                    "title": r.title, "url": r.url, "source": r.source, "topic": r.topic,
                    "updated": r.source_updated.date().isoformat() if r.source_updated else None,
                    "score": round(score[cid], 4), "by_meaning": cid in by_meaning, "by_words": cid in by_words})
    return out
