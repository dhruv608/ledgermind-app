"""The extended trial balance on screen: per firm code, the TB, the journals approved in the app and the final balance
(as on the workbook's B1-ETB sheet), with last year's final balance beside it."""

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup


def etb(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.reconciliation.control_accounts import _last_year_balances
    from backend.app.services.tax.ct_computation import final_balances

    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    tb: Dict[int, float] = {}
    names: Dict[int, List[str]] = {}
    for t in tb_records:
        if t.std_code is None:
            continue
        tb[t.std_code] = tb.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
        if t.raw_account_name and t.raw_account_name not in names.setdefault(t.std_code, []):
            names[t.std_code].append(t.raw_account_name)
    final = final_balances(str(engagement.id), tb_records, db)
    last = _last_year_balances(engagement, db, tb_records)
    chart = ChartLookup(db)

    rows = []
    for code in sorted(set(tb) | set(final) | set(last or {})):
        before, after = tb.get(code, 0.0), final.get(code, 0.0)
        # The opening balances give the balance sheet only: last year's profit and loss is then not known
        from_job = getattr(last, "from_job", False)
        ly = None if last is None or (chart.is_pl(code) and not from_job) else last.get(code)
        if all(abs(v or 0.0) < 0.005 for v in (before, after, ly)):
            continue
        rows.append({
            "code": code,
            "name": chart.name(code, f"Account {code}"),
            "accounts": names.get(code, []),
            "pl": bool(chart.is_pl(code)),
            "tb": round(before, 2),
            "journals": round(after - before, 2),
            "final": round(after, 2),
            "last_year": None if ly is None else round(ly, 2),
        })
    unmapped = sum(float(t.net_amount or 0.0) for t in tb_records if t.std_code is None)
    return {
        "rows": rows,
        "last_year_source": "" if last is None else ("last year's job" if getattr(last, "from_job", False)
                                                    else "the opening balances"),
        "unmapped": round(unmapped, 2),
        "totals": {k: round(sum(r[k] for r in rows), 2) for k in ("tb", "journals", "final")},
    }
