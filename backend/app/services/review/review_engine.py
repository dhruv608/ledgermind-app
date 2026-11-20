"""
The review engine: runs the three review stages in order and saves their points and proposed journals.
- Stage 1: Accounting checks (the firm's SOP checks, general checks, director's loan, industry checks)
- Stage 2: VAT review (returns against the ledger, coverage, VAT account, entertaining)
- Stage 3: Corporation tax computation (services/tax/ct_computation.py) and s455

Each stage is its own module (review/review_stages: accounting, vat, ct600), mixed into the engine.
"""
from typing import Any, Dict, List, Optional, Tuple
from backend.app.models.database import AuditFinding, ClientEngagement, GLTransaction, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM
from pathlib import Path
from backend.app.services.setup.profile_service import ProfileService
from sqlalchemy.orm import Session
from backend.app.services.review.setup_checks import TRIVIAL_NOTE, apply_materiality
from backend.app.services.checks.progress import step as _step
from datetime import datetime
import json
import logging

import pandas as pd
from sqlalchemy import or_
from backend.app.services.tax.vat_review import registration_findings
from backend.app.services.tax.s455 import s455_charge

from backend.app.services.review.review_stages.accounting import AccountingStage
from backend.app.services.review.review_stages.vat import VatStage
from backend.app.services.review.review_stages.ct600 import Ct600Stage

logger = logging.getLogger(__name__)


