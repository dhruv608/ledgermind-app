"""
Corporation tax computation, laid out as the firm's Tax_Comp sheet (accounts -> trading profit -> profits
chargeable -> tax), for any client.

Figures come from the final balances (TB plus journals approved in the app, the same numbers as the ETB), the firm
chart sections, and the tax facts on the client setup that are not in the books (associated companies, losses and
capital allowance pools brought forward, double tax relief, director loans repaid after the year end).

Rates and limits come from rules/parameters.json. The marginal relief limits are pro-rated for a short period and
divided by (associated companies + 1); a period that straddles 1 April is split by financial year.
Not covered (raised as review notes instead of guessed): group relief, R&D, chargeable gains, structures and
buildings allowance, car CO2 bands and the 50% loss restriction above £5m. Rent is a property business (its costs
go against it; split by income when there are other sales, unless the accountant gives them).

Parts: ct_constants (codes, rules, rates), ct_model (the computation's lines, the final balances), ct_rates
(financial years, the tax on profits, intangibles), ct_compute (the computation itself). This module holds the entry
the review and the workbook call, and re-exports every name."""

import json
from datetime import date, timedelta
from typing import Dict, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import DISALLOWABLE_FINES_NAME
from backend.app.services.tax.ct_compute import compute  # re-exported
from backend.app.services.tax.ct_constants import (AIA_ADDITIONS, CAPITAL_LEGAL, CA_TREATMENTS, CHARITABLE_DONATIONS,
                                                   COST_OF_ADDITIONS, CT_CHARGE, CT_TEXT, CT_UNSETTLED_LIMIT,
                                                   DISPOSALS, DISPOSAL_PROFIT_CODES, DIVIDEND_SECTIONS, DLA_CODES,
                                                   DOUBLE_CAB_AS_CAR_FROM, ENTERTAINING, FINE_LINE, FOREIGN_TAX_CODES,
                                                   GIFT_LINE, GOODWILL_CHARGE, GOODWILL_COST, HMRC_TAX_TEXT, HYBRID,
                                                   INTANGIBLES_POLICIES, INTANGIBLE_DEBIT, INTEREST_SECTION,
                                                   LATE_TAX_CHARGES, LEGAL_FEES, MAIN_POOL_WDA_BEFORE_APRIL_2026,
                                                   MAIN_RATE_FROM, NOT_A_CLIENT_GIFT, NOT_A_FINE,
                                                   NO_ALLOWANCE_ADDITIONS, OLD_FLAT_RATE, OTHER_INTANGIBLE_CHARGE,
                                                   OTHER_INTANGIBLE_COST, PARAMETERS_FILE, PICK_UP,
                                                   POLITICAL_DONATIONS, PRIOR_YEAR_TAX, RENTAL_INCOME_CODES, ROAD_TAX,
                                                   SINGLE_CAB, SMALL_POOL, SPECIAL_POOL_WDA, TAX_SECTIONS, VAN,
                                                   VEHICLE_ADDITIONS, VEHICLE_EXTRAS, ZERO_EMISSION, ct_hold_limit,
                                                   firm_intangibles_policy, tax_parameters)  # re-exported
from backend.app.services.tax.ct_model import CTComputation, CTLine, final_balances  # re-exported
from backend.app.services.tax.ct_rates import _financial_year_slices, _intangibles, corporation_tax  # re-exported



