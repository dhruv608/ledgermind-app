"""Last year's filed codes: the codes the accounts were filed with, used again where the account is the same."""

from typing import Any, Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction, MasterCOA, TBRecord
from backend.app.services.ingestion.client_identity import company_key
from backend.app.services.mapping.mapping_parts.common import (
    BANK_CODES, BANK_LIKE, CARD_CODES, account_key, name_words,
)
from backend.app.services.mapping.mapping_parts.rules import RuleMapping


class FiledCodes:
    """Last year's filed codes: the codes the accounts were filed with, used again where the account is the same. Mixed
    into MappingService."""

    @staticmethod
    def _filed_codes(rows: List[Dict[str, Any]], filed_lines: list, engagement_id: str, db: Session,
                     coa_by_code: Dict[int, MasterCOA]) -> Dict[int, Tuple[int, str, float]]:
        """{row: (code, reason)} from last year's filed TB in the firm's codes. Each account's opening balance (its
        closing balance less the year's ledger movement; a movement TB's closing already holds its opening) is found
        among last year's balances: to the penny, and by a shared name word when two of last year's balances are the
        same amount. Balance sheet balances only; fixed assets keep their own rules (last year's additions and charge
        roll into cost and depreciation brought forward); a balance two accounts could take is left."""
        from backend.app.services.mapping.chart_lookup import account_name_keys
        lines = [l for l in filed_lines if l.code is not None and 4200 <= l.code <= 7999 and abs(l.amount) >= 1]
        if not lines:
            return {}
        by_account: Dict[str, float] = {}
        for name, dr, cr in db.execute(select(GLTransaction.raw_account_name, GLTransaction.debit_amount,
                                              GLTransaction.credit_amount).where(
                GLTransaction.engagement_id == engagement_id)):
            by_account[name or ""] = by_account.get(name or "", 0.0) + float(dr or 0.0) - float(cr or 0.0)
        movement: Dict[str, float] = {}
        for name, mv in by_account.items():
            for key in account_name_keys(name):
                movement.setdefault(key, mv)
        claims: Dict[int, List[int]] = {}
        for i, row in enumerate(rows):
            mv = by_account.get(row["name"])
            if mv is None:
                mv = next((movement[k] for k in account_name_keys(row["name"]) if k in movement), 0.0)
            opening = float(row.get("net") or 0.0) - mv
            if abs(opening) < 1:
                continue
            same = [j for j, l in enumerate(lines) if abs(l.amount - opening) < 0.01]
            if len(same) > 1:
                own = name_words(row["name"])
                same = [j for j in same if own & name_words(lines[j].name)]
            if len(same) == 1:
                claims.setdefault(same[0], []).append(i)
        out: Dict[int, Tuple[int, str, float]] = {}
        for j, taken in claims.items():
            line = lines[j]
            if len(taken) != 1 or line.code not in coa_by_code:
                continue
            i = taken[0]
            if not RuleMapping._class_matches(rows[i].get("account_type"), coa_by_code[line.code]):
                continue
            out[i] = (line.code, f"Last year's filed TB: its opening balance {line.amount:,.2f} was "
                                 f"{line.code:04d} {line.name} last year.", line.amount)
        return out

    @staticmethod
    def _use_filed_codes(rows: List[Dict[str, Any]], results: List[Dict[str, Any]], filed_codes: Dict[int, Tuple[int, str, float]],
                         mem_by_name: Dict[str, Any], coa_by_code: Dict[int, MasterCOA]) -> None:
        """Last year's filed code replaces a balance sheet code the mapping gave. Never a P&L account or a reserve,
        whose balance can equal one of last year's by chance (e.g. opening stock in the P&L), unless the ledger itself
        opens the account at last year's balance, as only a balance sheet account does. Never an accountant's confirmed
        code. A bank stays a bank or becomes the credit card it was last year; no other account becomes a bank."""
        for i, (code, reason, amount) in filed_codes.items():
            r = results[i]
            now = (r or {}).get("std_code")
            if now is None or now == code or mem_by_name.get(rows[i]["name"].lower().strip()):
                continue
            opened = rows[i].get("opening")
            if not 4000 <= now <= 7999 and not (isinstance(opened, (int, float)) and abs(float(opened) - amount) < 0.01):
                continue
            if (r or {}).get("match_source") in ("MEMORY", "CONFIRMED", "MANUAL", "LAST_YEAR"):
                continue
            bank_now, bank_then = BANK_CODES[0] <= now <= BANK_CODES[1], BANK_CODES[0] <= code <= BANK_CODES[1]
            if bank_then != bank_now and not (bank_now and code in CARD_CODES) \
                    and not (bank_then and BANK_LIKE.search(rows[i]["name"])):
                continue
            results[i] = {"std_code": code, "std_name": coa_by_code[code].std_name, "mapping_status": "MATCHED",
                          "confidence_score": 0.98, "match_source": "LAST_YEAR", "mapping_reason": reason}

    @staticmethod
    def last_year_codes(engagement_id: str, db: Session) -> Dict[str, Tuple[int, Any]]:
        """{account key: (code, year end)} from the same company's previous year in the app."""
        eng = db.get(ClientEngagement, engagement_id)
        if eng is None or not eng.client_name:
            return {}
        key = company_key(eng.client_name)
        earlier = [e for e in db.execute(select(ClientEngagement).where(
                       ClientEngagement.id != engagement_id, ClientEngagement.owner_user_id == eng.owner_user_id)).scalars()
                   if company_key(e.client_name) == key and e.period_end_date < eng.period_end_date]
        if not earlier:
            return {}
        last = max(earlier, key=lambda e: e.period_end_date)
        # Only codes last year actually settled: never one still waiting for review; an AI suggestion only when last
        # year was finished with a final workbook (the accountant signed it off)
        from backend.app.models.database import GeneratedWorkpaper
        finished = any(not (w.filename or "").upper().endswith("_DRAFT.XLSX") for w in db.execute(
            select(GeneratedWorkpaper).where(GeneratedWorkpaper.engagement_id == last.id)).scalars())
        out: Dict[str, Tuple[int, Any]] = {}
        for t in db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars():
            if t.std_code is None or t.match_source == "ROLL_FORWARD" or t.mapping_status in ("NEEDS_REVIEW", "UNMAPPED"):
                continue
            if t.mapping_status == "AI_SUGGESTED" and not finished:
                continue
            out.setdefault(account_key(t.raw_account_name), (t.std_code, last.period_end_date))
        return out
