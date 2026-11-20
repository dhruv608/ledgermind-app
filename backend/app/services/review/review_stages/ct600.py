"""Stage 3: the corporation tax computation, s455, dividends and the CT600 points."""

from typing import Any, Dict, List, Tuple
from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import CT_CHARGE, CT_CREDITOR, ChartLookup
from sqlalchemy.orm import Session
from backend.app.services.tax.ct_computation import ct_computation, ct_hold_limit
import json, pandas as pd

from backend.app.services.review.review_stages.common import (
    CT_RECOVERABLE_SHORT, S455_RECOVERABLE, SUSPENSE_CODE, TRANSFERS_CODE)


class Ct600Stage:
    """Stage 3: the corporation tax computation, s455, dividends and the CT600 points. Mixed into SequentialReviewEngine."""

    # =========================================================================
    # Stage 3: corporation tax (CT600)
    # =========================================================================
    @classmethod
    def _execute_stage_3_ct600(
        cls,
        engagement: ClientEngagement,
        profile: ClientProfile,
        tb_records: List[TBRecord],
        gl_df: pd.DataFrame,
        prior_findings: List[AuditFinding],
        prior_journals: List[ProposedJournal],
        journal_counter: List[int],
        chart: ChartLookup,
        db: Session
    ) -> Tuple[List[AuditFinding], List[ProposedJournal], Dict[str, Any]]:
        findings = []
        journals = []

        # The firm's Tax_Comp computation, from the final balances: TB plus journals approved in the app
        # plus the journals this run proposes (prior_journals), so the tax is on the corrected profit
        comp = ct_computation(engagement, tb_records, db, prior_journals)
        ct_tax, s455_tax, total_ct_liability = comp.corporation_tax, comp.s455_tax, comp.total_tax

        # Next year's setup starts from what this computation carries forward (losses and capital allowance pools)
        if profile is not None:
            inputs = json.loads(profile.tax_inputs or "{}")
            inputs["_carried_forward"] = {"losses_bf": round(comp.losses_carried_forward + comp.property_losses_carried_forward, 2), "main_pool_bf": comp.main_pool_cf,
                                          "special_pool_bf": comp.special_pool_cf, "period_end": str(engagement.period_end_date)}
            profile.tax_inputs = json.dumps(inputs)

        # Last year's tax over / under provided: what is left on the CT creditor besides this year's charge
        from backend.app.services.review import yearend_journals as _yj
        from backend.app.services.sop.common import gl_lines as _gl_lines
        from backend.app.services.tax.ct_computation import final_balances as _fb
        py_findings, py_journals = _yj.ct_prior_year(engagement, chart, journal_counter,
                                                     _fb(engagement.id, tb_records, db, prior_journals),
                                                     _gl_lines(str(engagement.id), tb_records, db))
        findings.extend(py_findings)
        journals.extend(py_journals)

        # A bank-route profit is not final while money sits in suspense or a transfer has no other side (clearing them
        # can change the taxable profit a lot): the computation is shown, but no tax charge or dividend is proposed
        from backend.app.services.tax.ct_computation import final_balances as _fbs
        _now = _fbs(engagement.id, tb_records, db, prior_journals)
        unsettled = {c: round(_now.get(c, 0.0), 2) for c in (SUSPENSE_CODE, TRANSFERS_CODE)
                     if abs(_now.get(c, 0.0)) >= 0.005}
        # Only for books the app built from the bank (a TB client's suspense is often accounts still to map, which
        # the computation already notes)
        from backend.app.services.bank_only.books import is_books_client
        held = is_books_client(engagement) and round(sum(abs(v) for v in unsettled.values()), 2) > ct_hold_limit(db)
        if held:
            # 9998 is the bank route's own in-between account, not in the firm's chart
            names = {TRANSFERS_CODE: "transfers between own accounts", SUSPENSE_CODE: "Suspense account"}
            what = " and ".join(f"£{abs(v):,.2f} in {chart.name(c) or names[c]} ({c})" for c, v in unsettled.items())
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_3_CT600", procedure_ref="U-CT-003",
                procedure_name="Corporation tax computation (CT600 guide, Tax_Comp)", severity="HIGH",
                source_row_ref="H1-Taxation",
                finding_title=f"Corporation tax not proposed yet: {what} still to clear"[:255],
                finding_details=(f"The computation (tax £{ct_tax:,.2f}) runs on a profit that still holds {what}. Each "
                                 f"line there may be income, a cost, a loan or capital, so the profit and the tax are "
                                 f"not final. Clear them (the client questions, the Books tab), then run the review "
                                 f"again: the tax charge and any dividend are proposed then."),
                quantified_amount=round(sum(abs(v) for v in unsettled.values()), 2), suggested_journal=None,
                status="OPEN",
            ))

        # Propose the corporation tax provision when the accounts do not hold it yet. Not for a period over 12 months:
        # it is two CT accounting periods (CTA 2009 s10), each with its own computation, and one computation on the
        # whole is only an estimate (CT-GEN-001 asks for the split)
        to_provide = round(ct_tax - comp.tax_in_accounts, 2)
        # Losses brought forward probably there but not known: the reserves brought forward are in deficit and no loss
        # figure is entered or read from last year's working paper (CT-LOS-001 asks for it). Trading losses carried
        # forward are set against this year's profit (CTA 2010 s45 / s45A), so a charge worked out without them is too
        # high: it is not proposed until the figure is entered. Shown as a point instead
        from backend.app.services.workbook.ct600 import LOSS_HINT, RESERVES_BF
        _inputs = json.loads(profile.tax_inputs or "{}") if profile is not None else {}
        # The deficit as last year's filed closing shows it (reserve b/f, last year's P&L and dividends, debit +) when
        # known (this year's books can hold a different 8000), else this year's reserve brought forward
        from backend.app.services.review.opening_balances import last_year_closing
        _ly = last_year_closing(engagement, db)[1]
        _deficit = (round(sum(v for c, v in _ly.items() if c < 4000 or 8000 <= c <= 8099), 2) if _ly
                    else round(_now.get(RESERVES_BF, 0.0), 2))
        losses_unknown = (to_provide > 0.01 and _inputs.get("losses_bf") in (None, "")
                          and not (_inputs.get("_last_year_wp") or {}).get("losses_cf") and _deficit >= LOSS_HINT)
        if losses_unknown and not held:
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_3_CT600", procedure_ref="U-CT-004",
                procedure_name="Corporation tax computation (CT600 guide, Tax_Comp)", severity="HIGH",
                source_row_ref="H1-Taxation",
                finding_title="Corporation tax not proposed yet: losses brought forward not entered"[:255],
                finding_details=(f"The computation gives tax of £{ct_tax:,.2f} with no losses brought forward, but the "
                                 f"reserves brought forward are £{_deficit:,.2f} in deficit, so the company probably has "
                                 f"trading losses to set against this year's profit (CTA 2010 s45 / s45A). Enter the "
                                 f"losses carried forward from last year's CT600 under Corporation tax in the client "
                                 f"details (enter 0 if there are none), then run the review again: the tax charge is "
                                 f"proposed then."),
                quantified_amount=round(to_provide, 2), suggested_journal=None, status="OPEN",
            ))
        if abs(to_provide) > 0.01 and not held and not losses_unknown and comp.days <= 366:
            ref_code = f"AJ{journal_counter[0]:02d}"
            journal_counter[0] += 1
            journals.append(ProposedJournal(
                engagement_id=engagement.id,
                stage="STAGE_3_CT600",
                journal_ref=ref_code,
                description=("Corporation tax charge for the period (CT600 Box 440)" if not comp.tax_in_accounts else
                             f"Corporation tax: adjust the charge in the accounts (£{comp.tax_in_accounts:,.2f}) to the computation"),
                debit_code=CT_CHARGE if to_provide > 0 else CT_CREDITOR,
                debit_name=chart.name(CT_CHARGE if to_provide > 0 else CT_CREDITOR),
                credit_code=CT_CREDITOR if to_provide > 0 else CT_CHARGE,
                credit_name=chart.name(CT_CREDITOR if to_provide > 0 else CT_CHARGE),
                amount=abs(to_provide),
                status="PROPOSED",
            ))

        # A dividend to clear the overdrawn directors' loan, within the reserves, is the accountant's decision
        # (U-DIV-001): proposed only once the profit is final, and s455 stays on the whole overdrawn balance until the
        # accountant decides (the next review then runs on the dividend, or books the full s455)
        from backend.app.services.review.dividends import dividend_to_clear_dla, dividends_posted_elsewhere
        if held:
            div_findings, div_journals = [], []
        else:
            # Payments described as dividends but posted elsewhere (U-DIV-002) come first
            div_findings, div_journals, on_dla = dividends_posted_elsewhere(engagement, tb_records, chart, db,
                                                                             journal_counter, ct_tax,
                                                                             list(prior_journals) + journals)
            more_f, more_j, _ = dividend_to_clear_dla(engagement, tb_records, chart, db, journal_counter,
                                                      list(prior_journals) + journals + div_journals, ct_tax, s455_tax,
                                                      already_dividends=on_dla)
            div_findings, div_journals = div_findings + more_f, div_journals + more_j
        findings.extend(div_findings)
        journals.extend(div_journals)

        # s455 on the overdrawn directors' loan: recoverable from HMRC once the loan is repaid, so booked as a debtor
        # against the CT creditor, as the accountant does (Dr 4550 / Cr 5310), less what the books already hold. While a
        # dividend waits for the accountant's decision it is in the computation only: its journal follows the decision
        # (approved: the loan is cleared; rejected: the next review books the full s455)
        # Held only while a dividend to clear the loan waits for the decision; a dividend found on a P&L code (U-DIV-002)
        # does not touch the loan, so its s455 is booked as usual
        from backend.app.services.review.dividends import DESCRIPTION as CLEAR_LOAN
        clearing = [j for j in div_journals if (j.description or "").startswith(CLEAR_LOAN)]
        if s455_tax > 0.01 and not clearing:
            from backend.app.services.tax.ct_computation import final_balances
            after = final_balances(engagement.id, tb_records, db, prior_journals)
            in_books = round(sum(after.get(c, 0.0) for c in (S455_RECOVERABLE, CT_RECOVERABLE_SHORT)), 2)
            to_book = round(s455_tax - in_books, 2)
            if to_book > 0.01:
                ref_code = f"AJ{journal_counter[0]:02d}"
                journal_counter[0] += 1
                journals.append(ProposedJournal(
                    engagement_id=engagement.id,
                    stage="STAGE_3_CT600",
                    journal_ref=ref_code,
                    description=("s455 tax on the overdrawn directors' loan (CT600A), recoverable when the loan is repaid"
                                 + (f": £{in_books:,.2f} already in the books" if in_books > 0.01 else "")),
                    debit_code=S455_RECOVERABLE,
                    debit_name=chart.name(S455_RECOVERABLE),
                    credit_code=CT_CREDITOR,
                    credit_name=chart.name(CT_CREDITOR),
                    amount=to_book,
                    status="PROPOSED",
                ))

        rate_text = "; ".join(f"{sl['from']:%d/%m/%Y}-{sl['to']:%d/%m/%Y}: {sl['basis']}"
                              + (f" (relief £{sl['marginal_relief']:,.2f})" if sl["marginal_relief"] else "")
                              for sl in comp.rate_slices)
        findings.append(AuditFinding(
            engagement_id=engagement.id,
            stage="STAGE_3_CT600",
            procedure_ref="CT-01",
            procedure_name="Corporation tax computation (CT600 guide, Tax_Comp)",
            severity="HIGH" if total_ct_liability > 5000.0 else "MEDIUM",
            source_row_ref="H1-Taxation",
            finding_title=("Not final: " if held else "") + f"Corporation tax £{ct_tax:,.2f}" + (f" + s455 £{s455_tax:,.2f}" if s455_tax else "")
                          + f" on profits chargeable of £{comp.profits_chargeable:,.2f}",
            finding_details=(
                "\n".join(f"{l.label}{f' (Box {l.box})' if l.box else ''}: £{l.amount:,.2f}" for l in comp.lines)
                + (("\nCapital allowances: " + "; ".join(f"{a.label} £{a.amount:,.2f}" for a in comp.capital_allowances))
                   if comp.capital_allowances else "")
                + f"\nRate: {rate_text}. Associated companies: {comp.associated_companies}."
                + f"\nCarried forward: losses £{comp.losses_carried_forward:,.2f}, main pool £{comp.main_pool_cf:,.2f}, "
                  f"special rate pool £{comp.special_pool_cf:,.2f}."
                + (f"\nTax in the accounts £{comp.tax_in_accounts:,.2f}: difference £{comp.difference_to_accounts:,.2f}."
                   if comp.tax_in_accounts else "")
                + ("\nTo confirm: " + " ".join(comp.notes) if comp.notes else "")
            ),
            quantified_amount=total_ct_liability,
            status="OPEN",
            suggested_journal=f"Dr {CT_CHARGE} {chart.name(CT_CHARGE)} / Cr {CT_CREDITOR} {chart.name(CT_CREDITOR)} £{ct_tax:,.2f}",
        ))

        # The CT600 queries, each raised only when the books or the setup show its trigger
        from backend.app.services.workbook.ct600 import ct_queries
        from backend.app.services.tax.ct_computation import final_balances
        from backend.app.services.sop.common import gl_lines
        after_journals = final_balances(engagement.id, tb_records, db, prior_journals)
        queries_found = ct_queries(engagement, comp, list(tb_records), after_journals,
                                   chart.accounts, gl_lines(str(engagement.id), tb_records, db),
                                   json.loads(profile.tax_inputs or "{}") if profile is not None else {})
        findings.extend(queries_found)

        # Deferred tax (CT-DT-001): the difference proposed as a journal on its point, for the accountant to approve or
        # reject (FRS 102 s29; none for a micro-entity)
        from backend.app.services.workbook.ct600 import deferred_tax_working
        dt_point = next((f for f in queries_found if f.procedure_ref == "CT-DT-001"), None)
        dt = deferred_tax_working(engagement, comp, after_journals, chart.accounts) if dt_point is not None else None
        if dt is not None and not held:
            change = round(dt["needed"] - dt["provided"], 2)
            if abs(change) >= 0.01:
                DT_CHARGE, DT_PROVISION = 3801, 6100
                ref_code = f"AJ{journal_counter[0]:02d}"
                journal_counter[0] += 1
                up = change > 0
                j = ProposedJournal(
                    engagement_id=engagement.id, stage="STAGE_3_CT600", journal_ref=ref_code,
                    description=(f"Deferred tax on fixed assets: provision to £{dt['needed']:,.2f} "
                                 f"({dt['rate']:.1%} of £{dt['nbv'] - dt['wdv']:,.2f}, FRS 102 s29)"),
                    debit_code=DT_CHARGE if up else DT_PROVISION, debit_name=chart.name(DT_CHARGE if up else DT_PROVISION),
                    credit_code=DT_PROVISION if up else DT_CHARGE, credit_name=chart.name(DT_PROVISION if up else DT_CHARGE),
                    amount=abs(change), status="PROPOSED")
                j._point = dt_point
                journals.append(j)

        tax_comp = {
            "locked_pbt": comp.profit_before_tax,
            "disallowable_addbacks": round(sum(l.amount for l in comp.lines if l.label.startswith("Add:")), 2),
            "capital_allowances": round(sum(a.amount for a in comp.capital_allowances), 2),
            "taxable_profit": comp.profits_chargeable,
            "ct_rate_str": rate_text,
            "ct_tax": ct_tax,
            "marginal_relief": round(sum(sl["marginal_relief"] for sl in comp.rate_slices), 2),
            "s455_tax": s455_tax,
            "total_ct_due": total_ct_liability,
            "losses_carried_forward": comp.losses_carried_forward,
            "notes": comp.notes,
        }

        return findings, journals, tax_comp
