"""
VAT return review: return reconciliation and box tests (V-xxx test IDs below) for the returns
entered on the VAT returns screen against the ledger's own VAT (the VAT column of each line).

  V-F01  the year's returns cover the whole accounting period: no gaps, no overlaps
  V-F04  each return adds up: Box 3 = Box 1 + Box 2, Box 5 = Box 3 - Box 4; Box 1 / Box 6 and Box 4 / Box 7 sensible
  V-C01  Box 1 per return vs output VAT in the ledger for the same period (reverse charge added, as on the return)
  V-D01  Box 4 per return vs input VAT in the ledger for the same period (reverse charge added)
  V-I03  each difference: correct on the next return (up to £10,000, or 1% of Box 6 up to £50,000) or disclose (VAT652)
  V-F02  Box 6 for the year (time-apportioned) vs turnover in the accounts, within 2%
  V-F03  VAT account at the year end vs returns still unpaid (the same test G9 shows)
  V-B01  not VAT registered while taxable turnover passed the registration threshold in a rolling 12 months
  V-F06  flat rate scheme: the books' standard-rate VAT less the flat-rate returns (the surplus is income)
  V-C06  business gifts with input VAT claimed: over £50 to one person in a year is a deemed supply (output VAT due);
         staff entertainment itself is not restricted (V-D04 blocks client entertaining only)

A difference is not always an error: entries posted to a period after its return was filed show up as one return
over and the next one under. Both are listed so the accountant can see that.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction, TBRecord, VAT100Record
from backend.app.services.review.point_figures import amounts, row, table
from backend.app.services.mapping.chart_lookup import ChartLookup, account_name_keys
from backend.app.services.tax.ct_computation import final_balances, tax_parameters

INCOME_SECTIONS = {"Sales", "Other operating income"}
VAT_CONTROL = 5300
REVERSE_CHARGE_RATE = 0.20
TOLERANCE = 1.0                 # pennies of rounding between ledger and return
CORRECTION_LIMIT = 10000.0      # V-I03: net errors up to £10,000 ...
CORRECTION_PCT, CORRECTION_CAP = 0.01, 50000.0   # ... or 1% of Box 6, capped at £50,000, go on the next return
TURNOVER_TOLERANCE = 0.02       # V-F02: Box 6 within 2% of turnover
FRS_MATERIAL = 100.0            # V-F06: a flat rate surplus below this is rounding (the books already post the flat rate)
GIFT_LIMIT = 50.0               # V-C06: gifts to the same person over £50 in a year (VATA 1994 Sch 4 para 5)
GIFT_WORDS = re.compile(r"\b(gifts?|hampers?|vouchers?|flowers|bouquets?|presents?)\b", re.I)
NOT_GIFTS = re.compile(r"gift ?aid|gift ?(bags?|wrap\w*|tags?|boxes)|cellophane|\bfoil\b|packaging|gift ?cards? sold", re.I)


def _months_back(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@dataclass
class ReturnCheck:
    label: str
    start: date
    end: date
    box1: float
    box4: float
    box5: float
    box6: float
    ledger_output: float = 0.0       # incl. reverse charge
    ledger_input: float = 0.0        # incl. reverse charge
    reverse_charge: float = 0.0
    problems: List[str] = field(default_factory=list)

    @property
    def output_difference(self) -> float:
        return round(self.box1 - self.ledger_output, 2)

    @property
    def input_difference(self) -> float:
        return round(self.box4 - self.ledger_input, 2)

    @property
    def net_error(self) -> float:
        """VAT under-declared to HMRC (+) or over-declared (-) on this return, per the ledger."""
        return round((self.ledger_output - self.box1) - (self.ledger_input - self.box4), 2)

    @property
    def correction(self) -> str:
        limit = max(CORRECTION_LIMIT, min(CORRECTION_CAP, CORRECTION_PCT * self.box6))
        if abs(self.net_error) < TOLERANCE:
            return "agrees"
        return ("correct on the next return (Method 1)" if abs(self.net_error) <= limit
                else "disclose to HMRC on form VAT652 (Method 2)")


@dataclass
class VatFinding:
    test: str
    severity: str
    title: str
    details: str
    amount: float = 0.0
    # The point's figures as a small table for the screen (review/point_figures.py), when known
    figures: Optional[str] = None


@dataclass
class VatReview:
    returns: List[ReturnCheck]
    findings: List[VatFinding]
    ledger_has_vat: bool
    frs_surplus: Optional[float] = None       # flat rate scheme: books' VAT less the flat-rate returns (G9 line)
    after_last: Optional[float] = None        # VAT on ledger lines after the last return to the year end (owed +)
    year_start: Optional[date] = None


# The client's VAT setting holds the scheme and the basis together (the VAT reconciliation has a layout for each of
# the four): STANDARD and CASH are the standard scheme on the accruals or cash basis, FLAT_RATE and FLAT_RATE_CASH the flat
# rate scheme on either basis (Notice 733 s9: the flat rate turnover may be worked out on cash received)
SCHEMES = {"STANDARD": ("STANDARD", "ACCRUALS"), "CASH": ("STANDARD", "CASH"),
           "FLAT_RATE": ("FLAT_RATE", "ACCRUALS"), "FLAT_RATE_CASH": ("FLAT_RATE", "CASH")}


# A reverse charge VAT code, as Xero ('Reverse Charge Expenses (20%)') and QuickBooks ('20.0% RC SG' services from
# abroad, '20.0% RC CIS' construction, 'RC') name it: the customer puts the VAT in Box 1 and Box 4 itself, and the
# ledger line carries none (VATA 1994 s8, s55A; Notice 741A, construction reverse charge guide). '0.0% RC' is the
# supplier's side of the construction reverse charge (sales, no VAT of its own to account for): not one
REVERSE_CHARGE_CODE = re.compile(r"reverse charge|\brc\b", re.I)
ZERO_RATE_CODE = re.compile(r"^\s*0(\.0+)?\s*%")


def reverse_charge_code(vat_code: Optional[str]) -> bool:
    code = vat_code or ""
    return bool(REVERSE_CHARGE_CODE.search(code)) and not ZERO_RATE_CODE.search(code)


def box6_in_year(returns: Iterable[tuple], year_start: date, ped: date) -> tuple:
    """Box 6 for the accounting year from (start, end, box6) per return, a return straddling the year end counted by
    its days in the year; and the days of the year the returns cover (V-F02 and the Sales reconciliation)."""
    box6, covered = 0.0, 0
    for start, end, value in returns:
        days = (end - start).days + 1
        inside = (min(end, ped) - max(start, year_start)).days + 1
        box6 += value * max(0, inside) / days if days > 0 else 0
        covered += inside
    return box6, covered


def scheme_and_basis(value: Optional[str]) -> tuple:
    """('STANDARD' | 'FLAT_RATE', 'ACCRUALS' | 'CASH') for the client's VAT setting; anything else is standard, accruals."""
    return SCHEMES.get((value or "").upper(), ("STANDARD", "ACCRUALS"))


