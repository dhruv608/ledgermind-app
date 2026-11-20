"""A Self Assessment job's income lines, and the tax calculation made from them (engine/calc.py).

  P60s          each P60 read (or read with a point to check) becomes an employment line: pay and tax in this
                employment only (R-SA102-01); removing the document removes its line
  director      a director's dividends from the company's own books in LedgerMind: payments on the dividend codes
                (8010 / 8011) dated in the tax year, taxed when paid (R-DIR, R-SAV-04)
  savings       ISA interest is kept on the page but left out of the figures (R-SAV-01, R-SAV-05; ITTOIA s694)
  reliefs       Gift Aid and relief-at-source pension contributions as paid (net): grossed up ÷ 0.8, they extend the
                bands and lower adjusted net income (R-SAV-07, R-SAV-08); salary sacrifice: no entry (EIM42775)
  investments   VCT, EIS and SEIS subscriptions (SA101 Ai2): tax reductions at 30% / 30% / 50% (engine); qualifying
                loan interest: a relief from income, capped (ITA s24A)
  benefits      Jobseeker's Allowance and other taxable state benefits are non-savings income (EIM76222)"""

# Everything callers import from this package
from backend.app.sa.income.common import DIVIDEND_CODES, KINDS, tax_year_dates
from backend.app.sa.income.sync import drop_doc_lines, sync_p60_lines
from backend.app.sa.income.employment import sync_p11d_lines, sync_p45_lines
from backend.app.sa.income.savings import (BANK_BENEFIT_NOTE, BANK_INTEREST_NOTE, director_dividends,
                                           sync_dividend_lines, sync_donation_lines, sync_pension_lines,
                                           sync_savings_lines)
from backend.app.sa.income.property import sync_letting_items, sync_mortgage_items
from backend.app.sa.income.trading import (RECEIPT_DAYS, VAT_IN, VAT_OUT, sync_cis_takings, sync_client_sheets,
                                           sync_receipt_items, sync_statement_poa, sync_vat_returns, vat_returns)
from backend.app.sa.income.calculation import (CLASS4_CHOICES, CLASS4_EXEMPT, CLASS4_KEY, LOSS_CLAIMS, LOSS_KEY, _used,
                                               calculation, loss_claim, marriage_from_codes, to_income)
