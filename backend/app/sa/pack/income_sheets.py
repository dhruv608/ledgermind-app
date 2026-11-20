"""The schedule sheets for each source of income: employment, self-employment, property, savings, foreign income
and capital gains."""

from backend.app.sa.pack.style import BOLD, Sheet
from backend.app.sa.pack.law import law_of


def paye(wb, d):
    if not (d["employments"] or d["income"] or d["reliefs"]):
        return
    s = Sheet(wb, "PAYE", d, widths=(16, 30, 12, 18, 16, 14, 30, 10))
    if d["employments"]:
        s.head("", "Employer", "", "PAYE Ref", "Gross Pay", "Tax", "Note", "Doc", "Law")
        for n, e in enumerate(d["employments"], start=1):
            s.row(f"Employer {n} :", e["name"], "PAYE Ref:", e["ref"] or "", e["pay"], e["tax"], e["note"] or "", e["doc_id"],
                  law_of("EMPLOYMENT"))
        s.row("Total", "", "", "", round(sum(e["pay"] for e in d["employments"]), 2),
              round(sum(e["tax"] for e in d["employments"]), 2), bold=True)
        s.gap()
    if d["income"]:
        s.ws.append(["Income"])
        s.ws.cell(s.ws.max_row, 1).font = BOLD
        s.head("Description", "", "", "", "Amount £", "Tax £", "Note", "Doc", "Law")
        for i in d["income"]:
            s.row(i["name"], "", "", "", i["amount"], i["tax"] or None, i["note"], i["doc_id"], i.get("law", ""))
        s.row("Total Income", "", "", "", round(sum(i["amount"] for i in d["income"] if i["counted"]), 2), bold=True)
        s.gap()
    if d["reliefs"]:
        s.ws.append(["Expenses"])
        s.ws.cell(s.ws.max_row, 1).font = BOLD
        s.head("Description", "", "", "", "Paid £", "Gross £", "Note", "Doc", "Law")
        for i in d["reliefs"]:
            s.row(i["name"], "", "", "", i["amount"], i["gross"], i["note"], i["doc_id"], i.get("law", ""))
        s.row("Total Expense", "", "", "", round(sum(i["amount"] for i in d["reliefs"]), 2), bold=True)


