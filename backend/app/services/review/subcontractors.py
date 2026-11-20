"""
Subcontractor v employee, from the wages review method:

1. The employee list comes from the payroll file (its per-employee names; a summary of monthly totals has none, so
   "on the payroll" cannot be confirmed).
2. Every ledger line debited to a wages, subcontractor / labour or labour-type cost account (cost of sales, direct
   costs, commission, cleaning, repairs, consultancy, delivery...) is read; the payee is the contact before " - " in
   the description (Xero and QuickBooks both write it so).
3. Payees that look like individuals are kept: a first name and a surname, no company words (Ltd, Services...).
4. Flags (each a question for the client, not a conclusion):
   A  on the payroll AND paid as a subcontractor (employee and self-employed at once)
   B  paid as a subcontractor in 6+ months: employment status (CEST / IR35) and, in construction, CIS
   C  paid through a wages account but not on the payroll (only when the payroll gives names)
   D  an individual paid in 3+ months (£1,000+) through a labour-type cost account: staff or subcontractor
      costs in the wrong account
   E  subcontractor costs with no CIS account in the ledger: already raised by the CIS check (cis/codes.py)

U-SUB-001 .. U-SUB-004 below; the workbook's G6.4 tab lists every individual (subcontractor_rows).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from backend.app.models.database import (
    AuditFinding, ClientEngagement, ClientProfile, GLTransaction, TBRecord,
)

WAGE_CODES = {1450, 1500, 2450, 2500, 3000, 3004, 3010, 3014, 3015}
SUBCONTRACTOR_CODES = {1440, 2440, 3020}
COMMISSION_CODES = {1520, 2520, 3306}
WAGE_NAME = re.compile(r"\b(?:wages?|salar(?:y|ies)|payroll|staff)\b", re.I)
SUBCONTRACTOR_NAME = re.compile(r"sub-?contract|\bcis\b|\blabou?r\b|freelance|casual|agency|locum|contractor", re.I)
LABOUR_NAME = re.compile(r"cost of (?:sales|goods)|\bdirect\b|purchases|cleaning|repairs|consultan|professional|"
                         r"commission|delivery|driver|courier|security|maintenance", re.I)
COMPANY_WORDS = re.compile(
    r"\b(?:ltd|limited|plc|llp|lp|inc|co|company|services?|electrical|electrics|construction|supplies|supply|hire|"
    r"group|trading|solutions|uk|international|holdings?|partners?|associates|builders?|building|plumbing|heating|"
    r"roofing|scaffolding|engineering|transport|logistics|cars?|motors?|garage|systems?|consulting|consultancy|"
    r"design|properties|property|estates?|centre|center|shop|store|stores|bank|council|hmrc|insurance|finance|"
    r"direct|express|london|wholesale|foods?|catering|cleaning|security|maintenance|recruitment|agency|media|"
    r"marketing|studio|studios|clinic|pharmacy|amazon|ebay|paypal|stripe|tesco|asda|sainsbury|screwfix|toolstation|"
    r"wickes|travis|perkins|jewson|selco|b&q|homebase|shell|bp|esso|texaco|transfer|payment|refund|fee|fees|"
    r"interest|charge|charges|wages?|salary|cash|cheque|bill|invoice|loan|tax|vat|paye|cis|pension|nest|halal|"
    r"butchers?|gb|cafe|restaurant|takeaway|pizza|kebab|bakery|market|farm|traders?|enterprises?)\b", re.I)
TITLES = re.compile(r"^(?:mr|mrs|ms|miss|dr|mx|sir)\.?\s+", re.I)

# Common first names in UK ledgers (English, Irish, Scottish, Welsh, South Asian, Turkish, Eastern European, African):
# a payee is taken as a person only when it starts with one
FIRST_NAMES = set("""
aaron abbie abby abdul abdullah abi abigail abraham adam adele adrian ahmed ahmet aidan aiden aisha alan alana albert
alex alexander alexandra alexis alfie ali alice alicia alison alistair allan amanda amber amelia amir amit amy ana
andre andrea andreea andrei andrew andy angela angus anil anita ann anna anne annie anthony anton antonio april archie
arjun arthur ash asha ashley ashraf aston audrey austin ayesha aysha barbara barry bartosz becky bekir ben benjamin
bernard beth bethany betty bill billy blake bob bobby bogdan bradley brandon brendan brett brian bridget bruce bryan
burak caitlin callum calvin cameron cara carl carla carlos carmen carol caroline carter cassie catherine cathy cem
charlie charles charlotte chelsea cheryl chloe chris christian christina christine christopher ciara claire clara
clare colin connor conor craig cristian dale damian damien dan dani daniel daniela danielle danny darren dave david
dawn dean debbie deborah declan dee demi denis dennis derek dev dexter diana diane dilkaran dimitri dina dominic
donna dorota duncan dylan eddie edward elaine eleanor elena eliza elizabeth ella ellie elliot elliott ellis emily
emine emma emre eric erica erin ertugrul erkan esra ethan eve evelyn ewa ewan faisal farah farhan fatima fatma
fazal felix fiona florin francesca francis frank frankie fred freddie freya gabriel gabriela gail gareth gary gavin
gemma george georgia gerald gerard gillian gina glen glenn gordon grace graham grant greg gregory gurpreet hakan
haley hamza hannah harjit harley harmeet harpreet harriet harrison harry harvey hasan hassan hayden hayley hazel
heather helen henry holly hugh hugo hussain hussein ian ibrahim imran ioana ion irene isaac isabel isabella
isabelle isla ismail ivan ivor jack jackie jackson jacob jade jake jakub james jamie jan jane janet janice jas
jasmine jason jasper jay jayne jean jeff jeffrey jenna jennifer jenny jeremy jesse jessica jill jim jimmy jo joan
joanna joanne jodie joe joel john johnny jon jonathan jordan jose joseph josh joshua joy joyce judith judy julia
julian julie juliet justin kamal kamil karen karl karolina kate katherine kathleen kathryn katie kay kayleigh keith
kelly kemal ken kenneth kerry kevin khalid kieran kim kirsty krystian krzysztof kyle lara laura lauren lawrence
layla leah lee leigh leon leonard leslie lewis liam lily linda lindsay lisa liz lloyd logan lois lorna lorraine louis
louise lucas lucy luke lydia lynn lynne maciej madison mahmut mandy marc marcin marcus margaret maria marian marie
marina mario marion mark marta martin mary mason matt matthew maureen max maya megan mehmet melanie melissa mia
michael michal michael michelle mike milan miles mitchell mohamed mohammad mohammed molly monika muhammad murat
mustafa nadia naomi nasir natalie natasha nathan neil nicholas nick nickolas nicky nicola nicole nigel nikhil
nikki nina noah noel noor nuray oliver olivia omar oscar owen paige pamela patricia patrick paul paula pauline
pawel pedro penny peter petra phil philip phillip piotr poppy priya rachel rafal raj rajesh ralph ramesh ravi ray
raymond rebecca reece rhys richard ricky rob robbie robert robin roger ronald ronnie rory rosa rose rosie ross roy
ruby russell ruth ryan sadia sahil sajid sally sam samantha samir samuel sandra sara sarah sasha scarlett scott
sean sebastian selin semra serkan shabnam shane shannon sharon shaun shauna sheila shirley siobhan simon simone
sinead sofia sonia sophia sophie stacey stanley stefan stella stephanie stephen steve steven stewart stuart sue
sunil susan suzanne tanya tara teresa terry thomas tim timothy tina toby todd tom tomasz tommy toni tony tracey
tracy trevor tyler valentina vanessa veli vicky victor victoria vikram vincent violet vivek wayne wendy wesley
william willow yasar yasin yusuf zach zachary zainab zak zara zoe zofia
""".split())


def payee_of(description: str) -> str:
    """The contact before ' - ' in the description (Xero / QuickBooks write 'Contact - memo')."""
    text = (description or "").strip()
    return text.split(" - ")[0].strip() if " - " in text else text


def is_person(name: str) -> bool:
    n = TITLES.sub("", re.sub(r"\s+", " ", (name or "").strip()))
    words = n.split(" ")
    if not 2 <= len(words) <= 4 or COMPANY_WORDS.search(n) or re.search(r"\d|[@&/]", n):
        return False
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z'\-.]*", w) for w in words):
        return False
    return words[0].lower().strip(".") in FIRST_NAMES


def _parts(name: str) -> List[str]:
    return [w for w in re.findall(r"[a-z']+", TITLES.sub("", (name or "").lower())) if len(w) > 1]


def on_payroll(payee: str, employees: List[str]) -> bool:
    """Shares two name parts with an employee, or the same surname."""
    p = _parts(payee)
    for e in employees:
        q = _parts(e)
        if not p or not q:
            continue
        if len(set(p) & set(q)) >= 2 or p[-1] == q[-1]:
            return True
    return False


@dataclass
class Individual:
    name: str
    on_payroll: Optional[bool]               # None: the payroll gives no names
    total: float = 0.0
    payments: int = 0
    months: Set[str] = field(default_factory=set)
    via_wages: float = 0.0
    via_subcontractor: float = 0.0
    via_other: float = 0.0
    other_months: Set[str] = field(default_factory=set)
    sub_months: Set[str] = field(default_factory=set)
    accounts: Set[str] = field(default_factory=set)
    flags: List[str] = field(default_factory=list)


def _kind(code: Optional[int], name: str, category: Optional[str]) -> Optional[str]:
    if code is not None and code >= 4000:
        return None                           # balance sheet (banks, creditors...)
    if code in SUBCONTRACTOR_CODES or SUBCONTRACTOR_NAME.search(name):
        return "subcontractor"
    if code in WAGE_CODES or WAGE_NAME.search(name):
        return "wages"
    if code in COMMISSION_CODES or (category or "").lower() == "cost of sales" or LABOUR_NAME.search(name):
        return "other"
    return None


# A payee whose name says it supplies a service that is not labour (window cleaners, a coffee supplier, pest control
# in 'Subcontractor costs'): a cost of another kind, to reanalyse, never a subcontractor
NOT_LABOUR = [(re.compile(r"window clean|\bclean(?:ing|ers?)\b", re.I), "cleaning"),
              (re.compile(r"\bcoffee\b|\bvending\b|water cooler", re.I), "coffee / vending supplies"),
              (re.compile(r"\bpest\b|environmental", re.I), "pest control / environmental services"),
              (re.compile(r"\bwaste\b|\bskip hire\b|\brecycl", re.I), "waste collection"),
              (re.compile(r"\bhygiene\b|\blaundry\b|\blinen\b|\bwashroom\b", re.I), "hygiene / laundry")]


def not_labour(payee: str) -> str:
    """The kind of non-labour service a payee's name says ('' when none)."""
    return next((kind for pattern, kind in NOT_LABOUR if pattern.search(payee or "")), "")


