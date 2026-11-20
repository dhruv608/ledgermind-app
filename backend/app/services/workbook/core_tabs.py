"""The core tabs of the workbook, in the build's first steps: the cover and dividers, TTB, B2 journals, the
re-analysis tab, notes & queries, B1 ETB (with last year's balances), the general ledger detail and Section K (one
tab per P&L account). They also fill the context the later sections read: the TB list and codes, the firm chart's
names, the ETB codes, the opening balances and the ledger lines.

Split by step: core_front (steps 1-6), core_ledger (7, 7b), core_etb (8),
core_gl_k (9-12); this module holds the shared state and the order of the steps."""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.app.services.workbook.context import BuildContext

from backend.app.services.workbook import core_etb, core_front, core_gl_k, core_ledger


def add_core_tabs(ctx: BuildContext, gl_df: Optional[pd.DataFrame], journals: Optional[List[Dict[str, Any]]],
                  draft_note: Optional[str]) -> None:
    wb, engagement, db, tb_records = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records
    client_name, ye_str, report_notes = ctx.client_name, ctx.ye_str, ctx.report_notes
    bold_font, accounting_total_border = ctx.bold_font, ctx.accounting_total_border
    remove_sheet, account_name = ctx.remove_sheet, ctx.account_name
    s = SimpleNamespace(**{k: v for k, v in locals().items() if k != 's'})
    core_front.step_1(ctx, s)
    core_front.step_2(ctx, s)
    core_front.step_3(ctx, s)
    core_front.step_4(ctx, s)
    core_front.step_5(ctx, s)
    core_front.step_6(ctx, s)
    core_ledger.step_7(ctx, s)
    core_ledger.step_7b(ctx, s)
    core_etb.step_8(ctx, s)
    core_gl_k.step_9(ctx, s)
    core_gl_k.step_10(ctx, s)
    core_gl_k.step_11(ctx, s)
    core_gl_k.step_12(ctx, s)


# Also importable from here (tests and other callers use these names)
from backend.app.services.workbook.core_etb import OPENING_CHECK, SPEC_COL, _last_year_by_code  # noqa: E402
from backend.app.services.workbook.core_ledger import _foreign_cells  # noqa: E402

__all__ = ['add_core_tabs', 'OPENING_CHECK', 'SPEC_COL', '_foreign_cells', '_last_year_by_code']
