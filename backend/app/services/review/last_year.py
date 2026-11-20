"""
Last year vs this year: each account's balance last year beside this year's, and the big changes as client questions.

Last year's figures come from, in order: last year's job for the same client in the app, else last year's trial balance
uploaded with this year's files (Bank + Dext: last year's closing TB; Xero / QuickBooks: the optional "Last year's TB"),
else there is nothing to compare with.

Split by part: last_year_common (shared: last year's job and files), last_year_read
(reading last year's TB file), last_year_openings (opening balances from it), last_year_compare (last year v this
year and the client questions). This module re-exports every name, so no caller changes."""



from backend.app.services.review.last_year_common import (Comparison, GENERIC_WORDS, LastYearLine, SHARE_CAPITAL_NAME,
                                                          TB_PRIOR, _from_job, _prior_frame, _words_of, chart_names,
                                                          last_year_job, logger, pick_account, role_frame)  # re-exported
from backend.app.services.review.last_year_compare import (CHANGE_AMOUNT, CHANGE_SHARE, NOT_COMPARED, TRANSFERS,
                                                           _money, asked, compare, is_big_change, year_on_year_points)  # re-exported
from backend.app.services.review.last_year_openings import (_add_books_opening_tb, add_last_year_tb,
                                                            apply_prior_openings, openings_from_prior_names)  # re-exported
from backend.app.services.review.last_year_read import (DATE_TEXT, _amount, _code_of, _columns_without_heading,
                                                        _date_of, _firm_lines, _from_files, _words, _year_column,
                                                        firm_coded_lines, prior_balances_by_code, prior_lines,
                                                        prior_shows_share_capital, prior_uploaded)  # re-exported



__all__ = ['CHANGE_AMOUNT', 'CHANGE_SHARE', 'Comparison', 'DATE_TEXT', 'GENERIC_WORDS', 'LastYearLine',
           'NOT_COMPARED', 'SHARE_CAPITAL_NAME', 'TB_PRIOR', 'TRANSFERS', '_add_books_opening_tb', '_amount',
           '_code_of', '_columns_without_heading', '_date_of', '_firm_lines', '_from_files', '_from_job', '_money',
           '_prior_frame', '_words', '_words_of', '_year_column', 'add_last_year_tb', 'apply_prior_openings', 'asked',
           'chart_names', 'compare', 'firm_coded_lines', 'is_big_change', 'last_year_job', 'logger',
           'openings_from_prior_names', 'pick_account', 'prior_balances_by_code', 'prior_lines',
           'prior_shows_share_capital', 'prior_uploaded', 'role_frame', 'year_on_year_points']