def individuals(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session) -> Dict[str, object]:
    """{'people': [Individual], 'payroll_names': bool, 'subcontractor_costs': float, 'has_cis': bool}"""
    from backend.app.models.database import MasterCOA
    from backend.app.services.mapping.chart_lookup import account_name_keys
    category = {c.std_code: c.category for c in db.query(MasterCOA).all()}
    code_of: Dict[str, int] = {}
    for t in tb_records:
        if t.std_code is not None:
            for k in account_name_keys(t.raw_account_name or ""):
                code_of.setdefault(k, int(t.std_code))

    from backend.app.services.review.payroll_period import usable
    employees = sorted({p.employee_name for p in usable(engagement, db)[0]
                        if p.employee_name and p.employee_name != "All employees"})
    try:
        from backend.app.models.director_pay import PayrollDirectorPay
        dp = db.query(PayrollDirectorPay).filter(PayrollDirectorPay.engagement_id == engagement.id).first()
        employees += list(json.loads(dp.people or "{}")) if dp else []
    except Exception:
        pass
    names_known = bool(employees)

    people: Dict[str, Individual] = {}
    subcontractor_costs = 0.0
    has_cis = any(re.search(r"\bcis\b", t.raw_account_name or "", re.I) for t in tb_records)
    # Every payee on the subcontractor accounts, people and companies: gross less credit notes, and
    # the CIS the books withheld from them (credits to a CIS deducted / payable account naming the same payee)
    paid: Dict[str, Dict[str, float]] = {}
    sub_accounts: set = set()
    for g in db.query(GLTransaction).filter(GLTransaction.engagement_id == engagement.id):
        amount = float(g.debit_amount or 0) - float(g.credit_amount or 0)
        account = g.raw_account_name or ""
        code = next((code_of[k] for k in account_name_keys(account) if k in code_of), None)
        kind = _kind(code, account, category.get(code))
        payee = payee_of(g.description or "")
        if payee and kind == "subcontractor" and not re.search(r"\bcis\b", account, re.I):
            row = paid.setdefault(payee.upper(), {"gross": 0.0, "cis": 0.0, "payments": 0})
            row["gross"] += amount
            sub_accounts.add(account)
            row["payments"] += amount > 0
        elif payee and re.search(r"\bcis\b", account, re.I) and not re.search(r"suffer|recover|receiv|debtor", account, re.I):
            paid.setdefault(payee.upper(), {"gross": 0.0, "cis": 0.0, "payments": 0})["cis"] -= amount
        if amount <= 0:
            continue
        if kind is None:
            continue
        if kind == "subcontractor":
            subcontractor_costs += amount
            has_cis = has_cis or bool(re.search(r"\bcis\b", account, re.I))
        payee = payee_of(g.description or "")
        if not is_person(payee):
            continue
        key = " ".join(_parts(payee))
        person = people.get(key)
        if person is None:
            person = people[key] = Individual(name=payee.upper(), on_payroll=on_payroll(payee, employees) if names_known else None)
        month = g.transaction_date.strftime("%Y-%m") if g.transaction_date else ""
        person.total += amount
        person.payments += 1
        person.months.add(month)
        person.accounts.add(account)
        if kind == "wages":
            person.via_wages += amount
        elif kind == "subcontractor":
            person.via_subcontractor += amount
            person.sub_months.add(month)
        else:
            person.via_other += amount
            person.other_months.add(month)

    for p in people.values():
        if p.on_payroll and p.via_subcontractor >= 0.005:
            p.flags.append("A: on the payroll and paid as a subcontractor")
        if len(p.sub_months) >= 6:
            p.flags.append(f"B: paid as a subcontractor in {len(p.sub_months)} months - employment status / CIS")
        elif p.via_subcontractor >= 0.005:
            p.flags.append("Paid as a subcontractor")
        if p.via_wages >= 0.005 and p.on_payroll is False:
            p.flags.append("C: paid through a wages account but not on the payroll")
        if len(p.other_months) >= 3 and p.via_other >= 1000:
            p.flags.append(f"D: paid in {len(p.other_months)} months through cost accounts - staff or subcontractor "
                           f"cost in the wrong account?")
    # Listed: everyone paid through wages or subcontractor accounts, and those flagged D (one-off payments to a
    # person through a cost account are ordinary purchases)
    kept = [p for p in people.values() if p.via_wages >= 0.005 or p.via_subcontractor >= 0.005
            or any(f.startswith("D:") for f in p.flags)]
    subcontractors = sorted(({"name": k, "gross": round(v["gross"], 2), "cis": round(v["cis"], 2),
                              "payments": v["payments"], "not_labour": not_labour(k)}
                             for k, v in paid.items() if abs(v["gross"]) >= 0.005),
                            key=lambda s: -s["gross"])
    return {"people": sorted(kept, key=lambda p: -p.total), "payroll_names": names_known,
            "subcontractor_costs": round(subcontractor_costs, 2), "has_cis": has_cis, "subcontractors": subcontractors,
            "subcontractor_accounts": sorted(sub_accounts)}


