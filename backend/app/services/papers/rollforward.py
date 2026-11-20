"""A balance sheet account's year on the Balance sheet tab: opening balance + this year's ledger lines (named:
sales invoices raised, bank receipts ...) + the journals approved in the app = the closing balance. The same check as the
workbook's B3 sheet: the opening plus the lines must come to the TB's closing balance; a difference means lines are
missing from the ledger or the opening is wrong."""

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.papers.t_lines import account_kind, line_name, named_by_words

GROUPS_SHOWN = 8        # the larger named lines each on their own line, the rest as "Other lines"


def rollforward(engagement: ClientEngagement, db: Session, codes: List[int]) -> Dict[str, Any]:
    from backend.app.services.reconciliation.control_accounts import _last_year_balances
    from backend.app.services.sop.common import code_matcher, ledger_rows
    from backend.app.services.tax.ct_computation import final_balances

    wanted = set(codes)
    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    tb_closing = round(sum(float(t.net_amount or 0) for t in tb_records if t.std_code in wanted), 2)
    final = final_balances(str(engagement.id), tb_records, db)
    closing = round(sum(final.get(c, 0.0) for c in wanted), 2)

    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
    lines = [tx for tx in ledger_rows(str(engagement.id), db) if code_of(tx.raw_account_name) in wanted]
    movement = round(sum(float(tx.net_amount or 0) for tx in lines), 2)

    # The opening: last year's job in the app, else the TB's opening column; else only what the lines imply
    last = _last_year_balances(engagement, db, tb_records)
    if last is not None:
        opening = round(sum(last.get(c, 0.0) for c in wanted), 2)
        source = "last year's job in the app" if getattr(last, "from_job", False) else "the trial balance's opening balances"
    else:
        opening, source = round(tb_closing - movement, 2), ""

    # Each line named as the accountant reads it ("Sales invoices raised", "Bank receipts" ...; t_lines), the
    # software's types kept as the line's reference
    chart = ChartLookup(db)
    kind = account_kind(wanted, [chart.name(c) for c in wanted] + sorted({tx.raw_account_name or "" for tx in lines}))
    groups: Dict[str, Dict[str, Any]] = {}
    own_kind: Dict[str, str] = {}
    for tx in lines:
        dr, cr = float(tx.debit_amount or 0), float(tx.credit_amount or 0)
        # The account's own name first when it says what it is (a loan kept on the pension code); else the paper's
        acct = tx.raw_account_name or ""
        if acct not in own_kind:
            code = code_of(acct)
            k = account_kind([code] if code is not None else [], [acct]) if acct else "other"
            own_kind[acct] = k if k != "other" else kind
        name = line_name(own_kind[acct], tx.source, dr - cr > 0, tx.description)
        g = groups.setdefault(name, {"type": name, "lines": 0, "debit": 0.0, "credit": 0.0, "types": {}})
        g["lines"] += 1
        g["debit"] += dr
        g["credit"] += cr
        typed = (tx.source or "").strip() or "no type"
        g["types"][typed] = g["types"].get(typed, 0) + 1
    ordered = sorted([g for g in groups.values() if abs(g["debit"]) >= 0.005 or abs(g["credit"]) >= 0.005],
                     key=lambda g: -abs(g["debit"] - g["credit"]))
    if len(ordered) > GROUPS_SHOWN:
        rest = ordered[GROUPS_SHOWN - 1:]
        types: Dict[str, int] = {}
        for g in rest:
            for t, n in g["types"].items():
                types[t] = types.get(t, 0) + n
        ordered = ordered[:GROUPS_SHOWN - 1] + [{"type": "Other lines", "lines": sum(g["lines"] for g in rest),
                                                 "debit": sum(g["debit"] for g in rest),
                                                 "credit": sum(g["credit"] for g in rest), "types": types}]
    for g in ordered:
        g["debit"], g["credit"] = round(g["debit"], 2), round(g["credit"], 2)
        g["net"] = round(g["debit"] - g["credit"], 2)
        g["types"] = [t for t, _ in sorted(g["types"].items(), key=lambda x: -x[1])]

    # The journals approved in the app, each on its own line; depreciation journals together as the charge for the
    # year, shown apart on fixed assets as in FRS 102 1A's movement table
    from backend.app.models.database import ProposedJournal
    approved = db.execute(select(ProposedJournal).where(ProposedJournal.engagement_id == engagement.id,
                                                        ProposedJournal.status == "APPROVED")).scalars().all()
    depreciation, journal_lines = 0.0, []
    for j in sorted(approved, key=lambda j: j.journal_ref or ""):
        if j.lines:
            legs = [(int(l.account_code), float(l.debit or 0) - float(l.credit or 0)) for l in j.lines]
        else:
            legs = [(int(j.debit_code), float(j.amount)), (int(j.credit_code), -float(j.amount))]
        effect = round(sum(v for c, v in legs if c in wanted), 2)
        if abs(effect) < 0.005:
            continue
        if any(chart.is_depreciation(c) for c, _ in legs) or "depreciat" in (j.description or "").lower():
            depreciation += effect
        else:
            # A journal the T names (use of home, dividend, interest charged) shows under that name, its ref beside it
            named = named_by_words(kind, j.description)
            journal_lines.append({"label": named or f"{j.journal_ref} {j.description or ''}".strip(), "amount": effect,
                                  **({"named": True, "note": f"journal {j.journal_ref}"} if named else {})})
    names = [chart.name(c, f"Account {c}") for c in sorted(wanted)]
    if abs(depreciation) >= 0.005:
        journal_lines.insert(0, {"label": "Depreciation for the year", "amount": round(depreciation, 2)})
    elif any("depreciation" in n.lower() for n in names) and not lines:
        journal_lines.insert(0, {"label": "Depreciation for the year", "amount": None,
                                 "note": "not run yet: approve the depreciation journal on the Journals page"})
    rest = round(closing - tb_closing - sum(l["amount"] or 0 for l in journal_lines), 2)
    if abs(rest) >= 0.005:
        journal_lines.append({"label": "Other journals approved in the app", "amount": rest})

    return {
        "codes": sorted(wanted),
        "names": names,
        "opening": opening,
        "opening_source": source,                 # "": worked out from the closing balance less the lines
        "movements": ordered,
        "lines": len(lines),
        "movement": movement,
        "tb_closing": tb_closing,
        "journals": round(closing - tb_closing, 2),
        "journal_lines": journal_lines,           # the journals by name: depreciation for the year first
        "closing": closing,
        # Opening + lines less the TB's closing balance (None when the opening is only worked out from them)
        "difference": round(opening + movement - tb_closing, 2) if source else None,
    }
