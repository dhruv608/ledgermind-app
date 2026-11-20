"""The assistant's answer to one message: the model reads the client's figures through the tools (tools.py), streams
its answer, and ends with follow-up questions (and option buttons when a fact is missing).

Context is kept small: the last few messages as plain text (tool results are never sent again), a running summary
of anything older, and tool results capped by the tools themselves. Tokens and an estimated cost are saved on each
message and on the chat."""

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Tuple

from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core import ai_usage
from backend.app.core.config import settings
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.database import ClientEngagement
from backend.app.services.assistant import actions, law, outputs
from backend.app.services.assistant.tools import LABELS, SPECS, ClientData, run_tool

logger = logging.getLogger(__name__)

RECENT = 10               # messages sent in full; older ones go into the summary
SUMMARY_EVERY = 6         # the summary is brought up to date once this many messages have dropped out of RECENT
MAX_ROUNDS = 8            # model calls in one answer (the last one answers without tools)
MAX_TOKENS = 4000

# Bedrock prices, US$ per million tokens (input, output): the real London rates, kept in one place (core/ai_usage.py)
PRICES = ai_usage.PRICES

FOLLOWUPS = re.compile(r"<followups>(.*?)</followups>", re.S)
OPTIONS = re.compile(r"<options>(.*?)</options>", re.S)
# The message asks for a file: only then may the answer be an Excel or a PDF
FILE_ASKED = re.compile(r"\b(excel|xlsx|spreadsheet|pdf|file|download|export|sheet|workbook|report)\b", re.I)


def cost_of(model: str, tokens_in: int, tokens_out: int) -> float:
    from backend.app.core.ai_usage import cost
    return round(cost(model, tokens_in, tokens_out), 6)


def _client():
    from backend.app.core.s3 import aws_client
    return aws_client("bedrock-runtime", settings.BEDROCK_REGION or settings.AWS_REGION)


def app_rates() -> str:
    """The UK rates and limits (rules/parameters.json, the same ones the app's checks use), one per line. The
    model's own memory of UK rates is often a year or two out of date: these win."""
    from backend.app.services.tax.ct_computation import PARAMETERS_FILE
    try:
        with open(PARAMETERS_FILE, encoding="utf-8") as f:
            params = json.load(f)
    except (OSError, ValueError):
        return ""
    lines = []
    for p in params:
        value = p.get("Value")
        if value in (None, ""):
            continue
        extra = "; ".join(str(p[k]) for k in ("Effective From", "Notes") if p.get(k))
        lines.append(f"- {p.get('Description')}: {value}{f' ({extra[:120]})' if extra else ''}")
    # Earlier years, for periods before the current figures (the app's payroll checks use these too)
    lines += ["- Before 6 April 2025: employer NI 13.8%, secondary threshold £9,100, employment allowance £5,000",
              "- From 6 April 2025: employer NI 15%, secondary threshold £5,000, employment allowance £10,500 "
              "(no £100,000 employer NI limit any more)"]
    # Personal tax by tax year (the Self Assessment rates the app uses, sa/parameters/rates.json)
    try:
        from backend.app.sa.engine.calc import RATES
        for year in sorted(y for y in RATES if not y.startswith("_"))[-2:]:
            r = RATES[year]
            d, c2, sl, cgt = r["dividend_rates"], r["class2"], r["student_loan"], r["cgt"]["periods"][-1]
            plans = ", ".join(f"{k.replace('_', ' ').title()} £{v:,}" for k, v in sl.items() if k.startswith("PLAN"))
            lines.append(f"- {year} personal tax: personal allowance £{r['personal_allowance']:,}, basic band "
                         f"£{r['basic_band']:,}, dividends {d['basic']:.2%} / {d['higher']:.2%} / {d['additional']:.2%}, "
                         f"Class 2 £{c2['weekly']} a week (small profits threshold £{c2['small_profits_threshold']:,}), "
                         f"student loans {plans}, CGT exempt £{r['cgt']['exempt']:,}, BADR {cgt['badr']:.0%}, "
                         f"mileage {r['mileage']['car_first'] * 100:.0f}p / {r['mileage']['car_after'] * 100:.0f}p")
    except (ImportError, KeyError, TypeError):
        pass
    return "\n".join(lines)


