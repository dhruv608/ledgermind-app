"""Patterns the supplementary schedule readers share."""

import re


# BrightPay "Report 1": headings, then blocks of "Month 1 (Ending 30 April 2025)" with one line per employee; also
# written "Month 6 - Ending 30 September, 2024" or "Month 1 Ending 30 April, 2025", with "Take-home pay" for net pay
BRIGHTPAY_REQUIRED = {"name", "surname", "gross pay", "tax", "employee nics", "employer nics"}

BRIGHTPAY_NET = ("net pay", "take-home pay", "take home pay")

BRIGHTPAY_PERIOD = re.compile(r"^(?:month|week)\s+\d+\s*(?:\(\s*ending\s+(.+?)\)|[-–]?\s*ending\s+(.+?))\s*$", re.IGNORECASE)

# Words over the company's block of a 'Payroll Summary' (not a person's name)
SUMMARY_TITLE = re.compile(r"payroll|summary|employees|staff|company|client|year\s*end|period|total|ltd|limited|"
                           r"director|^\W*$|etb", re.IGNORECASE)

BRIGHTPAY_COLUMNS = {
    "gross pay": "gross_pay",
    "tax": "tax_deducted",
    "employee nics": "employee_nic",
    "employer nics": "employer_nic",
    "student loan deduction": "student_loan",
    "net pay": "net_pay",
    "employee pension": "pension_employee",
    "employer pension": "pension_employer",
}

MONTH_HEADING = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(\s*'?\d{2,4})?$", re.I)

GROUP_HEADING = re.compile(r"^(cost|depreciation|nbv|net book values?|accumulated depreciation)\b", re.I)

# The asset register's tab inside a full working paper file (e.g. 'C1-1-FA detail')
FAR_SHEET = re.compile(r"c1-1|fa detail|fixed asset|\bfar\b|asset register", re.I)
