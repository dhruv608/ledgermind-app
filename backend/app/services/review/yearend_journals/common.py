"""Shared pieces of the year-end journals: the stock and depreciation codes, the register class headings, and
the helpers that build a proposed journal and its review point."""

import re
from typing import List, Optional

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal
from backend.app.services.mapping.chart_lookup import ChartLookup

# Stock on the balance sheet and its P&L opening / closing lines in the firm chart
STOCK_LINES = {4300: (1000, 1900), 4301: (1010, 1910), 4302: (1030, 1930), 4303: (1020, 1920)}
OPENING_STOCK_PL = (1000, 1010, 1020, 1030)
CLOSING_STOCK_PL = (1900, 1910, 1920, 1930)
DEPRECIATION_PL = 3400
MIN_AMOUNT = 1.0
REGISTER_TOLERANCE = 0.5        # the register gives the charge to the penny

# The register's class headings ('Motor Vehicle -20%SLM', 'Office equipment-10%SLM') -> the firm's asset classes
FAR_CLASS = [
    # Intangibles first ('Goodwill', 'Intangible assets', 'Development costs', 'Patents and trade marks')
    (re.compile(r"goodwill", re.I), "Goodwill"),
    (re.compile(r"development\s+cost", re.I), "Development costs"),
    (re.compile(r"intellectual|patent|trade\s?marks?\b", re.I), "Intellectual property"),
    (re.compile(r"\bintangible", re.I), "Other intangible assets"),
    # Leasehold first: 'Leasehold L&B', 'Leasehold improvements' are not plant or freehold
    (re.compile(r"lease?hold|improvement|\bl\s*&\s*b\b", re.I), "Leasehold property"),     # also 'Leashold'
    (re.compile(r"motor|vehicle|van\b|car\b", re.I), "Motor vehicles"),
    (re.compile(r"computer|\bit\b|laptop", re.I), "Computers"),
    (re.compile(r"fixture|fitting|furniture|office", re.I), "Fixtures and fittings"),
    (re.compile(r"plant|machin|equipment|tool", re.I), "Plant and machinery"),
    (re.compile(r"freehold|building|\bland\b|propert", re.I), "Freehold property"),
]

def _journal(engagement: ClientEngagement, counter: List[int], description: str, dr: int, cr: int, amount: float,
             chart: ChartLookup, point: AuditFinding) -> ProposedJournal:
    j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                        description=description[:255], debit_code=dr, debit_name=chart.name(dr), credit_code=cr,
                        credit_name=chart.name(cr), amount=round(amount, 2), status="PROPOSED")
    counter[0] += 1
    j._point = point
    return j

def _point(engagement: ClientEngagement, ref: str, name: str, title: str, details: str, amount: float,
           entry: str, severity: Optional[str] = None) -> AuditFinding:
    return AuditFinding(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=ref, procedure_name=name,
                        severity=severity or ("HIGH" if amount >= 1000 else "MEDIUM"), source_row_ref=name[:100],
                        finding_title=title[:255], finding_details=details, quantified_amount=round(amount, 2),
                        suggested_journal=entry, status="OPEN")

def _entry(dr: int, cr: int, amount: float, chart: ChartLookup) -> str:
    return f"Dr {dr} {chart.name(dr)} (£{amount:,.2f}) / Cr {cr} {chart.name(cr)} (£{amount:,.2f})"
