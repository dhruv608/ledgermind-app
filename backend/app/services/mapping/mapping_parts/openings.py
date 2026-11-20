"""Opening balances: P&L openings closed to reserves, and fixed asset openings split or rolled forward from last year's
closing figures."""

from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA, TBRecord
from backend.app.services.mapping.mapping_parts.common import (
    BROUGHT_FORWARD, DIVIDEND_CODES, FIXED_ASSET_CODES, IN_YEAR_COST, IN_YEAR_DEPRECIATION,
)


class OpeningFixes:
    """Opening balances: P&L openings closed to reserves, and fixed asset openings split or rolled forward from last
    year's closing figures. Mixed into MappingService."""

    @staticmethod
    def close_pl_openings(engagement_id: str, records: List[TBRecord], db: Session) -> None:
        """A ledger whose year was not closed (Sage) gives P&L accounts an opening balance: last year's sales, costs and
        dividends. They open this year inside 8000 profit and loss b/fwd, so this year's P&L is this year's only.
        Runs again when a code changes (an account found to be P&L later is closed then)."""
        RETAINED = 8000
        chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars().all()}

        def is_pl(code: Optional[int]) -> bool:
            c = chart.get(code) if code is not None else None
            return bool(c and (c.financial_class == "Profit and Loss" or (8000 < code < 8100)))

        moving = [r for r in records if r.opening_amount is not None and abs(float(r.opening_amount or 0)) >= 0.005
                  and is_pl(r.std_code)]
        if not moving:
            return
        target = next((r for r in records if r.std_code == RETAINED), None)
        if target is None:
            name = chart[RETAINED].std_name if RETAINED in chart else "Balance b/fwd (Profit and loss account)"
            target = TBRecord(
                engagement_id=engagement_id, raw_account_name=f"{RETAINED:04d} - {name}",
                debit_amount=0.0, credit_amount=0.0, net_amount=0.0, opening_amount=0.0,
                std_code=RETAINED, std_name=name, mapping_status="MATCHED", confidence_score=1.0,
                match_source="ROLL_FORWARD", mapping_reason="Added to carry last year's profit and loss brought forward.",
            )
            records.append(target)
            db.add(target)
        for rec in moving:
            opening = round(float(rec.opening_amount), 2)
            # Last year's dividends the client already cleared to retained earnings this year (a credit on the dividend
            # account, e.g. Xero's "Opening equity adjustment" journal): that part is in 8000 already, so it stays
            # (opening and credit cancel) and only what is still on the account moves
            cleared = min(opening, float(rec.credit_amount or 0.0)) if rec.std_code in DIVIDEND_CODES and opening > 0 else 0.0
            if cleared >= 0.005:
                opening = round(opening - cleared, 2)
                rec.opening_amount = round(cleared, 2)
                note = f"Last year's £{cleared:,.2f} already cleared to retained earnings by the client's journal: not moved again."
                rec.mapping_reason = f"{rec.mapping_reason or ''} {note}".strip()
                if abs(opening) < 0.005:
                    continue
            else:
                rec.opening_amount = 0.0
            rec.net_amount = round(float(rec.net_amount or 0.0) - opening, 2)
            target.opening_amount = round(float(target.opening_amount or 0.0) + opening, 2)
            target.net_amount = round(float(target.net_amount or 0.0) + opening, 2)
            note = f"Last year's £{abs(opening):,.2f}{' Cr' if opening < 0 else ''} moved to {RETAINED:04d} profit and loss b/fwd."
            rec.mapping_reason = f"{rec.mapping_reason or ''} {note}".strip()

    @staticmethod
    def _fixed_asset_bf_codes(db: Session) -> Tuple[Dict[int, MasterCOA], Dict[int, int]]:
        """Each in-year fixed asset code (additions, disposals, depreciation charge, impairment...) with the brought-
        forward code of its asset group (cost b/fwd, depreciation / amortisation b/fwd)."""
        coa = {c.std_code: c for c in db.execute(
            select(MasterCOA).where(MasterCOA.std_code.between(*FIXED_ASSET_CODES))).scalars().all()}
        out: Dict[int, int] = {}
        for code, account in coa.items():
            group = [c for c in coa.values() if c.std_code // 10 == code // 10]
            if IN_YEAR_DEPRECIATION.search(account.std_name):
                target = next((c for c in group if BROUGHT_FORWARD.search(c.std_name)), None)
            elif IN_YEAR_COST.search(account.std_name):
                target = next((c for c in group if "cost" in c.std_name.lower()), None)
            else:
                continue
            if target is not None and target.std_code != code:
                out[code] = target.std_code
        return coa, out

    @staticmethod
    def _split_closing_fixed_asset_openings(engagement_id: str, pairs: List[Tuple[TBRecord, Optional[float]]],
                                            records: List[TBRecord], db: Session) -> None:
        """A closing TB keeps last year's balance on an in-year fixed asset account (QuickBooks and Xero never empty
        'Cost - additions' or 'Depn - charge'): the ledger's beginning balance on it is last year's, so it moves to
        the group's brought-forward account and the in-year account keeps this year's movement only. Without it last
        year's additions get this year's AIA and last year's charge reads as this year's depreciation."""
        moving = [(rec, op) for rec, op in pairs if op is not None and abs(op) >= 0.005 and rec.opening_amount is None]
        if not moving:
            return
        coa, bf = OpeningFixes._fixed_asset_bf_codes(db)
        by_code = {}
        for rec in records:
            by_code.setdefault(rec.std_code, rec)
        for rec, opening in moving:
            dest = bf.get(rec.std_code)
            if dest is None:
                continue
            target = by_code.get(dest)
            if target is None:
                target = TBRecord(
                    engagement_id=engagement_id, raw_account_name=f"{dest:04d} - {coa[dest].std_name}",
                    debit_amount=0.0, credit_amount=0.0, net_amount=0.0, opening_amount=None,
                    std_code=dest, std_name=coa[dest].std_name, mapping_status="MATCHED", confidence_score=1.0,
                    match_source="ROLL_FORWARD", mapping_reason="Added to carry last year's balance brought forward.")
                records.append(target)
                db.add(target)
                by_code[dest] = target
            rec.net_amount = round(float(rec.net_amount or 0.0) - opening, 2)
            target.net_amount = round(float(target.net_amount or 0.0) + opening, 2)
            # The trial balance tabs read the debit / credit columns: they show the split too (the TB still balances)
            for r in (rec, target):
                r.debit_amount, r.credit_amount = max(float(r.net_amount), 0.0), max(-float(r.net_amount), 0.0)
            note = (f"Last year's £{abs(opening):,.2f}{' Cr' if opening < 0 else ''} (the ledger's beginning balance) "
                    f"moved to {dest:04d} brought forward: this account shows this year only.")
            rec.mapping_reason = f"{rec.mapping_reason or ''} {note}".strip()

    @staticmethod
    def _roll_forward_fixed_asset_openings(engagement_id: str, records: List[TBRecord], db: Session) -> None:
        """Last year's in-year fixed asset accounts (additions, disposals, depreciation charge, impairment...) open
        the new year inside the brought-forward accounts of the same asset group: cost b/fwd and depreciation /
        amortisation b/fwd. Only opening balances move (clients whose TB holds this year's movements)."""
        coa = {c.std_code: c for c in db.execute(
            select(MasterCOA).where(MasterCOA.std_code.between(*FIXED_ASSET_CODES))).scalars().all()}

        def brought_forward_code(code: int) -> Optional[int]:
            account = coa.get(code)
            if account is None:
                return None
            group = [c for c in coa.values() if c.std_code // 10 == code // 10]
            if IN_YEAR_DEPRECIATION.search(account.std_name):
                target = next((c for c in group if BROUGHT_FORWARD.search(c.std_name)), None)
            elif IN_YEAR_COST.search(account.std_name):
                target = next((c for c in group if "cost" in c.std_name.lower()), None)
            else:
                return None
            return target.std_code if target is not None and target.std_code != code else None

        by_code = {}
        for rec in records:
            by_code.setdefault(rec.std_code, rec)

        for rec in list(records):
            opening = float(rec.opening_amount or 0.0)
            if abs(opening) < 0.005 or rec.std_code is None:
                continue
            dest = brought_forward_code(rec.std_code)
            if dest is None:
                continue
            target = by_code.get(dest)
            if target is None:
                target = TBRecord(
                    engagement_id=engagement_id,
                    raw_account_name=f"{dest:04d} - {coa[dest].std_name}",
                    debit_amount=0.0, credit_amount=0.0, net_amount=0.0, opening_amount=0.0,
                    std_code=dest, std_name=coa[dest].std_name,
                    mapping_status="MATCHED", confidence_score=1.0, match_source="ROLL_FORWARD",
                    mapping_reason="Added to carry last year's balance brought forward.",
                )
                records.append(target)
                db.add(target)
                by_code[dest] = target
            rec.opening_amount = 0.0
            rec.net_amount = round(float(rec.net_amount or 0.0) - opening, 2)
            target.opening_amount = round(float(target.opening_amount or 0.0) + opening, 2)
            target.net_amount = round(float(target.net_amount or 0.0) + opening, 2)
            note = f"Opening £{opening:,.2f} moved to {dest:04d} (last year's movement brought forward)."
            rec.mapping_reason = f"{rec.mapping_reason or ''} {note}".strip()
