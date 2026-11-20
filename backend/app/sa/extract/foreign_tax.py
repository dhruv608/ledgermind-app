"""A foreign tax assessment or return read (R-SA106-01, -05, -07): a French 'avis d'impôt', a South African ITA34,
a New Zealand IR3 or IR3NR... It says a foreign country taxed some income, so that income must be on the return: a
letter with no foreign income entered blocks the return until the income is found (R-SA106-07). The amounts stay in
their currency here: the accountant enters them in pounds on Foreign income, time-apportioned to the UK tax year when
the country's year differs (R-SA106-05)."""

from typing import Any, Dict, List, Optional, Tuple

PROMPT = """This is a tax assessment, notice or tax return from a country other than the UK (for example a French 'avis
d'impôt', a South African ITA34, a New Zealand IR3 or IR3NR, an Australian notice of assessment), sent for a UK Self
Assessment return. Reply with one JSON object only:
{"country": "3-letter code (FRA, ZAF, NZL, AUS, USA...)", "person": "the taxpayer's name as printed or null",
 "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null", "currency": "EUR, ZAR, NZD...",
 "income": [{"kind": "PROPERTY" | "PENSION" | "INTEREST" | "DIVIDEND" | "EMPLOYMENT" | "OTHER", "amount": number}],
 "tax": number or null (the tax charged or paid for the period)}
Amounts as plain numbers, in the document's currency."""


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace(" ", "").strip())), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    income = [{"kind": str(i.get("kind") or "OTHER").upper(), "amount": _num(i.get("amount"))} for i in a.get("income") or []]
    return {"country": str(a.get("country") or "").upper()[:3] or None, "person": (a.get("person") or "").strip() or None,
            "period_from": a.get("period_from"), "period_to": a.get("period_to"),
            "currency": str(a.get("currency") or "").upper()[:3] or None,
            "income": [i for i in income if i["amount"]], "tax": _num(a.get("tax"))}


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """Always a point for a person: the income is entered by hand, in pounds."""
    from backend.app.sa.extract.p60 import owner
    if person and f.get("person") and owner(f["person"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"This foreign tax document is for {f['person']}, not {person}: not used. If it is theirs, confirm it."]
    what = ", ".join(f"{i['kind'].lower()} {i['amount']:,.2f}" for i in f.get("income") or []) or "income"
    # The same figures in pounds at HMRC's average rate for the year (the foreign tax credit is worked in pounds)
    from backend.app.sa.fx import rate
    r = rate(f.get("currency"), tax_year) if f.get("currency") and f["currency"] != "GBP" else None
    pounds = ""
    if r:
        gbp = ", ".join(f"{i['kind'].lower()} £{i['amount'] / r:,.2f}" for i in f.get("income") or [])
        pounds = f" In pounds at {r} to £1 (HMRC average for the year): {gbp}, tax £{(f.get('tax') or 0) / r:,.2f}."
    return "CHECK", [f"A {f.get('country') or 'foreign'} tax document ({f.get('period_from')} to {f.get('period_to')}): "
                     f"{what} {f.get('currency') or ''}, tax {f.get('tax') or 0:,.2f}.{pounds} Enter the income in pounds on "
                     f"Foreign income, time-apportioned to 6 April to 5 April if the country's year differs (R-SA106-05)."]


def summary(f: Dict[str, Any]) -> str:
    what = ", ".join(f"{i['kind'].lower()} {i['amount']:,.2f}" for i in f.get("income") or [])
    return f"{f.get('country') or 'foreign'} {f.get('currency') or ''} {what}".strip()
