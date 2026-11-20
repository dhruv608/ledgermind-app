"""Checks after mapping: transfer and same-name accounts, depreciation credits and classes, purchases to additions,
accounts on the wrong side, and separate bank accounts."""

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.database import GLTransaction, MasterCOA
from backend.app.services.mapping.mapping_parts.common import (
    ASSET_FINANCE_NAME, ASSET_PURCHASE_NAME, BANK_CODES, BANK_NUMBER_NAME, CREDITOR_NAME, CREDITOR_SECTIONS,
    CREDIT_EXPENSE_NAME, DEBTOR_NAME, DEBTOR_SECTIONS, EXPENSE_CREDIT_MIN, FIXED_ASSET_SECTIONS, FLAGGED_SOURCES,
    INCOME_NAME, INCOME_SECTIONS, MOVABLE_SOURCES, NOT_EXPENSE_SECTIONS, NOT_INCOME_NAME, SUSPENSE_CODE,
    WRONG_SIDE_MIN_BALANCE, account_key,
)

# An account named for VAT ('VAT', 'VAT Control', 'GST') and not a bank ('VAT savings account at Barclays' is one)
VAT_NAME = re.compile(r"\b(vat|gst)\b", re.I)
BANK_WORDS = re.compile(r"\bbank|\bsavings? account|\bdeposit account|\bcurrent account|barclays|hsbc|lloyds|natwest|"
                        r"santander|starling|monzo|\btide\b|revolut|\bwise\b|\bpot\b|\bsav(ing|er)s?\b|\(\d{4,}\)", re.I)

# Freight on goods bought (cost of sales) v postage, couriers and carriage out (overheads)
DEPRECIATION, AMORTISATION = 3400, 3500
ADMIN_FREIGHT, SALES_FREIGHT = 3275, 1711
FREIGHT_IN_NAME = re.compile(r"\bfr(e|)ight|\bshipping\b|\bhaulage\b|\bclearance\b|\bimport\b|carriage in", re.I)
FREIGHT_OUT_NAME = re.compile(r"\bpostage\b|\bcourier|\boutwards?\b|carriage out|\bto customers?\b|\bdistribution\b",
                              re.I)
# A company's name (not the trade control accounts, a lender or a bank)
TRADE_DEBTORS, TRADE_CREDITORS, OTHER_DEBTORS, OTHER_CREDITORS = 4400, 5200, 4420, 5350
COMPANY_NAME = re.compile(r"\b(ltd|limited|llp|plc|trading)\b", re.I)
TRADE_OR_LOAN_NAME = re.compile(r"\b(debtors?|creditors?|receivables?|payables?|customers?|suppliers?|trade|control|"
                                r"a/?r|a/?p|ledger|loans?|finance|lend\w*|capital)\b", re.I)