def ct_computation(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session,
                   proposed: Iterable[ProposedJournal] = ()) -> CTComputation:
    """The computation for an engagement, from its final balances and client setup. The review passes the journals it
    has just proposed (proposed), so the tax is on the profit after them, as the accountant works it out last."""
    from backend.app.services.sop.common import gl_lines
    tb_records = list(tb_records)
    proposed = list(proposed)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    balances = final_balances(str(engagement.id), tb_records, db, proposed)
    profile = getattr(engagement, "profile", None)
    tax_inputs = json.loads(getattr(profile, "tax_inputs", None) or "{}") if profile is not None else {}
    # The client details' answers on rent: a letting business or part of the trade, and the property costs if known
    setup_ct = (json.loads(getattr(profile, "setup", None) or "{}").get("ct") or {}) if profile is not None else {}
    tax_inputs = {**tax_inputs, **{k: setup_ct[k] for k in ("rent_basis", "property_costs") if setup_ct.get(k) is not None},
                  "intangibles_policy": firm_intangibles_policy(db)}
    # Losses brought forward not entered: last year's final working paper's H1 says what it carried forward
    # (CTA 2010 s45 / s45A); the accountant's own figure (or last year's job in the app) comes first
    wp_losses = (tax_inputs.get("_last_year_wp") or {}).get("losses_cf")
    losses_from_wp = tax_inputs.get("losses_bf") in (None, "") and wp_losses
    if losses_from_wp:
        tax_inputs = {**tax_inputs, "losses_bf": float(wp_losses)}
    end = engagement.period_end_date
    start = engagement.prior_period_end_date + timedelta(days=1) if engagement.prior_period_end_date else \
        (date(end.year - 1, end.month, end.day) if not (end.month == 2 and end.day == 29) else date(end.year - 1, 2, 28)) + timedelta(days=1)
    # P&L account names, for fines and penalties. The interest accounts are looked at line by line below (interest on
    # late corporation tax is allowed, on other taxes not)
    tb_names = {t.raw_account_name: float(t.net_amount or 0) for t in tb_records if t.std_code is not None
                and t.std_code in chart and chart[t.std_code].financial_class == "Profit and Loss"
                and chart[t.std_code].category != "Interest payable and similar charges"}
    lines = gl_lines(str(engagement.id), tb_records, db)
    vehicle_lines = [(f"{l.account} {l.description}", l.debit - l.credit, l.when.isoformat() if l.when else None)
                     for l in lines if l.code in (VEHICLE_ADDITIONS, COST_OF_ADDITIONS[VEHICLE_ADDITIONS])]
    # Opening balances of the cost accounts, when the TB holds the year's movements (its openings are known)
    openings: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code in COST_OF_ADDITIONS.values() and t.opening_amount is not None:
            openings[t.std_code] = openings.get(t.std_code, 0.0) + float(t.opening_amount or 0)
    # Mappings not yet reviewed change the tax: say which
    unreviewed = [t.raw_account_name for t in tb_records if t.mapping_status in ("NEEDS_REVIEW", "UNMAPPED")
                  and abs(float(t.net_amount or 0)) >= 1]
    dla_advances = [(l.when, l.debit) for l in lines if l.code in DLA_CODES and l.debit > 0]
    dla_rows = [t for t in tb_records if t.std_code in DLA_CODES]
    dla_opening = (sum(float(t.opening_amount or 0) for t in dla_rows)
                   if dla_rows and any(t.opening_amount is not None for t in dla_rows) else None)
    # Fines inside other accounts, as the bank or ledger line says ('PCN', 'HMRC late filing penalty' in motor
    # expenses or sundries): added back too
    fines_named = {n for n in tb_names if DISALLOWABLE_FINES_NAME.search(n)}
    fine_lines = round(sum(l.debit - l.credit for l in lines if l.account not in fines_named and l.code in chart
                           and chart[l.code].financial_class == "Profit and Loss"
                           and chart[l.code].category != "Interest payable and similar charges"
                           and FINE_LINE.search(l.description or "")
                           and not NOT_A_FINE.search(f"{l.account} {l.description or ''}")), 2)
    # A line a journal has already moved out of the P&L (a capital item to fixed assets, a cost to the director's
    # loan) is not in the profit any more: it is not added back again (a conveyancing fee moved to
    # property by the capital review is not also a capital legal cost). Matched by its code and amount
    from collections import Counter
    approved_now = db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                                    ProposedJournal.status == "APPROVED").all()
    moved_out = Counter((int(j.credit_code), round(float(j.amount or 0), 2)) for j in list(proposed) + approved_now
                        if getattr(j, "status", "PROPOSED") != "REJECTED")

    def still_in_pl(l) -> bool:
        key = (l.code, round(l.debit - l.credit, 2))
        if moved_out.get(key):
            moved_out[key] -= 1
            return False
        return True
    is_pl_line = lambda l: (l.code in chart and chart[l.code].financial_class == "Profit and Loss"
                            and chart[l.code].category not in ("Sales",) and l.code not in (3360, 3361))
    # Legal costs of a capital nature inside legal / professional fees (CTA 2009 s53)
    capital_legal = round(sum(l.debit - l.credit for l in lines if is_pl_line(l)
                              and (l.code == LEGAL_FEES or "legal" in (l.account or "").lower())
                              and CAPITAL_LEGAL.search(l.description or "") and still_in_pl(l)), 2)
    # Gifts named on a line or an account (CTA 2009 s1298), not staff gifts or charity
    gifts = round(sum(l.debit - l.credit for l in lines if is_pl_line(l)
                      and l.code != ENTERTAINING and chart[l.code].category != "Cost of sales"
                      and GIFT_LINE.search(f"{l.account} {l.description or ''}")
                      and not NOT_A_CLIENT_GIFT.search(f"{l.account} {l.description or ''}") and still_in_pl(l)), 2)
    # Donations paid in the period: the charge's ledger lines less journals (an accrual is not a payment)
    donation_lines = [l for l in lines if l.code == 3360]
    donations_paid = (round(sum(l.debit - l.credit for l in donation_lines if "journal" not in (l.source or "").lower()), 2)
                      if donation_lines else None)
    # Interest and penalties on late tax inside the interest accounts: every line on late payment tax charges (3670)
    # and lines naming HMRC, VAT, PAYE or CIS (or a penalty) on the others, except interest on late corporation tax.
    # Without ledger lines, the late payment tax charges account as a whole
    interest_codes = {k for k, c in chart.items() if c.category == "Interest payable and similar charges"}
    interest_lines = [l for l in lines if l.code in interest_codes]
    if interest_lines:
        tax_interest = sum(l.debit - l.credit for l in interest_lines
                           if not CT_TEXT.search(f"{l.account} {l.description or ''}")
                           and (l.code == LATE_TAX_CHARGES or HMRC_TAX_TEXT.search(l.description or "")
                                or (FINE_LINE.search(l.description or "")
                                    and not NOT_A_FINE.search(f"{l.account} {l.description or ''}"))))
        # Journals on late payment tax charges (the U-PAY-023 move of PAYE interest out of 5320) are not ledger lines:
        # the code's balance beyond its ledger lines is added too
        on_ledger = sum(l.debit - l.credit for l in interest_lines if l.code == LATE_TAX_CHARGES)
        tax_interest += max(0.0, balances.get(LATE_TAX_CHARGES, 0.0) - on_ledger)
    else:
        tax_interest = balances.get(LATE_TAX_CHARGES, 0.0)
    # Repaid within nine months (s458) not typed: next year's ledger, when uploaded, shows it
    dla_after = None
    if tax_inputs.get("dla_repaid_within_9_months") in (None, "") and end is not None:
        from backend.app.services.ingestion.next_year import next_year_lines
        from backend.app.services.tax.dla_repaid import repaid_after
        later = next_year_lines(str(engagement.id), db)
        if later:
            dla_after = repaid_after(end, later)
            if dla_after.repaid or dla_after.left_out:
                tax_inputs = {**tax_inputs, "dla_repaid_within_9_months": dla_after.repaid}
    comp = compute(start, end, balances, chart, tax_inputs, tb_names, vehicle_lines, dla_advances, openings, dla_opening,
                   max(fine_lines, 0.0), round(tax_interest, 2), max(capital_legal, 0.0), max(gifts, 0.0),
                   donations_paid)
    if dla_after and dla_after.note and comp.s455_tax is not None and \
            sum(balances.get(k, 0.0) for k in DLA_CODES) > 0.01:
        comp.notes.append(dla_after.note)
    if losses_from_wp:
        comp.notes.append(f"Trading losses brought forward of £{float(wp_losses):,.2f} are taken from last year's final "
                          f"working paper (its H1 losses carried forward). Enter them on the client setup to change them.")
    if unreviewed:
        comp.notes.insert(0, f"{len(unreviewed)} account mapping(s) still need review and can change this computation "
                             f"({', '.join(unreviewed[:5])}{' and others' if len(unreviewed) > 5 else ''}).")
    # Say how much of the profit comes from the journals still waiting for a decision
    if proposed:
        before = final_balances(str(engagement.id), tb_records, db)
        pl = lambda code: (code in chart and chart[code].financial_class == "Profit and Loss"
                           and chart[code].category not in TAX_SECTIONS)
        effect = round(-sum(v - before.get(k, 0.0) for k, v in balances.items() if pl(k)), 2)
        if abs(effect) >= 0.01:
            comp.notes.append(
                f"The profit includes the {len(proposed)} journal(s) this review proposes (profit "
                f"{'up' if effect > 0 else 'down'} £{abs(effect):,.2f}). If you reject any of them, run the review "
                f"again so the tax follows.")
    return comp