# The page the user is on (the client page's ?tab= and ?area=), so "this" in a question means what is on screen
TABS = {"review": "All points (every review point)", "journals": "Journals", "queries": "Queries (questions for the client)",
        "data": "Files (what is in the client's files and what is missing)", "setup": "Client details",
        "books": "Books (a bank-only client's bank lines)", "accounts": "Accounts (the TB and its mapping, GL scrutiny)",
        "inputs": "VAT & payroll (VAT returns, payroll report)", "recs": "Balance sheet (each account against what it agrees to)",
        "workbook": "Workbook"}
AREAS = {"opening": "Opening balances", "bank": "Bank and cash", "sales": "Sales and debtors",
         "purchases": "Purchases and creditors", "payroll": "Net wages and payroll", "vat": "VAT",
         "accruals": "Accruals and prepayments", "fixed": "Fixed assets", "stock": "Stock", "loans": "Loans and HP",
         "dla": "Director's loan and dividends", "tax": "Corporation tax", "coding": "Coding review (re-analysis, mispostings)",
         "reanalysis": "Coding review (re-analysis)", "mispostings": "Coding review (mispostings)", "general": "General checks"}


def page_line(context: Optional[Dict[str, Any]]) -> str:
    """'The user is on the VAT area page ...', or '' when the page is not known."""
    tab, area = (context or {}).get("tab"), (context or {}).get("area")
    if tab == "area" and area in AREAS:
        return (f"The user is on the {AREAS[area]} area page (its balances against what they should be, its points, "
                f"its transactions, evidence, queries and notes). 'This', 'here' or 'the difference' in a question "
                f"means this area: look at its accounts and points first.")
    if tab in TABS:
        return f"The user is on the {TABS[tab]} tab: 'this' or 'here' in a question means what that tab shows."
    return ""