def vat_review(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session) -> VatReview:
    tb_records = list(tb_records)
    chart = ChartLookup(db)
    ped = engagement.period_end_date
    year_start = (engagement.prior_period_end_date + timedelta(days=1)) if engagement.prior_period_end_date else \
        _months_back(ped, 12) + timedelta(days=1)
    profile = getattr(engagement, "profile", None)
    findings: List[VatFinding] = []
    frs_surplus: Optional[float] = None
    scheme, basis = scheme_and_basis(getattr(profile, "vat_scheme", None))
    flat_rate = scheme == "FLAT_RATE"

    # Ledger lines with VAT, split into output (income accounts) and input (everything else)
    codes = chart.gl_account_codes(tb_records)
    lines = []
    gifts = []                       # (date, account, contact, description, net, vat): P&L costs that look like gifts
    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement.id)).scalars():
        if not tx.transaction_date:
            continue
        code = next((codes[k] for k in account_name_keys(tx.raw_account_name or "") if k in codes), None)
        text = f"{tx.description or ''} {tx.raw_account_name or ''}"
        if (code is not None and chart.is_pl(code) and float(tx.debit_amount or 0) > 0
                and GIFT_WORDS.search(text) and not NOT_GIFTS.search(text)):
            gifts.append((tx.transaction_date, tx.raw_account_name or "", (tx.reference or "").strip(), tx.description or "",
                          float(tx.debit_amount or 0) - float(tx.credit_amount or 0), tx.signed_vat))
        vat_code = (tx.vat_code or "").lower()
        vat = tx.signed_vat
        net = float(tx.debit_amount or 0) - float(tx.credit_amount or 0)
        income = chart.section(code) in INCOME_SECTIONS if code is not None else "income" in vat_code
        # The reverse charge on the cost (or asset) side only: QuickBooks puts the code on the bank or supplier line
        # that pays it too, and counting both doubled it (Box 1 and Box 4 each over by the same amount)
        cost_side = code is None or chart.is_pl(code) or chart.is_fixed_asset_addition(code)
        rc = REVERSE_CHARGE_RATE * abs(net) if reverse_charge_code(vat_code) and not vat and cost_side else 0.0
        if vat or rc:
            lines.append((tx.transaction_date, income, vat, rc))
    ledger_has_vat = bool(lines)

    # Returns entered on the VAT returns screen that end in this accounting year
    entered = sorted((r for r in db.execute(select(VAT100Record).where(VAT100Record.engagement_id == engagement.id)).scalars()
                      if r.period_end and year_start <= r.period_end <= ped), key=lambda r: r.period_end)
    checks: List[ReturnCheck] = []
    previous_end: Optional[date] = None
    for r in entered:
        start = r.period_start or (previous_end + timedelta(days=1) if previous_end else _months_back(r.period_end, 3) + timedelta(days=1))
        c = ReturnCheck(r.period_label or f"{start:%b %y}-{r.period_end:%b %y}", start, r.period_end,
                        float(r.box1_vat_due_sales or 0), float(r.box4_vat_reclaimed or 0), float(r.box5_net_vat or 0),
                        float(r.box6_total_sales_ex_vat or 0))
        box2, box3 = float(r.box2_vat_due_acquisitions or 0), float(r.box3_total_vat_due or 0)
        box7 = float(r.box7_total_purchases_ex_vat or 0)
        # V-F04 arithmetic and sense
        if box3 and abs(box3 - (c.box1 + box2)) > TOLERANCE:
            c.problems.append(f"Box 3 £{box3:,.2f} is not Box 1 + Box 2 (£{c.box1 + box2:,.2f})")
        if c.box5 and abs(abs(c.box5) - abs((box3 or c.box1 + box2) - c.box4)) > TOLERANCE:
            c.problems.append(f"Box 5 £{c.box5:,.2f} is not Box 3 - Box 4 (£{(box3 or c.box1 + box2) - c.box4:,.2f})")
        if c.box6 and c.box1 / c.box6 > 0.205:
            c.problems.append(f"Box 1 is {c.box1 / c.box6:.1%} of Box 6: more than the 20% standard rate")
        if box7 and c.box4 / box7 > 0.205:
            c.problems.append(f"Box 4 is {c.box4 / box7:.1%} of Box 7: more than the 20% standard rate")
        # V-C01 / V-D01: the ledger's VAT for the same dates
        for when, income, vat, rc in lines:
            if start <= when <= r.period_end:
                if income:
                    c.ledger_output += -vat
                else:
                    c.ledger_input += vat
                c.ledger_output += rc
                c.ledger_input += rc
                c.reverse_charge += rc
        c.ledger_output, c.ledger_input = round(c.ledger_output, 2), round(c.ledger_input, 2)
        # V-F01 coverage
        if previous_end and start > previous_end + timedelta(days=1):
            findings.append(VatFinding("V-F01", "HIGH", f"Gap between VAT returns: {previous_end + timedelta(days=1):%d/%m/%Y} "
                                       f"to {start - timedelta(days=1):%d/%m/%Y} is on no return",
                                       "Check whether a return is missing from the VAT returns screen."))
        if previous_end and start <= previous_end:
            findings.append(VatFinding("V-F01", "HIGH", f"VAT returns overlap: {c.label} starts {start:%d/%m/%Y}, before the "
                                       f"previous return ended ({previous_end:%d/%m/%Y})", "Check the period dates."))
        previous_end = r.period_end
        checks.append(c)

    if not entered:
        if profile is not None and profile.is_vat_registered:
            findings.append(VatFinding("V-F01", "MEDIUM", "No VAT returns entered for this year",
                                       "Upload the client's VAT summary or enter the year's VAT returns on the VAT returns "
                                       "screen so they can be reconciled. If the client is not VAT registered (a VAT account "
                                       "alone does not show it is), say so on the setup: the VAT tabs then go, and any VAT "
                                       "balance is listed to reclassify."))
    else:
        if checks[0].start > year_start + timedelta(days=31):
            findings.append(VatFinding("V-F01", "MEDIUM", f"VAT returns start {checks[0].start:%d/%m/%Y}, after the year began",
                                       f"The year starts {year_start:%d/%m/%Y}: is a return (or the year-end overlap) missing?"))
        if checks[-1].end < ped - timedelta(days=31):
            findings.append(VatFinding("V-F01", "LOW", f"Last VAT return entered ends {checks[-1].end:%d/%m/%Y}",
                                       f"The year ends {ped:%d/%m/%Y}: enter the return covering the last months if filed."))
        for c in checks:
            if c.problems:
                findings.append(VatFinding("V-F04", "MEDIUM", f"VAT return {c.label}: the boxes do not add up", "; ".join(c.problems)))
        if ledger_has_vat and flat_rate:
            # V-F06 flat rate scheme: the returns charge a flat % of gross turnover, so Box 1 / Box 4 never equal the
            # standard-rate VAT the books may hold. Books kept at standard rates hold more VAT than the returns: the
            # surplus is income (other operating income), unless the bookkeeping already posts the flat-rate VAT
            ledger_net = sum(c.ledger_output - c.ledger_input for c in checks)
            due = sum(c.box1 - c.box4 for c in checks)
            frs_surplus = round(ledger_net - due, 2)
            # Only a sensible surplus: more VAT in the books than the returns, by less than the VAT due itself (a flat
            # rate surplus is typically a quarter of it). Less VAT in the books, or a wild figure, means the software
            # already posts the flat-rate VAT or its VAT column is not the VAT charged: nothing to propose
            if not (FRS_MATERIAL <= frs_surplus <= abs(due)):
                frs_surplus = None
            if frs_surplus is not None:
                findings.append(VatFinding(
                    "V-F06", "MEDIUM",
                    f"Flat rate scheme: the books hold £{frs_surplus:,.2f} more VAT than the flat-rate returns for the "
                    f"same periods",
                    (f"VAT in the books at standard rates £{ledger_net:,.2f} (output less input) v VAT due on the flat-rate "
                     f"returns £{due:,.2f}. Under the flat rate scheme the VAT due is the flat rate % of gross turnover; the "
                     f"rest of the VAT charged to customers is the business's income. Suggested journal: Dr {VAT_CONTROL} VAT "
                     f"/ Cr other operating income (flat rate surplus) £{frs_surplus:,.2f}, unless the bookkeeping software "
                     f"already posts the flat-rate VAT. Check the flat rate % and the sector (and the limited cost trader "
                     f"rate of 16.5%)."),
                    abs(frs_surplus)))
        elif ledger_has_vat:
            for c in checks:
                if abs(c.output_difference) >= TOLERANCE or abs(c.input_difference) >= TOLERANCE:
                    sev = "HIGH" if "Method 2" in c.correction else "MEDIUM" if abs(c.net_error) >= 100 else "LOW"
                    findings.append(VatFinding(
                        "V-C01" if abs(c.output_difference) >= abs(c.input_difference) else "V-D01", sev,
                        f"VAT return {c.label}: Box 1 differs from the ledger by £{c.output_difference:,.2f}, Box 4 by £{c.input_difference:,.2f}",
                        (f"Ledger output VAT £{c.ledger_output:,.2f} vs Box 1 £{c.box1:,.2f}; ledger input VAT £{c.ledger_input:,.2f} "
                         f"vs Box 4 £{c.box4:,.2f}" + (f" (reverse charge £{c.reverse_charge:,.2f} added to both)" if c.reverse_charge else "")
                         + f". Net {'under' if c.net_error > 0 else 'over'}-declared by £{abs(c.net_error):,.2f}: {c.correction} (V-I03). "
                         f"Entries posted after the return was filed show as a difference here and the opposite on a later return."),
                        abs(c.net_error),
                        table(["", "Ledger", "Return", "Difference"], [
                            row("Box 1 VAT on sales", c.ledger_output, c.box1, c.output_difference),
                            row("Box 4 VAT reclaimed", c.ledger_input, c.box4, c.input_difference),
                            row(f"Net {'under' if c.net_error > 0 else 'over'}-declared", None, None, abs(c.net_error), strong=True)])))

    # V-F02: Box 6 for the year vs turnover in the accounts (returns cut by days to the year)
    balances = final_balances(str(engagement.id), tb_records, db)
    turnover = -sum(v for k, v in balances.items() if chart.section(k) == "Sales")
    # Only when every return in the year gives its Box 6 (a return typed with Box 1 and Box 4 alone would count as
    # nil sales and show a false -100%); the VAT summary's net sales column fills Box 6
    in_year_checks = [c for c in checks if (min(c.end, ped) - max(c.start, year_start)).days >= 0]
    box6_given = bool(in_year_checks) and all(abs(c.box6) >= 0.005 for c in in_year_checks)
    # (Under the flat rate scheme Box 6 is the VAT-inclusive turnover: not comparable with the accounts' net sales)
    if checks and turnover and box6_given and not flat_rate:
        box6, covered = box6_in_year(((c.start, c.end, c.box6) for c in checks), year_start, ped)
        year_days = (ped - year_start).days + 1
        if covered >= year_days - 31 and abs(box6 - turnover) > TURNOVER_TOLERANCE * abs(turnover):
            findings.append(VatFinding("V-F02", "MEDIUM", f"Box 6 for the year £{box6:,.2f} vs turnover £{turnover:,.2f}",
                                       f"Difference £{box6 - turnover:,.2f} ({(box6 - turnover) / turnover:.1%}), more than 2% "
                                       f"(returns straddling the year end counted by days). Reasons to check: zero-rated, "
                                       f"exempt or outside-the-scope income; sales posted to other income accounts; cut-off; "
                                       f"cash accounting (Box 6 on receipts, the accounts on invoices).",
                                       abs(box6 - turnover),
                                       amounts([("Box 6 sales on the returns", box6), ("Turnover in the accounts", turnover),
                                                ("Difference", box6 - turnover, True)])))

    # V-F03: VAT account at the year end vs returns still unpaid (owed to HMRC is a credit)
    if checks:
        # Last year's returns still unpaid when the year began (as on G9), plus this year's returns
        earlier = [r for r in db.execute(select(VAT100Record).where(VAT100Record.engagement_id == engagement.id)).scalars()
                   if r.period_end and r.period_end < year_start]
        brought_forward = sum(float(r.bfwd_outstanding if r.bfwd_outstanding is not None else r.box5_net_vat or 0) for r in earlier)
        owed_per_returns = brought_forward + sum(c.box5 for c in checks)
        # A payment made before the first listed return had ended paid an earlier return that is not listed
        first_end = min([r.period_end for r in earlier] + [c.end for c in checks])
        # HMRC lines on the VAT account: payments, and apart from them interest and penalties HMRC charged (as on
        # G9: they change what is owed but are not VAT paid)
        from backend.app.services.reconciliation.control_accounts import CHARGE_TEXT
        hmrc_paid = charges = 0.0
        for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement.id)).scalars():
            code = next((codes[k] for k in account_name_keys(tx.raw_account_name or "") if k in codes), None)
            if (code == VAT_CONTROL and "hmrc" in (tx.description or "").lower() and tx.transaction_date
                    and first_end < tx.transaction_date <= ped):
                net = float(tx.debit_amount or 0) - float(tx.credit_amount or 0)
                if CHARGE_TEXT.search(tx.description or ""):
                    charges -= net                   # a charge is a credit: more owed
                else:
                    hmrc_paid += net
        ledger_owed = -balances.get(VAT_CONTROL, 0.0)
        after_last = 0.0
        if checks[-1].end < ped:
            after_last = sum(-v for when, _inc, v, _rc in lines if checks[-1].end < when <= ped)   # output VAT is a credit (-)
        # Cash accounting (Notice 731): the returns count VAT when the money moves, the ledger when the invoice is
        # raised, so the ledger is ahead by the output VAT in unpaid sales invoices and behind by the input VAT in unpaid
        # bills (their change over the year); a sixth of the gross balances (standard rate), as G9
        cash_timing = 0.0
        if basis == "CASH":
            change = lambda code: sum(float(t.net_amount or 0) - float(t.opening_amount or 0)
                                      for t in tb_records if t.std_code == code)
            cash_timing = round(change(4400) / 6 + change(5200) / 6, 2)   # debtors up: more output VAT in the ledger
        expected = owed_per_returns - hmrc_paid + charges + after_last + cash_timing
        if abs(expected - ledger_owed) > 10:
            findings.append(VatFinding("V-F03", "MEDIUM", f"VAT account £{ledger_owed:,.2f} owed vs £{expected:,.2f} per the returns",
                                       f"Returns in the year £{owed_per_returns:,.2f}, HMRC payments on the VAT account £{hmrc_paid:,.2f}"
                                       + (f", interest / penalties posted to it £{charges:,.2f} (not VAT)" if charges else "")
                                       + (f", VAT on entries after the last return £{after_last:,.2f}" if after_last else "")
                                       + (f", cash accounting: VAT in unpaid invoices and bills £{cash_timing:,.2f} (a sixth "
                                          f"of the change in trade debtors and creditors)" if cash_timing else "")
                                       + f". Difference £{ledger_owed - expected:,.2f}: see G9 for the return-by-return payments.",
                                       abs(expected - ledger_owed),
                                       amounts([("Owed per the books", ledger_owed), ("Owed per the returns, less payments", expected),
                                                ("Difference", ledger_owed - expected, True)])))

    # V-B01 (registration) is checked for every client, registered or not: registration_findings below
    # V-C06: business gifts with input VAT claimed. The ledger rarely names who received a gift, so the point lists the
    # gift costs and asks for them by recipient (the guide's question); only lines with VAT claimed, or every gift line
    # when the ledger export has no VAT column (then whether VAT was claimed is not known)
    claimed = [g for g in gifts if g[5] > 0] if ledger_has_vat else gifts
    if claimed and (sum(g[4] for g in claimed) > GIFT_LIMIT):
        listed = "; ".join(f"{g[0]:%d/%m/%Y} {g[3][:50] or g[1]} £{g[4]:,.2f}" + (f" (VAT £{g[5]:,.2f})" if g[5] else "")
                           for g in sorted(claimed)[:12])
        vat_note = (f"Input VAT claimed on them: £{sum(g[5] for g in claimed):,.2f}. " if ledger_has_vat else
                    "The ledger export has no VAT column, so whether input VAT was claimed is not shown. ")
        findings.append(VatFinding(
            "V-C06", "LOW", f"Business gifts: {len(claimed)} line(s), £{sum(g[4] for g in claimed):,.2f}",
            f"{vat_note}Gifts of goods to the same person costing more than £{GIFT_LIMIT:,.0f} in a year are a deemed supply: "
            f"output VAT is due on them (VATA 1994 Sch 4 para 5). Staff entertainment VAT is not restricted. Lines: {listed}"
            f"{' and others' if len(claimed) > 12 else ''}. Client question: Please list business gifts by recipient.",
            sum(g[5] for g in claimed)))
    # VAT on the ledger's lines after the last return, to the year end: on the next return, not yet filed
    after = None
    if checks and ledger_has_vat:
        after = round(sum(-v for when, _inc, v, _rc in lines if checks[-1].end < when <= ped), 2) if checks[-1].end < ped else 0.0
    return VatReview(checks, findings, ledger_has_vat, frs_surplus, after, year_start)


