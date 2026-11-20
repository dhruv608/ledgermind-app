"""Stage 1: accounting checks (SOPs, general checks, director's loan, industry, fixed assets, stock, accruals, payroll, loans)."""

from typing import Any, Dict, List, Optional, Tuple
from backend.app.models.database import (
    AuditFinding, ClientEngagement, ClientProfile, FixedAssetRecord, ProposedJournal, TBRecord)
from backend.app.services.mapping.chart_lookup import ChartLookup, DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM, PAYE_NIC
from sqlalchemy.orm import Session
from backend.app.services.checks.progress import step as _step
from backend.app.services.review.point_figures import row, table
from backend.app.services.review.payroll_journals import (
    accrual_not_released, allowance_in_payroll, director_pay, directors_per_payroll, employment_allowance,
    hmrc_in_net_wages, missing_payroll, net_pay_overpaid_to_director, net_wages_cleared_elsewhere,
    prepayment_not_released)
from backend.app.services.setup.profile_service import confirmed_industry
from backend.app.services.review.setup_checks import depreciation_points, industry_points, prior_year_points
from backend.app.services.review.universal_checks import general_checks
import json, pandas as pd
from backend.app.services.sop.old_accruals import old_open_accruals
from backend.app.services.sop.findings import sop_findings

from backend.app.services.review.review_stages.common import INDUSTRIES_DIR


PACK_OF = {"prd": "prp", "cns": "pro"}      # property trading -> property, contractors -> professional