def system_prompt(engagement: Optional[ClientEngagement], summary: Optional[str],
                  context: Optional[Dict[str, Any]] = None) -> str:
    client = (f"The open client is {engagement.client_name}, year end {engagement.period_end_date:%d/%m/%Y}, "
              f"books from {engagement.source_system}." if engagement else
              "No client is open: answer general questions, and ask the user to open a client for its figures.")
    text = f"""You are LedgerMind Assistant, built into LedgerMind, a UK year-end working papers app used by firms of
accountants. You help the accountant with the open client's figures and with UK accounting and tax.

{client} Today is {date.today():%d/%m/%Y}. {page_line(context) if engagement else ""}

Rules:
- Figures come ONLY from the tools. Never make up or estimate a number, a date, a name or an account code. Quote an
  account code, period or ref only when a tool result shows it, exactly as shown. If a tool does not have it, say so
  and say which file or screen would give it.
- Do not list possible causes in general terms when the tools can show the actual cause: look at the ledger lines
  (account_transactions) or the review points first, then say what you found.
- Call the tools you need before answering (several at once when useful). Search with words the client would use.
- Costs in the wrong account (a merchant, a reclass, re-analysis, mispostings): read coding_review first; it has the
  lines, totals and the account each should be in.
- Money is pounds sterling: write £12,400.00. Balances in the tools say Dr / Cr or what they are in words ("owed to
  HMRC", "due from HMRC"): keep that meaning exactly. A Dr on a liability account means it is the other way round
  (e.g. VAT Dr = a repayment due from HMRC). Never write a minus sign on a figure (no "£-3,263.21").
- Look up only what the question needs: usually one to three tool calls.
- Write for an accountant: short and plain, the answer first, then the detail. Use a small table for several figures.
  No long introductions, no repeating the question.
- Explaining a review point or a difference: three short parts, in this order: **Issue** (what is wrong, one line),
  **Detail** (the figures that show it, from the tools), **Action** (the one thing to do: the journal, the document
  to ask for, or why it can be cleared).
- Never say a thing has been done, posted, approved or saved unless a tool result says so.
- Name where a figure comes from: the account, the review point ref (e.g. U-PAY-007) or the workbook tab (e.g. F3).
- UK tax, VAT and company law questions (a rule, a rate, a relief, what is allowed): ALWAYS call search_law first
  and answer ONLY from the passages it returns. Cite every point with its reference as a link, exactly as given:
  [CTM61505](its link), [VATA 1994 s30](its link), [Notice 700 s4](its link), with the link given in the passage.
  Every reference is a link: never a bare [ITA 2007 s24] without its (link). The answer is written in the chat,
  never only in a file.
  Quote the exact words when they decide the point.
- Rates and limits change each year and the sources hold several years: use the passage for the year the question
  is about (the open client's period unless the user says another year), say which tax year a rate is for, and when
  the year is not clear give each year's figure on its own line. A helpsheet marked "(2025)" is for the 2024-25 tax
  year; a Finance Act's changes apply from the date it gives, not from the Act's year.
- Before relying on a passage, check it is about the same kind of taxpayer and situation as the question: a company
  or an individual (many property and loan rules differ: the finance cost restriction is for individuals, not
  companies), the tax (CT, income tax, VAT), the date. If the passages only cover the other kind, say so.
- Personal tax (an individual's own Self Assessment: a sole trader, a landlord, payments on account, the Child Benefit
  charge, CGT for individuals, a director's dividends and salary on their own return): call search_law with topic SA.
  A company job's questions are about the company: search without a topic (company law first) unless the question is
  about a person's own tax.
- If search_law finds nothing relevant, say "I could not find this in the sources I have (HMRC manuals, VAT
  notices, gov.uk guidance, the VAT Act, Companies Act, Corporation Tax Acts, Capital Allowances Act, ITEPA, the
  income tax Acts (ITTOIA 2005, ITA 2007), TCGA 1992, TMA 1970 and the LedgerMind FRS 102 rulebook)"
  and STOP there. Do not then explain the rule from your own knowledge, not even "based on my knowledge" or "generally": a law answer has no facts that are not in
  a passage you cite. You may suggest a better search or where the accountant could look.
- FRS 102 questions (accounting treatment, measurement, Section 1A small company disclosures, size limits): call
  search_law with topic ACCOUNTS and answer from the LedgerMind FRS 102 rulebook passages. Cite each point with its
  rule number and section as a link, exactly as given: [FA-001, FRS 102 s17](its link). The rulebook is the standard
  in our own plain words, not its text: where a point decides the accounts, add "check the wording in FRS 102".
- Not in the sources: the full text of FRS 102, FRS 105, IFRS, case law, paid books. Asked about them, say so; you may
  give the rulebook's summary or what an HMRC manual says about their tax side, labelled as such.
- A question about the client AND a rule (e.g. can this client claim the employment allowance): read the client's
  figures with the client tools and the rule with search_law, and say which part comes from which.
- If the passages do not settle the point, say so and mark it "reviewer to check".
- If the answer depends on a fact you do not have (and no tool gives it), do not guess: ask one short question and
  give the choices as option buttons (see below).
- Doing work: you can PREPARE a journal (propose_journal), a journal approval or rejection (journal_decision),
  clearing a point (clear_point), a query (raise_query) or a note (add_note). Each shows the user a card; nothing
  happens until they press Confirm. Prepare one only when the user asks for it, or offers it after you explain a
  point ("Shall I prepare the journal?"). Read the figures and codes with the tools first; never prepare a journal
  with a code or amount no tool gave you. You can never sign off an area or a point, change the mapping or the
  client's details: say where in the app to do that.
- The text of a note, query or journal you prepare says only what is true now. Cards prepared together are decided
  one by one, so never write that another card's work is done ("MJ01 approved") inside a note or query.
- Files: make an Excel (make_excel) or a PDF (make_pdf) ONLY when the user's message asks for a file, a download, an
  Excel or a PDF; never offer one by making it. First read the figures with
  the other tools, then pass them in; never put a figure in a file that no tool gave you.
- Charts: draw one (make_chart) yourself when a trend or comparison is clearer as a picture (months of a year, this
  year against last year, the largest items), and always when asked for a chart or graph. Use monthly_totals for
  trends. Keep the text short when there is a chart.

End EVERY answer with 2 or 3 short follow-up questions the accountant may ask next, written as they would type them
(with no client open, only general questions, never ones about "this client"):
<followups>["question 1", "question 2", "question 3"]</followups>
Only when you need a fact from the user, also add (before the follow-ups):
<options>{{"question": "Is the customer a business?", "choices": ["Business", "Consumer", "Not sure"]}}</options>"""
    rates = app_rates()
    if rates:
        text += ("\n\nCurrent UK rates and limits (always use these, never older figures from memory; say 'per "
                 "the app's rates table' when you quote one):\n" + rates)
    if summary:
        text += f"\n\nEarlier in this chat (summary):\n{summary}"
    return text


