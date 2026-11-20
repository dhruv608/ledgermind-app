"""What the assistant can read about the open client: each tool returns the app's own figures, short and in £, so
the model never has to guess a number. Read only: nothing here changes the client.

Every tool result is kept small (rows capped, text cut) so a chat stays cheap: the model asks again with a search
when it needs more."""

# The tools live in this package's modules; the specs the model sees and the dispatcher are here.

from typing import Any, Callable, Dict, Optional

from backend.app.services.assistant.tools.client_data import (  # noqa: F401
    CT_SUMMARY, MAX_ROWS, ClientData, _codes_for, _cut, _date, _r, drcr, match_accounts,
)
from backend.app.services.assistant.tools.books import (  # noqa: F401
    account_balances, account_transactions, client_overview, control_accounts, fixed_assets, journals,
    monthly_totals, payroll, review_points, tax_computation, vat_returns,
)
from backend.app.services.assistant.tools.papers import (  # noqa: F401
    account_year, client_queries, coding_review, debtors_by_age, files_check, gl_scrutiny, ledger_view,
    payroll_by_month, signoffs_and_evidence, vat_proof,
)

def _spec(name: str, description: str, props: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"toolSpec": {"name": name, "description": description,
                         "inputSchema": {"json": {"type": "object", "properties": props or {}, "required": []}}}}


_S = lambda desc: {"type": "string", "description": desc}

TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "client_overview": client_overview, "account_balances": account_balances,
    "account_transactions": account_transactions, "review_points": review_points,
    "control_accounts": control_accounts, "journals": journals, "tax_computation": tax_computation,
    "payroll": payroll, "vat_returns": vat_returns, "fixed_assets": fixed_assets,
    "monthly_totals": monthly_totals, "debtors_by_age": debtors_by_age, "gl_scrutiny": gl_scrutiny,
    "account_year": account_year, "payroll_by_month": payroll_by_month, "client_queries": client_queries,
    "vat_proof": vat_proof, "files_check": files_check, "coding_review": coding_review,
    "signoffs_and_evidence": signoffs_and_evidence, "ledger_view": ledger_view,
}

