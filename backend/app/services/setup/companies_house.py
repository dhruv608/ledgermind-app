"""
Companies House (public register of UK companies): find a client company and the people who were its directors or
shareholders with more than 25% (persons with significant control) during the financial year.
The API key lives in the backend .env (COMPANIES_HOUSE_API_KEY) and never reaches the browser.
"""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.app.core.config import settings

API = "https://api.company-information.service.gov.uk"
TITLES = re.compile(r"^(mr|mrs|ms|miss|dr|sir|dame|lord|lady|prof)\.?\s+", re.I)
LEGAL_WORDS = re.compile(r"\b(ltd|limited|plc|llp)\b|[^a-z0-9 ]")


class CompaniesHouseError(Exception):
    """A problem the accountant can act on (no key, company not found, service down)."""


def _key() -> str:
    key = (getattr(settings, "COMPANIES_HOUSE_API_KEY", None) or "").strip()
    if not key:
        raise CompaniesHouseError("No Companies House key: add COMPANIES_HOUSE_API_KEY to backend/.env.")
    return key


def _get(path: str) -> Dict[str, Any]:
    auth = "Basic " + base64.b64encode(f"{_key()}:".encode()).decode()
    req = urllib.request.Request(API + path, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        if e.code == 401:
            raise CompaniesHouseError("Companies House did not accept the key in backend/.env.") from e
        raise CompaniesHouseError(f"Companies House answered {e.code}; please try again.") from e
    except urllib.error.URLError as e:
        raise CompaniesHouseError("Companies House could not be reached; please try again.") from e


def company_key(name: str) -> str:
    """'Acme Ltd' and 'ACME LIMITED' compare equal."""
    return " ".join(LEGAL_WORDS.sub(" ", (name or "").lower()).split())


def search(name: str) -> List[Dict[str, Any]]:
    """Companies whose name looks like this one, exact name first."""
    items = _get("/search/companies?" + urllib.parse.urlencode({"q": name, "items_per_page": 8})).get("items", [])
    found = [{
        "company_number": i.get("company_number"),
        "company_name": i.get("title"),
        "status": i.get("company_status"),
        "address": i.get("address_snippet"),
        # The same name written with or without spaces ('ACME FOODS LTD' is ACMEFOODS LTD)
        "exact": company_key(i.get("title", "")).replace(" ", "") == company_key(name).replace(" ", ""),
    } for i in items]
    return sorted(found, key=lambda c: not c["exact"])


# SIC 2007 code ranges -> the firm's industries (first match on the company's first SIC code)
SIC_INDUSTRY = [
    # The firm's industry list: the more specific codes first. 68100 buying / selling own property and 41100
    # development are property trading; 9602 / 9604 hair and beauty; 88990 / 94910 charities; 86-88 health and care;
    # 6420 / 6430 holding and investment companies
    (("68100", "4110"), "PRD"), (("9602", "9604"), "HBB"), (("88990", "94910"), "CHR"), (("86", "87", "88"), "HLT"),
    (("6420", "6430"), "HLD"),
    # 55 is accommodation (hotels, holiday lets): property, not food; 56 is food and drink service
    (("41", "42", "43"), "CON"), (("56",), "RES"), (("55",), "PRP"), (("4791",), "ECM"), (("78",), "REC"),
    (("62", "631", "5829"), "SAAS"), (("68",), "PRP"), (("49", "50", "51", "52", "53"), "TRN"),
    (("45", "46", "47"), "RTL"), (("69", "70", "71", "72", "73", "74"), "PRO"),
    (tuple(f"{n:02d}" for n in range(10, 34)), "MFG"),
]


def industry_from_sic(codes) -> Optional[str]:
    for code in codes or []:
        code = str(code)
        for prefixes, industry in SIC_INDUSTRY:
            if code.startswith(prefixes):
                return industry
    return None


def sic_industry(register: Dict[str, Any]) -> Optional[str]:
    """The industry the register's SIC codes give: its pack, or 'UNIV' (general checks) when the codes have none
    (cleaning, care...). None when the register has no SIC codes."""
    codes = (register or {}).get("sic_codes") or []
    if not codes:
        return None
    return register.get("industry_from_sic") or industry_from_sic(codes) or "UNIV"


COMPANY_NUMBER = re.compile(r"(?:company|registration|reg\.?|crn)\s*(?:no\.?|number|num)?\s*[:#.\-]?\s*"
                            r"([A-Z]{2}\d{6}|\d{7,8})\b", re.I)
CHOICES_SHOWN = 3


def number_in_text(text: str) -> Optional[str]:
    """A company number written in a file heading ('Company number : 12345678', 'Reg No. SC123456'), as the
    register writes it (8 characters, leading zeros)."""
    m = COMPANY_NUMBER.search(text or "")
    if not m:
        return None
    number = m.group(1).upper()
    return number.zfill(8) if number.isdigit() else number


def find_client(client_name: str, year_end: date, year_start: Optional[date] = None,
                company_number: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """(register entry, choices). By the company number when it is known (the accountant's, last year's, or one in
    the files): exact. Otherwise by name: one exact match is taken; else the closest companies come back for the
    accountant to confirm ('Is this your company?'). Nothing when Companies House cannot be asked."""
    try:
        if company_number:
            return people(company_number.strip().upper(), year_end, year_start), []
        found = search(client_name)
        exact = [c for c in found if c["exact"]]
        if len(exact) == 1:
            return people(exact[0]["company_number"], year_end, year_start), []
        return None, found[:CHOICES_SHOWN]
    except (CompaniesHouseError, ValueError, KeyError, OSError):
        return None, []


def year_end_for(client_name: str, first: date, last: date) -> Optional[Tuple[date, str]]:
    """The client's year end when its files do not say it (bank statements): the company's accounting reference date on
    Companies House (CA 2006 s391), in the year that the statements from first to last cover most of. (date, why), or
    None when the name matches no single company or Companies House cannot be asked."""
    try:
        found = [c for c in search(client_name) if c["exact"]]
        if len(found) != 1:
            return None
        profile = _get(f"/company/{found[0]['company_number']}")
    except (CompaniesHouseError, ValueError, KeyError, OSError):
        return None
    ard = ((profile.get("accounts") or {}).get("accounting_reference_date") or {})
    try:
        day, month = int(ard["day"]), int(ard["month"])
    except (KeyError, TypeError, ValueError):
        return None
    import calendar
    candidates = []
    for year in range(first.year - 1, last.year + 2):
        end = date(year, month, min(day, calendar.monthrange(year, month)[1]))
        start = date(year - 1, month, min(day, calendar.monthrange(year - 1, month)[1])) + timedelta(days=1)
        covered = (min(end, last) - max(start, first)).days
        candidates.append((covered, end))
    covered, end = max(candidates)
    if covered <= 0:
        return None
    return end, (f"Companies House: {profile.get('company_name', client_name)} makes its accounts up to "
                 f"{end:%d %B} each year")


def person_name(raw: str, elements: Optional[Dict[str, str]] = None) -> str:
    """'SMITH, John Paul' / 'Mr John Paul Smith' -> 'John Paul Smith'."""
    if elements and elements.get("surname"):
        parts = [elements.get("forename"), elements.get("middle_name"), elements.get("surname")]
        return " ".join(p.strip().title() for p in parts if p)
    raw = (raw or "").strip()
    if "," in raw:
        surname, rest = raw.split(",", 1)
        raw = f"{rest.strip()} {surname.strip()}"
    raw = TITLES.sub("", raw)
    return " ".join(w if any(c.islower() for c in w) else w.title() for w in raw.split())


def _day(value: Optional[str]) -> Optional[date]:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def filed_accounts_text(company_number: str, before: date) -> Tuple[Optional[str], Optional[date]]:
    """The text of the company's latest accounts filed for a period ending before `before` (last year's accounts, as
    filed: the iXBRL document) and the date they are made up to. (None, date) when only a PDF was filed; (None, None)
    when there are none. Raises CompaniesHouseError when Companies House cannot be asked."""
    import html as _html
    import requests
    items = _get(f"/company/{company_number}/filing-history?category=accounts&items_per_page=25").get("items", [])
    dated = [(i, _day(i.get("action_date"))) for i in items]
    dated = [(i, d) for i, d in dated if d and d < before]
    if not dated:
        return None, None
    item, made_up = max(dated, key=lambda x: x[1])
    url = (item.get("links") or {}).get("document_metadata") or ""
    if not url:
        return None, made_up
    try:
        # requests drops the key on the redirect to the document store (urllib would send it on, and be refused)
        meta = requests.get(url, auth=(_key(), ""), timeout=20).json()
        if "application/xhtml+xml" not in (meta.get("resources") or {}):
            return None, made_up
        doc = requests.get(url + "/content", auth=(_key(), ""), headers={"Accept": "application/xhtml+xml"}, timeout=40)
        doc.raise_for_status()
    except (requests.RequestException, ValueError) as e:
        raise CompaniesHouseError("Companies House documents could not be read; please try again.") from e
    text = _html.unescape(re.sub(r"<[^>]+>", " ", doc.text))
    return re.sub(r"\s+", " ", text), made_up


def _in_year(start: Optional[date], end: Optional[date], year_start: date, year_end: date) -> bool:
    """Held the role at some point in the financial year."""
    return (start is None or start <= year_end) and (end is None or end >= year_start)


DIRECTOR_ROLES = ("Director", "Designated member", "Member")


def officer_role(raw: str) -> Optional[str]:
    """The register's officer role as the accounts name it: a company's directors; an LLP's designated members and
    members, who run it as directors run a company. A
    secretary and other roles are not taken."""
    raw = raw.lower()
    if "director" in raw:
        return "Director"
    if "llp-designated-member" in raw:
        return "Designated member"
    if "llp-member" in raw:
        return "Member"
    return None


def people(company_number: str, year_end: date, year_start: Optional[date] = None) -> Dict[str, Any]:
    """Directors and shareholders over 25% during the year (from the register), one entry per person."""
    year_start = year_start or (year_end.replace(year=year_end.year - 1) + timedelta(days=1)
                                if not (year_end.month == 2 and year_end.day == 29)
                                else date(year_end.year - 1, 3, 1))
    profile = _get(f"/company/{company_number}")
    if not profile:
        raise CompaniesHouseError(f"Company number {company_number} was not found on Companies House.")

    by_name: Dict[str, Dict[str, Any]] = {}

    def add(name: str, role: str, start: Optional[date], end: Optional[date], kind: str = "person"):
        if not name:
            return
        entry = by_name.setdefault(name.lower(), {"name": name, "roles": [], "kind": kind,
                                                   "from": None, "to": None})
        if role not in entry["roles"]:
            entry["roles"].append(role)
        if start and (entry["from"] is None or start.isoformat() < entry["from"]):
            entry["from"] = start.isoformat()
        if end:
            entry["to"] = end.isoformat() if entry["to"] is None or end.isoformat() > entry["to"] else entry["to"]

    officers = _get(f"/company/{company_number}/officers?items_per_page=100").get("items", [])
    for o in officers:
        role = officer_role(o.get("officer_role") or "")
        if role is None:
            continue
        start, end = _day(o.get("appointed_on")), _day(o.get("resigned_on"))
        if _in_year(start, end, year_start, year_end):
            corporate = "corporate" in (o.get("officer_role") or "")
            add(o.get("name", "").strip() if corporate else person_name(o.get("name", ""), o.get("name_elements")),
                role, start, end, "company" if corporate else "person")

    pscs = _get(f"/company/{company_number}/persons-with-significant-control?items_per_page=100").get("items", [])
    for p in pscs:
        start, end = _day(p.get("notified_on")), _day(p.get("ceased_on"))
        if not _in_year(start, end, year_start, year_end):
            continue
        share = next((n for n in p.get("natures_of_control", []) if n.startswith("ownership-of-shares")), None)
        role = ("Shareholder " + share.replace("ownership-of-shares-", "").replace("-to-", "-").replace("-percent", "%")
                if share else "Significant control")
        corporate = "corporate" in (p.get("kind") or "") or "legal-person" in (p.get("kind") or "")
        add((p.get("name") or "").strip() if corporate else person_name(p.get("name", ""), p.get("name_elements")),
            role, start, end, "company" if corporate else "person")

    return {
        "company_number": company_number,
        "company_name": profile.get("company_name"),
        "status": profile.get("company_status"),
        "incorporated": profile.get("date_of_creation"),       # a company formed in the year has no opening balances
        "sic_codes": profile.get("sic_codes", []),
        "industry_from_sic": industry_from_sic(profile.get("sic_codes", [])),
        "year": [year_start.isoformat(), year_end.isoformat()],
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%d"),
        "people": sorted(merge_same_person(list(by_name.values())), key=lambda e: e["name"]),
    }


def _name_words(name: str) -> List[str]:
    return [w for w in re.sub(r"[^a-z]+", " ", name.lower()).split() if w not in ("mr", "mrs", "ms", "miss", "dr", "sir")]


def same_person(a: str, b: str) -> bool:
    """Directors and shareholders are separate lists on the register, and one person can be named differently on each
    ('John Paul Smith-Jones' and 'John Smith'): same first name, and every word of the shorter name is in the
    longer one."""
    wa, wb = _name_words(a), _name_words(b)
    if len(wa) < 2 or len(wb) < 2 or wa[0] != wb[0]:
        return False
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return set(short) <= set(long_)


def merge_same_person(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per person: the shorter name is kept as also_listed_as on the fuller one (roles and dates combined)."""
    out: List[Dict[str, Any]] = []
    for e in sorted(entries, key=lambda x: -len(_name_words(x["name"]))):
        twin = next((o for o in out if o["kind"] == e["kind"] == "person" and same_person(o["name"], e["name"])), None)
        if twin is None:
            out.append(e)
            continue
        twin.setdefault("also_listed_as", []).append(e["name"])
        twin["roles"] += [r for r in e["roles"] if r not in twin["roles"]]
        if e["from"] and (twin["from"] is None or e["from"] < twin["from"]):
            twin["from"] = e["from"]
        if e["to"] and twin["to"] and e["to"] > twin["to"]:
            twin["to"] = e["to"]
    return out
