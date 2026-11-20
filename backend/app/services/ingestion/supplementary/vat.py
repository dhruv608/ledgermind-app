"""VAT: the VAT 100 returns and a VAT summary."""

import re
from typing import List

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models.database import VAT100Record
from backend.app.services.ingestion import vat_summary


class VatParsing:
    """VAT: the VAT 100 returns and a VAT summary. Mixed into SupplementaryParserService."""

    @classmethod
    def _store_vat_summary(cls, engagement_id: str, rows: List[List[str]], db: Session) -> int:
        """The VAT summary's returns as the client's VAT returns (Box 1 output, Box 4 input, Box 5 due, Box 6 the net
        sales when given; an opening row is last year's return still unpaid at the year start), with what was paid
        and when, and the VAT basis it was kept on. It replaces the returns entered before. Returns the count."""
        import json
        from backend.app.models.database import ClientEngagement, ClientProfile
        from backend.app.models.vat_payments import VatReturnPayment
        eng = db.get(ClientEngagement, engagement_id)
        if eng is None or eng.period_end_date is None:
            return 0
        summary = vat_summary.read(rows, eng.period_end_date)
        if summary is None or not summary.returns:
            return 0
        db.query(VAT100Record).filter(VAT100Record.engagement_id == engagement_id).delete(synchronize_session=False)
        db.query(VatReturnPayment).filter(VatReturnPayment.engagement_id == engagement_id).delete(synchronize_session=False)
        money = lambda v: None if v is None else round(float(v), 2)
        for r in summary.returns:
            due = money(r.due) or 0.0
            db.add(VAT100Record(
                engagement_id=engagement_id, period_label=r.label[:100], period_start=r.start, period_end=r.end,
                box1_vat_due_sales=money(r.output) or 0.0, box2_vat_due_acquisitions=0.0,
                box3_total_vat_due=money(r.output) or 0.0, box4_vat_reclaimed=money(r.input) or 0.0,
                box5_net_vat=due, box6_total_sales_ex_vat=money(r.sales) or 0.0,
                bfwd_outstanding=due if r.opening else None))
            db.add(VatReturnPayment(
                engagement_id=engagement_id, period_label=r.label[:100], period_end=r.end, paid=money(r.paid),
                paid_date=r.paid_date, paid_date_text=r.paid_date_text or None, outstanding=money(r.outstanding),
                interest=money(r.interest), basis=summary.basis))
        # A VAT summary means the client is VAT registered; its basis is the scheme (unless the accountant has
        # already confirmed an answer on the setup)
        profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement_id).first()
        if profile is not None:
            confirmed = set(json.loads(profile.confirmed_fields or "[]"))
            if "is_vat_registered" not in confirmed:
                profile.is_vat_registered = True
                if summary.basis:
                    profile.vat_scheme = summary.basis
        db.commit()
        return len(summary.returns)

    @classmethod
    def _parse_vat_100(cls, engagement_id: str, df: pd.DataFrame, db: Session) -> int:
        """Reads Box 1 to Box 9 from a VAT 100 return; the same return uploaded twice is stored once."""
        records_added = 0
        
        # Flatten text to locate box values
        box_values = {f"box{i}": 0.0 for i in range(1, 10)}
        period_label = "Quarter / Return Summary"

        for row_idx, row in df.iterrows():
            row_str = " ".join([str(v).lower() for v in row.values if pd.notna(v)])
            for i in range(1, 10):
                box_pattern = rf"box\s*{i}\b|box\s*0?{i}\b"
                if re.search(box_pattern, row_str):
                    # The last number in the row is the box value
                    nums = []
                    for val in row.values:
                        try:
                            clean_val = str(val).replace("£", "").replace(",", "").strip()
                            n = float(clean_val)
                            nums.append(n)
                        except (ValueError, TypeError):
                            continue
                    if nums:
                        box_values[f"box{i}"] = nums[-1]

        # If no boxes found via df iteration, fall back to line-by-line regex search across all cell values
        if not any(v != 0.0 for v in box_values.values()):
            try:
                for row_idx, row in df.iterrows():
                    for cell in row.values:
                        if pd.notna(cell):
                            cell_str = str(cell)
                            for i in range(1, 10):
                                m = re.search(rf"box\s*0?{i}\b[:\s\w\-\(\)\/]*?([£\$\€]?\s*[\d\,]+\.?\d*)", cell_str, re.IGNORECASE)
                                if m:
                                    clean_val = m.group(1).replace("£", "").replace("$", "").replace("€", "").replace(",", "").strip()
                                    try:
                                        box_values[f"box{i}"] = float(clean_val)
                                    except ValueError:
                                        pass
            except Exception:
                pass

        # Calculate Box 3 and Box 5 if omitted
        if box_values["box3"] == 0.0 and (box_values["box1"] != 0.0 or box_values["box2"] != 0.0):
            box_values["box3"] = round(box_values["box1"] + box_values["box2"], 2)
        if box_values["box5"] == 0.0 and (box_values["box3"] != 0.0 or box_values["box4"] != 0.0):
            box_values["box5"] = round(box_values["box3"] - box_values["box4"], 2)

        # Store record if any box has value (the same return uploaded again is not stored twice)
        same = db.query(VAT100Record).filter(
            VAT100Record.engagement_id == engagement_id,
            VAT100Record.box1_vat_due_sales == box_values["box1"],
            VAT100Record.box4_vat_reclaimed == box_values["box4"],
            VAT100Record.box6_total_sales_ex_vat == box_values["box6"],
            VAT100Record.box7_total_purchases_ex_vat == box_values["box7"],
        ).first()
        if same is None and any(v != 0.0 for v in box_values.values()):
            vat_rec = VAT100Record(
                engagement_id=engagement_id,
                period_label=period_label,
                box1_vat_due_sales=box_values["box1"],
                box2_vat_due_acquisitions=box_values["box2"],
                box3_total_vat_due=box_values["box3"],
                box4_vat_reclaimed=box_values["box4"],
                box5_net_vat=box_values["box5"],
                box6_total_sales_ex_vat=box_values["box6"],
                box7_total_purchases_ex_vat=box_values["box7"],
                box8_supplies_to_eu=box_values["box8"],
                box9_acquisitions_from_eu=box_values["box9"],
            )
            db.add(vat_rec)
            db.commit()
            records_added += 1

        return records_added
