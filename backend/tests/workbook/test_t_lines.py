"""The T's lines named as an accountant reads them."""

from backend.app.services.papers.t_lines import account_kind, line_name


def test_kind_from_codes_then_names():
    assert account_kind([4800, 5351], []) == "bank"
    assert account_kind([4400], []) == "debtors"
    assert account_kind([5200], []) == "creditors"
    assert account_kind([5300], []) == "vat"
    assert account_kind([5320], []) == "paye"
    assert account_kind([5350], ["Pension liability"]) == "pension"
    assert account_kind([5500], ["Bounce back loans"]) == "loan"
    assert account_kind([4420], ["Other debtors"]) == "other"


def test_debtors_and_creditors():
    assert line_name("debtors", "Invoice", True) == "Sales invoices raised"
    assert line_name("debtors", "Receivable Invoice", True) == "Sales invoices raised"
    assert line_name("debtors", "Payment", False) == "Bank receipts from customers"
    assert line_name("debtors", "Receivable Credit Note", False) == "Credit notes"
    assert line_name("creditors", "Bill", False) == "Purchase bills received"
    assert line_name("creditors", "Payable Invoice", False) == "Purchase bills received"
    assert line_name("creditors", "Bill Payment (Cheque)", True) == "Bank payments to suppliers"
    assert line_name("creditors", "Supplier Credit", True) == "Supplier credit notes"
    assert line_name("creditors", "Journal Entry", True) == "Journals in the books"


def test_bank_vat_payroll():
    assert line_name("bank", "Expense", False) == "Bank payments"
    assert line_name("bank", "", True) == "Bank receipts"
    assert line_name("bank", "Transfer", True) == "Transfers between accounts"
    assert line_name("vat", "Sales Receipt", False) == "VAT on sales (output VAT)"
    assert line_name("vat", "Refund", True) == "VAT on sales (output VAT)"
    assert line_name("vat", "Bill", True) == "VAT on purchases (input VAT)"
    assert line_name("vat", "Supplier Credit", False) == "VAT on purchases (input VAT)"
    assert line_name("vat", "VAT Payment", True) == "VAT paid to HMRC"
    assert line_name("paye", "Journal Entry", False) == "PAYE and NI owed per the payroll"
    assert line_name("paye", "Expense", True) == "Paid to HMRC"
    assert line_name("wages", "Expense", True) == "Wages paid"


def test_dla_loans_and_unknown():
    assert line_name("dla", "Expense", True) == "Personal paid expenses"
    assert line_name("dla", "Receive Money", False) == "Funds introduced"
    assert line_name("loan", "Expense", True) == "Instalments paid"
    assert line_name("other", "Expense", True) == "Expense"
    assert line_name("other", "", False) == "Credits"


def test_named_by_words():
    assert line_name("dla", "Journal Entry", False, "Use of home 2025") == "Use of home"
    assert line_name("dla", "Journal Entry", False, "Interim dividend") == "Dividend"
    assert line_name("dla", "Transfer", True, "To director") == "Drawings"
    assert line_name("loan", "Journal Entry", False, "Loan interest charged") == "Interest charged"
    assert line_name("loan", "Expense", True, "Funding Circle repayment") == "Instalments paid"
    assert line_name("bank", "Expense", False, "Dividend paid") == "Bank payments"


def test_dla_drawings_by_words():
    assert line_name("dla", "Expense", True, "J R MCKENZIE - DIRECTORS LOAN") == "Drawings"
    assert line_name("dla", "Expense", True, "Tfl travel") == "Personal paid expenses"
