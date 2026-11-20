"""Constants the review engine and its stages share."""

from pathlib import Path


S455_RECOVERABLE = 4550         # Corporation tax recoverable (debtors > 1 year): s455 until the loan is repaid
CT_RECOVERABLE_SHORT = 4450
SUSPENSE_CODE, TRANSFERS_CODE = 9999, 9998
RULES_DIR = Path(__file__).resolve().parents[3] / "rules"     # backend/app/rules
INDUSTRIES_DIR = RULES_DIR / "industries"
