"""The review sheets: summary, client details, last year, the tax computation, queries, decisions, the evidence map
and the export by SA box."""

import json
from typing import Dict, Optional, Tuple

from backend.app.sa.pack.style import FIRM_QUERIES, Sheet, _money


def summary(wb, d):
    s = Sheet(wb, "Summary", d, widths=(46, 18, 18, 40))
    r = d["result"]
    s.row("Client", d["person"], bold=True)
    s.row("UTR", d["utr"] or "")
    s.row("Tax year", d["tax_year"])
    s.row("Pack", f"{d['kind'].title()} version {d['version']}")
    s.row("Version note", d["note"] or "")
    s.row("Made", d["made"])
    s.gap()
    s.head("Schedule", "Figure", "State", "From")
    for sec in d["sections"]:
        s.row(sec["label"], _money(sec["amount"]), {"done": "Done", "look": "To check", "empty": "No figures"}.get(sec["state"], sec["state"]), sec["from"])
    s.gap()
    s.head("Result", "£")
    for label, key in (("Income tax due", "income_tax_due"), ("Class 4 NIC", "class4"), ("Class 2 NIC", "class2"),
                       ("Capital gains tax", "cgt"), ("Total liability", "liability"), ("Tax deducted at source", "tax_deducted"),
                       ("Balance to pay (refund if negative)", "balance"), ("Each payment on account for next year", "poa_each"),
                       ("Due by 31 January", "due_31_january")):
        if key != "cgt" or r.get("cgt"):
            s.row(label, _money(r.get(key, 0.0)), bold=key in ("balance", "due_31_january"))
    s.gap()
    s.head("Deadline", "Date")
    for label, when in d["deadlines"]:
        s.row(label, when)
    s.gap()
    s.head("Open items", "Number")
    s.row("Blocks open", d["blocks"], bold=bool(d["blocks"]))
    s.row("Client queries open", d["counts"]["client"])
    s.row("Accountant decisions open", d["counts"]["decisions"])


def client_info(wb, d):
    s = Sheet(wb, "Client info", d, widths=(30, 50))
    s.row("Client:", d["person"])
    s.row("Tax year:", d["tax_year"])
    s.row("UTR:", d["utr"] or "")
    s.row("NI number:", d["ni"] or "")
    s.row("Returning client:", "No: first return with us" if d["first_return"] else "Yes")
    s.row("Director of:", d["company"] or "")
    s.row("Kinds of income:", ", ".join(d["sources"]))


def last_year(wb, d):
    s = Sheet(wb, "Last year vs this year", d, widths=(18, 34, 16, 16, 12, 14, 44))
    ly = d["last_year"]
    if not ly["lines"] and not ly["new"]:
        s.row("No working paper from last year: first return with us, or not added.", note=True)
        return
    s.head("Source", "Name", "Last year £", "This year £", "Change %", "Status", "Explanation")
    for l in ly["lines"]:
        change, this = None, l["this_amount"]
        if l.get("group"):
            # One trade split by contract last year: this year's profit and the change once, on the trade's first line
            last = l["group_last"]
            this = this if l.get("group_first") else None
            if l.get("group_first") and last and this is not None:
                change = round((this - last) / abs(last), 4)
        elif l["last_amount"] and this is not None:
            change = round((this - l["last_amount"]) / abs(l["last_amount"]), 4)
        why = "; ".join(x for x in (l["answer"] or l["ended"] or l["note"], l.get("group") if l.get("group_first") else None) if x)
        s.row(l["source_label"], l["name"], l["last_amount"], this, change, l["status_label"] or "", why)
        if change is not None:
            s.ws.cell(s.ws.max_row, 5).number_format = "0%"
    for n in ly["new"]:
        s.row(n["source_label"], n["name"], None, n["amount"], None, "New", "")


def tax_computation(wb, d):
    s = Sheet(wb, "Tax computation", d, widths=(46, 18, 10, 18))
    c, inc = d["calc"], d["inc"]
    s.head("Income", "£")
    for label, key in (("Employment", "employment"), ("Self-employment", "self_employment"), ("UK property", "property"),
                       ("Pensions and benefits", "pensions"), ("Foreign", "foreign"), ("Other", "other"),
                       ("Savings interest", "savings"), ("Dividends", "dividends")):
        if round(inc[key], 2):
            s.row(label, round(inc[key], 2))
    s.row("Total income", c["total_income"], bold=True)
    if inc["reliefs"]:
        s.row("Less reliefs", -inc["reliefs"])
    s.row("Net income", c["net_income"])
    s.row("Adjusted net income", c["adjusted_net_income"])
    s.row("Personal allowance", c["personal_allowance"])
    s.gap()
    s.head("Tax", "On £", "Rate", "Tax £")
    for l in c["lines"]:
        s.row(f"{l['kind'].replace('_', '-').title()}: {l['band']}", l["amount"], l["rate"], l["tax"])
        s.ws.cell(s.ws.max_row, 3).number_format = "0.0%"
    s.row("Income tax", "", "", c["income_tax"], bold=True)
    for k, v in (c.get("reductions") or {}).items():
        if v:
            s.row(f"Less: {k.replace('_', ' ')}", "", "", -v)
    s.row("Income tax due", "", "", c["income_tax_due"], bold=True)
    for label, key in (("Class 4 NIC", "class4"), ("Class 2 NIC", "class2"), ("High Income Child Benefit Charge", "hicbc"),
                       ("Student loan", "student_loan")):
        if c[key]:
            s.row(label, "", "", c[key])
    if c.get("cgt"):
        s.row("Capital gains tax", "", "", c["cgt"])
    s.row("Total liability", "", "", c["liability"], bold=True)
    s.row("Less tax deducted at source (PAYE, CIS)", "", "", -c["tax_deducted"])
    if c.get("cgt_paid"):
        s.row("Less capital gains tax paid on 60-day returns", "", "", -c["cgt_paid"])
    s.row("Balance to pay (refund if negative)", "", "", c["balance"], bold=True)
    s.row("Each payment on account for next year", "", "", c["poa_each"])
    s.row("Due by 31 January", "", "", c["due_31_january"], bold=True)
    for n in d["notes"]:
        s.row(n, note=True)


