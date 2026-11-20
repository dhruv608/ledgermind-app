"""The rules applied to each source and the law each figure is taxed under, and the sheet that lists them."""

from typing import Optional

from backend.app.sa.pack.style import Sheet


# The rules applied to each source, with the law behind them (law references checked against the law knowledge base):
# the 'verified with the law' part of the working paper
RULES = {
    "all": [("R-IN-05", "Documents outside the tax year are kept off the return", "ITA 2007 s4; PIM1010"),
            ("R-IN-07", "Each document's owner checked (NI number first, then the name)", "SOP"),
            ("R-EX-02", "Last year's return or working paper read and compared with this year", "SOP")],
    "employment": [("R-SA102-01", "Only pay and tax in this employment (P60, P45, final payslip to date)", "ITEPA 2003 s62"),
                   ("R-SA102-06", "Compensation on leaving: £30,000 exempt, the rest taxable", "ITEPA 2003 s403; EIM12979"),
                   ("R-SA102-07", "Payrolled benefits not added again from a P11D", "PAYE58701"),
                   ("R-FAM-04", "Tax code suffix: Marriage Allowance (N gives, M receives)", "ITA 2007 s55B")],
    "self_employment": [("R-SA103-03", "Books from the bank on the cash basis (the default): no accruals, plant deducted on entry",
                         "ITTOIA 2005 s25A; BIM70067"),
                        ("R-SA103-10", "CIS deductions from the contractor's statements, on the gross before materials",
                         "FA 2004 s61"),
                        ("R-SA103-12", "Travel: business journeys allowed, commuting not", "BIM37600; EIM31802"),
                        ("R-SA103-13", "Use of home at the flat rate by hours", "ITTOIA 2005 s94H; BIM75010"),
                        ("R-SA103-16", "A VAT-registered trade worked net of VAT", "BIM31525"),
                        ("SEF 5", "Balance sheet from the bank: capital account agrees with the bank", "HS229")],
    "property": [("R-SA105-01", "Rent and costs per property, as received (cash basis)", "ITTOIA 2005 s271A; PIM1051"),
                 ("R-SA105-05", "Mortgage interest is a 20% credit, not a cost", "ITTOIA 2005 s272A, s274A"),
                 ("R-SA105-08", "Repairs allowed, improvements kept as capital", "PIM2030"),
                 ("R-SA105-01", "A year to 31 March is the tax year", "ITTOIA 2005 s275A; PIM1015")],
    "property_abroad": [("Law", "Overseas property in pounds at HMRC's average rate for the year", "BIM39505; HS264"),
                        ("R-SA105-08", "No foreign depreciation", "PIM2030"),
                        ("R-SA106-04", "Foreign tax credit up to the UK tax, as the treaty allows", "HS263; treaty table")],
    "savings": [("R-SAV-01", "ISA interest left out, joint accounts split", "SAIM1080; SAIM9070"),
                ("R-SAV-02", "The interest for this tax year only, from the provider", "ITTOIA 2005 s370")],
    "dividends": [("R-SAV-04", "Dividends from vouchers; dividends paid into the bank with no voucher raised",
                   "ITA 2007 s13A; CTM15205"),
                  ("R-SAV-05", "Dividends inside an ISA or SIPP left out", "SAIM9070")],
    "pensions": [("R-SAV-06", "Pensions from the P60 or the provider", "ITEPA 2003 s566-567"),
                 ("R-SP-02", "The State Pension or a taxable benefit from the DWP letter", "ITEPA 2003 s577")],
    "foreign": [("R-SA106-07", "A foreign tax assessment's income is on the UK return", "ITTOIA 2005 s830; HS261"),
                ("R-SA106-05", "Foreign income time-apportioned when the country's year differs", "HS261"),
                ("R-SA106-02", "Treaty: where only the UK may tax, the foreign tax is reclaimed there", "HS261; treaty table"),
                ("R-SA106-04", "Foreign tax credit: the lower of the foreign tax (treaty rate) and the UK tax", "HS263")],
    "reliefs": [("R-SAV-07", "Relief at source pension payments grossed up, the basic rate band extended", "PTM056120"),
                ("R-SAV-08", "Gift Aid grossed up, the basic rate band extended", "ITA 2007 s414")],
    "cgt": [("R-SA108-01", "Each disposal with its gain or loss and the 60-day report", "HS297; TCGA 1992")],
    "tax": [("R-FAM-05", "Personal allowance taper over £100,000", "ITA 2007 s35"),
            ("R-FAM-03", "Payments on account from HMRC's statement", "TMA 1970 s59A")],
    "class2": [("R-NIC-01", "Voluntary Class 2 offered when profits are under the small profits threshold", "SSCBA 1992 s11")],
}


