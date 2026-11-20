"""The firm chart's short names and the ledger lines every later tab reads (ctx.tx_rows)."""

from datetime import datetime
from typing import Dict

import pandas as pd
from sqlalchemy import select

from backend.app.models.database import GLTransaction
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.workbook.context import short_chart_names


def _foreign_cells(currency, rate, amount):
    """(currency, rate, foreign amount) for GL Detail: a line in pounds (rate 1, no foreign amount) gives blanks."""
    def num(v):
        try:
            return float(str(v).replace(",", "").strip()) if v is not None and not pd.isna(v) and str(v).strip() else None
        except (TypeError, ValueError):
            return None
    rate, amount = num(rate), num(amount)
    cur = str(currency).strip().upper() if currency is not None and not pd.isna(currency) and str(currency).strip() else None
    if (rate is None or abs(rate - 1) < 1e-9) and cur in (None, "GBP"):
        return None, None, None
    if rate is None and amount is None:
        return None, None, None
    return cur, rate, amount


def step_7(ctx, s) -> None:
    """Account names from the firm chart (short form, without the bracketed section)"""
    ctx, db = s.ctx, s.db
    # STEP 7: Account names from the firm chart (short form, without the bracketed section)
    # -------------------------------------------------------------
    chart_names: Dict[int, str] = {}
    if db is not None:
        chart_names = short_chart_names(db)
    ctx.chart_names = chart_names

    # -------------------------------------------------------------


def step_7b(ctx, s) -> None:
    """the ledger lines (the ETB's movement per GL is read from them). Each: (date, code, type, account, source,
    description, reference, debit, credit, VAT, VAT code, currency, rate, foreign amount, name, split)"""
    ctx, db, engagement, gl_df, tb_records = s.ctx, s.db, s.engagement, s.gl_df, s.tb_records
    # STEP 7b: the ledger lines (the ETB's movement per GL is read from them)
    # -------------------------------------------------------------
    tx_rows = []
    if gl_df is not None and not gl_df.empty:
        for _, r in gl_df.iterrows():
            acc = str(r.get("Account") or r.get("Parent_Account") or r.get("raw_account_name") or "").strip()
            if not acc or acc.lower() in ["nan", "total"]:
                continue
            dt_val = r.get("Date") or r.get("Transaction date") or ""
            dt_str = dt_val.strftime("%d/%m/%Y") if isinstance(dt_val, (datetime, pd.Timestamp)) else str(dt_val) if pd.notna(dt_val) else ""
            desc = str(r.get("Description", "")).strip() if pd.notna(r.get("Description")) else ""
            ref = str(r.get("Reference", "") or r.get("No.", "")).strip() if pd.notna(r.get("Reference") or r.get("No.")) else ""
            src = str(r.get("Source", "") or r.get("Transaction type", "")).strip() if pd.notna(r.get("Source") or r.get("Transaction type")) else "GL"
            deb = float(r.get("Debit", 0.0) or 0.0)
            cred = float(r.get("Credit", 0.0) or 0.0)
            acc_code = str(r.get("Account Code") or "").strip()
            acc_type = str(r.get("Account Type") or "").strip()
            vat = r.get("VAT")
            vat = float(vat) if vat is not None and pd.notna(vat) and str(vat).strip() not in ("", "nan") else None
            vat_code = str(r.get("VAT Code") or "").strip() if pd.notna(r.get("VAT Code")) else ""
            # (the VAT on the line and its code, carried to GL Detail and the NL tabs when the ledger has them)
            fx = _foreign_cells(r.get("Currency"), r.get("Exchange Rate"), r.get("Foreign Amount"))
            party = tuple(str(r.get(k)).strip() if r.get(k) is not None and pd.notna(r.get(k)) and str(r.get(k)).strip()
                          else None for k in ("Name", "Split"))
            tx_rows.append((dt_str, acc_code, acc_type, acc, src, desc, ref, deb, cred, vat, vat_code, *fx, *party))
    elif db is not None:
        # In the ledger's own order (the order the lines were read): without it the database may return them in any
        # order, and the GL tab's rows would move between builds
        db_txs = db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement.id)
                            .order_by(GLTransaction.id)).scalars().all()
        from backend.app.services.sop.common import code_matcher
        gl_code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))   # sub-accounts by their parent too
        # A line in another currency: its currency, rate and own amount, kept beside it
        from backend.app.models.gl_foreign import GLForeign
        foreign = {f.gl_transaction_id: f for f in db.query(GLForeign).filter(GLForeign.engagement_id == engagement.id)}
        # The line's name and split (QuickBooks), kept beside it
        from backend.app.models.gl_parties import GLParty
        parties = {p.gl_transaction_id: (p.name, p.split)
                   for p in db.query(GLParty).filter(GLParty.engagement_id == engagement.id)}
        for tx in db_txs:
            dt_str = tx.transaction_date.strftime("%d/%m/%Y") if tx.transaction_date else ""
            acc_name = tx.raw_account_name or ""
            found = gl_code_of(acc_name)
            acc_code = str(found) if found is not None else ""
            tx_rows.append((
                dt_str,
                acc_code,
                "",
                acc_name,
                tx.source or "GL",
                tx.description or "",
                tx.reference or "",
                float(tx.debit_amount or 0.0),
                float(tx.credit_amount or 0.0),
                float(tx.vat_amount) if tx.vat_amount is not None else None,
                tx.vat_code or "",
                *_foreign_cells(*((foreign[tx.id].currency, foreign[tx.id].exchange_rate, foreign[tx.id].foreign_amount)
                                  if tx.id in foreign else (None, None, None))),
                *parties.get(tx.id, (None, None)),
            ))

    ctx.tx_rows = tx_rows

    # -------------------------------------------------------------
    s.tx_rows = tx_rows
