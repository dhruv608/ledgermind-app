"""What the app remembers: the firm's defaults, the client's notebook of past answers, the client's own name accounts
and bank account codes."""

import re
from typing import Any, Dict, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientAccountMapping, ClientEngagement, MasterCOA
from backend.app.services.ingestion.client_identity import company_key
from backend.app.services.mapping.firm_rules import first_rule
from backend.app.services.mapping.mapping_parts.common import NOT_BANK_WORDS, account_key


class ClientMemory:
    """What the app remembers: the firm's defaults, the client's notebook of past answers, the client's own name
    accounts and bank account codes. Mixed into MappingService."""

    @staticmethod
    def _firm_default(raw_name: str, coa_by_code: Dict[int, MasterCOA], firm_rules) -> Optional[Dict[str, Any]]:
        rule = first_rule(firm_rules, raw_name)
        if rule is None or rule.std_code not in coa_by_code:
            return None
        return {"std_code": rule.std_code, "std_name": coa_by_code[rule.std_code].std_name, "mapping_status": "MATCHED",
                "confidence_score": 0.95, "match_source": "FIRM_DEFAULT",
                "mapping_reason": f"Firm account rule: {rule.note or rule.words[:60]} ({rule.std_code:04d})."}

    @staticmethod
    def _client_name_key(engagement_id: Optional[str], db: Session) -> Optional[str]:
        eng = db.get(ClientEngagement, engagement_id) if engagement_id else None
        return company_key(eng.client_name) if eng is not None and eng.client_name else None

    @staticmethod
    def _is_own_name_account(raw_name: str, own_key: str) -> bool:
        """'ACME LTD (8768)' for Acme Ltd: the company's name with an account number is how QuickBooks names a bank
        feed account."""
        m = re.match(r"^(.*?)\s*[\(\[#-]?\s*(\d{4,})\s*[\)\]]?\s*$", raw_name.strip())
        return bool(m) and bool(m.group(1).strip()) and company_key(m.group(1)) == own_key

    @staticmethod
    def _bank_account_code(raw_name: str, own_key: Optional[str]) -> Optional[int]:
        """The bank code family (4800 current, 4810 deposit) when the name is plainly one of the client's own bank
        accounts, however the bank feed names it: the company's own name ('ACME FOOD SERVICES LTD', 'ACME LTD#001',
        'Acme - EURO', or squashed as 'ACMEFOODSERL'), a masked number ('XXXX3477') or 'Deposit a/c' /
        'Current - Bank 2614'. Never a name that says what else it is (a loan, the directors, tax)."""
        name = (raw_name or "").strip()
        low = name.lower()
        if not name or NOT_BANK_WORDS.search(low):
            return None
        deposit = 4810 if re.search(r"\b(deposit|savings?|saver|reserve)\b", low) else 4800
        if re.fullmatch(r"[x*\s]{2,}\d{3,}", low):                       # 'XXXX3477', '**** 1234'
            return 4800
        if re.match(r"^(current|deposit|savings?|business|reserve)\s*(a/?c|account)\b", low) or \
                re.match(r"^(current|deposit|savings?)\s*[-–:]\s*[a-z].*\d{3,}", low):
            return deposit
        if not own_key:
            return None
        # The company's own name, without its legal words, a number, a currency or a feed suffix
        stripped = re.sub(r"[#(\[]?\s*\d{2,}\s*[)\]]?|\b(gbp|eur|euro|usd|current|account|a/c)\b", " ", low)
        plain = lambda ws: {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in ws if w != "and"}
        words = plain(w for w in re.findall(r"[a-z0-9]+", company_key(stripped) or "") if len(w) > 1)
        # ...the whole name (only part of it, 'Acme UK' for Acme Holdings (UK), can be a group company)
        own = plain(own_key.split()) - {"uk", "gb", "group", "holdings", "the", "co", "company"}
        if words and own and words <= own | {"uk", "gb"} and len(words & own) >= 0.8 * len(own) \
                and (len(words) >= 2 or any(len(w) >= 6 for w in words)):
            return deposit
        # A bank feed's squashed, cut-off name: 'A&BFOODSERL' or 'AB FOOD SERVICES' for 'A&B Food & Service Ltd'
        squashed = re.sub(r"[^a-z]", "", re.sub(r"\b(and|ltd|limited)\b", "", stripped))
        full = re.sub(r"[^a-z]", "", re.sub(r"\band\b", "", own_key))
        common = next((i for i, (a, b) in enumerate(zip(squashed, full)) if a != b), min(len(squashed), len(full)))
        # (cut off only when written as one word; with spaces, nearly the whole company name)
        if len(squashed) >= 8 and common >= 8 and common >= 0.8 * len(squashed) \
                and common >= (0.6 if " " not in name else 0.8) * len(full):
            return deposit
        return None

    @staticmethod
    def _owner_of(engagement_id: Optional[str], db: Session) -> Optional[int]:
        eng = db.get(ClientEngagement, engagement_id) if engagement_id else None
        return eng.owner_user_id if eng is not None else None

    @staticmethod
    def _company_of(engagement_id: Optional[str], db: Session) -> Optional[str]:
        """The key of this client's earlier AI answers: its owner and company ('1:acme')."""
        if not engagement_id:
            return None
        eng = db.get(ClientEngagement, engagement_id)
        return f"{eng.owner_user_id}:{company_key(eng.client_name)}" if eng and eng.client_name else None

    @staticmethod
    def _notebook(company: str, db: Session) -> Dict[str, ClientAccountMapping]:
        entries = db.execute(select(ClientAccountMapping).where(ClientAccountMapping.company_key == company)).scalars().all()
        return {e.account_key: e for e in entries}

    @staticmethod
    def _from_notebook(entry: Optional[ClientAccountMapping], row: Dict[str, Any], coa_by_code: Dict[int, MasterCOA]) -> Optional[Dict[str, Any]]:
        """The saved answer, unless its code has left the chart or the client changed the account's type."""
        if entry is None or entry.std_code not in coa_by_code:
            return None
        now_type = (row.get("account_type") or "").strip().lower()
        then_type = (entry.account_type or "").strip().lower()
        if now_type and then_type and now_type != then_type:
            return None
        return {
            "std_code": entry.std_code,
            "std_name": coa_by_code[entry.std_code].std_name,
            "mapping_status": entry.mapping_status,
            "confidence_score": entry.confidence_score,
            "match_source": "AI",
            "mapping_reason": f"Same as this client's earlier AI answer. {entry.mapping_reason or ''}".strip(),
        }

    @staticmethod
    def _save_to_notebook(company: str, row: Dict[str, Any], mapping: Dict[str, Any], model: str,
                          notebook: Dict[str, ClientAccountMapping], db: Session) -> None:
        key = account_key(row["name"])
        entry = notebook.get(key)
        if entry is None:
            entry = ClientAccountMapping(company_key=company, account_key=key)
            db.add(entry)
            notebook[key] = entry
        entry.account_type = row.get("account_type")
        entry.std_code = mapping["std_code"]
        entry.mapping_status = mapping["mapping_status"]
        entry.confidence_score = mapping["confidence_score"]
        entry.mapping_reason = (mapping.get("mapping_reason") or "")[:500]
        entry.model = model

    @staticmethod
    def forget_ai_answer(raw_account_name: str, db: Session, engagement_id: Optional[str] = None) -> int:
        """'Reset to AI': drop this client's saved AI answer for this account name, so the AI is asked again."""
        where = [ClientAccountMapping.account_key == account_key(raw_account_name)]
        company = ClientMemory._company_of(engagement_id, db)
        if company:
            where.append(ClientAccountMapping.company_key == company)
        result = db.execute(delete(ClientAccountMapping).where(*where))
        return result.rowcount or 0