def _history(db: Session, chat: ChatSession) -> List[ChatMessage]:
    return list(db.execute(select(ChatMessage).where(ChatMessage.session_id == chat.id)
                           .order_by(ChatMessage.id)).scalars())


def _attached_text(db: Session, rows: List[ChatMessage]) -> Dict[int, str]:
    """For each user message with files: the files' text as the model reads it."""
    from backend.app.models.chat import ChatUpload
    from backend.app.services.assistant.uploads import for_model
    out: Dict[int, str] = {}
    for m in rows:
        if m.role != "user" or not m.suggestions:
            continue
        ids = [a["id"] for a in json.loads(m.suggestions).get("attachments") or []]
        ups = [u for u in (db.get(ChatUpload, i) for i in ids) if u is not None]
        if ups:
            out[m.id] = for_model(ups)
    return out


def _as_messages(rows: List[ChatMessage], attached: Optional[Dict[int, str]] = None) -> List[Dict[str, Any]]:
    """Plain text turns, alternating user / assistant as the API needs (a failed answer leaves two user turns).
    attached: the text of files sent with a user message, put before its question."""
    out: List[Dict[str, Any]] = []
    for m in rows:
        text = m.content or ("(no answer)" if m.role == "assistant" else "")
        if attached and m.id in attached:
            text = f"{attached[m.id]}\n\n[Question]\n{text}"
        if m.role == "assistant" and m.suggestions:
            # What became of the cards it prepared, so a later answer knows what was done
            for c in json.loads(m.suggestions).get("actions") or []:
                state = {"DONE": f"confirmed by the user: {c.get('result', '')}", "CANCELLED": "cancelled by the user",
                         "FAILED": f"could not be done: {c.get('result', '')}"}.get(c.get("status"), "not confirmed yet")
                text += f"\n[Card '{c.get('title')}': {state}]"
        if out and out[-1]["role"] == m.role:
            out[-1]["content"][0]["text"] += "\n\n" + text
        else:
            out.append({"role": m.role, "content": [{"text": text}]})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _update_summary(db: Session, chat: ChatSession, rows: List[ChatMessage]) -> Tuple[int, int, str]:
    """Brings the running summary up to date with the messages that have dropped out of RECENT."""
    upto = max(0, len(rows) - RECENT)
    if upto - (chat.summary_upto or 0) < SUMMARY_EVERY:
        return 0, 0, ""
    new = rows[chat.summary_upto or 0:upto]
    text = "\n".join(f"{m.role.upper()}: {(m.content or '')[:1500]}" for m in new)
    prompt = (f"Summary so far:\n{chat.summary or '(none)'}\n\nNew messages:\n{text}\n\nWrite the updated summary of "
              "this chat in at most 150 words: the client facts and figures found, what was decided, and what is "
              "still open. Plain text only.")
    model = settings.ASSISTANT_MODEL
    r = _client().converse(modelId=model, messages=[{"role": "user", "content": [{"text": prompt}]}],
                           inferenceConfig={"maxTokens": 600})
    summary = "".join(b.get("text", "") for b in r["output"]["message"]["content"]).strip()
    if summary:
        chat.summary, chat.summary_upto = summary[:3000], upto
    u = r.get("usage", {})
    return u.get("inputTokens", 0), u.get("outputTokens", 0), model