def self_employment(wb, d):
    for n, b in enumerate(d["businesses"], start=1):
        s = Sheet(wb, f"SE {b['name']}", d, widths=(42, 10, 16, 16, 16, 40))
        s.row("Business", b["name"], bold=True)
        s.row("Accounts", "Cash basis" if b["cash_basis"] else "Traditional accounting (accruals)")
        s.row("Page", b["page"])
        s.gap()
        s.head("Heading", "SA103F box", "Amount £", "Disallowed £", "Allowed £", "Law")
        for key, h in b["headings"].items():
            if round(h["amount"], 2) or round(h["disallowed"], 2):
                allowed = h["amount"] if h["kind"] == "income" else round(h["amount"] - h["disallowed"], 2)
                s.row(h["label"], h["box"], h["amount"], h["disallowed"] or None, allowed,
                      law_of("TRADE", "DEPRECIATION" if key == "DEPRECIATION" else h["kind"]))
        s.gap()
        s.head("Profit for tax", "", "£")
        rows = [("Income", b["income"]), ("Less costs", -b["costs"]), ("Net profit per accounts", b["accounts_profit"]),
                ("Add: disallowed (incl. depreciation)", b["disallowed"]), ("Less: use of home (flat rate)", -b["use_of_home"]),
                ("Less: mileage (flat rate)", -b["mileage"]), ("Less: capital allowances", -b["capital_allowances"]),
                ("Add: balancing charges", b["balancing_charges"])]
        if b["trading_allowance"]:
            rows = [("Income", b["income"]), ("Less: trading allowance", -b["trading_allowance"]),
                    ("Add: balancing charges", b["balancing_charges"])]
        for label, v in rows:
            if round(v, 2) or label.startswith(("Income", "Net profit")):
                s.row(label, "", round(v, 2))
        s.row("Adjusted profit (loss)", "", b["adjusted_profit"], bold=True)
        if b["losses_used"]:
            s.row("Less: loss brought forward", "", -b["losses_used"])
        s.row("Taxable profit", "", b["taxable_profit"], bold=True)
        if b["loss_cf"]:
            s.row("Loss to carry forward", "", b["loss_cf"])
        if b["cis_deducted"]:
            s.row("CIS deducted by contractors (tax paid)", "", b["cis_deducted"])
        for w in b["warnings"]:
            s.row(w, note=True)
        bs = b.get("balance_sheet")
        if bs:
            s.gap()
            s.head(f"Balance sheet at {bs['period']['end']} (SEF 5)", "", "£")
            for a in bs["assets"]:
                s.row(a["name"], "", a["amount"])
            s.row("Net business assets", "", bs["net_assets"], bold=True)
            c = bs["capital"]
            for label, v in (("Capital at the start (bank balances)", c["opening"]), ("Add: profit from the bank", c["profit"]),
                             ("Add: money put in", c["introduced"]), ("Less: drawings", -c["drawings"]),
                             ("Less: moved to other own accounts", -c["transfers"]), ("Less: loans or HP repaid", -c["loans_repaid"]),
                             ("Add: loans received", -c.get("loans_received", 0.0)),
                             ("Less: VAT paid (net of refunds)", -c.get("vat", 0.0)),
                             ("Less: capital assets bought", -c.get("assets_bought", 0.0)),
                             ("Less: bank lines not sorted yet", -c["unsorted"])):
                if round(v, 2) or label.startswith(("Capital", "Add: profit")):
                    s.row(label, "", round(v, 2))
            s.row("Capital at the end", "", c["closing"], bold=True)
            s.row("Check: capital at the end less net assets", "", bs["difference"], bold=True)
            for n_ in bs["notes"]:
                s.row(n_, note=True)
        if b["items"]:
            s.gap()
            s.head("Item", "Heading", "Amount £", "Disallowed £", "", "Doc")
            for it in b["items"]:
                s.row(it["description"], it["heading"], it["amount"], it["disallowed"] or None, "", it["doc_id"])
        if b["bank"]:
            # The statements' lines on their own sheet, named as the firm names its bank sheets
            k = Sheet(wb, f"Bank {n}", d, widths=(12, 50, 14, 14, 30, 8))
            k.row("Business", b["name"], bold=True)
            k.gap()
            k.head("Date", "Description", "In £", "Out £", "Heading", "Doc")
            for l in b["bank"]:
                k.row(l["on"], l["description"], l["in"] or None, l["out"] or None, l["heading"], l["doc_id"])
            k.row("Total", "", round(sum(l["in"] for l in b["bank"]), 2), round(sum(l["out"] for l in b["bank"]), 2), bold=True)


def property_sheet(wb, d, key="property", title="Property"):
    p = d.get(key)
    if not p:
        return
    s = Sheet(wb, title, d, widths=(40, 12, 16, 16, 16, 30))
    for prop in p["properties"]:
        s.row(f"Property: {prop['name']}" + (f" ({prop['country']})" if prop.get("country") else ""), "Share", prop["share"], bold=True)
        s.ws.cell(s.ws.max_row, 3).number_format = "0%"
        s.head("Heading", "SA105 box", "Whole property £", "Person's share £", "", "Law")
        for key, (label, box, amount) in prop["headings"].items():
            if round(amount, 2):
                s.row(label, box, amount, round(amount * prop["share"], 2), "", law_of("PROPERTY", key))
        s.row("Profit (before finance costs)", "", prop["profit_whole"], prop["profit"], bold=True)
        if prop["items"]:
            s.head("Date", "Description", "Amount £", "Heading", "", "Doc")
            for it in prop["items"]:
                s.row(it["on"], it["description"], it["amount"], it["heading"], "", it["doc_id"])
        s.gap()
    s.head("UK property business (all properties)", "", "£")
    if p["allowance"]:
        s.row("Property allowance instead of expenses", "", p["allowance_used"])
    s.row("Profit (loss) for the year", "", p["before_losses"], bold=True)
    if p["losses_used"]:
        s.row("Less: loss brought forward", "", -p["losses_used"])
    s.row("Taxable property profit", "", p["profit"], bold=True)
    if p["loss_cf"]:
        s.row("Loss to carry forward", "", p["loss_cf"])
    s.row("Residential finance costs for the 20% credit (incl. brought forward)", "", p["finance_costs"])
    if p.get("finance_cf"):
        s.row("Unused finance costs to carry forward", "", p["finance_cf"])