def _listing(people: List[Individual], amount) -> str:
    shown = "; ".join(f"{p.name} £{amount(p):,.2f}" for p in people[:12])
    return shown + (f" and {len(people) - 12} more (G6.4)" if len(people) > 12 else "")


def subcontractor_points(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                         db: Session) -> List[AuditFinding]:
    found = individuals(engagement, tb_records, db)
    people: List[Individual] = found["people"]
    out: List[AuditFinding] = []

    def point(ref: str, title: str, details: str, amount: float, severity: str = "MEDIUM") -> None:
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=ref,
            procedure_name="Payroll: subcontractor v employee", severity=severity,
            source_row_ref="Subcontractors (G6.4)", finding_title=title[:255], finding_details=details,
            quantified_amount=round(amount, 2), status="OPEN"))

    a = [p for p in people if any(f.startswith("A:") for f in p.flags)]
    if a:
        point("U-SUB-001", f"{len(a)} person(s) on the payroll and also paid as a subcontractor",
              "Paid through the payroll and through subcontractor / labour accounts: " + _listing(a, lambda p: p.via_subcontractor)
              + ". The same person cannot be employed and self-employed for the same work: ask the client.",
              sum(p.via_subcontractor for p in a), "HIGH")
    b = [p for p in people if any(f.startswith("B:") for f in p.flags)]
    if b:
        point("U-SUB-002", f"{len(b)} individual(s) paid as a subcontractor in 6 or more months",
              "Paid regularly through subcontractor / labour accounts: " + _listing(b, lambda p: p.via_subcontractor)
              + ". A regular engagement: confirm employment status (HMRC CEST / IR35) and, for construction, that "
                "CIS was applied (verified, deductions made, monthly return).", sum(p.via_subcontractor for p in b))
    c = [p for p in people if any(f.startswith("C:") for f in p.flags)]
    if c:
        point("U-SUB-003", f"{len(c)} individual(s) paid through wages but not on the payroll",
              "Payments through a wages account to people the payroll report does not name: "
              + _listing(c, lambda p: p.via_wages) + ". Cash wages outside the payroll, a casual worker or a "
                "subcontractor: ask the client.", sum(p.via_wages for p in c))
    d = [p for p in people if any(f.startswith("D:") for f in p.flags)]
    if d:
        point("U-SUB-004", f"{len(d)} individual(s) paid regularly through cost accounts",
              "Individuals paid in 3 or more months (£1,000 or more) through cost of sales / direct / commission type "
              "accounts: " + _listing(d, lambda p: p.via_other) + ". Possibly staff or subcontractor costs in the "
              "wrong account (and outside the payroll / CIS): ask the client.", sum(p.via_other for p in d), "LOW")
    return out
