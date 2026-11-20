"""Mapping by rules: the client's own codes, the firm's code list, names against the statutory synonyms, and whether a
code's class matches the account type."""

import re
from typing import Any, Dict, List, Optional

from backend.app.models.database import MappingMemory, MasterCOA
from backend.app.services.mapping.mapping_parts.common import (
    BS_ACCOUNT_TYPES, CLIENT_CODE_RE, FIRM_CODES_MIN_ACCOUNTS, FIRM_CODES_MIN_SHARE, GENERAL_NAMES,
    GENERAL_PARENT_HEADINGS, NAME_FILLER_WORDS, PLACEHOLDER_ACCOUNT, PLACEHOLDER_PREFIX_RE, PL_ACCOUNT_TYPES,
    SHORT_CODE_RE, STATUTORY_SYNONYM_RULES, SUSPENSE_CODE, name_words, same_words,
)


class RuleMapping:
    """Mapping by rules: the client's own codes, the firm's code list, names against the statutory synonyms, and
    whether a code's class matches the account type. Mixed into MappingService."""

    @staticmethod
    def _client_code(raw_name: str, short: bool = False) -> Optional[int]:
        """Leading account code of a client account; a sub-account like '1100-1 - ...' gives its parent 1100. With
        short, a one or two digit code too ('0 - Retainer fees'): only for a client whose chart follows the firm's
        codes, where 0 is Sales; elsewhere a lone '0 - ' is a blank placeholder."""
        name = PLACEHOLDER_PREFIX_RE.sub("", raw_name.strip())
        m = CLIENT_CODE_RE.match(name) or (SHORT_CODE_RE.match(name) if short else None)
        return int(m.group(1)) if m else None

    @staticmethod
    def _code_name_agrees(raw_name: str, coa: MasterCOA) -> bool:
        name = re.sub(r"^\d+(?:-\d+)?[\s\-_:]+", "", raw_name.strip()).lower()
        core = name_words(re.sub(r"\(.*?\)", "", coa.std_name.lower())) - name_words(" ".join(NAME_FILLER_WORDS))
        return bool(core & name_words(name))

    @staticmethod
    def _client_uses_firm_codes(names: List[str], coa_by_code: Dict[int, MasterCOA]) -> bool:
        coded = agreeing = 0
        for name in names:
            code = RuleMapping._client_code(name)
            if code is None:
                continue
            coded += 1
            if code in coa_by_code and RuleMapping._code_name_agrees(name, coa_by_code[code]):
                agreeing += 1
        return coded >= FIRM_CODES_MIN_ACCOUNTS and agreeing / coded >= FIRM_CODES_MIN_SHARE

    @staticmethod
    def _resolve_by_rules(raw_name: str, coa_by_code: Dict[int, MasterCOA], mem_by_name: Dict[str, MappingMemory], trust_client_codes: bool = False) -> Optional[Dict[str, Any]]:
        clean_name = re.sub(r"^(client|company|name)\s*:\s*", "", raw_name, flags=re.IGNORECASE).strip()
        name_without_num = re.sub(r"^\d+[\s\-_:]+", "", clean_name).strip()
        name_lower = (name_without_num or clean_name).lower()

        def matched(code: int, source: str, confidence: float, reason: str) -> Dict[str, Any]:
            return {
                "std_code": code,
                "std_name": coa_by_code[code].std_name,
                "mapping_status": "MATCHED",
                "confidence_score": confidence,
                "match_source": source,
                "mapping_reason": reason,
            }

        category_stripped = re.sub(r"^(bank|expenses?|cost of sales|creditors?|debtors?|fa\s*-\s*[a-z0-9&]+)\s*:\s*", "", name_lower).strip()

        def rule_code() -> Optional[int]:
            """The firm code of the first naming rule that matches this account, if any."""
            for pattern, code in STATUTORY_SYNONYM_RULES:
                if code in coa_by_code and (re.search(pattern, name_lower, flags=re.IGNORECASE)
                                            or (category_stripped and re.search(pattern, category_stripped, flags=re.IGNORECASE))):
                    return code
            return None

        def exact_firm_name() -> Optional[MasterCOA]:
            """The firm account with this exact name. A name in several sections ('Printing, postage and stationery' in
            cost of sales, distribution and general admin) gives the overhead one unless the name says otherwise."""
            found = []
            # The same words, however written: plurals, '&' for 'and', a note in brackets, 'bfwd' / 'b/f' / 'brought
            # forward' ('Motor Vehicles - depreciation bfwd' is 'Motor vehicles - depreciation b/fwd')
            own_words = same_words(name_lower)
            for c in coa_by_code.values():
                if c.is_extended:  # name matching offers the firm standard list only
                    continue
                std_lower = c.std_name.lower()
                std_core = re.sub(r"\s*\(.*?\)", "", std_lower).strip()
                if name_lower in (std_lower, std_core) or (category_stripped and category_stripped in (std_lower, std_core))                         or (len(own_words) >= 3 and own_words == same_words(std_core)):
                    found.append(c)
            if not found:
                return None
            direct = ("Cost of sales", "Distribution costs")
            return sorted(found, key=lambda c: (c.category in direct, c.std_code))[0]

        # 1. Accountant-confirmed memory
        mem = mem_by_name.get(clean_name.lower()) or mem_by_name.get(name_lower)
        if mem and mem.std_code in coa_by_code and mem.std_code != SUSPENSE_CODE:   # suspense is never a code to reuse
            # The memory is the whole firm's, by name only: a naming rule for the other kind of account (balance sheet
            # v profit and loss: 'Corporation Tax' the liability, remembered from another client as the charge) wins
            ruled = rule_code()
            if ruled is not None and coa_by_code[ruled].financial_class != coa_by_code[mem.std_code].financial_class:
                result = matched(ruled, "RULE", 0.75,
                                 f"Check: confirmed before as {mem.std_code:04d} {coa_by_code[mem.std_code].std_name}, "
                                 f"but the name is a {coa_by_code[ruled].financial_class.lower()} account "
                                 f"({ruled:04d}) - please check.")
                result["mapping_status"] = "NEEDS_REVIEW"
                return result
            if name_lower.strip() in GENERAL_NAMES:
                result = matched(mem.std_code, "MEMORY", 0.7,
                                 f"Confirmed before as {mem.std_code:04d}, but '{clean_name.strip()}' is too general a name "
                                 f"to be sure it is the same kind of account here - please check.")
                result["mapping_status"] = "NEEDS_REVIEW"
                return result
            return matched(mem.std_code, "MEMORY", 1.0, "Previously confirmed by an accountant.")

        # 2. Client code is a firm code AND the names agree (a number alone is not enough) ...
        client_code = RuleMapping._client_code(clean_name, short=trust_client_codes)
        if client_code is not None and client_code in coa_by_code:
            c = coa_by_code[client_code]
            core_tokens = name_words(re.sub(r"\(.*?\)", "", c.std_name.lower()))
            if core_tokens and core_tokens <= name_words(name_lower):
                return matched(c.std_code, "CODE_AND_NAME", 1.0, f"Client code and name both match firm account {c.std_code:04d}.")
            # ... or this client's chart already follows the firm's codes, so its code is trusted,
            # unless the name is exactly another firm account (e.g. '610 - Prepayments' -> 4900 Prepayments)
            if trust_client_codes:
                # When the account name starts with a code in the chart, a P&L code is kept whatever the name
                # suggests ('3250 - Equipment' is an expense, capitalised item by item, never moved whole to plant
                # 4120). Only balance sheet codes are second-guessed by name ('5401 Lloyds Bank Loan' is a bank loan,
                # not the director's loan 5401)
                pl_code = c.financial_class == "Profit and Loss"
                by_name = None if pl_code else exact_firm_name()
                if by_name and by_name.std_code != c.std_code:
                    return matched(by_name.std_code, "COA_NAME", 0.95, f"Name is identical to firm account {by_name.std_code:04d} (client code {client_code} ignored).")
                if RuleMapping._code_name_agrees(clean_name, c):
                    # One shared word is not enough when a naming rule says it is another kind of account
                    # ('5401 Lloyds Bank Loan': 'loan' as in 5401 Director's loan, but a bank loan)
                    other = None if pl_code else rule_code()
                    if other is not None and other != c.std_code and coa_by_code[other].category != c.category                             and coa_by_code[other].financial_class == c.financial_class:
                        result = matched(other, "RULE", 0.75,
                                         f"Client code {c.std_code:04d} ('{c.std_name}') is another kind of account; the name "
                                         f"points to firm account {other:04d} - please confirm.")
                        result["mapping_status"] = "NEEDS_REVIEW"
                        return result
                    return matched(c.std_code, "CLIENT_FIRM_CODE", 0.97, f"Client's chart uses the firm's codes; mapped to {c.std_code:04d}.")
                # The code is only a placeholder ('Purchases Type D') or means something else ('5401 Lloyds Bank Loan':
                # 5401 is a director's loan in the firm chart): if a naming rule points elsewhere, suggest that instead
                # (still for review). Otherwise the client's code is kept, for review.
                suggested = None if pl_code else rule_code()
                # ... only when the rule's account is a different kind (5401 director's loan vs 5500 bank loan), not a
                # near neighbour in the same section (3290 vs 3291), where the client's own code stays
                if suggested is not None and suggested != c.std_code and not PLACEHOLDER_ACCOUNT.search(c.std_name.lower())                         and coa_by_code[suggested].category == c.category:
                    suggested = None
                if suggested is not None and suggested != c.std_code:
                    result = matched(suggested, "RULE", 0.75,
                                     f"Client code {c.std_code:04d} ('{c.std_name}') does not fit the name; the name points to "
                                     f"firm account {suggested:04d} - please confirm.")
                    result["mapping_status"] = "NEEDS_REVIEW"
                    return result
                result = matched(c.std_code, "CLIENT_FIRM_CODE", 0.70, f"Client code {c.std_code:04d} kept, but the name differs from the firm account '{c.std_name}' - please confirm.")
                result["mapping_status"] = "NEEDS_REVIEW"
                return result

        # 3. Deterministic synonym rules
        code = rule_code()
        if code is not None:
            return matched(code, "RULE", 0.98, "Matched a standard account-name rule.")

        # 4. Exact firm account name (ignoring the bracketed section)
        by_name = exact_firm_name()
        if by_name:
            return matched(by_name.std_code, "COA_NAME", 0.95, "Name is identical to a firm account name.")

        # 5. A sub-account follows its parent account ('Sales:Consulting Fees' -> Sales), unless the parent is only a
        #    general heading ('Expenses:...', 'Income:...') that says nothing about the account
        if ":" in clean_name:
            parent_name = clean_name.rsplit(":", 1)[0].strip()
            if parent_name.lower() not in GENERAL_PARENT_HEADINGS:
                parent = RuleMapping._resolve_by_rules(parent_name, coa_by_code, mem_by_name, trust_client_codes)
                if parent:
                    return matched(parent["std_code"], "PARENT", 0.92,
                                   f"Sub-account of '{parent_name}', mapped like its parent ({parent['std_code']:04d}).")

        return None

    @staticmethod
    def _class_matches(account_type: Optional[str], coa: Optional[MasterCOA]) -> bool:
        """True unless the client's own account type contradicts the firm account's class."""
        if not isinstance(account_type, str) or not account_type.strip() or coa is None:
            return True
        t = account_type.strip().lower()
        if t in PL_ACCOUNT_TYPES:
            return coa.financial_class == "Profit and Loss"
        if t in BS_ACCOUNT_TYPES:
            return coa.financial_class == "Balance Sheet"
        return True