def queries(wb, d):
    s = Sheet(wb, "Queries", d, widths=(6, 70, 44, 12))
    s.head("No.", "Query", "Answers", "Actioned")
    n = 0
    for q in FIRM_QUERIES:
        n += 1
        s.row(n, q, "", "")
    for q in [i for i in d["queries"] if i["kind"] == "CLIENT"]:
        n += 1
        s.row(n, q["text"] + (" [Block]" if q["block"] else ""), q["answer"] or "", "Yes" if q["status"] == "DONE" else "")


def decisions(wb, d):
    s = Sheet(wb, "Accountant decisions", d, widths=(6, 70, 36, 12, 18))
    s.head("No.", "Decision", "Choice and reason", "Status", "Signed off by")
    for n, q in enumerate([i for i in d["queries"] if i["kind"] == "DECISION"], start=1):
        s.row(n, q["text"] + (" [Block]" if q["block"] else ""), q["answer"] or "", "Done" if q["status"] == "DONE" else "Open", "")
    if s.ws.max_row <= 5:
        s.row("", "None.")


def first_sentence(note: Optional[str]) -> str:
    text = (note or "").strip()
    cut = text.find(". ")
    return (text[:cut + 1] if 0 < cut < 200 else text[:200]).strip()


def outcome(doc, used: bool) -> Tuple[str, str]:
    """(what happened to the document, why): every document sent is accounted for, used or not (R-IN-01: every
    document is read, checked and put on the working paper)."""
    f = json.loads(doc.fields) if doc.fields else {}
    why = first_sentence(doc.note)
    if f.get("other_person"):
        return "Another person's", why or "The document is for someone else: not used."
    if doc.status == "DUPLICATE":
        return "A copy", why or "The same document was sent more than once: counted once."
    if doc.status == "OTHER_YEAR":
        return "Another year", why or "Not this tax year: kept off the return (R-IN-05)."
    if doc.status == "UNREADABLE":
        return "Could not be opened", why or "The file could not be opened: ask for another copy."
    if used:
        return ("Used, to check", why) if doc.status == "CHECK" else ("Used", "")
    if doc.status == "CHECK":
        return "Held for a check", why or "Read, but held for the accountant to confirm before its figures count."
    if doc.kind == "WORKING_PAPER":
        return "Filed", why or ("Last year's working paper: compared with this year." if f else
                                "The firm's own working paper: kept for reference, its figures are not taken as evidence.")
    if doc.status == "FILED":
        return "Filed", why or "Kept with the return: no figure for this year's return in it."
    return "Read, no figure", why or "Read: nothing in it for this year's return."


def evidence(wb, d):
    s = Sheet(wb, "Evidence map", d, widths=(8, 44, 18, 10, 12, 12, 40, 22, 18, 60))
    counts: Dict[str, int] = {}
    for e in d["evidence"]:
        what = (e.get("outcome") or ("", ""))[0]
        counts[what] = counts.get(what, 0) + 1
    if counts and any(counts):
        # Every document sent is on this sheet with what happened to it: nothing is left out unseen
        s.row(f"{len(d['evidence'])} document(s): " + ", ".join(f"{k.lower()} {v}" for k, v in counts.items() if k), bold=True)
        s.gap()
    s.head("Doc", "File", "Kind", "Year", "In year", "Status", "Lines it answers", "Read by", "What happened", "Why")
    for e in d["evidence"]:
        what, why = e.get("outcome") or ("", "")
        s.row(e["id"], e["file"], e["kind"], e["tax_year"] or "", e["in_year"], e["status"], e["answers"], e["read_by"] or "",
              what, why)


def export(wb, d):
    s = Sheet(wb, "Export", d, widths=(12, 8, 56, 18, 40))
    s.head("Form", "Box", "What", "Figure", "Note")
    for p in d["boxes"]["pages"]:
        s.row(p["form"], "", p["title"], bold=True)
        for r in p["rows"]:
            s.row("", r["box"], r["label"], r["value"], r["note"])
    for l in d["boxes"]["left"]:
        s.row(l, note=True)