class AccountingStage:
    """Stage 1: accounting checks (SOPs, general checks, director's loan, industry, fixed assets, stock, accruals, payroll, loans). Mixed into SequentialReviewEngine."""

    # =========================================================================
    # Stage 1: accounting checks
    # =========================================================================
    @classmethod
    def _execute_stage_1_accounting(
        cls,
        engagement: ClientEngagement,
        profile: ClientProfile,
        tb_records: List[TBRecord],
        gl_df: pd.DataFrame,
        journal_counter: List[int],
        chart: ChartLookup,
        db: Session,
        record: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
        findings = []
        journals = []

        cap_limit = float(profile.capitalisation_threshold or 500.0)
        mat_limit = float(profile.materiality_threshold or 1000.0)

        # --- Opening balances: last year's closing against this year's opening, and the reserve brought forward ---
        _step("opening")
        from backend.app.services.review.opening_balances import opening_points
        ob_findings, ob_journals, ob_compared = opening_points(engagement, tb_records, chart, db, journal_counter,
                                                               mat_limit)
        findings.extend(ob_findings)
        journals.extend(ob_journals)
        from backend.app.services.review.opening_balances import reserves_moved
        findings.extend(reserves_moved(engagement, tb_records, chart, db, mat_limit))

        _step("general")
        # --- Revenue vs capital, prepayments and missing accruals, from the firm's SOPs (flags only: no journal is proposed) ---
        findings.extend(sop_findings(engagement, tb_records, db))

        # --- Checks for every client (Industry Query Library, UNIV): going concern, dividends, old debtors, cash ---
        for gf in general_checks(engagement, tb_records, db).findings:
            findings.append(AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref=gf.query,
                procedure_name="General checks (Industry Query Library, every client)",
                severity=gf.severity,
                source_row_ref="A1 - General checks",
                finding_title=gf.title[:255],
                finding_details=gf.details,
                quantified_amount=gf.amount,
                figures=gf.figures,
                status="OPEN",
            ))

        _step("cis")
        # --- CIS: labour with no CIS tax account, wages carrying CIS, CIS in the books but not in the setup ---
        from backend.app.services.cis.codes import cis_points
        from backend.app.services.sop.common import gl_lines as _gl_lines
        for p in cis_points(list(tb_records), _gl_lines(str(engagement.id), tb_records, db),
                            {t.std_code for t in tb_records if chart.is_sales(t.std_code)},
                            ((record or {}).get("cis") or {}).get("status")):
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=p.ref,
                procedure_name="CIS", severity=p.severity, source_row_ref="CIS",
                finding_title=p.title[:255], finding_details=p.details, quantified_amount=p.amount, status="OPEN"))
        # Subcontractor v employee: flags A-D on the individuals paid
        from backend.app.services.review.subcontractors import subcontractor_points
        findings.extend(subcontractor_points(engagement, profile, list(tb_records), db))
        # The CIS tests against HMRC (T1-T10): each failing test with the SOP's query
        from backend.app.services.cis.checks import check_points
        setup_cis = (json.loads(profile.setup or "{}").get("cis") or {}) if profile is not None and profile.setup else {}
        for c in check_points(engagement, db, setup_cis):
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=f"CIS-{c.ref}",
                procedure_name="CIS against HMRC", severity="HIGH" if c.ref in ("T1", "T10", "HMRC") else "MEDIUM",
                source_row_ref="CIS", finding_title=f"CIS {c.ref}: {c.name}: {c.summary}"[:255],
                finding_details=(f"Query to the {c.query_to.lower()}: {c.query}" if c.query else c.summary),
                quantified_amount=c.amount, status="OPEN"))
        # IND-CON-04: CIS suffered per the contractors' statements above the books: sales posted net, grossed up
        from backend.app.services.cis.gross_up import gross_up
        gu_findings, gu_journals = gross_up(engagement, list(tb_records), db, setup_cis, chart, journal_counter)
        findings.extend(gu_findings)
        journals.extend(gu_journals)
        # Loan repayments posted to a cost account (review/loan_repayments.py): moved to the loan
        from backend.app.services.review.loan_repayments import loan_repayment_points
        lr_findings, lr_journals = loan_repayment_points(engagement, list(tb_records), chart, db, journal_counter)
        findings.extend(lr_findings)
        journals.extend(lr_journals)
        # A debtor code in credit at the year end (review/wrong_side.py): a point, the reclassification suggested
        from backend.app.services.review.wrong_side import wrong_side_points
        findings.extend(wrong_side_points(engagement, list(tb_records), chart, db))

        # --- The FRS 102 rulebook: framework v size, accruals basis, netting, reserves b/fwd, amortisation, investment
        # property, loans written off, asset sales in turnover, the 2026 lease rules ---
        from backend.app.services.review.frs102_checks import frs102_points
        findings.extend(frs102_points(engagement, profile, list(tb_records), db))
        if ob_compared:
            # The opening balances check covers the reserve brought forward (E-004) balance by balance
            findings = [f for f in findings if f.procedure_ref != "E-004"]

        # --- The Industry Query Library checked against the books: a query is raised only when its trigger finds it ---
        from backend.app.services.review.query_triggers import triggered_points
        findings.extend(triggered_points(engagement, tb_records, record, confirmed_industry(profile), db))

        _step("dla")
        # --- Lead schedule F: the director's loan account, overdrawn and s455 ---
        dla_balance, s455 = cls._directors_loan_s455(tb_records, gl_df, chart, engagement, db)
        # A director overdrawn while another is owed: hidden by the net balance above (U-DLA-010)
        from backend.app.services.review.dla_per_director import overdrawn_hidden
        findings.extend(overdrawn_hidden(engagement, tb_records))
        dla_account_name = next((tb.raw_account_name for tb in tb_records if tb.std_code in (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM)), chart.name(DIRECTORS_LOAN))

        if dla_balance > 0.01: # a debit balance: the company has lent money to the director
            f = AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref="U-DLA-001",
                procedure_name="F Lead Schedule: Overdrawn Director Loan Account (s455)",
                severity="CRITICAL" if dla_balance > 10000.0 else "HIGH",
                source_row_ref=dla_account_name,
                finding_title=f"Overdrawn Director Loan Account: £{dla_balance:,.2f}",
                finding_details=(
                    f"The director loan account '{dla_account_name}' shows a net debtor balance of £{dla_balance:,.2f}. "
                    f"Under CTA 2010 Section 455, loans to participators outstanding 9 months and 1 day post year-end "
                    f"attract Section 455 tax of £{s455['tax']:,.2f}"
                    + (f" ({s455['explanation']})" if s455.get('explanation') else "") + ". "
                    "The rate depends on when each loan was made; repayments are taken to clear the oldest loans first."
                ),
                quantified_amount=dla_balance,
                status="OPEN",
            )
            findings.append(f)
        # Over £10,000 at any time in the year (not only at the year end): a beneficial loan for the P11D
        from backend.app.services.review.dla_peak import beneficial_loan_points
        findings.extend(beneficial_loan_points(engagement, list(tb_records), db,
                                               (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM)))

        _step("industry")
        # --- Industry queries from the query packs (only for an industry the accountant has confirmed) ---
        industry_code = (confirmed_industry(profile) or "UNIV").lower()
        from backend.app.services.setup.companies_house import sic_industry
        register = json.loads(profile.companies_house or "{}") if profile.companies_house else {}
        by_sic = sic_industry(register)
        if confirmed_industry(profile) and by_sic and confirmed_industry(profile) != by_sic:
            from backend.app.services.setup.engagement_setup import INDUSTRY_NAMES
            findings.append(AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref="U-TB-006",
                procedure_name="Industry differs from Companies House",
                severity="MEDIUM",
                source_row_ref="Client setup",
                finding_title=(f"Industry set as {INDUSTRY_NAMES.get(confirmed_industry(profile), confirmed_industry(profile))}, "
                               f"but the Companies House SIC code {', '.join(register.get('sic_codes', []))} says "
                               f"{INDUSTRY_NAMES.get(by_sic, by_sic)}")[:255],
                finding_details=("The industry decides which industry questions are asked. If the business has changed, "
                                 "keep it and clear this point with the reason; otherwise change the industry in the setup. "
                                 "Client question: Please confirm the principal activities of the business."),
                quantified_amount=0.0,
                status="OPEN",
            ))
        if confirmed_industry(profile) is None:
            from backend.app.services.setup.engagement_setup import INDUSTRY_NAMES as INDUSTRY_LABEL
            suggested = by_sic or (json.loads(profile.detection_signals or "{}") or {}).get("detected_industry") or profile.industry_code
            findings.append(AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref="U-TB-005",
                procedure_name="Client industry not confirmed",
                severity="LOW",
                source_row_ref="Client setup",
                finding_title=f"Please confirm the client's industry (the app suggests {INDUSTRY_LABEL.get(suggested, suggested)})",
                finding_details=("Industry-specific checks run only once the industry is confirmed on the client setup "
                                 "screen. " + (f"The suggestion comes from the Companies House SIC code "
                                 f"{', '.join(register.get('sic_codes', []))}. " if by_sic else
                                 "The suggestion comes from words in the accounts and ledger and can be wrong. ") +
                                 "Client question: Please confirm the principal activities of the business."),
                quantified_amount=0.0,
                status="OPEN",
            ))
        # Industries with no query pack of their own use the nearest one
        sector_file = INDUSTRIES_DIR / f"industry_{PACK_OF.get(industry_code, industry_code)}.json"
        sector_rules = cls._load_json(sector_file)

        if not sector_rules and industry_code != "univ":
            sector_rules = cls._load_json(INDUSTRIES_DIR / "industry_univ.json")

        # Industry queries: the setup answers decide which run (Yes on, No off, unanswered on)
        if confirmed_industry(profile):
            findings.extend(industry_points(engagement, profile, industry_code, sector_rules or [], record))

        _step("fixed_assets")
        # Depreciation at the rates on the setup, and last year's issues retested
        from backend.app.services.tax.ct_computation import final_balances
        from backend.app.services.review import yearend_journals
        after_approved = final_balances(engagement.id, tb_records, db)
        # Depreciation is charged on the fixed assets as they open, including the ones the opening balances journal
        # brings back from last year's closing (otherwise assets missing from the books get no depreciation)
        fa_base = dict(after_approved)
        for j in ob_journals:
            for l in (j.lines or []):
                if 4000 <= int(l.account_code) < 4200:
                    fa_base[int(l.account_code)] = fa_base.get(int(l.account_code), 0.0) + float(l.debit or 0) - float(l.credit or 0)
        # One ledger account holding both additions and disposals (or the charge and depreciation on disposals): each
        # side to its own code for the fixed asset note and the capital allowances (U-FA-020; class totals unchanged)
        from backend.app.services.review.fa_disposals import disposal_split
        ds_findings, ds_journals = disposal_split(engagement, tb_records, chart, db, journal_counter)
        findings.extend(ds_findings)
        journals.extend(ds_journals)
        register = db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement.id).all()
        if register:
            # The asset register gives the charge asset by asset; additions are dated from the ledger
            from backend.app.services.review.payroll_journals import _lines
            dated: Dict[int, list] = {}
            for code, g in _lines(engagement, tb_records, chart, db):
                if code in {c["cost"][i] for c in yearend_journals.ASSET_CLASS_CODES.values() for i in (0, 1)}:
                    dated.setdefault(code, []).append((g.transaction_date, float(g.net_amount or 0)))
            # Register additions the books expensed (found by amount and date in the P&L): moved to fixed assets first,
            # so the depreciation and the register / books check below see them as fixed assets
            from backend.app.services.sop.common import gl_lines
            # Register classes the books keep under another class's codes (fixtures in plant): one class for every check
            merged = yearend_journals.merged_classes(register, tb_records, after_approved)
            cap_findings, cap_journals, moved = yearend_journals.far_additions_in_pl(
                engagement, register, after_approved, gl_lines(engagement.id, tb_records, db), chart, journal_counter,
                merged=merged)
            after_far = dict(fa_base)
            for code, change in moved.items():
                after_far[code] = after_far.get(code, 0.0) + change
            # A class the register cannot give (not in it, or its value at the start differs from the books'):
            # worked from the books, as without a register (e.g. a class missing from the register, or assets filed
            # under the wrong class)
            from backend.app.services.review.setup_checks import depreciation_points as _books_dep
            unreliable = yearend_journals.register_unreliable_classes(register, tb_records, after_far, merged)
            dep_findings, dep_journals = yearend_journals.far_depreciation(
                engagement, profile, tb_records, chart, journal_counter, after_far, register, dated, skip=unreliable,
                merged=merged)
            if unreliable:
                bf, bj = _books_dep(engagement, profile, tb_records, chart, journal_counter, after_far, db, only=unreliable)
                dep_findings, dep_journals = dep_findings + bf, dep_journals + bj
            # The register tied to the books class by class (cost, additions, disposals, depreciation b/f)
            dep_findings = cap_findings + dep_findings + yearend_journals.far_books_check(
                engagement, register, after_far, dep_findings, merged)
            dep_journals = cap_journals + dep_journals
        else:
            # No register: P&L costs naming an asset moved to additions first, so the depreciation sees them
            from backend.app.services.review.capital_journals import capital_journals, g1_key, register_request
            cap_findings, cap_journals, moved, replaced = capital_journals(engagement, tb_records, chart, db,
                                                                           journal_counter)
            findings = [f for f in findings if not (f.procedure_ref == "G1" and g1_key(f) in replaced)]
            # And the other way round: running costs and repairs posted to the asset codes
            from backend.app.services.review.capital_journals import revenue_in_assets
            rev_findings, rev_journals, rev_moved = revenue_in_assets(engagement, tb_records, chart, db, journal_counter)
            cap_findings, cap_journals = cap_findings + rev_findings, cap_journals + rev_journals
            for code, change in rev_moved.items():
                moved[code] = round(moved.get(code, 0.0) + change, 2)
            after_cap = dict(fa_base)
            for code, change in moved.items():
                after_cap[code] = after_cap.get(code, 0.0) + change
            dep_findings, dep_journals = depreciation_points(engagement, profile, tb_records, chart, journal_counter,
                                                             after_cap, db)
            dep_findings = cap_findings + dep_findings + register_request(engagement, tb_records, after_cap)
            dep_journals = cap_journals + dep_journals
        findings.extend(dep_findings)
        journals.extend(dep_journals)
        _step("stock")
        stock_findings, stock_jnls = yearend_journals.stock_journals(engagement, profile, tb_records, chart,
                                                                     journal_counter, after_approved, db)
        findings.extend(stock_findings)
        journals.extend(stock_jnls)
        _step("accruals")
        # Accruals and prepayments entered line by line (and last year's, reversed cost by cost)
        from backend.app.services.review.adjustments import adjustment_journals, last_year_lines
        adj_findings, adj_journals = adjustment_journals(engagement, tb_records, chart, db, journal_counter, after_approved)
        # Not entered line by line: the fee accrual, prepayments and last year's released proposed as journals
        from backend.app.services.review.accrual_journals import accrual_prepayment_journals
        ap_findings, ap_journals, ap_replaces = accrual_prepayment_journals(engagement, tb_records, chart, db, journal_counter)
        # The accountant's own line for a cost wins: the app's accrual or prepayment on that cost is not proposed again
        # (an app item edited into the accountant's line)
        from backend.app.services.review.adjustment_edit import accountant_wins
        ap_findings, ap_journals = accountant_wins(engagement, db, ap_findings, ap_journals)
        findings.extend([f for f in adj_findings if f.procedure_ref not in ap_replaces] + ap_findings)
        journals.extend(adj_journals + ap_journals)
        # Next year's ledger, when uploaded: bills after the year end that belong to it (U-ACC-010)
        from backend.app.services.review.post_year_end_bills import post_year_end_accruals
        py_findings, py_journals = post_year_end_accruals(engagement, list(tb_records), chart, db, journal_counter, journals)
        findings.extend(py_findings)
        journals.extend(py_journals)
        from backend.app.services.review.adjustments import use_of_home
        uh_findings, uh_journals = use_of_home(engagement, tb_records, chart, db, journal_counter)
        findings.extend(uh_findings)
        journals.extend(uh_journals)
        # The director's salary the accountant gave (client details), through the director's loan
        from backend.app.services.review.adjustments import director_salary
        ds_findings, ds_journals = director_salary(engagement, tb_records, chart, db, journal_counter)
        findings.extend(ds_findings)
        journals.extend(ds_journals)
        # Dividends declared in the year that the books do not hold, as the accountant gave them (U-DIV-003)
        from backend.app.services.review.adjustments import dividends_declared
        dd_findings, dd_journals = dividends_declared(engagement, tb_records, chart, db, journal_counter)
        findings.extend(dd_findings)
        journals.extend(dd_journals)
        findings.extend(prior_year_points(engagement, profile, tb_records, chart, db))
        from backend.app.services.review.last_year import year_on_year_points
        findings.extend(year_on_year_points(engagement, tb_records, chart, db))

        # The uploaded fixed asset register (FAR): what it gave
        far_records = db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement.id).all()
        if far_records:
            total_far_additions = sum(float(r.additions or 0) for r in far_records)
            cap_limit = float(profile.capitalisation_threshold or 500.0)
            large_additions = [r for r in far_records if float(r.additions or 0) >= cap_limit]
            f_far = AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref="U-FAR-001",
                procedure_name="Lead Schedule B: Fixed Asset Register Roll-Forward",
                severity="LOW" if large_additions else "MEDIUM",
                source_row_ref="Fixed Asset Register",
                finding_title=f"Fixed asset register read: {len(far_records)} assets (£{total_far_additions:,.2f} additions)",
                finding_details=(
                    f"The fixed asset register gave {len(far_records)} assets, with additions of £{total_far_additions:,.2f} "
                    f"this period ({len(large_additions)} at or above the £{cap_limit:,.2f} capitalisation limit). Whether "
                    f"it agrees to the books is checked class by class (U-FAR-002); the capital allowances follow the "
                    f"additions in the books (H1)."
                ),
                quantified_amount=total_far_additions,
                status="OPEN",
            )
            findings.append(f_far)

        _step("payroll")
        # The payroll report (P32) against the books
        missing_er_ni = 0.0
        ea_in_payroll = 0.0
        ni_not_in_books, mp_ni = False, 0.0
        # The payroll report's rows for this accounting year (a file can hold more months); a row with
        # no date (a year's summary) is kept
        from backend.app.services.review.paye_check import _year as _pay_year
        _ps, _pe = _pay_year(engagement)
        # (none when the report is for another period: the Data check asks for this year's, payroll_period.py)
        from backend.app.services.review.payroll_period import usable as _usable_payroll
        payroll_records = [r for r in _usable_payroll(engagement, db)[0]
                           if r.period_end is None or _ps <= r.period_end <= _pe]
        # Pay the payroll report shows but the books never posted (or last year's director's salary, no report)
        mp_findings, mp_journals = missing_payroll(engagement, profile, tb_records, chart, db, journal_counter)
        findings.extend(mp_findings)
        journals.extend(mp_journals)
        if payroll_records:
            total_p32_gross = sum(float(r.gross_pay or 0) for r in payroll_records)
            total_p32_er_nic = sum(float(r.employer_nic or 0) for r in payroll_records)
            total_p32_hmrc = sum(float(r.total_hmrc_due or 0) for r in payroll_records)

            # Gross pay without an account named employer NI that the firm codes with the wages
            from backend.app.services.review.payroll_journals.common import EMPLOYER_NI_NAME
            tb_gross = chart.total_where([t for t in tb_records if not EMPLOYER_NI_NAME.search(t.raw_account_name or "")],
                                         chart.is_gross_wages)
            tb_paye_due = chart.balance(tb_records, PAYE_NIC)

            diff_gross = round(abs(total_p32_gross - tb_gross), 2)
            f_pay = AuditFinding(
                engagement_id=engagement.id,
                stage="STAGE_1_ACCOUNTING",
                procedure_ref="U-PAY-001",
                procedure_name="Lead Schedule I: Payroll P32 Triangulation",
                severity="HIGH" if diff_gross > 100.0 else "LOW",
                source_row_ref="P32 vs TB gross wages",
                finding_title=(f"Payroll report agrees with the books: £{total_p32_gross:,.2f} gross pay" if diff_gross <= 1
                               else f"Payroll report £{total_p32_gross:,.2f} gross pay vs books £{tb_gross:,.2f}: "
                                    f"£{diff_gross:,.2f} difference"),
                finding_details=(
                    f"P32 reports total Gross Pay of £{total_p32_gross:,.2f} and Employer NIC of £{total_p32_er_nic:,.2f}. "
                    f"Trial Balance gross wages and directors' salaries total £{tb_gross:,.2f}. Gross Pay variance is £{diff_gross:,.2f}. "
                    f"Total HMRC liability submitted: £{total_p32_hmrc:,.2f} vs TB PAYE/NIC creditor {PAYE_NIC} (£{abs(tb_paye_due):,.2f})."
                ),
                quantified_amount=diff_gross,
                status="OPEN",
                figures=table(["", "Payroll", "Books", "Difference"],
                              [row("Gross pay", total_p32_gross, tb_gross, diff_gross, strong=True),
                               row("Employer NIC", total_p32_er_nic, None, None)]),
            )
            findings.append(f_pay)

            # Employer NI in the payroll report but not in the books (the client posted gross pay only): propose the
            # journal the accountant would post (Dr employer NI / Cr PAYE & NI owed)
            employer_ni_codes = {3001, 3011, 1451, 1501, 2451, 2501}     # employee costs, cost of sales, distribution
            # The books: the TB plus employer NI already posted by approved journals (their debits only; the
            # employment allowance journal credits the same account and does not mean NI is missing)
            posted = 0.0
            for j in db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                                      ProposedJournal.status == "APPROVED").all():
                if j.lines:
                    posted += sum(float(l.debit or 0) for l in j.lines if int(l.account_code) in employer_ni_codes)
                elif int(j.debit_code) in employer_ni_codes:
                    posted += float(j.amount or 0)
            # and the employer NI in the missing payroll journal just proposed
            posted += sum(float(l.debit or 0) for j in mp_journals for l in j.lines if int(l.account_code) in employer_ni_codes)
            # The payroll report's NI is before the employment allowance: the books are compared before it too, so an
            # allowance already in the books ('EA' lines crediting employer NI) is added back (otherwise the allowance
            # would show as missing NI)
            from backend.app.services.review.payroll_journals import allowance_in_books_total, employer_ni_on_wage_codes
            # ...and NI the firm codes with the wages (an account named employer NI on 3000 / 1500): not missing
            books_er_ni = round(sum(float(t.net_amount or 0) for t in tb_records if t.std_code in employer_ni_codes)
                                + employer_ni_on_wage_codes(tb_records) + posted + max(allowance_in_books_total(engagement, tb_records, chart, db), 0.0), 2)
            # The payroll report shows NI before the employment allowance; books posted by the payroll's own
            # journals hold it after. That gap is the allowance, not missing NI
            ea_in_payroll = allowance_in_payroll(engagement, profile, tb_records, chart, db, total_p32_er_nic,
                                                 books_er_ni, employer_ni_codes)
            # The client's own books hold (almost) no employer NI: the NI comes from the payroll report through this
            # review (allowance step, below)
            ni_not_in_books = total_p32_er_nic >= 1.0 and books_er_ni - posted <= 0.1 * total_p32_er_nic
            mp_ni = round(sum(float(l.debit or 0) for j in mp_journals for l in j.lines
                              if int(l.account_code) in employer_ni_codes), 2)
            missing_er_ni = 0.0 if ea_in_payroll else round(total_p32_er_nic - books_er_ni, 2)
            if missing_er_ni >= 1.0:
                entry = (f"Dr 3001 {chart.name(3001)} (£{missing_er_ni:,.2f}) / "
                         f"Cr {PAYE_NIC} {chart.name(PAYE_NIC)} (£{missing_er_ni:,.2f})")
                f_ni = AuditFinding(
                    engagement_id=engagement.id,
                    stage="STAGE_1_ACCOUNTING",
                    procedure_ref="U-PAY-002",
                    procedure_name="Payroll: employer NI per the payroll report",
                    severity="HIGH" if missing_er_ni >= 1000.0 else "MEDIUM",
                    source_row_ref="Payroll report vs books",
                    finding_title=f"Employer NI £{missing_er_ni:,.2f} in the payroll report is not in the books",
                    finding_details=(
                        f"The payroll report shows employer NI of £{total_p32_er_nic:,.2f} for the year; the books (with the "
                        f"journals already approved) hold £{books_er_ni:,.2f} on the employer NI accounts. The cost is missing, so profit is overstated by "
                        f"£{missing_er_ni:,.2f}. A journal is proposed (Journals tab): {entry}."
                    ),
                    quantified_amount=missing_er_ni,
                    suggested_journal=entry,
                    status="OPEN",
                )
                j_ni = ProposedJournal(
                    engagement_id=engagement.id,
                    stage="STAGE_1_ACCOUNTING",
                    journal_ref=f"AJ{journal_counter[0]:02d}",
                    description="Employer NI per the payroll report, not posted in the books",
                    debit_code=3001,
                    debit_name=chart.name(3001),
                    credit_code=PAYE_NIC,
                    credit_name=chart.name(PAYE_NIC),
                    amount=missing_er_ni,
                    status="PROPOSED",
                )
                journal_counter[0] += 1
                j_ni._point = f_ni
                findings.append(f_ni)
                journals.append(j_ni)

        # The accountant's usual year-end payroll journals: employment allowance, directors' pay in the staff
        # accounts; and last year's prepayment still not released
        # The employer NI this review posts from the payroll report: U-PAY-002's and the missing payroll journal's
        ea_findings, ea_journals = employment_allowance(engagement, profile, tb_records, chart, db, journal_counter,
                                                        max(missing_er_ni, 0.0) + mp_ni, ea_in_payroll, ni_not_in_books)
        dp_findings, dp_journals = director_pay(engagement, profile, tb_records, chart, db, journal_counter)
        pp_findings, pp_journals = directors_per_payroll(engagement, tb_records, chart, db, journal_counter,
                                                         dp_journals + mp_journals)
        dp_findings, dp_journals = dp_findings + pp_findings, dp_journals + pp_journals
        nw_findings, nw_journals = net_wages_cleared_elsewhere(engagement, tb_records, chart, db, journal_counter)
        hm_findings, hm_journals = hmrc_in_net_wages(engagement, tb_records, chart, db, journal_counter)
        nw_findings, nw_journals = nw_findings + hm_findings, nw_journals + hm_journals
        from backend.app.services.review.payroll_journals.hmrc_elsewhere import hmrc_paye_elsewhere
        he_findings, he_journals = hmrc_paye_elsewhere(engagement, tb_records, chart, db, journal_counter,
                                                       journals + ea_journals + dp_journals + nw_journals)
        nw_findings, nw_journals = nw_findings + he_findings, nw_journals + he_journals
        from backend.app.services.review.payroll_journals.not_on_payroll import pay_not_on_payroll
        no_findings, no_journals = pay_not_on_payroll(engagement, tb_records, chart, db, journal_counter,
                                                      journals + ea_journals + dp_journals + nw_journals)
        nw_findings, nw_journals = nw_findings + no_findings, nw_journals + no_journals
        op_findings, op_journals = net_pay_overpaid_to_director(engagement, profile, tb_records, chart, db, journal_counter)
        nw_findings, nw_journals = nw_findings + op_findings, nw_journals + op_journals
        _step("loans")
        # PAYE and the pension agreed to the HMRC and provider statements typed on the Balance sheet tab
        from backend.app.services.review.paye_check import interest_on_paye, other_tax_on_paye, statement_points
        findings.extend(statement_points(engagement, tb_records, chart, db, mat_limit))
        # Any other typed statement figure that does not agree and has no reason: a query (U-REC-001)
        from backend.app.services.review.statement_differences import unexplained_differences
        findings.extend(unexplained_differences(engagement, tb_records, chart, db, mat_limit))
        # A currency bank's statement at the year-end rate: the exchange difference journal (U-REC-002)
        from backend.app.services.review.fx_difference import fx_journals
        fx_findings, fx_js = fx_journals(engagement, list(tb_records), chart, db, journal_counter)
        findings.extend(fx_findings)
        journals.extend(fx_js)
        findings.extend(other_tax_on_paye(engagement, tb_records, chart, db))
        findings.extend(interest_on_paye(engagement, tb_records, chart, db))
        from backend.app.services.review.payroll_journals.unpaid import unpaid_over_two_months
        findings.extend(unpaid_over_two_months(engagement, db))
        from backend.app.services.review.loans_review import (
            loan_openings_by_code, loan_openings_missing, loan_schedule_points)
        findings.extend(loan_openings_missing(engagement, db))
        findings.extend(loan_openings_by_code(engagement, tb_records))
        ln_findings, ln_journals = loan_schedule_points(engagement, tb_records, chart, db, journal_counter)
        # The split from the ledger's rate (U-LOAN-003 / U-LOAN-009)
        from backend.app.services.review.loans_review import rate_splits
        rs_findings, rs_journals = rate_splits(engagement, tb_records, chart, db, journal_counter)
        ln_findings, ln_journals = ln_findings + rs_findings, ln_journals + rs_journals
        from backend.app.services.review.loan_statements import loan_statement_points
        ls_findings, ls_journals = loan_statement_points(engagement, tb_records, chart, db, journal_counter)
        ln_findings, ln_journals = ln_findings + ls_findings, ln_journals + ls_journals
        findings.extend(ln_findings)
        journals.extend(ln_journals)
        findings.extend(nw_findings)
        journals.extend(nw_journals)
        # 'Last year's accrual / prepayment not released' only while last year's lines are not entered (they reverse it)
        _entered = {l.kind for l in last_year_lines(engagement, db)[0]}
        findings.extend(ea_findings + dp_findings
                        + ([] if "PREPAYMENT" in _entered or "U-PRE-002" in ap_replaces
                           else prepayment_not_released(engagement, tb_records, chart, db))
                        + ([] if "ACCRUAL" in _entered or "U-ACC-003" in ap_replaces
                           else accrual_not_released(engagement, tb_records, chart, db)))

        # Accruals entered during the year and never released (a duplicate when the bill was posted as well)
        # Approved journals that release accruals (Dr Accruals) count against the largest groups first
        from backend.app.services.tax.ct_computation import final_balances
        released_by_journals = max(final_balances(engagement.id, tb_records, db).get(5360, 0.0)
                                   - chart.balance(tb_records, 5360), 0.0)
        for g in old_open_accruals(engagement.id, engagement.period_end_date, tb_records, db):
            used = min(released_by_journals, g.total)
            released_by_journals -= used
            open_left = round(g.total - used, 2)
            if open_left < 1.0:
                continue
            listing = "; ".join(f"{l.when:%d/%m/%Y} £{l.credit:,.2f}" for l in sorted(g.lines, key=lambda l: l.when)[:15])
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ACC-002",
                procedure_name="Accruals: old accruals not released",
                severity="HIGH" if g.later_bills > 0 and g.total >= 1000 else "MEDIUM",
                source_row_ref=f"Accruals: {g.supplier}"[:100],
                finding_title=f"{g.supplier[:60]}: £{open_left:,.2f} of accruals from {g.first:%d/%m/%Y} still open at the year end"[:255],
                finding_details=(f"{len(g.lines)} accrual(s) entered during the year are still in the accruals balance, never "
                                 f"released: {listing}{' and more' if len(g.lines) > 15 else ''}. A year-end accrual is dated "
                                 f"at the year end."
                                 + (f" £{used:,.2f} of them is already reversed by an approved journal; £{open_left:,.2f} is left." if used >= 1 else "")
                                 + (f" The supplier's own bills of £{g.later_bills:,.2f} were also posted after the first of "
                                    f"them, so the cost may be counted twice." if g.later_bills > 0 else "")
                                 + " Check each one against the supplier's bills and reverse the duplicates "
                                   "(Dr Accruals / Cr the cost). Client question: were these bills received and posted?"),
                quantified_amount=open_left, suggested_journal=None, status="OPEN",
            ))

        journals.extend(ea_journals + dp_journals)

        return findings, journals