class MappingChecks:
    """Checks after mapping: transfer and same-name accounts, depreciation credits and classes, purchases to additions,
    accounts on the wrong side, and separate bank accounts. Mixed into MappingService."""

    @staticmethod
    def _flag_transfer_accounts(engagement_id: str, rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                                coa_by_code: Dict[int, MasterCOA], db: Session) -> None:
        """An account whose ledger lines are bank transfers (Xero: money moved between the client's own accounts) is a
        bank account, whatever its name says ('E - Tax', a savings pot): on a P&L or tax code it goes to review."""
        transfer_accounts = {account_key(a) for (a,) in db.execute(
            select(GLTransaction.raw_account_name).where(GLTransaction.engagement_id == engagement_id,
                                                         func.lower(GLTransaction.source) == "bank transfer").distinct())}
        if not transfer_accounts:
            return
        for row, r in zip(rows, results):
            if not r or account_key(row["name"]) not in transfer_accounts or r.get("std_code") not in coa_by_code:
                continue
            account = coa_by_code[r["std_code"]]
            if account.financial_class == "Profit and Loss" or "tax" in (account.std_name or "").lower():
                r["mapping_status"] = "NEEDS_REVIEW"
                r["mapping_reason"] = (f"Check: its ledger lines are bank transfers between the client's own accounts, "
                                       f"so it looks like a bank account (48xx), not {account.std_code:04d} "
                                       f"{account.std_name}. {r.get('mapping_reason') or ''}").strip()

    @staticmethod
    def _flag_same_name(rows: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> None:
        """Two accounts of one TB with the same name on the same code ('Corporation Tax' twice: the charge in the
        P&L and the tax owed) are two different accounts: both go to review, one at a time."""
        seen: Dict[Tuple[str, int], List[int]] = {}
        for i, (row, r) in enumerate(zip(rows, results)):
            if r and r.get("std_code") not in (None, SUSPENSE_CODE):
                seen.setdefault((account_key(row["name"]), r["std_code"]), []).append(i)
        for (_, code), idx in seen.items():
            if len(idx) < 2:
                continue
            for i in idx:
                r = results[i]
                if (r.get("mapping_reason") or "").startswith("Check:"):
                    continue
                r["mapping_status"] = "NEEDS_REVIEW"
                r["mapping_reason"] = (f"Check: {len(idx)} accounts named '{rows[i]['name']}' are all on {code:04d}: "
                                       f"is one of them another kind of account? {r.get('mapping_reason') or ''}").strip()

    @staticmethod
    def _depreciation_not_amortisation(rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                                       coa_by_code: Dict[int, MasterCOA]) -> None:
        """A depreciation charge (the name says depreciation, not amortisation or intangibles) put on amortisation
        3500 goes to depreciation 3400: amortisation is for intangibles, and the tax computation adds it back under
        the intangibles rules ('Depreciation Expense - ROU Assets' is not goodwill). A leased vehicle's right-of-use
        asset is not an intangible (CTA 2009 s805)."""
        if DEPRECIATION not in coa_by_code:
            return
        for i, row in enumerate(rows):
            r = results[i]
            name = row["name"].lower()
            if not r or r.get("std_code") != AMORTISATION or r["match_source"] not in MOVABLE_SOURCES:
                continue
            if "depreciat" not in name or re.search(r"amortis|amortiz|intangible|goodwill|software|licen[cs]e", name):
                continue
            r.update({"std_code": DEPRECIATION, "std_name": coa_by_code[DEPRECIATION].std_name,
                      "mapping_reason": f"Its name says depreciation, not amortisation: {DEPRECIATION:04d} "
                                        f"{coa_by_code[DEPRECIATION].std_name}. {r.get('mapping_reason') or ''}".strip()})

    @staticmethod
    def _depreciation_credits_to_balance_sheet(rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                                               coa_by_code: Dict[int, MasterCOA]) -> None:
        """A depreciation account with a credit balance is the balance sheet side ('Computer equipment depreciation
        charge for the year', 'Office Equipment Depreciation'): on a P&L depreciation code it cancels the expense and
        overstates profit. It goes to its asset class's depreciation code on the balance sheet:
        the charge in year, or brought forward when the name says b/f or accumulated. Sent to review with the reason."""
        from backend.app.services.review.setup_checks import ASSET_CLASS_CODES
        from backend.app.services.review.yearend_journals import FAR_CLASS
        by_charge = {code: cls for cls, codes in ASSET_CLASS_CODES.items() for code in codes["charge"]}
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in FLAGGED_SOURCES or r["std_code"] not in coa_by_code:
                continue
            account = coa_by_code[r["std_code"]]
            name = re.sub(r"^\d+[\s\-_:]+", "", row["name"]).lower()
            if (account.financial_class != "Profit and Loss" or "depreciat" not in account.std_name.lower()
                    or "depreciat" not in name or float(row.get("net") or 0.0) > -WRONG_SIDE_MIN_BALANCE):
                continue
            cls = by_charge.get(r["std_code"]) or next((c for pattern, c in FAR_CLASS if pattern.search(name)), None)
            if cls is None:
                r["mapping_status"] = "NEEDS_REVIEW"
                r["mapping_reason"] = (f"Check: a credit balance on a P&L depreciation code cancels the charge; it is "
                                       f"probably accumulated depreciation (balance sheet). {r.get('mapping_reason') or ''}").strip()
                continue
            acc = ASSET_CLASS_CODES[cls]["acc"]
            # 'charge for the year' is this year's; any other balance sheet depreciation account holds the total to date
            target = acc[1] if re.search(r"charge|for the year|this year", name) else acc[0]
            if target not in coa_by_code:
                continue
            r["mapping_reason"] = (f"Check: credit balance, so balance sheet depreciation ({target:04d}), not the P&L "
                                   f"charge {r['std_code']:04d}. {r.get('mapping_reason') or ''}").strip()
            r["std_code"], r["std_name"] = target, coa_by_code[target].std_name
            r["mapping_status"] = "NEEDS_REVIEW"

    @staticmethod
    def _depreciation_by_class(rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                               coa_by_code: Dict[int, MasterCOA]) -> None:
        """A depreciation account left in suspense whose name says its asset class ('Fixtures & Fittings - depreciation
        charge for the year (B/S)', 'Motor Vehicle - depreciation charge b/fwd') goes to that class's depreciation code:
        brought forward when the name says b/fwd or accumulated, else this year's charge on the balance sheet for a
        credit (a debit is the P&L charge). A name with neither ('Plant and Equipment - Depreciation') is this year's
        charge when the same class also has a b/fwd account, else the total brought forward. Sent to review with the
        reason; left in suspense, the class's depreciation could not be worked at all."""
        from backend.app.services.review.setup_checks import ASSET_CLASS_CODES
        from backend.app.services.review.yearend_journals import FAR_CLASS
        brought = re.compile(r"b\s*/\s*f|b/?fwd|brought|accumulated|\bacc\b", re.I)
        in_year = re.compile(r"charge|for the year|this year|in year", re.I)

        def class_of(name: str) -> Optional[str]:
            cls = next((c for pattern, c in FAR_CLASS if pattern.search(name)), None)
            return cls if cls in ASSET_CLASS_CODES else None

        names = [re.sub(r"^\d+[\s\-_:]+", "", row["name"]).lower() for row in rows]
        with_bf = {class_of(n) for n in names if "depreciat" in n and brought.search(n)}
        for i, (row, name) in enumerate(zip(rows, names)):
            r = results[i]
            if "depreciat" not in name or (r and r.get("std_code") not in (None, SUSPENSE_CODE)):
                continue
            cls = class_of(name)
            if cls is None:
                continue
            codes = ASSET_CLASS_CODES[cls]
            net = float(row.get("net") or 0.0)
            if brought.search(name):
                target, why = codes["acc"][0], "brought forward"
            elif in_year.search(name) or cls in with_bf:
                target, why = (codes["charge"][0], "this year's charge (P&L)") if net > 0 else (codes["acc"][1], "this year's charge")
            else:
                target, why = codes["acc"][0], "the total to date"
            if target not in coa_by_code:
                continue
            mapped = {"std_code": target, "std_name": coa_by_code[target].std_name, "mapping_status": "NEEDS_REVIEW",
                      "confidence_score": 0.7, "match_source": "RULE",
                      "mapping_reason": f"Check: {cls.lower()} depreciation by its name, {why} ({target:04d})."}
            if r is None:
                results[i] = mapped
            else:
                r.update(mapped)

    @staticmethod
    def _purchases_to_additions(rows: List[Dict[str, Any]], results: List[Dict[str, Any]], coa_by_code: Dict[int, MasterCOA]) -> None:
        """An account of this year's asset purchases ('Equipment Purchase') goes to the additions code of its asset
        group (4121), not the cost brought forward (4120)."""
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in MOVABLE_SOURCES or r["std_code"] not in coa_by_code:
                continue
            account = coa_by_code[r["std_code"]]
            if account.category not in FIXED_ASSET_SECTIONS or not account.std_name.lower().endswith("- cost"):
                continue
            if not ASSET_PURCHASE_NAME.search(row["name"].lower()) or ASSET_FINANCE_NAME.search(row["name"].lower()):
                continue
            additions = next((c for c in coa_by_code.values() if c.std_code // 10 == r["std_code"] // 10
                              and "additions" in c.std_name.lower()), None)
            if additions:
                r["mapping_reason"] = (f"{r.get('mapping_reason') or ''} This year's purchases: additions "
                                       f"{additions.std_code:04d}, not cost brought forward {r['std_code']:04d}.").strip()
                r["std_code"], r["std_name"] = additions.std_code, additions.std_name

    @staticmethod
    def _freight_to_cost_of_sales(rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                                  coa_by_code: Dict[int, MasterCOA]) -> None:
        """Freight on goods bought ('Freight and services', 'Sea Freight Charges', 'Import clearance') is part of the
        cost of the stock (FRS 102 s13.6, rule S-002: cost includes carriage in): carriage and freight in cost of sales
        (1711), not the general admin one (3275). Postage, couriers and carriage out to customers stay in overheads."""
        # The firm's own cost of sales code for it (firm policy 'freight_in_code'): a firm may use purchases (1100)
        # or keep the chart's 1711
        target = SALES_FREIGHT
        try:
            from backend.app.services.shared import rules_store
            target = int(rules_store.load("firm_policies").get("freight_in_code") or SALES_FREIGHT)
        except (OSError, ValueError, TypeError):
            pass
        if target not in coa_by_code:
            target = SALES_FREIGHT
        if ADMIN_FREIGHT not in coa_by_code or target not in coa_by_code:
            return
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in MOVABLE_SOURCES or r["std_code"] not in (ADMIN_FREIGHT, SALES_FREIGHT):
                continue
            if r["std_code"] == target:
                continue
            name = row["name"].lower()
            if r["std_code"] == ADMIN_FREIGHT and (not FREIGHT_IN_NAME.search(name) or FREIGHT_OUT_NAME.search(name)):
                continue
            r["mapping_reason"] = (f"{r.get('mapping_reason') or ''} Freight on goods bought is a cost of sales "
                                   f"(FRS 102 s13.6), on the firm's code for it: {target:04d}, not "
                                   f"{r['std_code']:04d}.").strip()
            r["std_code"], r["std_name"] = target, coa_by_code[target].std_name

    # The client's own grouping says cost of sales: a 'Cost of sales:' / 'Direct costs:' parent, or the software's
    # account type
    COS_PARENT = re.compile(r"^(cost of (sales|goods sold)|direct (costs?|expenses)|cogs)\s*:", re.I)
    COS_TYPES = {"direct costs", "direct cost", "cost of sales", "cost of goods sold", "costofgoodssold", "cogs"}
    SECTION_TAG = re.compile(r"\s*\((general admin|employee costs|premises expenses|distribution costs|cost of sales)\)\s*$",
                             re.I)

    @staticmethod
    def _cost_of_sales_twin(rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                            coa_by_code: Dict[int, MasterCOA]) -> None:
        """A cost the firm chart has twice, in overheads and in cost of sales ('Commissions payable' 3306 and 1520,
        insurance, carriage, subcontractors), goes to the cost of sales one when the client's own books put it there:
        the account sits under a 'Cost of sales:' parent or the software marks it a direct cost (FRS 102 s5: cost of
        sales is the client's own grouping of costs): 'Cost of sales:Commissions payable' goes to 1520, not 3306."""
        def base(name: str) -> str:
            return MappingChecks.SECTION_TAG.sub("", name or "").strip().lower()
        cos = {}
        for c in coa_by_code.values():
            if c.std_code < 4000 and (c.category or "") == "Cost of sales":
                cos.setdefault(base(c.std_name), c.std_code)
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in MOVABLE_SOURCES or r["std_code"] >= 4000:
                continue
            here = coa_by_code.get(r["std_code"])
            if here is None or (here.category or "") == "Cost of sales":
                continue
            kind = re.sub(r"[\s_]+", " ", (row.get("account_type") or "")).strip().lower()
            if not (MappingChecks.COS_PARENT.search(row["name"].strip()) or kind in MappingChecks.COS_TYPES):
                continue
            twin = cos.get(base(here.std_name))
            if twin is None or twin not in coa_by_code:
                continue
            r["mapping_reason"] = (f"{r.get('mapping_reason') or ''} The client's books put it in cost of sales, so "
                                   f"the cost of sales code {twin:04d}, not {r['std_code']:04d}.").strip()
            r["std_code"], r["std_name"] = twin, coa_by_code[twin].std_name

    @staticmethod
    def _company_balances_not_trade(rows: List[Dict[str, Any]], results: List[Dict[str, Any]],
                                    coa_by_code: Dict[int, MasterCOA]) -> None:
        """A balance sheet account named after a company ('Acme Trading', 'ABC Limited') is a balance with a related or
        group company, not trade: the customers and suppliers sit in the debtors and creditors control accounts. Other
        debtors (4420) when a debit, other creditors (5350) when a credit, not trade debtors (4400) or trade creditors
        (5200). Names that say customer, supplier, debtors, creditors or a loan keep the code given."""
        if not {TRADE_DEBTORS, TRADE_CREDITORS, OTHER_DEBTORS, OTHER_CREDITORS} <= set(coa_by_code):
            return
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in MOVABLE_SOURCES or r["std_code"] not in (TRADE_DEBTORS, TRADE_CREDITORS):
                continue
            name = re.sub(r"[_\-]+", " ", re.sub(r"^\d+[\s\-_:]+", "", row["name"])).lower()     # 'Loan_Acme LTD'
            if not COMPANY_NAME.search(name) or TRADE_OR_LOAN_NAME.search(name) or BANK_WORDS.search(name):
                continue
            code = OTHER_DEBTORS if float(row.get("net") or 0.0) >= 0 else OTHER_CREDITORS
            r["mapping_reason"] = (f"{r.get('mapping_reason') or ''} Named after a company, so a related or group "
                                   f"company balance, not trade: {code:04d}, not {r['std_code']:04d}.").strip()
            r["std_code"], r["std_name"] = code, coa_by_code[code].std_name

    # Names that are on either side depending on the balance: (name, code for a debit, code for a credit). Corporation tax
    # is the year's charge (a debit, nothing brought forward) or the tax owed (a credit); 'Consulting' is fees paid (a
    # debit) or fees earned (a credit)
    EITHER_SIDE = [(re.compile(r"^(corporation tax|ct)( charge| expense| provision)?$"), 3800, 5310),
                   (re.compile(r"^consult(ing|ancy)( fees?)?$"), 3304, 440)]

    @staticmethod
    def _either_side(rows: List[Dict[str, Any]], results: List[Dict[str, Any]], coa_by_code: Dict[int, MasterCOA]) -> None:
        """An either-side name put on the side its balance is not: moved to the other code of its pair. Only a code the
        app chose (the client's own code or the accountant's stays), and only from one of the pair's two codes."""
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in FLAGGED_SOURCES - {"MEMORY", "LAST_YEAR"}:
                continue
            name = re.sub(r"\s+", " ", re.sub(r"[_\-]+", " ", re.sub(r"^\d+[\s\-_:]+", "", row["name"]))).strip().lower()
            for pattern, debit_code, credit_code in MappingChecks.EITHER_SIDE:
                if not pattern.match(name) or r["std_code"] not in (debit_code, credit_code):
                    continue
                balance, opening = float(row.get("net") or 0.0), float(row.get("opening") or 0.0)
                want = debit_code if balance > 0 and abs(opening) < 1 else credit_code if balance < 0 else r["std_code"]
                if want != r["std_code"] and want in coa_by_code:
                    r["mapping_reason"] = (f"{r.get('mapping_reason') or ''} Its balance is a "
                                           f"{'debit' if balance > 0 else 'credit'}, so {want:04d} "
                                           f"{coa_by_code[want].std_name}, not {r['std_code']:04d}.").strip()
                    r["std_code"], r["std_name"] = want, coa_by_code[want].std_name
                break

    @staticmethod
    def _flag_wrong_side(rows: List[Dict[str, Any]], results: List[Dict[str, Any]], coa_by_code: Dict[int, MasterCOA]) -> None:
        """Send a mapping to review (without changing it) when the account's own name or balance contradicts the
        code: a 'Debtors' account on a creditor code (or the reverse), or an income code holding a debit balance
        (money going out, e.g. a dividend paid booked to dividend income)."""
        for row, r in zip(rows, results):
            if not r or r["match_source"] not in FLAGGED_SOURCES or r["std_code"] not in coa_by_code:
                continue
            section = coa_by_code[r["std_code"]].category or ""
            name = re.sub(r"^\d+[\s\-_:]+", "", row["name"]).lower()
            balance = float(row.get("net") or 0.0)
            problem = None
            if DEBTOR_NAME.search(name) and section in CREDITOR_SECTIONS:
                problem = "the name says debtors but the code is a creditor"
            elif CREDITOR_NAME.search(name) and section in DEBTOR_SECTIONS:
                problem = "the name says creditors but the code is a debtor"
            elif section in FIXED_ASSET_SECTIONS and ASSET_FINANCE_NAME.search(name):
                problem = "the name mentions finance on an asset, which may be a liability (e.g. hire purchase 5000/5001)"
            elif (section in FIXED_ASSET_SECTIONS and balance < -WRONG_SIDE_MIN_BALANCE
                  and re.search(r"- (cost|additions)$", coa_by_code[r["std_code"]].std_name.lower())):
                problem = (f"a fixed asset cost code holds a credit balance of {-balance:,.2f} "
                           f"(finance owed on the asset is a liability, e.g. hire purchase 5000/5001)")
            elif section in INCOME_SECTIONS and balance > WRONG_SIDE_MIN_BALANCE:
                problem = (f"an income code holds a debit balance of {balance:,.2f}, which is money going out "
                           f"(a loss, or e.g. a dividend paid, which belongs in equity 8010/8011)")
            else:
                problem = MappingChecks._nature_problem(name, balance, coa_by_code[r["std_code"]])
            if problem:
                r["mapping_status"] = "NEEDS_REVIEW"
                r["mapping_reason"] = f"Check: {problem}. {r.get('mapping_reason') or ''}".strip()

    @staticmethod
    def _nature_problem(name: str, balance: float, account: MasterCOA) -> Optional[str]:
        """What is wrong when the account's nature (its name and the side of its balance) does not fit the code, for a
        TB with no account types to lock the code's class: income on a liability, tax or cost code; a cost code well
        in credit; debtors in credit or creditors in debit; a bank account number on a non-bank code."""
        section = account.category or ""
        code_name = (account.std_name or "").lower()
        if section == "Suspense and misposting":
            return None             # already waiting for a code
        plain =re.sub(r"\s*\(.*?\)\s*", " ", name).strip()          # 'deposits in (non-refundable)' -> 'deposits in'
        if (balance < -WRONG_SIDE_MIN_BALANCE and INCOME_NAME.search(plain) and not NOT_INCOME_NAME.search(plain)
                and section not in INCOME_SECTIONS):
            return (f"the name says income and the balance is a credit of {-balance:,.2f}, but the code is "
                    f"{account.std_code:04d} {account.std_name} (not income)")
        if (account.financial_class == "Profit and Loss" and section not in NOT_EXPENSE_SECTIONS
                and balance < -EXPENSE_CREDIT_MIN
                and not CREDIT_EXPENSE_NAME.search(code_name) and not CREDIT_EXPENSE_NAME.search(name)):
            return (f"a cost code holds a credit balance of {-balance:,.2f}: income, a refund, or a balance "
                    f"sheet item on the wrong code?")
        if account.std_code == 3800 and balance < -EXPENSE_CREDIT_MIN:
            return (f"the corporation tax charge holds a credit balance of {-balance:,.2f}: usually the tax owed "
                    f"(5310 Corporation tax, a creditor), unless it is last year's over-provision")
        # (No side check on balance-sheet codes: a TB of the year's movements shows debtors in credit when they fell)
        if BANK_NUMBER_NAME.match(name.strip()) and section != "Cash at bank and in hand":
            return "the account is named by a bank account number, but the code is not a bank account"
        # The VAT account on a bank code puts the HMRC payments in a bank tab and leaves the VAT reconciliation with no
        # movement. But a VAT savings pot is a bank ('4804 - VAT' in debit, 'Monzo VAT Pot Account'): only a credit
        # balance, what is owed to HMRC, is the VAT account itself
        if (section == "Cash at bank and in hand" and VAT_NAME.search(plain) and not BANK_WORDS.search(name)
                and balance < -WRONG_SIDE_MIN_BALANCE):
            return (f"the name says VAT and the balance is a credit of {-balance:,.2f} (owed to HMRC), but the code is "
                    f"a bank account (the VAT owed is a creditor, 5300)")
        return None

    @staticmethod
    def _separate_bank_accounts(results: List[Dict[str, Any]], coa_by_code: Dict[int, MasterCOA]) -> None:
        """Each bank account keeps its own line: when several accounts land on the same bank code (current
        4800-4809, deposit 4810-4819, reserve 4820-4829), the later ones move to the next free code of that kind.
        Codes set by an accountant or by the client's own firm codes are never moved."""
        taken = {r["std_code"] for r in results if r}
        seen = set()
        for r in results:
            code = r["std_code"] if r else None
            if code is None or not BANK_CODES[0] <= code <= BANK_CODES[1]:
                continue
            if code not in seen or r["match_source"] not in MOVABLE_SOURCES:
                seen.add(code)
                continue
            family = range(code // 10 * 10, BANK_CODES[1] + 1)
            free = next((c for c in family if c not in taken and c in coa_by_code), None)
            if free is None:
                continue  # every bank code is used; leave it for review
            r["std_code"], r["std_name"] = free, coa_by_code[free].std_name
            r["mapping_reason"] = f"{r.get('mapping_reason') or ''} Each bank account has its own line: {code:04d} was already used, so {free:04d}.".strip()
            taken.add(free)
            seen.add(free)
