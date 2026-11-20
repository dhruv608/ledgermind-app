"""The working paper pack: one Excel workbook in the firm's working paper style (the client's name and year end at
the top of every sheet, a sheet per schedule, Queries numbered with Answers and Actioned), with four more sheets:
Summary, Evidence map, Last year vs this year, and the Export of figures by SA box.

  R-OUT-01  a FINAL pack cannot be made while any Block is open; a DRAFT can, for review, and says so on every sheet
  R-OUT-02  every version is kept as made, never changed (sa_packs), and the pack names its version and note
  R-OUT-03  notes and queries come from this client's own lines; nothing is carried from a template
  evidence  every row taken from a document carries its document number (the Evidence map lists them all)

gather() reads the job into plain figures; workbook() writes them, so the layout is tested without a database. The
pack becomes next year's 'last year' working paper: its sheets are plain rows the last-year reader takes in."""

# Everything callers import from this package
from backend.app.sa.pack.style import (BOLD, DRAFT, FINAL, FIRM_QUERIES, GREY, MONEY, RED, TEAL, TITLE, Sheet, _money,
                                       _ordinal, deadlines, year_end_words)
from backend.app.sa.pack.law import LAW, RULES, law_of, rules_sheet
from backend.app.sa.pack.income_sheets import (capital_gains, foreign_sheet, paye, property_abroad_sheet,
                                               property_sheet, savings_dividends, self_employment)
from backend.app.sa.pack.review_sheets import (client_info, decisions, evidence, export, first_sentence, last_year,
                                               outcome, queries, summary, tax_computation)
from backend.app.sa.pack.gather import _share, gather
from backend.app.sa.pack.book import SHEETS, file_name, make, out, workbook