def savings_dividends(wb, d):
    if not (d["savings"] or d["dividends"]):
        return
    s = Sheet(wb, "Savings and dividends", d, widths=(40, 14, 16, 10, 16, 30, 10))
    if d["savings"]:
        s.head("Account", "Tag", "Interest £", "Share", "Taxable £", "Note", "Doc", "Law")
        for a in d["savings"]:
            s.row(a["name"], a["tag"], a["amount"], a["share"], a["taxable"], a["note"], a["doc_id"], a.get("law", ""))
        s.row("Total taxable interest", "", "", "", round(sum(a["taxable"] for a in d["savings"]), 2), bold=True)
        s.gap()
    if d["dividends"]:
        s.head("Payer", "Paid on", "Dividend £", "Share", "Taxable £", "Note", "Doc", "Law")
        for a in d["dividends"]:
            s.row(a["name"], a["paid_on"] or "", a["amount"], a["share"], a["taxable"], a["note"], a["doc_id"], a.get("law", ""))
        s.row("Total dividends", "", "", "", round(sum(a["taxable"] for a in d["dividends"]), 2), bold=True)
    for c in s.ws["D"]:
        if isinstance(c.value, float) and c.row > 3:
            c.number_format = "0%"


def foreign_sheet(wb, d):
    rows = d.get("foreign") or []
    if not rows:
        return
    s = Sheet(wb, "Foreign", d, widths=(10, 30, 26, 14, 14, 14, 14, 14, 40, 8))
    s.head("Country", "Payer", "Kind", "Gross £", "Foreign tax £", "Exempt (10%) £", "Taxable £", "Credit £", "Treaty", "Doc")
    for r in rows:
        s.row(r["country"], r["payer"], r["kind_label"], r["gross"], r["foreign_tax"], r["exempt"] or None, r["taxable"],
              r["credit"] or None, r["treaty"] or ("Deduction instead of credit" if not r["claim"] else ""), r["doc_id"])
    s.row("Total", "", "", round(sum(r["gross"] for r in rows), 2), round(sum(r["foreign_tax"] for r in rows), 2), "",
          round(sum(r["taxable"] for r in rows), 2), round(sum(r["credit"] for r in rows), 2), bold=True)
    for r in rows:
        for n in r["notes"]:
            s.row(n, note=True)


def capital_gains(wb, d):
    cg = d.get("cgt")
    if not cg or not cg["disposals"]:
        return
    s = Sheet(wb, "Capital gains", d, widths=(30, 22, 12, 14, 14, 14, 14, 14, 10))
    s.head("Asset", "Kind", "Contract date", "Proceeds £", "Allowable costs £", "Gain before relief £", "Home relief £", "Gain (loss) £", "Doc")
    for r in cg["disposals"]:
        s.row(r["name"] + ("" if r["in_year"] else " (not this year)"), r["kind_label"] + (" (BADR)" if r["badr"] else ""),
              r["sold"] or "", r["proceeds"], r["allowable"], r["before_relief"], r["relief"] or None, r["gain"], r["doc_id"])
    s.gap()
    m = cg["summary"]
    s.head("Computation", "", "", "£")
    for label, v in (("Gains", m["gains"]), ("Less losses this year", -m["losses"]), ("Net gains", m["net"]),
                     ("Less losses brought forward", -m["losses_bf_used"]), ("Less annual exempt amount", -m["exempt_used"]),
                     ("Chargeable gains", m["chargeable"])):
        s.row(label, "", "", v, bold=label in ("Net gains", "Chargeable gains"))
    for l in m["lines"]:
        s.row(f"{l['name']}: {l['band']}", "", f"{l['rate']:.0%}", l["amount"], "", l["tax"])
    s.row("Capital gains tax", "", "", "", "", m["tax"], bold=True)
    if m["paid_60_day"]:
        s.row("Paid on 60-day returns", "", "", "", "", -m["paid_60_day"])
    if m["loss_cf"]:
        s.row("Losses to carry forward", "", "", m["loss_cf"])
    for n in cg["notes"]:
        s.row(n, note=True)


def property_abroad_sheet(wb, d):
    property_sheet(wb, d, "property_abroad", "Property abroad")
