"""
Supplementary Schedule Parser Service
Intelligently classifies and extracts structured records from:
1. VAT 100 Returns (Quarterly or Annual HMRC 9-Box schedules)
2. Fixed Asset Registers (Asset descriptions, additions >£500, depreciation, NBV)
3. Payroll P32 / Annual Summaries (Gross pay, PAYE, Employee & Employer NIC, Pensions)

Each schedule is its own module (ingestion/supplementary: fixed_assets, payroll, vat),
mixed into the service.
"""

import csv
import io
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models.database import SupplementaryDocument
from backend.app.services.ingestion import vat_summary
from backend.app.services.loans import register as loans_register
from backend.app.services.ingestion.supplementary.fixed_assets import FixedAssetParsing
from backend.app.services.ingestion.supplementary.payroll import PayrollParsing
from backend.app.services.ingestion.supplementary.vat import VatParsing


class SupplementaryParserService(FixedAssetParsing, PayrollParsing, VatParsing):
    @classmethod
    def classify_file(cls, filename: str, content: bytes) -> str:
        """
        Classifies the file type into:
        - VAT_100
        - FIXED_ASSET_REGISTER
        - PAYROLL_P32
        - UNKNOWN
        """
        fname_lower = filename.lower()
        if "vat" in fname_lower and any(k in fname_lower for k in ["100", "return", "recon", "box", "q1", "q2", "q3", "q4"]):
            return "VAT_100"
        if any(k in fname_lower for k in ["fixed asset", "asset register", "depreciation schedule"]) or re.search(
                r"(^|[^a-z])far([^a-z]|$)", fname_lower):
            return "FIXED_ASSET_REGISTER"
        if any(k in fname_lower for k in ["payroll", "p32", "p60", "wages", "payslip"]):
            return "PAYROLL_P32"

        # Content inspection
        try:
            if fname_lower.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content), nrows=25, header=None)
            else:
                df = pd.read_excel(io.BytesIO(content), nrows=25, header=None)
            
            raw_text = " ".join(df.astype(str).values.flatten()).lower()
            
            # VAT checks
            if any(k in raw_text for k in ["box 1", "box 4", "box 6", "box 5", "vat due on sales", "vat reclaimed"]):
                return "VAT_100"
            
            # FAR checks
            if any(k in raw_text for k in ["net book value", "cost b/fwd", "depr b/fwd", "additions", "nbv"]):
                return "FIXED_ASSET_REGISTER"

            # Payroll checks
            if any(k in raw_text for k in ["employer nic", "employee nic", "gross pay", "p32", "tax deducted"]):
                return "PAYROLL_P32"
        except Exception:
            pass

        return "UNKNOWN"

    @classmethod
    def parse_and_store(
        cls,
        engagement_id: str,
        filename: str,
        content: bytes,
        forced_type: Optional[str] = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Reads the document by its type and saves its records; returns the stored document's details."""
        # Last year's final working paper in its own slot: read as any working paper is (its accruals,
        # prepayments, fixed asset tab, tax losses and final balances), and kept under its own name
        if forced_type == "LAST_YEAR_WP":
            info = cls.parse_and_store(engagement_id, filename, content, None, db)
            doc = db.get(SupplementaryDocument, info["id"])
            if doc is not None:
                doc.doc_type = "LAST_YEAR_WP"
                db.commit()
            return {**info, "doc_type": "LAST_YEAR_WP"}
        doc_type = forced_type or cls.classify_file(filename, content)
        if doc_type == "UNKNOWN":
            doc_type = "OTHER"

        file_size = len(content)
        parsed_count = 0

        # Next year's ledger: the months after the year end, kept apart as evidence
        if doc_type == "NEXT_YEAR_LEDGER":
            from backend.app.services.ingestion.next_year import store_next_year
            parsed_count = store_next_year(engagement_id, filename, content, db)
            return cls._store_document(engagement_id, doc_type, filename, file_size, parsed_count, db)

        # Last year's final working paper: its accruals and prepayments, item by item, to reverse this year; the file
        # goes on to the register reading below (its fixed asset tab)
        if filename.lower().endswith((".xlsx", ".xlsm")):
            cls._store_last_year_adjustments(engagement_id, content, db)

        # BrightPay payroll report: one line per employee per month
        rows = cls._raw_rows(filename, content)
        # Last year's final working paper as the register: its fixed asset tab (C1-1-FA detail), one row per asset
        if doc_type in ("FIXED_ASSET_REGISTER", "OTHER") and not cls._far_headers(rows):
            tab = cls._far_sheet_rows(filename, content)
            if tab:
                rows = tab

        # The firm's loans register (one row per loan / HP agreement): the terms for the loan schedules (G4)
        if loans_register.header_row(rows) is not None:
            parsed_count = cls._store_loan_agreements(engagement_id, rows, db)
            return cls._store_document(engagement_id, "LOANS_REGISTER", filename, file_size, parsed_count, db)
        brightpay_header = cls._brightpay_header(rows)
        if brightpay_header is not None:
            doc_type = "PAYROLL_P32"
            parsed_count = cls._parse_brightpay(engagement_id, rows, brightpay_header, db)
            cls._store_director_pay(engagement_id, filename, rows, db)
            return cls._store_document(engagement_id, doc_type, filename, file_size, parsed_count, db)

        # The client's VAT summary (the firm's layout: a row per return with output, input, due, paid, date, sales)
        if doc_type in ("VAT_100", "OTHER") and vat_summary.header_row(rows) is not None:
            parsed_count = cls._store_vat_summary(engagement_id, rows, db)
            if parsed_count:
                return cls._store_document(engagement_id, "VAT_100", filename, file_size, parsed_count, db)

        # The register as a summary: one column per asset class, the roll-forward down the rows
        if doc_type in ("FIXED_ASSET_REGISTER", "OTHER") and not cls._far_headers(rows) and cls._far_summary(rows):
            parsed_count = cls._parse_far_summary(engagement_id, rows, db)
            if parsed_count:
                return cls._store_document(engagement_id, "FIXED_ASSET_REGISTER", filename, file_size, parsed_count, db)

        # The firm's own fixed asset register (the working-paper layout): a block per class of asset
        if doc_type in ("FIXED_ASSET_REGISTER", "OTHER") and cls._far_headers(rows):
            parsed_count = cls._parse_far_schedule(engagement_id, rows, db)
            if parsed_count:
                return cls._store_document(engagement_id, "FIXED_ASSET_REGISTER", filename, file_size, parsed_count, db)
            # The register's headings with nothing but zeros under them: a blank template, reported as such on the
            # Data check rather than 'could not be read'
            if cls._far_blank(rows):
                return cls._store_document(engagement_id, "FIXED_ASSET_REGISTER_EMPTY", filename, file_size, 0, db)

        # A 'Payroll Summary (built from GL postings)': the books' own wage accounts month by month, not a payroll
        # report (no tax, NI or net pay to check against): kept as a file, nothing read from it
        if doc_type in ("PAYROLL_P32", "OTHER") and any(re.search(r"built\s+from\s+(?:the\s+)?(?:gl|general ledger|ledger)",
                                                                  " ".join(r), re.I) for r in rows[:6]):
            return cls._store_document(engagement_id, "PAYROLL_FROM_GL", filename, file_size, 0, db)

        # The firm's own 'Payroll Summary' (the working-paper layout): the company's months, then a block per person
        if cls._summary_headers(rows):
            parsed_count = cls._parse_payroll_summary(engagement_id, rows, db)
            if parsed_count:
                cls._store_director_pay(engagement_id, filename, rows, db)
                return cls._store_document(engagement_id, "PAYROLL_P32", filename, file_size, parsed_count, db)

        # Read into dataframe
        df = None
        try:
            if filename.lower().endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content))
            else:
                df = pd.read_excel(io.BytesIO(content))
        except Exception:
            # If reading with default header fails, read with no header
            try:
                if filename.lower().endswith(".csv"):
                    df = pd.read_csv(io.BytesIO(content), header=None)
                else:
                    df = pd.read_excel(io.BytesIO(content), header=None)
            except Exception:
                pass

        if df is not None and not df.empty:
            if doc_type == "VAT_100":
                parsed_count = cls._parse_vat_100(engagement_id, df, db)
            elif doc_type == "FIXED_ASSET_REGISTER":
                parsed_count = cls._parse_far(engagement_id, df, db)
            elif doc_type == "PAYROLL_P32":
                parsed_count = cls._parse_payroll(engagement_id, df, db)
        if doc_type == "PAYROLL_P32":
            cls._store_director_pay(engagement_id, filename, rows, db)

        return cls._store_document(engagement_id, doc_type, filename, file_size, parsed_count, db)

    @staticmethod
    def _store_wp_read(eng, got: dict, used: bool, db: Session) -> None:
        """What was read from last year's working paper, shown on the Data check for the reviewer to confirm: the year
        end, the ETB tab and its codes, the items."""
        import json as _json
        profile = getattr(eng, "profile", None)
        if profile is None:
            return
        try:
            inputs = _json.loads(profile.tax_inputs or "{}")
        except ValueError:
            inputs = {}
        tax = got.get("tax") or {}
        # Every spreadsheet uploaded is tried as last year's paper (payroll, supplier listings...): one that is not a
        # paper (no year end, no ETB) says nothing about it, and a paper read and used is not replaced by one not used
        if not got.get("year_end") and not tax.get("etb_tab"):
            return
        before = inputs.get("_last_year_wp_read") or {}
        if before.get("used") and not used:
            return
        kinds = [k for k, _n, _a in got.get("items") or []]
        inputs["_last_year_wp_read"] = {
            "year_end": got["year_end"].isoformat() if got.get("year_end") else None, "used": bool(used),
            "etb_tab": tax.get("etb_tab"), "etb_codes": len(tax.get("etb_final") or {}),
            "accruals": kinds.count("ACCRUAL"), "prepayments": kinds.count("PREPAYMENT"),
            "claims": len(got.get("claims") or []), "losses_cf": tax.get("losses_cf"),
            "loans": len(tax.get("loans_cf") or {}),
            "open_queries": len(tax.get("open_queries") or [])}
        profile.tax_inputs = _json.dumps(inputs)
        db.commit()

    @classmethod
    def _store_last_year_adjustments(cls, engagement_id: str, content: bytes, db: Session) -> int:
        """Last year's accruals and prepayments from last year's final WP (a paper whose year end is about a year
        before this job's) as the LAST_YEAR lines review/adjustments.py reverses, when none were entered by hand.
        Returns how many were stored."""
        from backend.app.models.database import ClientEngagement, TBRecord
        from backend.app.models.yearend_adjustments import YearEndAdjustment
        from backend.app.services.ingestion import last_year_adjustments as L
        from backend.app.services.mapping.chart_lookup import ChartLookup
        eng = db.get(ClientEngagement, engagement_id) if db is not None else None
        if eng is None or eng.period_end_date is None:
            return 0
        got = L.read(content)
        used = got["year_end"] is not None and 300 <= (eng.period_end_date - got["year_end"]).days <= 430
        cls._store_wp_read(eng, got, used, db)
        if not used:
            return 0
        # The director's claims last year's paper posted through the loan (use of home, salary, mileage)
        from backend.app.models.yearend_adjustments import LastYearClaim
        db.query(LastYearClaim).filter(LastYearClaim.engagement_id == engagement_id).delete(synchronize_session=False)
        for kind, why, amount in got.get("claims") or []:
            db.add(LastYearClaim(engagement_id=engagement_id, kind=kind, description=why[:255], amount=amount))
        # Last year's tax computation's losses carried forward (H1): this year's losses b/f unless the accountant
        # enters them (tax/ct_computation.py reads '_last_year_wp')
        profile = getattr(eng, "profile", None)
        if profile is not None:
            import json as _json
            try:
                inputs = _json.loads(profile.tax_inputs or "{}")
            except ValueError:
                inputs = {}
            inputs["_last_year_wp"] = got.get("tax") or {}
            profile.tax_inputs = _json.dumps(inputs)
        db.commit()
        if not got["items"]:
            return 0
        typed = db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement_id,
                                                   YearEndAdjustment.period == "LAST_YEAR")
        if any(not (r.description or "").endswith(L.SOURCE) for r in typed):
            return 0                                     # the accountant's own lines win
        typed.delete(synchronize_session=False)          # a re-upload replaces the paper's lines
        chart = ChartLookup(db)
        tb = [(t.std_code, t.raw_account_name) for t in db.query(TBRecord).filter(TBRecord.engagement_id == engagement_id)
              if t.std_code is not None]
        stored = 0
        # Only cost accounts: an accrual or prepayment is a cost paid late or early ('Interest on loan' is interest
        # payable, never 'Bank interest receivable')
        def is_cost(code: int) -> bool:
            return chart.section(code) in L.COST_SECTIONS
        for kind, name, amount in got["items"]:
            code = L.cost_code(name, tb, is_cost)
            # No cost found ('Accruals b/f 4,026.47'): kept with code 0, never reversed, but counted in last year's
            # total, so a list larger than what is still on 5360 / 4900 (the books released some) reverses nothing
            # automatically (U-ADJ-002)
            db.add(YearEndAdjustment(engagement_id=engagement_id, kind=kind, period="LAST_YEAR",
                                     description=f"{name[:200]}{L.SOURCE}", cost_code=code or 0, amount=amount))
            stored += 1
        db.commit()
        return stored

    @classmethod
    def _store_document(cls, engagement_id: str, doc_type: str, filename: str, file_size: int, parsed_count: int, db: Session) -> Dict[str, Any]:
        supp_doc = SupplementaryDocument(
            engagement_id=engagement_id,
            doc_type=doc_type,
            filename=filename,
            file_size_bytes=file_size,
            parsed_records_count=parsed_count,
        )
        db.add(supp_doc)
        db.commit()
        db.refresh(supp_doc)

        return {
            "id": supp_doc.id,
            "engagement_id": engagement_id,
            "doc_type": doc_type,
            "filename": filename,
            "file_size_bytes": file_size,
            "parsed_records_count": parsed_count,
            "created_at": supp_doc.created_at,
        }

    @classmethod
    def _raw_rows(cls, filename: str, content: bytes) -> List[List[str]]:
        """Every row of the file as text cells (the CSV or the first sheet)."""
        try:
            if filename.lower().endswith(".csv"):
                return [r for r in csv.reader(io.StringIO(content.decode("utf-8-sig", errors="replace")))]
            df = pd.read_excel(io.BytesIO(content), header=None)
            return [["" if pd.isna(v) else str(v) for v in r] for r in df.values.tolist()]
        except Exception:
            return []

    @classmethod
    def _store_loan_agreements(cls, engagement_id: str, rows: List[List[str]], db: Session) -> int:
        """The agreements on the loans register (replacing an earlier register's)."""
        from backend.app.models.loan_agreements import LoanAgreement
        found = loans_register.read(rows)
        db.query(LoanAgreement).filter(LoanAgreement.engagement_id == engagement_id).delete(synchronize_session=False)
        db.query(SupplementaryDocument).filter(SupplementaryDocument.engagement_id == engagement_id,
                                               SupplementaryDocument.doc_type == "LOANS_REGISTER").delete(synchronize_session=False)
        for a in found:
            db.add(LoanAgreement(engagement_id=engagement_id, lender=a.lender, kind=a.kind or None, drawdown=a.drawdown,
                                 first_payment=a.first_payment, amount=a.amount, deposit=a.deposit, payments=a.payments,
                                 per_year=a.per_year, rate=a.rate, charge=a.charge, payment=a.payment,
                                 balloon=a.balloon, method=a.method))
        db.commit()
        return len(found)
