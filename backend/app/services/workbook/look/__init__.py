"""The LedgerMind house style of a built workbook, applied after tidy_workbook. Only the look: no value, formula or tab
name changes.

- Title band: rows 1-2 teal across the tab, the client (A1) large and white, the year end (A2), the reference (E1)
  white and large on the right; the tab's title (A4) in teal. (No link back to the cover: the coloured tabs and A0's
  links are the way round.)
- Section headings (a bold line on its own: 'Reconciliation', 'Ledger lines this year') teal with a teal line below.
- Lead schedules as a clean T-account: no lines but a thin line above 'Closing per books' and a thin line above and a
  double line below 'Balance c/fwd'; check rows ('must be nil') small and grey on a light strip, their amount green
  when nil and red when not.
- Tables: teal heading row with white bold text, a light line under each row, every other row lightly shaded, totals
  bold with a line above and a double line below.
- Cells for the accountant to type in: their yellow with a dashed amber border.
- No gridlines; tab colours by section; headings frozen on long tabs; A4 printing one page wide (landscape when
  wide) with the heading row on every page.

Teal is the house colour; no purple."""

from backend.app.services.workbook.look.base import *  # noqa: F401,F403
from backend.app.services.workbook.look.page import (_band, _check_colours, _clear_lines, _code_colour, _inputs,
                                                     _leads,
                                                     _section_headings, _style_tables, _style_totals)
from backend.app.services.workbook.look.layouts import ETB, _colour, _etb, _filters, _fit_header_dates, _layouts, _print_and_freeze
from backend.app.services.workbook.look.cover import _a0_summary, _cover
from backend.app.services.workbook.look.figures import check_refs, chip, red_negatives, tiles


def _clear_template_print(ws) -> None:
    """The template's own print area and page breaks (B2 printed to row 20, C1 to row 36, C1-1 a page of title and
    then columns A-N only): another client's layout, which cut off this client's rows and check columns. Each tab
    prints whole instead, fitted to the page width (_print_and_freeze)."""
    from openpyxl.worksheet.pagebreak import ColBreak, RowBreak
    ws.print_area = None              # (openpyxl clears it with None)
    ws.row_breaks = RowBreak()
    ws.col_breaks = ColBreak()


def finish_look(wb) -> None:
    has_cover = COVER in wb.sheetnames
    _cover(wb)
    _a0_summary(wb)
    for ws in wb.worksheets:
        _clear_template_print(ws)
        if ws.sheet_state != "visible":
            continue
        if ws.title == COVER:
            _print_and_freeze(ws)
            continue
        CURRENT["dark"], CURRENT["tint"] = _palette(ws.title)
        ws.sheet_view.showGridLines = False
        _clear_lines(ws)
        _code_colour(ws)
        lead_rows = _leads(ws)
        table_rows = _style_tables(ws)
        _style_totals(ws, lead_rows)
        _section_headings(ws, table_rows | lead_rows)
        _layouts(ws, lead_rows)
        _inputs(ws)
        _check_colours(ws)
        _band(ws, has_cover)
        chip(ws, check_refs(ws))
        tiles(ws)
        red_negatives(ws)
        _print_and_freeze(ws)
        if ws.title == ETB:
            _etb(ws)
        _filters(ws)
        _fit_header_dates(ws)
        colour = _colour(ws.title)
        if colour:
            ws.sheet_properties.tabColor = colour