def _fix_links(text: str, sources: List[Dict[str, Any]]) -> str:
    """A cited reference whose link the model left out or wrote as a placeholder ('[PIM2052](url)'): the real link
    of that source."""
    links = {x["ref"]: x["url"] for x in sources if x.get("ref") and x.get("url")}
    return re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]*\)",
                  lambda m: f"[{m.group(1)}]({links[m.group(1)]})" if m.group(1) in links else m.group(1), text)


def split_extras(text: str) -> Tuple[str, Dict[str, Any]]:
    """The answer without its follow-ups / options blocks, and those blocks read."""
    extras: Dict[str, Any] = {}
    m = FOLLOWUPS.search(text)
    if m:
        try:
            extras["followups"] = [str(q)[:200] for q in json.loads(m.group(1))][:3]
        except ValueError:
            pass
    m = OPTIONS.search(text)
    if m:
        try:
            o = json.loads(m.group(1))
            if o.get("question") and o.get("choices"):
                extras["options"] = {"question": str(o["question"])[:300], "choices": [str(c)[:80] for c in o["choices"]][:5]}
        except (ValueError, AttributeError):
            pass
    clean = OPTIONS.sub("", FOLLOWUPS.sub("", text))
    clean = re.sub(r"<(followups|options)>.*$", "", clean, flags=re.S)     # a block cut off at the end
    return clean.strip(), extras