SPECS = [
    _spec("client_overview", "The open client: name, year end, software, VAT / payroll / CIS, directors, profit, "
                             "open review points, files uploaded, workbook status."),
    _spec("account_balances", "Year-end balances by firm account code (trial balance plus approved journals), with last "
                              "year and the client's own account names. Debit positive, credit negative.",
          {"search": _S("Words or a code to filter, e.g. 'bank', 'director', '5400', 'repairs'"),
           "section": _S("'pl' for profit and loss only, 'bs' for balance sheet only")}),
    _spec("account_transactions", "Ledger (GL) lines of an account, to explain a balance or find items.",
          {"account": _S("Client account name or firm code, e.g. 'Barclays', '7100'"),
           "search": _S("Words in the description or reference"),
           "date_from": _S("YYYY-MM-DD"), "date_to": _S("YYYY-MM-DD"),
           "order": _S("'date' (default) or 'largest'"), "limit": {"type": "integer", "description": "Max lines, up to 80"}}),
    _spec("review_points", "The review's points (findings) for the client, with severity, details and amount.",
          {"status": _S("OPEN (default), CLEARED or ALL"), "search": _S("Words or a ref like 'U-PAY' or 'G4'")}),
    _spec("control_accounts", "Each control account (bank, VAT, PAYE, pension, debtors, creditors, CT, CIS...) in the "
                              "books against the figure it is agreed to, and the difference."),
    _spec("journals", "The adjusting journals (proposed and approved) with their lines.",
          {"status": _S("PROPOSED, APPROVED or REJECTED; empty for all")}),
    _spec("tax_computation", "The corporation tax computation: adjustments, capital allowances, losses, tax, s455."),
    _spec("payroll", "The payroll report totals: gross, tax, NI, pensions, net pay.",
          {"by": _S("'month' (default) or 'employee'")}),
    _spec("vat_returns", "The VAT returns entered (boxes 1, 4, 5, 6, 7 per period), and what was paid on each and is "
                         "still unpaid, matched as the VAT reconciliation does."),
    _spec("fixed_assets", "The fixed asset register: cost, additions, depreciation, NBV."),
    _spec("monthly_totals", "Month by month totals of an account from the ledger (and the same months last year when "
                            "known): for trends, seasonality and charts.",
          {"account": _S("Client account name, firm code or words, e.g. 'sales', 'wages', '3230'"),
           "search": _S("Only lines whose description has these words")}),
    _spec("debtors_by_age", "Who owes the client money and for how long: each customer's balance in not due, 1-30, "
                            "31-60, 61-90 and 91+ days, from the client's aged receivables report.",
          {"only_old": {"type": "boolean", "description": "true: only customers with anything over 90 days"}}),
    _spec("gl_scrutiny", "GL scrutiny (line by line check of the ledger): without an account, each account's lines "
                         "checked, moved, asked about and flagged lines still to check; with an account, its flagged "
                         "lines (maybe an asset, unusual, related party, opposite side, round sum) and decisions.",
          {"account": _S("Client account name or firm code, e.g. 'repairs', '3200'; empty for the summary")}),
    _spec("account_year", "A balance sheet account's year: opening balance, this year's ledger lines by type "
                          "(invoices, receipts, payments...), approved journals, closing, and whether it agrees to "
                          "the trial balance.",
          {"account": _S("Client account name or firm code, e.g. 'trade debtors', '4400', 'Barclays'")}),
    _spec("payroll_by_month", "Net wages, PAYE / NI and pension from the ledger month by month (owed, paid, balance "
                              "and a note on months that look wrong), and payroll cost against what was owed out."),
    _spec("client_queries", "The job's queries (Queries tab): questions for the client, for the accountant and fixes "
                            "in the app, with status and answers.",
          {"status": _S("'open' (default), 'answered' or 'all'"),
           "audience": _S("CLIENT, ACCOUNTANT or INTERNAL; empty for all")}),
    _spec("vat_proof", "The VAT proof (VAT reconciliation): outstanding VAT per the returns, VAT yet to file, opening "
                       "variance, VAT filed but not in the accounts, adjustments, against the VAT account in the books."),
    _spec("files_check", "The Files tab: which files or figures the working papers still need (missing, unreadable, "
                         "must fix) and whether the workbook can be built."),
    _spec("coding_review", "Coding review: costs in the wrong account. Re-analysis moves (merchant, from and to "
                           "account, reason) and mispostings (a supplier split across accounts)."),
    _spec("signoffs_and_evidence", "Each area's sign-off (prepared, reviewed, approved with initials and date) and the "
                                   "documents uploaded on its Evidence tab."),
    _spec("ledger_view", "One account as originally uploaded and as it is now: lines moved off or onto it and every "
                         "journal touching it, with the totals.",
          {"account": _S("Client account name or firm code, e.g. 'packaging', '1710'")}),
]

LABELS = {
    "client_overview": "Reading the client", "account_balances": "Looking at balances",
    "account_transactions": "Reading the ledger", "review_points": "Reading review points",
    "control_accounts": "Checking control accounts", "journals": "Reading journals",
    "tax_computation": "Reading the tax computation", "payroll": "Reading the payroll",
    "vat_returns": "Reading VAT returns", "fixed_assets": "Reading the asset register",
    "monthly_totals": "Adding up by month", "debtors_by_age": "Ageing the debtors",
    "gl_scrutiny": "Reading GL scrutiny", "account_year": "Rolling the account forward",
    "payroll_by_month": "Checking payroll by month", "client_queries": "Reading the queries",
    "vat_proof": "Reading the VAT proof", "files_check": "Checking the files", "coding_review": "Reading the coding review",
    "signoffs_and_evidence": "Reading sign-offs and documents", "ledger_view": "Reading the ledger views",
}


def run_tool(name: str, args: Dict[str, Any], data: ClientData) -> Dict[str, Any]:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name}"}
    try:
        return fn(data, **{k: v for k, v in (args or {}).items() if v not in (None, "")})
    except TypeError as e:
        return {"error": f"Wrong inputs: {e}"}
    except Exception as e:
        data.db.rollback()
        return {"error": f"Could not read this: {str(e)[:200]}"}