class SequentialReviewEngine(AccountingStage, VatStage, Ct600Stage):
    @classmethod
    def _load_json(cls, file_path: Path) -> Any:
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    @classmethod
    def run_full_sequential_review(
        cls,
        engagement_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """Runs the three stages in order (accounting, VAT, corporation tax), reading the job's ledger once for the
        whole run (sop/common.ledger_read_once)."""
        from backend.app.services.sop.common import ledger_read_once
        with ledger_read_once():
            return cls._run_full_sequential_review(engagement_id, db)

    @classmethod
    def _run_full_sequential_review(
        cls,
        engagement_id: str,
        db: Session
    ) -> Dict[str, Any]:
        _step("books")
        engagement = db.query(ClientEngagement).filter(ClientEngagement.id == engagement_id).first()
        if not engagement:
            raise ValueError(f"Engagement {engagement_id} not found")

        # The client profile, detected when the job has none yet
        profile = engagement.profile
        if not profile:
            profile = ProfileService.auto_detect_profile(db, engagement_id)

        # No asset register this year: last year's LM job's asset list carried forward
        from backend.app.services.ingestion.supplementary.far_carry import carry_assets_from_last_year
        carry_assets_from_last_year(engagement, db)

        # Clear existing unapproved findings & proposed journals for this engagement. Cleared points stay, and the
        # same point is not raised again below; the tax computation (CT-01) is always rebuilt.
        db.query(AuditFinding).filter(
            AuditFinding.engagement_id == engagement_id,
            or_(AuditFinding.status == "OPEN", AuditFinding.procedure_ref == "CT-01",
                AuditFinding.cleared_note.like(f"{TRIVIAL_NOTE}%")),
        ).delete(synchronize_session=False)
        already_cleared = {
            (f.procedure_ref, f.finding_title, f.source_row_ref or "")
            for f in db.query(AuditFinding).filter(AuditFinding.engagement_id == engagement_id).all()
        }
        
        # Only the engine's own unapproved proposals are replaced; journals entered by an accountant stay. Their lines
        # go first: a bulk delete does not cascade, and Postgres refuses journals whose lines are still there
        from sqlalchemy import delete, select
        from backend.app.models.database import JournalLine
        replaced = select(ProposedJournal.id).where(
            ProposedJournal.engagement_id == engagement_id,
            ProposedJournal.status == "PROPOSED",
            or_(ProposedJournal.source == "REVIEW", ProposedJournal.source.is_(None)),
        )
        db.execute(delete(JournalLine).where(JournalLine.journal_id.in_(replaced)))
        db.query(ProposedJournal).filter(ProposedJournal.id.in_(replaced)).delete(synchronize_session=False)
        db.commit()

        # Load GL transactions into DataFrame
        gl_rows = db.query(GLTransaction).filter(GLTransaction.engagement_id == engagement_id).all()
        if gl_rows:
            gl_data = []
            for r in gl_rows:
                debit = float(r.debit_amount or 0.0)
                credit = float(r.credit_amount or 0.0)
                net = float(r.net_amount or (debit - credit))
                gl_data.append({
                    "date": r.transaction_date,
                    "account_name": r.raw_account_name or "",
                    "description": r.description or "",
                    "counterparty": r.reference or "",
                    "reference": r.reference or "",
                    "net_amount": net,
                    "vat_amount": r.signed_vat,   # the ledger's VAT column with the line's sign (none if the export has no VAT)
                    "vat_code": r.vat_code or "",
                    "gross_amount": abs(net),
                    "source_row": f"GL-{r.id}",
                })
            gl_df = pd.DataFrame(gl_data)
        else:
            gl_df = pd.DataFrame()

        tb_records = db.query(TBRecord).filter(TBRecord.engagement_id == engagement_id).all()
        tb_diff = round(sum(float(t.net_amount or 0) for t in tb_records), 2)
        tb_all_nil = not tb_records or not any(abs(float(t.net_amount or 0)) >= 0.01 for t in tb_records)
        if abs(tb_diff) >= 0.01 or tb_all_nil:
            title = (
                f"The trial balance is out by £{abs(tb_diff):,.2f} — fix the TB import before running the review"
                if abs(tb_diff) >= 0.01
                else "The trial balance has no balances — fix the TB import before running the review"
            )
            what_found = (
                f"Debits less credits come to £{tb_diff:,.2f} (expected £0.00)."
                if abs(tb_diff) >= 0.01
                else "Every line in the trial balance has a zero net balance."
            )
            finding = AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref="U-TB-001",
                procedure_name="Industry Library (UNIV): TB integrity",
                severity="CRITICAL",
                source_row_ref="TB integrity",
                finding_title=title[:255],
                finding_details=(
                    f"What the app found: {what_found} All downstream checks (accruals, going concern, "
                    "debtors/creditors, payroll, VAT, and corporation tax) have been skipped until the trial balance "
                    "is valid.\n\n"
                    "Query to the client: The trial balance provided does not balance. Please provide a balanced TB "
                    "or explain the difference.\n"
                    "Evidence: Balanced TB export from the ledger. Ref: 2 Concepts"
                ),
                quantified_amount=abs(tb_diff),
                status="OPEN",
            )
            db.add(finding)
            engagement.review_run_at = datetime.utcnow()
            db.commit()
            return {
                "engagement_id": engagement_id,
                "total_findings": 1,
                "total_journals": 0,
                "tax_computation": None,
                "stages": {
                    "stage_1_accounting": 1,
                    "stage_2_vat": 0,
                    "stage_3_ct600": 0,
                },
            }

        chart = ChartLookup(db)

        findings: List[AuditFinding] = []
        journals: List[ProposedJournal] = []
        kept_refs = [j.journal_ref for j in db.query(ProposedJournal.journal_ref)
                     .filter(ProposedJournal.engagement_id == engagement_id).all()]
        journal_counter = [1 + max((int(r[2:]) for r in kept_refs if r and r.startswith("AJ") and r[2:].isdigit()),
                                   default=0)]

        # The client setup as the review reads it (materiality, framework); None if it cannot be built
        try:
            from backend.app.services.setup.engagement_setup import build_record
            record = build_record(engagement, profile, db)
        except Exception:
            record = None

        # -------------------------------------------------------------
        # Stage 1: accounting checks
        # -------------------------------------------------------------
        s1_findings, s1_journals = cls._execute_stage_1_accounting(
            engagement, profile, tb_records, gl_df, journal_counter, chart, db, record
        )
        findings.extend(s1_findings)
        journals.extend(s1_journals)

        _step("vat")
        # -------------------------------------------------------------
        # Stage 2: VAT review (returns against the ledger)
        # -------------------------------------------------------------
        if profile.is_vat_registered:
            s2_findings, s2_journals = cls._execute_stage_2_vat(
                engagement, profile, tb_records, gl_df, journal_counter, chart, db
            )
            findings.extend(s2_findings)
            journals.extend(s2_journals)
        # VAT registration from the evidence, registered or not: over the threshold without registration, a VAT
        # balance on an unregistered client, a VAT account with no returns and no HMRC payment
        for vf in registration_findings(engagement, tb_records, db):
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref=vf.test,
                procedure_name="VAT Review: registration", severity=vf.severity, source_row_ref="Setup: VAT registration",
                finding_title=vf.title[:255], finding_details=vf.details, quantified_amount=vf.amount, status="OPEN"))

        # An LLP (setup/entity.py): no dividends, no s455, no corporation tax; its members are taxed on their shares
        from backend.app.services.setup.entity import COMPANY_ONLY_REFS, is_llp
        llp = is_llp(engagement, profile)
        if llp:
            dropped = {id(f) for f in findings if (f.procedure_ref or "").startswith(COMPANY_ONLY_REFS)}
            findings = [f for f in findings if id(f) not in dropped]
            journals = [j for j in journals if id(getattr(j, "_point", None)) not in dropped]

        _step("ct")
        # -------------------------------------------------------------
        # Stage 3: corporation tax (CT600)
        # -------------------------------------------------------------
        # The tax comes last, on the profit after the journals this run proposes: only the ones that will be saved
        # (not those of points the accountant already cleared, nor of points too small to raise)
        live = [f for f in findings if (f.procedure_ref, f.finding_title, f.source_row_ref or "") not in already_cleared]
        live_ids = set(map(id, live))
        to_save = [j for j in apply_materiality(live, journals, record)
                   if getattr(j, "_point", None) is None or id(j._point) in live_ids]
        if llp:
            s3_journals, tax_comp = [], None
            s3_findings = [AuditFinding(
                engagement_id=engagement.id, stage="STAGE_3_CT600", procedure_ref="U-CT-LLP",
                procedure_name="Corporation tax: not for an LLP", severity="LOW", source_row_ref="Setup: entity",
                finding_title="An LLP pays no corporation tax: no tax computation or CT600",
                finding_details=("The client is a limited liability partnership. Its trade is treated as carried on by "
                                 "its members in partnership (CTA 2009 s1273), who are taxed on their profit shares "
                                 "through their own returns, so no corporation tax is charged in the accounts. It has "
                                 "no shares, so no dividends, and is not a close company, so no s455 charge on money "
                                 "a member owes. The members' drawings stay on their accounts."),
                status="OPEN")]
        else:
            s3_findings, s3_journals, tax_comp = cls._execute_stage_3_ct600(
                engagement, profile, tb_records, gl_df, findings, to_save, journal_counter, chart, db
            )
        findings.extend(s3_findings)
        journals.extend(s3_journals)
        # An overdrawn directors' loan is one decision: the dividend-or-s455 point takes in the
        # overdrawn point's s455 working, so the area shows one point with the choice, not two
        dividend_point = next((f for f in findings if f.procedure_ref == "U-DIV-001"), None)
        overdrawn_point = next((f for f in findings if f.procedure_ref == "U-DLA-001"), None)
        if dividend_point is not None and overdrawn_point is not None:
            dividend_point.finding_details = f"{overdrawn_point.finding_details}\n\n{dividend_point.finding_details}"
            if overdrawn_point.severity == "CRITICAL":
                dividend_point.severity = "CRITICAL"
            findings.remove(overdrawn_point)

        _step("save")
        # Save all generated findings & journals (not the ones the accountant has already cleared, nor their journals).
        # Each journal records the point that proposed it; the corporation tax journal belongs to the computation.
        ct_point = next((f for f in findings if f.procedure_ref == "CT-01"), None)
        for j in journals:
            if getattr(j, "_point", None) is None and j.stage == "STAGE_3_CT600":
                j._point = ct_point
        findings = [f for f in findings if (f.procedure_ref, f.finding_title, f.source_row_ref or "") not in already_cleared]
        # Materiality from the setup: clearly trivial points are logged (cleared with a note), large ones raised
        journals = apply_materiality(findings, journals, record)
        kept = set(map(id, findings))
        journals = [j for j in journals if getattr(j, "_point", None) is None or id(j._point) in kept]
        from backend.app.services.review.point_gate import gate_points
        gate_points(findings)
        for f in findings:
            db.add(f)
        db.flush()
        for j in journals:
            if getattr(j, "_point", None) is not None:
                j.finding_id = j._point.id
            db.add(j)
        db.commit()

        engagement.review_run_at = datetime.utcnow()
        db.commit()

        return {
            "engagement_id": engagement_id,
            # Open points to look at: not the tax computation, not the trivial ones logged as cleared
            "total_findings": sum(1 for f in findings if f.status == "OPEN" and f.procedure_ref != "CT-01"),
            "total_journals": len(journals),
            "tax_computation": tax_comp,
            "stages": {
                "stage_1_accounting": len(s1_findings),
                "stage_2_vat": len(s2_findings) if profile.is_vat_registered else 0,
                "stage_3_ct600": len(s3_findings),
            }
        }

    @classmethod
    def _directors_loan_s455(cls, tb_records: List[TBRecord], gl_df: pd.DataFrame, chart: ChartLookup,
                             engagement: Optional[ClientEngagement] = None, db: Optional[Session] = None) -> Tuple[float, Dict[str, Any]]:
        """Overdrawn directors' loan balance and its s455 charge, with loans dated from the DLA ledger rows. The balance
        is after the journals approved in the app (e.g. a dividend credited to the DLA clears it), as in the tax
        computation."""
        dla_codes = (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM)
        dla_balance = chart.balance(tb_records, *dla_codes)
        advances = []
        if engagement is not None and db is not None:
            from backend.app.services.tax.ct_computation import final_balances
            after = final_balances(engagement.id, tb_records, db)
            journal_effect = round(sum(after.get(c, 0.0) for c in dla_codes) - dla_balance, 2)
            if abs(journal_effect) >= 0.01:
                dla_balance = round(dla_balance + journal_effect, 2)
                advances.append((engagement.period_end_date, journal_effect))
        if not gl_df.empty:
            gl_codes = chart.gl_account_codes(tb_records)
            for _, row in gl_df.iterrows():
                if gl_codes.get(str(row.get("account_name", "")).lower().strip()) in dla_codes:
                    advances.append((row.get("date"), float(row.get("net_amount") or 0.0)))
        # Last year's overdrawn balance carried its own s455 last year (as in the tax computation)
        dla_rows = [t for t in tb_records if t.std_code in dla_codes]
        charged_before = (max(0.0, sum(float(t.opening_amount or 0) for t in dla_rows))
                          if any(t.opening_amount is not None for t in dla_rows) else 0.0)
        return dla_balance, s455_charge(max(0.0, dla_balance - charged_before), advances)
