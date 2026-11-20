"""Building the working papers workbook (services/workbook/excel_service.py is the front door the app calls).

builder.py        the order of the steps: template, context, each part, accountant's tabs, tidy, QA, save
context.py        what every part shares (BuildContext) and the shared helpers
core_tabs.py      the core tabs' steps in order (core_front: cover, TTB, B2 journals, re-analysis, notes;
                  core_ledger: ledger lines; core_etb: B1 ETB; core_gl_k: GL detail, Section K)
fixed_assets.py   C1 lead and detail, C1.2 capital review, C1.3 property review
balance_sheet.py  the balance sheet steps in order (bs_stock_debtors: D, E, E3; bs_bank_creditors: F, G2; bs_sops:
                  duplicates, related parties, pattern, restaurant; bs_dla: G3), and G10 accruals, J2 reserves
payroll.py        G6 net wages, G6.2 payroll summary, G6.3 employees, G7 PAYE / NI, G8 pension
vat.py            G9, G9.1, G9.3, G9.5
tax.py            H1 tax computation, H2 CT600 boxes (ct600.py), A1 general checks
balance_tabs.py   the accountant's tabs: one per bank account, loans and HP, deposits, s455, dividends
setup_tabs.py     size test, associated companies, fee accrual, checklists
qa.py, recalc.py, tidy.py   the pre-release checks, working out the formulas, one look for every tab
"""