def _stream_round(client, model: str, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """One model call, streamed: yields {'delta': text} as it writes, then {'end': message, 'stop': ..., 'usage': ...}."""
    kw: Dict[str, Any] = {"modelId": model, "messages": messages, "system": [{"text": system}],
                          "inferenceConfig": {"maxTokens": MAX_TOKENS}}
    if "kimi" not in model.lower():
        kw["inferenceConfig"]["temperature"] = 0.2
    if tools:
        kw["toolConfig"] = {"tools": tools}
    resp = client.converse_stream(**kw)
    blocks: Dict[int, Dict[str, Any]] = {}
    stop, usage = "", {}
    for ev in resp["stream"]:
        if "contentBlockStart" in ev:
            start = ev["contentBlockStart"]
            if "toolUse" in start.get("start", {}):
                t = start["start"]["toolUse"]
                blocks[start["contentBlockIndex"]] = {"tool": {"toolUseId": t["toolUseId"], "name": t["name"]}, "input": ""}
        elif "contentBlockDelta" in ev:
            i, delta = ev["contentBlockDelta"]["contentBlockIndex"], ev["contentBlockDelta"]["delta"]
            if "text" in delta:
                blocks.setdefault(i, {"text": ""})
                blocks[i]["text"] = blocks[i].get("text", "") + delta["text"]
                yield {"delta": delta["text"]}
            elif "toolUse" in delta:
                blocks.setdefault(i, {"tool": {}, "input": ""})["input"] += delta["toolUse"].get("input", "")
        elif "messageStop" in ev:
            stop = ev["messageStop"].get("stopReason", "")
        elif "metadata" in ev:
            usage = ev["metadata"].get("usage", {})
    content = []
    for i in sorted(blocks):
        b = blocks[i]
        if "tool" in b and b["tool"].get("name"):
            try:
                args = json.loads(b["input"] or "{}")
            except ValueError:
                args = {}
            content.append({"toolUse": {**b["tool"], "input": args if isinstance(args, dict) else {}}})
        elif b.get("text"):
            content.append({"text": b["text"]})
    yield {"end": {"role": "assistant", "content": content or [{"text": " "}]}, "stop": stop, "usage": usage}


def answer(db: Session, chat: ChatSession, user_text: str,
           context: Optional[Dict[str, Any]] = None, file_ids: Optional[List[str]] = None) -> Iterator[Dict[str, Any]]:
    """Answers one message, yielding events for the panel: status (a step), delta (answer text), reset (drop the
    text written before a tool call), done (the saved message), error. file_ids: files attached to the question
    (read when they were added): their text goes to the model before the question, their tiles stay on the message."""
    from backend.app.models.chat import ChatUpload
    from backend.app.services.assistant.uploads import upload_json
    engagement = db.get(ClientEngagement, chat.engagement_id) if chat.engagement_id else None
    attached = [u for u in (db.get(ChatUpload, f) for f in (file_ids or [])) if u is not None]
    for u in attached:
        u.session_id = chat.id
    db.add(ChatMessage(session_id=chat.id, role="user", content=user_text[:8000],
                       suggestions=json.dumps({"attachments": [upload_json(u) for u in attached]}) if attached else None))
    if (chat.title or "New chat") == "New chat":
        chat.title = re.sub(r"\s+", " ", user_text).strip()[:80] or "New chat"
    chat.updated_at = datetime.utcnow()
    db.commit()

    rows = _history(db, chat)
    tin = tout = 0
    # Tokens of the other model calls in this answer (the summary, the law search ordering its pages), each at its
    # own model's price; counted once, on the message
    extra_in = extra_out = 0
    extra_usd = 0.0
    try:
        sin, sout, smodel = _update_summary(db, chat, rows)
        if smodel:
            extra_in, extra_out, extra_usd = sin, sout, cost_of(smodel, sin, sout)
    except Exception:
        logger.exception("The chat summary could not be updated")
    start = max(chat.summary_upto or 0, len(rows) - RECENT)
    messages = _as_messages(rows[start:], _attached_text(db, rows[start:]))
    system = system_prompt(engagement, chat.summary if start > 0 else None, context)

    data = ClientData(engagement, db) if engagement else None
    # The client's figures when a client is open; making files and charts always
    tool_specs = (SPECS + actions.SPECS if data is not None else []) + [law.SPEC] + outputs.SPECS
    sources: List[Dict[str, Any]] = []
    client = _client()
    models = [settings.ASSISTANT_MODEL, settings.ASSISTANT_BACKUP_MODEL]
    model, steps, text = models[0], [], ""
    files: List[Dict[str, Any]] = []
    charts: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []          # work prepared for the user to confirm
    use_tools = True
    read_figures = False      # a client or law tool has been read in this answer (charts and files need one first)
    nudged = False
    for rnd in range(MAX_ROUNDS):
        end = None
        candidates = [model] + [x for x in models if x != model]
        for attempt, m in enumerate(candidates):
            try:
                text = ""
                for ev in _stream_round(client, m, system, messages, tool_specs):
                    if "delta" in ev:
                        text += ev["delta"]
                        yield {"type": "delta", "text": ev["delta"]}
                    else:
                        end = ev
                model = m
                break
            except ClientError as e:
                logger.warning("Assistant model %s failed: %s", m, e)
                if text:
                    yield {"type": "reset"}
                    text = ""
                if attempt == len(candidates) - 1:
                    yield {"type": "error", "text": "The AI service did not answer. Please try again in a minute."}
                    return
        u = end["usage"]
        tin, tout = tin + u.get("inputTokens", 0), tout + u.get("outputTokens", 0)
        messages.append(end["end"])
        uses = [b["toolUse"] for b in end["end"]["content"] if "toolUse" in b]
        if (not uses and data is not None and not read_figures and not nudged
                and re.search(r"£\s?\d|\d{1,3},\d{3}|\d+\.\d{2}\b", text)):
            # Figures written with no tool read: the model guessed them. Ask again, from the tools this time
            nudged = True
            yield {"type": "reset"}
            messages.append({"role": "user", "content": [{"text": (
                "Do not answer from memory: that answer has figures no tool gave you. Read the client's figures "
                "with the tools first (for example payroll_by_month, account_balances, account_transactions), "
                "then answer only from what they return.")}]})
            continue
        if not uses or not use_tools:
            break
        if text:
            yield {"type": "reset"}          # 'Let me check...' before the tools: the answer comes after them
        results = []
        for t in uses:
            label = LABELS.get(t["name"]) or actions.LABELS.get(t["name"]) or (law.LABEL if t["name"] == law.NAME else None) \
                or outputs.LABELS.get(t["name"], t["name"])
            hint = next((str(v) for k, v in (t.get("input") or {}).items() if k in ("search", "account", "query") and v), "")
            step = f"{label}{f': {hint}' if hint else ''}"
            steps.append(step)
            yield {"type": "status", "text": step}
            if t["name"] == law.NAME:
                args = t.get("input") or {}
                with ai_usage.collect() as calls:          # the search's own model call (it orders the pages)
                    result, found = law.search_law(args.get("query", ""), args.get("topic"))
                extra_in += sum(c["in"] for c in calls)
                extra_out += sum(c["out"] for c in calls)
                extra_usd += sum(c["usd"] for c in calls)
                # What was found, shown live only (not kept with the answer's steps)
                refs = ", ".join(dict.fromkeys(f["ref"] for f in found))
                yield {"type": "status", "text": f"Found {len(found)} {'page' if len(found) == 1 else 'pages'}: {refs}"
                       if found else "Nothing found in the sources"}
                new = [f for f in found if f["url"] not in {x["url"] for x in sources}]
                sources += new
                if new:
                    yield {"type": "sources", "sources": new}
            elif t["name"] in ("make_excel", "make_pdf") and not FILE_ASKED.search(user_text):
                # The answer belongs in the chat: a file only when the message asks for one
                result = {"error": "The user did not ask for a file: write the answer in the chat. Offer a file in "
                                   "one line at the end if it would help."}
            elif t["name"] in outputs.NAMES and not read_figures:
                # A chart or file holds only figures a tool gave: refused until one has been read
                result = {"error": "Read the figures first with the client or law tools; a chart or file may only "
                                   "hold figures a tool returned in this answer."}
            elif t["name"] in outputs.NAMES:
                result = _make(db, chat, engagement, t["name"], t.get("input") or {}, files, charts)
                if files and t["name"] != "make_chart" and result.get("ok"):
                    yield {"type": "file", "file": files[-1]}
                elif t["name"] == "make_chart" and result.get("ok"):
                    yield {"type": "chart", "chart": charts[-1]}
            elif data is None:
                result = {"error": "No client is open: open a client to read its figures."}
            elif t["name"] in actions.NAMES:
                result, card = actions.prepare(db, engagement, t["name"], t.get("input") or {})
                if card:
                    cards.append(card)
                    yield {"type": "action", "action": card}
            else:
                result = run_tool(t["name"], t.get("input") or {}, data)
            if t["name"] not in outputs.NAMES | actions.NAMES and not (isinstance(result, dict) and result.get("error")):
                read_figures = True
            results.append({"toolResult": {"toolUseId": t["toolUseId"],
                                           "content": [{"json": json.loads(json.dumps(result, default=str))}]}})
        yield {"type": "status", "text": "Reading what it found"}
        if rnd >= MAX_ROUNDS - 2:
            # The last call: no more looking things up, answer with what was found
            use_tools = rnd < MAX_ROUNDS - 2
            results.append({"text": "That is all you can look up for this question. Answer now with what you have "
                                    "found, and say what else could be checked."})
        messages.append({"role": "user", "content": results})
    else:
        text = "I needed more steps than I am allowed for one answer. Please ask a narrower question."
        yield {"type": "delta", "text": text}

    if not text.strip():
        text = "I could not finish this answer. Please ask a narrower question."
        yield {"type": "delta", "text": text}
    # DeepSeek now and then writes its own tool-call markup into the text ("<｜DSML｜function_calls>"): cut it off
    text = re.sub(r"<\s*[｜|]\s*DSML.*$", "", text, flags=re.S).strip() or text
    clean, extras = split_extras(_fix_links(text, sources))
    if files:
        extras["files"] = files
    if charts:
        extras["charts"] = charts
    if cards:
        extras["actions"] = cards
    # The sources shown under the answer: only the ones it cites (none when it found nothing to rely on)
    cited = [x for x in sources if x["url"] in clean or (x["ref"] and x["ref"] in clean)]
    if cited:
        extras["sources"] = cited
    cost = round(cost_of(model, tin, tout) + extra_usd, 6)
    tin, tout = tin + extra_in, tout + extra_out
    msg = ChatMessage(session_id=chat.id, role="assistant", content=clean, steps=json.dumps(steps),
                      suggestions=json.dumps(extras) if extras else None, model=model, tokens_in=tin,
                      tokens_out=tout, cost_usd=Decimal(str(cost)))
    db.add(msg)
    chat.tokens_in = (chat.tokens_in or 0) + tin
    chat.tokens_out = (chat.tokens_out or 0) + tout
    chat.cost_usd = Decimal(str(float(chat.cost_usd or 0) + cost))
    chat.updated_at = datetime.utcnow()
    db.commit()
    yield {"type": "done", "message": message_json(msg)}


def _make(db: Session, chat: ChatSession, engagement: Optional[ClientEngagement], name: str, args: Dict[str, Any],
          files: List[Dict[str, Any]], charts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Runs make_excel / make_pdf / make_chart; what the model is told back is short (the file is in the panel)."""
    client_name = engagement.client_name if engagement else ""
    year_end = engagement.period_end_date if engagement else None
    try:
        if name == "make_chart":
            chart = outputs.check_chart(args)
            if chart is None:
                return {"error": "The chart needs labels and, for each series, one number per label."}
            charts.append(chart)
            return {"ok": True, "note": "The chart is shown above your answer. Do not describe it point by point."}
        title = str(args.get("title") or ("Assistant export" if name == "make_excel" else "Assistant note"))[:120]
        # The client's name once, at the front (the model often puts it in the title too)
        short = re.sub(re.escape(client_name), "", title, flags=re.I).strip(" -·:") if client_name else title
        base = outputs.safe_name(f"{client_name} - {short or title}" if client_name else title, "Assistant")
        if name == "make_excel":
            sheets = [s for s in (args.get("sheets") or []) if isinstance(s, dict)]
            if not sheets or not any(s.get("columns") for s in sheets):
                return {"error": "make_excel needs at least one sheet with columns and rows."}
            f = outputs.save_file(db, chat, outputs.build_excel(title, sheets, client_name, year_end), f"{base}.xlsx", "xlsx")
        else:
            sections = [s for s in (args.get("sections") or []) if isinstance(s, dict)]
            if not sections:
                return {"error": "make_pdf needs at least one section."}
            f = outputs.save_file(db, chat, outputs.build_pdf(title, sections, client_name, year_end), f"{base}.pdf", "pdf")
        files.append(outputs.file_json(f))
        return {"ok": True, "file": f.filename, "note": "The download link is shown to the user. Say in one line what is in it."}
    except Exception as e:
        db.rollback()
        logger.exception("The assistant could not make %s", name)
        return {"error": f"The file could not be made: {str(e)[:150]}"}


def message_json(m: ChatMessage) -> Dict[str, Any]:
    return {"id": m.id, "role": m.role, "content": m.content, "steps": json.loads(m.steps or "[]"),
            "suggestions": json.loads(m.suggestions or "{}"), "model": m.model,
            "tokens": (m.tokens_in or 0) + (m.tokens_out or 0), "cost_usd": float(m.cost_usd or 0),
            "created_at": m.created_at.isoformat() + "Z" if m.created_at else None}