__all__ = ['AIA_ADDITIONS', 'CAPITAL_LEGAL', 'CA_TREATMENTS', 'CHARITABLE_DONATIONS', 'COST_OF_ADDITIONS',
           'CTComputation', 'CTLine', 'CT_CHARGE', 'CT_TEXT', 'CT_UNSETTLED_LIMIT', 'DISPOSALS',
           'DISPOSAL_PROFIT_CODES', 'DIVIDEND_SECTIONS', 'DLA_CODES', 'DOUBLE_CAB_AS_CAR_FROM', 'ENTERTAINING',
           'FINE_LINE', 'FOREIGN_TAX_CODES', 'GIFT_LINE', 'GOODWILL_CHARGE', 'GOODWILL_COST', 'HMRC_TAX_TEXT',
           'HYBRID', 'INTANGIBLES_POLICIES', 'INTANGIBLE_DEBIT', 'INTEREST_SECTION', 'LATE_TAX_CHARGES', 'LEGAL_FEES',
           'MAIN_POOL_WDA_BEFORE_APRIL_2026', 'MAIN_RATE_FROM', 'NOT_A_CLIENT_GIFT', 'NOT_A_FINE',
           'NO_ALLOWANCE_ADDITIONS', 'OLD_FLAT_RATE', 'OTHER_INTANGIBLE_CHARGE', 'OTHER_INTANGIBLE_COST',
           'PARAMETERS_FILE', 'PICK_UP', 'POLITICAL_DONATIONS', 'PRIOR_YEAR_TAX', 'RENTAL_INCOME_CODES', 'ROAD_TAX',
           'SINGLE_CAB', 'SMALL_POOL', 'SPECIAL_POOL_WDA', 'TAX_SECTIONS', 'VAN', 'VEHICLE_ADDITIONS',
           'VEHICLE_EXTRAS', 'ZERO_EMISSION', '_financial_year_slices', '_intangibles', 'compute', 'corporation_tax',
           'ct_hold_limit', 'final_balances', 'firm_intangibles_policy', 'tax_parameters', 'ct_computation']
