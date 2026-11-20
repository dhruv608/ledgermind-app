"""The assistant's search_law tool: the public law knowledge base (HMRC manuals, VAT notices, gov.uk guidance, the VAT
Act 1994 and Companies Act 2006), searched by meaning and exact words (services/kb/store.py). The model gets the best
pieces with their references and links, capped in size; the panel shows the same references as the answer's sources.

Company law comes first: with no topic, a question searches everything but the Self Assessment (personal tax) sources,
unless it reads as a personal tax question (a sole trader, a landlord, payments on account...). A company's director's
own tax is personal tax: the model asks with topic SA."""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.core.database import engine

NAME = "search_law"
LABEL = "Searching HMRC manuals, notices and the law"
TOPICS = ("CT", "VAT", "PAYROLL", "CIS", "PROPERTY", "COMPANIES", "ACCOUNTS", "SA")
COMPANY_TOPICS = [t for t in TOPICS if t != "SA"]
# A question that reads as personal tax (Self Assessment) searches the SA sources too
PERSONAL = re.compile(r"self[- ]?assessment|\bsa ?1\d\d\b|sole trader|self[- ]employ|personal allowance|"
                      r"income tax (rate|band)|(higher|basic|additional) rate|payments? on account|child benefit|"
                      r"hicbc|marriage allowance|gift aid|student loan|capital gains|\bcgt\b|landlord|rental income|"
                      r"rent a room|dividend (tax|allowance)|personal savings allowance|class [24] (nic|ni|national)|"
                      r"pension (tax )?relief|tax return|trading allowance|property allowance|foreign income|"
                      r"remittance|private residence|individual", re.I)
RESULTS = 6
MAX_CHARS = 24000            # about 6,000 tokens of law text to the model per search

SPEC = {"toolSpec": {
    "name": NAME,
    "description": ("Search UK tax and company law: HMRC manuals (Company Taxation, Capital Allowances, Business "
                    "Income, VAT Input Tax, VAT Flat Rate Scheme, VAT Construction, Construction Industry Scheme, "
                    "Employment Income (benefits in kind, company cars and vans, beneficial loans, expenses), Property "
                    "Income (rental businesses, repairs v capital, finance costs), National Insurance (Class 1 incl. "
                    "directors, Class 1A, Class 1B), PAYE (employer payments and penalties, employment allowance, "
                    "termination payments), Self Assessment, Self Assessment Claims, Savings and Investment, Capital "
                    "Gains, Pensions Tax, VAT Registration, VAT Partial Exemption, Corporate Finance, Employment "
                    "Status, Partnership, Residence and FIG regime, Double Taxation Relief, Trusts Settlements and "
                    "Estates, National Minimum Wage), VAT notices (incl. 700, 700/12, 700/21, 700/45, 700/64, 706 "
                    "partial exemption, 706/2 capital goods scheme, 708 buildings and construction, 742 land and "
                    "property, 742A option to tax, 709/1 catering, 701/14 food, 701/49 finance, 701/57 health, 700/22 "
                    "MTD for VAT, 731, 732, 733, 735, VAT penalties and interest), Revenue and Customs Briefs, gov.uk "
                    "guidance (also pay employers' PAYE, workplace pensions and auto-enrolment thresholds, Scottish and "
                    "Welsh income tax, ATED, filing Companies House accounts) "
                    "(CT rates, marginal relief, directors' loans, employment allowance, employer rates, CIS 340 and "
                    "the CIS contractor / subcontractor guides; for individuals: income tax rates, payments on "
                    "account, Child Benefit charge, Marriage Allowance, savings and dividend tax, pension relief, Gift "
                    "Aid, student loans, self-employed expenses, simplified expenses, cash basis, Class 2 / 4 NIC, "
                    "trading and property allowances, rental income and finance cost relief, Rent a Room, foreign "
                    "income, Capital Gains Tax), and the Acts: "
                    "VAT Act 1994, Companies Act 2006, Corporation Tax Acts 2009 and 2010 (incl. s455 loans to "
                    "participators, small profits rate s18A), Capital Allowances Act 2001, ITEPA 2003, ITTOIA 2005, "
                    "Income Tax Act 2007, TCGA 1992, TMA 1970, SSCBA 1992, Finance Acts 2025 and 2026 (this year's "
                    "rate changes); the standards FRS 102 and FRS 105 paragraph by paragraph; and the LedgerMind "
                    "FRS 102 rulebook (140 accounting rules in plain words: recognition, measurement, Section 1A small "
                    "company disclosures, size thresholds). Returns the most relevant passages with their reference "
                    "(e.g. CTM61505, VATA 1994 s30, Notice 700 s4, FA-001, FRS 102 s17) and link. "
                    "Use it for every question about a rule, a rate, a relief or what the law says."),
    "inputSchema": {"json": {"type": "object", "properties": {
        "query": {"type": "string", "description": "The question in plain words, with any reference or term that "
                                                   "matters, e.g. 'when is s455 tax repaid after the loan is repaid'"},
        "topic": {"type": "string", "description": "Only when the question is clearly one area: CT, VAT, PAYROLL "
                                                   "(employment income, benefits, PAYE), CIS, PROPERTY, COMPANIES, ACCOUNTS (FRS 102 "
                                                   "accounting treatment and disclosure) or SA (an individual's own tax: "
                                                   "Self Assessment, a sole trader, a landlord, a director's dividends "
                                                   "and salary on their personal return, CGT for individuals)"},
    }, "required": ["query"]}}}}


def search_law(query: str, topic: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """(what the model is told, the sources for the panel)."""
    from backend.app.services.kb.store import search
    query = (query or "").strip()
    if not query:
        return {"error": "Give the question to search for."}, []
    if topic and topic.upper() in TOPICS:
        topics = [topic.upper()]
    else:
        # Company law first: the Self Assessment sources only for a question about an individual's own tax
        topics = None if PERSONAL.search(query) else COMPANY_TOPICS
    try:
        # Re-ranked: an AI model reads the best 30 and puts the ones that answer first (right page in the top 3 for
        # 91% of the test questions, against 74% without; backend/scripts/kb_search_score.py)
        hits = search(engine, query, k=RESULTS, topics=topics, reranked=True)
        if not hits and topics:
            hits = search(engine, query, k=RESULTS, reranked=True)          # the topic was too narrow: everything
    except Exception as e:
        return {"error": f"The law search is not available: {str(e)[:150]}"}, []
    if not hits:
        return {"results": [], "note": "Nothing found in the sources for this. Say so; do not answer from memory."}, []
    # Pieces of the same page together, as one passage and one source
    by_page: Dict[str, Dict[str, Any]] = {}
    for h in hits:
        page = by_page.get(h["url"])
        if page is None:
            by_page[h["url"]] = {**h, "texts": [h["text"]]}
        elif h["text"] not in page["texts"]:
            page["texts"].append(h["text"])
    results, sources, used = [], [], 0
    for h in by_page.values():
        text = "\n...\n".join(h["texts"])[:max(0, MAX_CHARS - used)]
        if not text:
            break
        used += len(text)
        results.append({"ref": h["ref"], "title": h["title"], "source": h["document"], "url": h["url"],
                        "updated": h["updated"], "text": text})
        sources.append({"ref": h["ref"], "title": h["title"], "document": h["document"], "url": h["url"],
                        "updated": h["updated"]})
    return {"results": results}, sources