def rules_sheet(wb, d):
    """The rules applied to this return's sources, with their law."""
    s = Sheet(wb, "Rules and law", d, widths=(18, 14, 62, 34))
    s.head("Source", "Rule", "What was done", "Law")
    present = ["all"]
    present += ["employment"] if d.get("employments") else []
    present += ["self_employment"] if d.get("businesses") else []
    present += ["property"] if d.get("property") and d["property"].get("properties") else []
    present += ["property_abroad"] if d.get("property_abroad") and d["property_abroad"].get("properties") else []
    present += ["savings"] if d.get("savings") else []
    present += ["dividends"] if d.get("dividends") else []
    present += ["pensions"] if d.get("income") else []
    present += ["foreign"] if d.get("foreign") else []
    present += ["reliefs"] if d.get("reliefs") else []
    present += ["cgt"] if (d.get("cgt") or {}).get("disposals") else []
    present += ["tax"] + (["class2"] if d.get("businesses") else [])
    names = {"all": "Every source", "self_employment": "Self-employment", "property_abroad": "Property abroad",
             "cgt": "Capital gains", "tax": "Tax computation",
             "class2": "Class 2 NI", "pensions": "Pensions and other"}
    for key in present:
        for n, (rule, what, law) in enumerate(RULES[key]):
            s.row(names.get(key, key.title()) if n == 0 else "", rule, what, law)


# The law each figure is taxed (or relieved) under, by its source and kind: printed beside every line of the working
# paper so a reviewer sees the document, the amount and the law on one row
LAW = {
    ("EMPLOYMENT", None): "ITEPA 2003 s62 (earnings)", ("EMPLOYMENT", "BENEFIT"): "ITEPA 2003 s63 (benefits)",
    ("PENSIONS", "PENSION"): "ITEPA 2003 s566-567", ("PENSIONS", "STATE_PENSION"): "ITEPA 2003 s577",
    ("PENSIONS", "BENEFIT"): "ITEPA 2003 s660 (taxable benefits)", ("PENSIONS", None): "ITEPA 2003 Part 9",
    ("FOREIGN", None): "ITTOIA 2005 Part 5; ITEPA s575 (foreign pension)",
    ("RELIEFS", "PENSION_RAS"): "FA 2004 s192; ITA 2007 s58 (band extended)", ("RELIEFS", "GIFT_AID"): "ITA 2007 s414",
    ("RELIEFS", None): "ITA 2007 s24",
    ("SAVINGS", "INTEREST"): "ITTOIA 2005 s369", ("SAVINGS", "ISA"): "ITTOIA 2005 s694 (ISA: exempt)",
    ("SAVINGS", None): "ITTOIA 2005 s369", ("DIVIDENDS", None): "ITTOIA 2005 s383",
    ("TRADE", "income"): "ITTOIA 2005 s5 (trade profits)", ("TRADE", "cost"): "ITTOIA 2005 s34 (wholly and exclusively)",
    ("TRADE", "DEPRECIATION"): "ITTOIA 2005 s33 (capital: not allowed)",
    ("PROPERTY", "RENT"): "ITTOIA 2005 s268", ("PROPERTY", None): "ITTOIA 2005 s272 (s34 applied)",
    ("PROPERTY", "RES_FINANCE"): "ITTOIA 2005 s272A (20% credit, s274A)",
    ("PROPERTY", "DOMESTIC_ITEMS"): "ITTOIA 2005 s311A (replacement of domestic items)",
    ("PROPERTY", "CAPITAL"): "ITTOIA 2005 s33 (capital: not allowed)",
}


def law_of(source: str, kind: Optional[str] = None) -> str:
    return LAW.get((source, kind)) or LAW.get((source, None), "")