THRESHOLD_BEFORE_APRIL_2024 = 85000.0   # the registration threshold until 31 March 2024 (£90,000 from 1 April 2024)
VAT_ACCOUNTS = (5300, 5700)


def registration_findings(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session) -> List[VatFinding]:
    """VAT registration from the evidence, for every client (the VAT review itself runs only for registered ones):
      V-B01  not registered while turnover is over the registration threshold: confirm registration
      V-B03  confirmed not registered, yet the books hold a VAT balance: reclassify it"""
    from backend.app.models.database import ClientProfile
    from backend.app.services.setup.profile_service import confirmed_fields
    tb_records = list(tb_records)
    profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement.id).first()
    if profile is None or engagement.period_end_date is None:
        return []
    ped = engagement.period_end_date
    chart = ChartLookup(db)
    balances = final_balances(str(engagement.id), tb_records, db)
    turnover = -sum(v for k, v in balances.items() if chart.section(k) == "Sales")
    vat_balance = sum(v for k, v in balances.items() if k in VAT_ACCOUNTS)
    confirmed = "is_vat_registered" in confirmed_fields(profile)
    findings: List[VatFinding] = []

    if not profile.is_vat_registered:
        threshold = tax_parameters().get("P-VAT-REG", 90000.0) if ped >= date(2024, 4, 1) else THRESHOLD_BEFORE_APRIL_2024
        if turnover > threshold:
            findings.append(VatFinding(
                "V-B01", "HIGH", f"Turnover £{turnover:,.2f} is over the VAT registration threshold (£{threshold:,.0f}) and "
                f"the client is not marked VAT registered",
                "Confirm the VAT registration (number, effective date, scheme), or that the turnover is below the threshold "
                "in every rolling 12 months: exempt income (residential rent, insurance, most education and health) and "
                "income outside the scope do not count. The threshold is £90,000 from 1 April 2024 (£85,000 before). Late "
                "registration means VAT owed on past sales plus a penalty. Client question: Is the company VAT registered? "
                "If so, please send the VAT number and the VAT returns for the year.", turnover))
        if confirmed and abs(vat_balance) >= 1:
            findings.append(VatFinding(
                "V-B03", "MEDIUM", f"VAT balance £{abs(vat_balance):,.2f} on a client that is not VAT registered",
                "The client is confirmed as not VAT registered, so there should be no VAT account. Find where the VAT "
                "postings came from (a bank feed or invoice with a VAT code) and reclassify them to the expense or "
                "income they belong to.", abs(vat_balance)))
    return findings
