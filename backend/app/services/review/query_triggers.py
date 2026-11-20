"""
The Industry Query Library, checked against the client's own figures. Each query with a trigger in
rules/query_triggers.json is raised only when the trial balance or ledger shows it applies, with what the app found
(amounts and the ledger lines). A query without a trigger is left to the setup questions (setup_checks.industry_points).

A trigger names a test below and its settings:
  keyword_lines   ledger lines whose text matches words (money in or out, P&L or balance sheet), unless the books
                  already show what the query looks for (an account with a balance, or other words)
  balance         accounts (codes, sections or names) holding a balance
  ...and tests worked out from the figures: TB out of balance, suspense, balances on the wrong side, a month's
  sales far from the months around it, turnover over the VAT threshold, round-sum journals, ledger vs aged lists.

Split by part: qt_common (the context, helpers and the test register), qt_books (tests
on the books' balances and lines), qt_patterns (pattern and ratio tests). This module keeps the run over the rules
and re-exports every name; importing it registers every test."""

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, MasterCOA, TBRecord
from backend.app.services.tax.ct_computation import final_balances
from backend.app.services.sop.common import gl_lines
from backend.app.services.queries.placeholders import fill
from backend.app.services.review.qt_books import (abnormal_balances, balance, deferred_tax_missing, flat_rate_limit,
                                                  keyword_lines, ledger_vs_aged_list, loan_without_interest,
                                                  monthly_sales_swing, round_journals, suspense, tb_out_of_balance,
                                                  vat_threshold)  # re-exported
from backend.app.services.review.qt_common import (Ctx, FLAT_RATE_LEAVE_THRESHOLD, Hit, INCOME_SECTIONS, RULES,
                                                   SALES_SECTIONS, TESTS, VAT_REGISTRATION_THRESHOLD, _has_balance,
                                                   _line, _matching, _money, _payee, _where, test)  # re-exported
from backend.app.services.review.qt_patterns import (absent_balance, absent_words, debtor_days, debtors_vs_quarter,
                                                     investment_property_at_cost, last_month_spike,
                                                     limited_cost_trader, main_customer, monthly_margin_swing,
                                                     monthly_swing, months_without, one_account_in_section,
                                                     regular_payee, sales_present, share_of_sales,
                                                     single_sales_account, stock_days, stock_unchanged)  # re-exported
from backend.app.services.review.qt_industry import framework_is, margin_vs_last_year  # registers the tests



# ---------------------------------------------------------------------------------------------------------------
# Running the library
# ---------------------------------------------------------------------------------------------------------------
def triggers() -> Dict[str, Dict[str, Any]]:
    from backend.app.services.shared import rules_store
    return rules_store.load("query_triggers")


def library() -> Dict[str, Dict[str, Any]]:
    from backend.app.services.shared import rules_store
    return {q["Query_ID"]: q for q in rules_store.load("all_industry_queries")}


ALSO_RUNS = {"PRD": "PRP", "CNS": "PRO"}


def triggered_points(engagement: ClientEngagement, tb_records: Iterable[TBRecord], record: Optional[Dict[str, Any]],
                     industry: Optional[str], db: Session) -> List[AuditFinding]:
    """Every library query with a trigger, for every client (UNIV) and the client's confirmed industry, raised only
    when its trigger finds something in the books."""
    tb_records = list(tb_records)
    ctx = Ctx(engagement, tb_records, {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()},
              final_balances(str(engagement.id), tb_records, db), gl_lines(str(engagement.id), tb_records, db),
              record or {}, db)
    lib = library()
    # Property trading runs the property rules too, contractors the professional ones (as their query packs)
    wanted = {"UNIV"} | ({industry.upper(), ALSO_RUNS.get(industry.upper(), "")} if industry else set())
    out = []
    for qid, trig in triggers().items():
        q = lib.get(qid)
        if q is None or q.get("Industry") not in wanted or trig.get("test") not in TESTS:
            continue
        try:
            hit = TESTS[trig["test"]](ctx, trig)
        except Exception:
            continue
        if hit is None:
            continue
        severity = str(q.get("Severity", "Medium")).upper()
        # The template's amount blank takes the figure the trigger found; other blanks are left out with their sentence
        found = {"x": f"{abs(hit.amount):,.2f}"} if hit.amount else {}
        details = (f"What the app found: {hit.details}"
                   + ("\n" + "\n".join(hit.lines) if hit.lines else "")
                   + f"\n\nQuery to the client: {fill(q.get('Query to Client', ''), found)}"
                   + f"\nEvidence: {fill(q.get('Evidence Required', ''), found)}."
                   + (f" Ref: {q.get('FRS 102 Ref')}" if q.get("FRS 102 Ref") else "")
                   + (f"; {q.get('Tax / VAT / HMRC Ref')}" if q.get("Tax / VAT / HMRC Ref") else ""))
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=qid,
            procedure_name=f"Industry Library ({q.get('Industry')}): {q.get('Account_Area', '')}"[:100],
            severity=severity if severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "MEDIUM",
            source_row_ref=str(q.get("Account_Area", ""))[:100], finding_title=hit.title[:255],
            finding_details=details, quantified_amount=round(hit.amount, 2), status="OPEN", figures=hit.figures,
        ))
    return out


__all__ = ['Ctx', 'FLAT_RATE_LEAVE_THRESHOLD', 'Hit', 'INCOME_SECTIONS', 'RULES', 'SALES_SECTIONS', 'TESTS',
           'VAT_REGISTRATION_THRESHOLD', '_has_balance', '_line', '_matching', '_money', '_payee', '_where',
           'abnormal_balances', 'absent_balance', 'absent_words', 'balance', 'debtor_days', 'debtors_vs_quarter',
           'deferred_tax_missing', 'flat_rate_limit', 'framework_is', 'investment_property_at_cost', 'keyword_lines',
           'margin_vs_last_year',
           'last_month_spike', 'ledger_vs_aged_list', 'limited_cost_trader', 'loan_without_interest', 'main_customer',
           'monthly_margin_swing', 'monthly_sales_swing', 'monthly_swing', 'months_without', 'one_account_in_section',
           'regular_payee', 'round_journals', 'sales_present', 'share_of_sales', 'single_sales_account', 'stock_days',
           'stock_unchanged', 'suspense', 'tb_out_of_balance', 'test', 'vat_threshold', 'library', 'triggered_points',
           'triggers']
