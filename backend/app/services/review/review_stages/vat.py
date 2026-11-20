"""Stage 2: the VAT review (returns against the ledger, the VAT account, blocked input VAT, other tax on the VAT account, flat rate scheme)."""

import logging
from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import (
    CLIENT_ENTERTAINING, CT_CREDITOR, ChartLookup, PAYE_NIC, VAT_CONTROL, account_name_keys)
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from backend.app.services.setup.profile_service import confirmed_industry
import pandas as pd
from backend.app.services.tax.vat_review import vat_review
from backend.app.services.review.point_figures import amounts

logger = logging.getLogger("backend.app.services.review.review_engine")   # the engine's own log name


class VatStage:
    """Stage 2: the VAT review (returns against the ledger, the VAT account, blocked input VAT, other tax on the VAT account, flat rate scheme). Mixed into SequentialReviewEngine."""

    # =========================================================================
    # Stage 2: VAT review
    # =========================================================================
    @classmethod
    def _execute_stage_2_vat(
        cls,
        engagement: ClientEngagement,
        profile: ClientProfile,
        tb_records: List[TBRecord],
        gl_df: pd.DataFrame,
        journal_counter: List[int],
        chart: ChartLookup,
        db: Session
    ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
        findings = []
        journals = []

        # --- Test V-D04: input VAT claimed on client entertaining ---
        # Blocked under SI 1992/3222 art 5 (staff entertaining is allowed): ledger lines on the accounts mapped to the
        # firm's client entertaining code, with the VAT the ledger shows was claimed
        entertaining_vat = 0.0
        entertaining_sources = []
        gl_codes = chart.gl_account_codes(tb_records)
        if not gl_df.empty:
            for _, row in gl_df.iterrows():
                code = next((gl_codes[k] for k in account_name_keys(row.get("account_name", "")) if k in gl_codes), None)
                if code == CLIENT_ENTERTAINING:
                    vat_claimed = row.get("vat_amount", 0.0)
                    if vat_claimed and vat_claimed > 0.01:
                        entertaining_vat += vat_claimed
                        entertaining_sources.append(row.get("source_row") or "")
        found_vat = round(entertaining_vat, 2)
        already = round(sum(float(j.amount or 0) for j in db.query(ProposedJournal).filter(
            ProposedJournal.engagement_id == engagement.id, ProposedJournal.status == "APPROVED",
            ProposedJournal.debit_code == CLIENT_ENTERTAINING, ProposedJournal.credit_code == VAT_CONTROL).all()), 2)
        entertaining_vat = round(found_vat - already, 2)

        # A question, not a journal: the account mixes client and staff entertaining more often than not, and the VAT on
        # staff entertaining may be claimed. The journal is written out for the accountant to post when the answer is
        # clients.
        if entertaining_vat > 0.01:
            journal_text = (f"Dr {CLIENT_ENTERTAINING} {chart.name(CLIENT_ENTERTAINING)} (£{entertaining_vat:,.2f}) / "
                            f"Cr {VAT_CONTROL} {chart.name(VAT_CONTROL)} (£{entertaining_vat:,.2f})")
            f = AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_2_VAT",
                procedure_ref="V-D04",
                procedure_name="VAT Review: Input Tax on Entertaining",
                severity="MEDIUM",
                source_row_ref=", ".join(entertaining_sources[:3]),
                finding_title=f"VAT claimed on entertaining (£{entertaining_vat:,.2f}): clients or staff?",
                finding_details=(
                    f"£{found_vat:,.2f} of VAT was claimed on the entertaining account"
                    + (f" (£{already:,.2f} already moved by approved journals, £{entertaining_vat:,.2f} left)" if already else "")
                    + ". VAT on entertaining UK clients cannot be claimed (VATA 1994 s24(7), SI 1992/3222 art 5); VAT on "
                    f"entertaining staff can. If it was clients, post: {journal_text}. If it was staff, nothing to change."
                    f"\n\nQuery to the client: Were these entertaining costs for clients or for your own staff (for example "
                    f"a staff party)? Please say which for each."
                ),
                quantified_amount=entertaining_vat,
                status="OPEN",
            )
            f.suggested_journal = journal_text
            findings.append(f)

        findings.extend(cls._blocked_input_vat(engagement, tb_records, gl_df, chart, db))
        findings.extend(cls._vat_code_mixes(engagement, tb_records, gl_df, chart))

        # --- VAT returns vs the ledger (V-F01 coverage, V-F04 arithmetic, V-C01/V-D01 Box 1 and Box 4 per
        #     return with V-I03 correction method, V-F02 Box 6 vs turnover, V-F03 VAT account vs unpaid returns, V-B01) ---
        review = vat_review(engagement, tb_records, db)
        for vf in review.findings:
            findings.append(AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_2_VAT",
                procedure_ref=vf.test,
                procedure_name="VAT Review: returns vs ledger (VAT guide)",
                severity=vf.severity,
                source_row_ref="G9.5 VAT return review",
                finding_title=vf.title[:255],
                finding_details=vf.details,
                quantified_amount=vf.amount,
                figures=vf.figures,
                status="OPEN",
            ))
        findings = cls._vat_account_point(engagement, tb_records, db, findings)
        other_findings, other_journals = cls._other_tax_on_vat(engagement, tb_records, journal_counter, chart, db)
        findings.extend(other_findings)
        journals.extend(other_journals)
        frs_findings, frs_journals = cls._flat_rate_scheme(engagement, profile, tb_records, review, journal_counter,
                                                           chart, db)
        if frs_journals:
            # The surplus journal (from the VAT account itself) replaces the written V-F06 point
            findings = [f for f in findings if f.procedure_ref != "V-F06"]
        findings.extend(frs_findings)
        journals.extend(frs_journals)
        if review.returns and not review.ledger_has_vat:
            findings.append(AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_2_VAT",
                procedure_ref="V-A02",
                procedure_name="VAT Review: returns vs ledger (VAT guide)",
                severity="LOW",
                source_row_ref="Ledger export",
                finding_title="The ledger export has no VAT columns: Box 1 and Box 4 could not be checked against the books",
                finding_details="Export the general ledger with the VAT code and VAT amount columns to check each return.",
                quantified_amount=0.0,
                status="OPEN",
            ))

        # Construction (CON): a reminder to check the CIS domestic reverse charge
        if confirmed_industry(profile) == "CON":
            f_drc = AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_2_VAT",
                procedure_ref="V-D05",
                procedure_name="VAT Review: CIS Domestic Reverse Charge (DRC)",
                severity="HIGH",
                source_row_ref="CIS Subcontractors",
                finding_title="Domestic Reverse Charge (DRC) Verification Required",
                finding_details=(
                    "Under VATA 1994 s55A, construction services between CIS registered contractors must be billed "
                    "with reverse charge wording where the customer accounts for Box 1 output tax instead of paying the supplier. "
                    "Confirm subcontractor invoices state: 'Reverse charge: Customer to pay the VAT to HMRC'."
                ),
                quantified_amount=0.0,
                status="OPEN",
            )
            findings.append(f_drc)

        return findings, journals

    # The VAT proof's lines that explain a VAT account differing from the returns (tested in this order),
    # with what each means and what to do
    VAT_EXPLAINS = {
        "opening_variance": ("opening variance", "the VAT account at the start of the year did not agree with what was owed "
                             "on last year's returns: check last year's VAT workings; an old error is cleared by journal"),
        "filed_not_in_accounts": ("VAT filed but not in the accounts", "the VAT account differs from the returns for the "
                                  "same months: an entry posted after its return was filed, or a return that does not "
                                  "match the books (G9 compares them return by return)"),
        "exception": ("exception report", "items on the software's VAT exception report, as typed in"),
        "flat_rate_surplus": ("flat rate surplus", "VAT charged at standard rates above the flat-rate VAT due: income (V-F06)"),
        "adjustments": ("adjustments", "as typed in on the VAT proof"),
    }

    @classmethod
    def _vat_account_point(cls, engagement: ClientEngagement, tb_records: List[TBRecord], db: Session,
                           findings: List[AuditFinding]) -> List[AuditFinding]:
        """V-F03 (VAT account v the returns) from the VAT proof, so the point and the proof on the VAT page always agree:
        the gap between the books and what the returns say is owed, the proof's lines that explain it (opening
        variance first, then the returns v the books by quarter), and a query only for what is left."""
        point = next((f for f in findings if f.procedure_ref == "V-F03"), None)
        if point is None:
            return findings
        from backend.app.services.tax.vat_proof import vat_proof
        try:
            proof = vat_proof(engagement, tb_records, db)
        except Exception:
            logger.exception("VAT proof failed for engagement %s: V-F03 left as worked out", engagement.id)
            return findings
        if proof.get("total") is None or proof.get("difference") is None:
            return findings
        books = proof["books"]
        explaining = [(l["key"], *cls.VAT_EXPLAINS[l["key"]], l["amount"]) for l in proof["lines"]
                      if l["key"] in cls.VAT_EXPLAINS and l["amount"] is not None and abs(l["amount"]) >= 1]
        per_returns = round(proof["total"] - sum(e[3] for e in explaining), 2)
        gap = round(books - per_returns, 2)
        left = proof["difference"]
        if abs(gap) <= 10:
            return [f for f in findings if f is not point]
        listed = "; ".join(f"{name} £{amount:,.2f}: {meaning}" for _k, name, meaning, amount in explaining)
        point.finding_details = (
            f"VAT owed per the books £{books:,.2f}; per the returns, less HMRC payments, plus VAT after the last return "
            f"£{per_returns:,.2f}: difference £{gap:,.2f}. "
            + (f"Where it sits, per the VAT proof: {listed}. " if explaining else "")
            + (f"Still unexplained £{left:,.2f}: check for journals posted to the VAT account, VAT on items that carry "
               f"none (wages, rates, insurance, bank charges), reverse charge lines that do not net to nil, and PAYE or "
               f"corporation tax payments posted to it." if abs(left) > 10 else "Nothing is left unexplained.")
        )
        point.figures = amounts([("Owed per the books", books), ("Owed per the returns, less payments", per_returns),
                                 ("Difference", gap, True)]
                                + [(f"of which: {name.lower()}", amount) for _k, name, _m, amount in explaining]
                                + ([("Still unexplained", left, True)] if abs(left) > 10 else []))
        if abs(left) > 10:
            point.finding_title = (f"VAT account £{books:,.2f} owed vs £{per_returns:,.2f} per the returns: "
                                   f"£{left:,.2f} unexplained")[:255]
            point.quantified_amount = abs(left)
        else:
            point.finding_title = (f"VAT account £{books:,.2f} owed vs £{per_returns:,.2f} per the returns: the "
                                   f"£{abs(gap):,.2f} is in the " + ", ".join(e[1] for e in explaining))[:255]
            point.quantified_amount = abs(gap)
            # An opening variance or a return that differs from the books still needs looking at; only what the
            # accountant typed in, or the flat rate surplus (its own point, V-F06), settles it
            if all(e[0] in ("exception", "adjustments", "flat_rate_surplus") for e in explaining):
                point.severity = "LOW"
        return findings

    @classmethod
    def _vat_code_mixes(cls, engagement: ClientEngagement, tb_records: List[TBRecord], gl_df: pd.DataFrame,
                        chart: ChartLookup) -> List[AuditFinding]:
        """V-A04: the same supplier coded more than one VAT way on the same P&L account (tax/vat_codes)."""
        from backend.app.services.tax.vat_codes import describe, supplier_mixes
        if gl_df.empty or "vat_code" not in gl_df.columns:
            return []
        gl_codes = chart.gl_account_codes(tb_records)
        lines = []
        for _, r in gl_df.iterrows():
            code = next((gl_codes[k] for k in account_name_keys(r.get("account_name", "")) if k in gl_codes), None)
            if code is not None and chart.is_pl(code):
                name = str(r.get("account_name", "")).strip()
                lines.append((name if name[:1].isdigit() else f"{code} {name}", r.get("description") or "", r.get("date"),
                              float(r.get("net_amount") or 0.0), r.get("vat_code") or ""))
        mixes = supplier_mixes(lines)
        if not mixes:
            return []
        title, details, amount, severity = describe(mixes)
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref="V-A04",
            procedure_name="VAT Review: VAT code consistency", severity=severity, finding_title=title[:255],
            finding_details=details, quantified_amount=amount, status="OPEN")]

    @classmethod
    def _blocked_input_vat(cls, engagement: ClientEngagement, tb_records: List[TBRecord], gl_df: pd.DataFrame,
                           chart: ChartLookup, db: Session) -> List[AuditFinding]:
        """V-D06 VAT on costs that carry none and V-D07 VAT on cars and fuel, from the ledger's VAT column
        (vat_blocked)."""
        from backend.app.services.tax import vat_blocked as vb
        if gl_df.empty or "vat_amount" not in gl_df.columns:
            return []
        gl_codes = chart.gl_account_codes(tb_records)
        rows = ((next((gl_codes[k] for k in account_name_keys(r.get("account_name", "")) if k in gl_codes), None),
                 float(r.get("vat_amount") or 0.0), r.get("source_row") or "") for _, r in gl_df.iterrows())
        by_code = vb.vat_by_code(rows)
        if not by_code:
            return []
        moved: Dict[int, float] = {}
        for j in db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                                  ProposedJournal.status == "APPROVED").all():
            if j.credit_code == VAT_CONTROL:
                moved[j.debit_code] = moved.get(j.debit_code, 0.0) + float(j.amount or 0)
            elif j.debit_code == VAT_CONTROL:
                moved[j.credit_code] = moved.get(j.credit_code, 0.0) - float(j.amount or 0)
        out: List[AuditFinding] = []
        for p in (vb.no_vat_costs(by_code, chart.name, lambda c: moved.get(c, 0.0)),
                  vb.cars_and_fuel(by_code, chart.name, lambda c: moved.get(c, 0.0))):
            if p is None:
                continue
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref=p.ref,
                procedure_name="VAT Review: input tax that cannot be claimed", severity=p.severity,
                source_row_ref=", ".join(p.sources), finding_title=p.title[:255], finding_details=p.details,
                quantified_amount=p.amount, status="OPEN", figures=p.figures)
            f.suggested_journal = p.journal
            out.append(f)
        return out

    # Corporation tax or PAYE paid to HMRC but posted to the VAT account (5300): moved to the right liability by
    # journal, one per tax
    OTHER_TAX_CODES = {"CT": (CT_CREDITOR, "corporation tax"), "PAYE": (PAYE_NIC, "PAYE and NI")}

    @classmethod
    def _other_tax_on_vat(cls, engagement: ClientEngagement, tb_records: List[TBRecord], journal_counter: List[int],
                          chart: ChartLookup, db: Session) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
        from backend.app.services.reconciliation.control_accounts import vat_position
        from backend.app.services.sop.common import gl_lines
        lines = gl_lines(str(engagement.id), tb_records, db)
        pos = vat_position(db, engagement, ((l.when, str(l.code), l.description, l.debit - l.credit, l.source)
                                            for l in lines))
        findings: List[AuditFinding] = []
        journals: List[ProposedJournal] = []
        for kind, (code, what) in cls.OTHER_TAX_CODES.items():
            paid = [t for t in pos.other_tax if t[3] == kind]
            net = round(sum(t[2] for t in paid), 2)        # debit +: paid; credit (-): a refund received
            amount = abs(net)
            if amount < 1:
                continue
            refund = net < 0
            dr, cr = (VAT_CONTROL, code) if refund else (code, VAT_CONTROL)
            listed = "; ".join(f"{t[0]:%d/%m/%Y} {str(t[1])[:60]} £{t[2]:,.2f}" for t in paid[:6])
            entry = f"Dr {dr} {chart.name(dr)} (£{amount:,.2f}) / Cr {cr} {chart.name(cr)} (£{amount:,.2f})"
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref="V-M08",
                procedure_name="VAT Review: other taxes on the VAT account", severity="HIGH" if amount >= 1000 else "MEDIUM",
                source_row_ref="VAT account",
                finding_title=(f"{what.capitalize()} {'refund' if refund else 'payment'} of £{amount:,.2f} posted to "
                               f"the VAT account")[:255],
                finding_details=(
                    (f"HMRC refunds of {what} were posted to the VAT account, so the VAT owed looks different and the "
                     f"{what} account still shows the refund due: " if refund else
                     f"HMRC payments for {what} were posted to the VAT account, so VAT looks paid when it is not and the "
                     f"{what} account looks unpaid: ")
                    + f"{listed}. They are not counted as VAT payments. A journal is proposed (Journals tab): {entry}."),
                quantified_amount=amount, suggested_journal=entry, status="OPEN")
            j = ProposedJournal(
                engagement_id=engagement.id, stage="STAGE_2_VAT", journal_ref=f"AJ{journal_counter[0]:02d}",
                description=f"{what.capitalize()} {'refund' if refund else 'paid'} posted to the VAT account, moved",
                debit_code=dr, debit_name=chart.name(dr), credit_code=cr, credit_name=chart.name(cr),
                amount=amount, status="PROPOSED")
            journal_counter[0] += 1
            j._point = f
            findings.append(f)
            journals.append(j)
        return findings, journals

    # Flat rate scheme (Notice 733): the VAT charged to customers above the flat-rate VAT due is the business's income,
    # not left in the VAT account, so it is cleared to income
    FRS_RATIO = (0.04, 0.17)        # Box 1 / Box 6 on flat rate returns (flat % of gross); standard-rated is about 0.20

    FRS_OTHER_INCOME = 550          # Other income - contributing to other operating income

    @classmethod
    def _flat_rate_scheme(cls, engagement: ClientEngagement, profile: ClientProfile, tb_records: List[TBRecord],
                          review, journal_counter: List[int], chart: ChartLookup, db: Session
                          ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
        from backend.app.services.tax.vat_review import FRS_MATERIAL, scheme_and_basis
        findings: List[AuditFinding] = []
        journals: List[ProposedJournal] = []
        checks = review.returns
        if not checks:
            return findings, journals
        scheme, _ = scheme_and_basis(getattr(profile, "vat_scheme", None))
        if scheme != "FLAT_RATE":
            # The returns look flat rate: nothing reclaimed in Box 4, Box 1 a flat % of the VAT-inclusive Box 6. Asked,
            # not assumed: a client query to confirm the scheme
            box1, box6 = sum(c.box1 for c in checks), sum(c.box6 for c in checks)
            reclaimed_nil = all(c.box4 <= max(50.0, 0.02 * c.box1) for c in checks)
            if box6 > 0 and box1 > 0 and reclaimed_nil and cls.FRS_RATIO[0] <= box1 / box6 <= cls.FRS_RATIO[1]:
                findings.append(AuditFinding(
                    engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref="V-F07",
                    procedure_name="VAT Review: flat rate scheme?", severity="MEDIUM", source_row_ref="VAT returns",
                    finding_title=(f"The VAT returns look like the flat rate scheme (Box 1 {box1 / box6:.1%} of Box 6, "
                                   f"nothing reclaimed): confirm the VAT scheme"),
                    finding_details=(
                        f"On all {len(checks)} return(s) this year Box 4 is nil or almost nil and Box 1 (£{box1:,.2f}) is "
                        f"{box1 / box6:.1%} of Box 6 (£{box6:,.2f}): a flat percentage of turnover, as on the flat rate "
                        f"scheme, where standard-rated returns show about 20% and reclaim input VAT. If the client is on "
                        f"the flat rate scheme, set it in the client details (VAT scheme: flat rate): the VAT the books "
                        f"charge above the flat-rate VAT due is then taken to income (Notice 733). Query to the client: "
                        f"Are you on the VAT flat rate scheme, and at what percentage?"),
                    quantified_amount=0.0, status="OPEN"))
            return findings, journals

        from backend.app.services.tax.vat_proof import vat_proof
        proof = vat_proof(engagement, tb_records, db)
        amounts = {l["key"]: l["amount"] for l in proof.get("lines", [])}
        surplus = amounts.get("flat_rate_surplus")
        if surplus is not None and surplus >= FRS_MATERIAL:
            entry = (f"Dr {VAT_CONTROL} {chart.name(VAT_CONTROL)} (£{surplus:,.2f}) / "
                     f"Cr {cls.FRS_OTHER_INCOME} {chart.name(cls.FRS_OTHER_INCOME)} (£{surplus:,.2f})")
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref="V-F06",
                procedure_name="VAT Review: flat rate surplus", severity="HIGH" if surplus >= 1000 else "MEDIUM",
                source_row_ref="VAT account", finding_title=f"Flat rate scheme: surplus of £{surplus:,.2f} left in the VAT account",
                finding_details=(
                    f"The VAT account this year holds £{surplus:,.2f} more than the flat-rate returns charged for the same "
                    f"months: the books charge customers VAT at the full rate, the returns pay a flat % of turnover, and the "
                    f"difference is the business's income (VAT Notice 733), not owed to HMRC. A journal is "
                    f"proposed (Journals tab): {entry}. Check the flat % and the sector (16.5% for a limited cost trader)."),
                quantified_amount=surplus, suggested_journal=entry, status="OPEN")
            j = ProposedJournal(
                engagement_id=engagement.id, stage="STAGE_2_VAT", journal_ref=f"AJ{journal_counter[0]:02d}",
                description="Flat rate scheme surplus taken to income", debit_code=VAT_CONTROL,
                debit_name=chart.name(VAT_CONTROL), credit_code=cls.FRS_OTHER_INCOME,
                credit_name=chart.name(cls.FRS_OTHER_INCOME), amount=surplus, status="PROPOSED")
            journal_counter[0] += 1
            j._point = f
            findings.append(f)
            journals.append(j)
        earlier = amounts.get("opening_variance")
        if earlier is not None and earlier >= FRS_MATERIAL:
            # Earlier years' surplus never cleared: whether to clear it is a judgement, so asked
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_2_VAT", procedure_ref="V-F08",
                procedure_name="VAT Review: flat rate surplus of earlier years", severity="MEDIUM",
                source_row_ref="VAT account",
                finding_title=f"VAT account brought forward £{earlier:,.2f} more than the returns then owed",
                finding_details=(
                    f"At the start of the year the VAT account held £{earlier:,.2f} more than the flat-rate returns still "
                    f"owed: probably earlier years' flat rate surplus never taken to income. If so, it belongs to the "
                    f"years it arose (a prior year adjustment, FRS 102 s10) or, if small, to income this year: decide and "
                    f"post (Dr {VAT_CONTROL} / Cr reserves or income). If part is VAT really owed, check with HMRC."),
                quantified_amount=earlier, status="OPEN"))
        return findings, journals
