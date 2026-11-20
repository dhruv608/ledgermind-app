"""
Chart of Accounts (COA) Mapping Service
Maps each client trial balance account to one of the firm's standard codes (master_coa):
1. Mapping memory (accountant-confirmed)
2. Client code + name both agree with a firm account
   (or, when the client's chart already follows the firm's codes, the client code alone; '1100-1' rolls up to 1100)
3. Deterministic synonym rules
4. Exact firm account name
5. This client's earlier AI answer for the same account (client_account_mappings), so re-uploads and next year
   give the same answer
6. AWS Bedrock AI for everything else (its answers are saved for step 5)
Every result is checked against the account type from the client's software (P&L vs Balance Sheet).

The rules behind it are in mapping/mapping_parts (rules, ai_mapping, memory, filed_codes, checks,
openings), mixed into the service;
shared patterns and the synonym rules in mapping_parts/common.py (re-exported here for callers).
"""

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MappingMemory, MasterCOA, TBRecord
from backend.app.models.client_codes import TBClientCode   # its table is made at import, before any upload transaction
from backend.app.services.mapping.firm_rules import load_rules

from backend.app.services.mapping.mapping_parts.rules import RuleMapping
from backend.app.services.mapping.mapping_parts.ai_mapping import AiMapping
from backend.app.services.mapping.mapping_parts.memory import ClientMemory
from backend.app.services.mapping.mapping_parts.filed_codes import FiledCodes
from backend.app.services.mapping.mapping_parts.checks import MappingChecks
from backend.app.services.mapping.mapping_parts.openings import OpeningFixes
from backend.app.services.mapping.mapping_parts.common import SUSPENSE_CODE, account_key
from backend.app.services.ingestion.ledger_files.common import firm_code_of

# Staff pay codes and their directors' twins (salary, NI, pensions, bonuses), and a director's pay account's name
DIRECTOR_TWIN = {3000: 3010, 3001: 3011, 3002: 3012, 3003: 3013, 3004: 3014}
DIRECTOR_PAY = re.compile(r"\bdirectors?'?s?\b", re.I)

logger = logging.getLogger(__name__)

__all__ = ["MappingService", "mapping_service", "SUSPENSE_CODE"]


class MappingService(RuleMapping, AiMapping, ClientMemory, FiledCodes, MappingChecks, OpeningFixes):
    @staticmethod
    def map_engagement_tb(engagement_id: str, raw_tb_rows: List[Dict[str, Any]], db: Session, commit: bool = True,
                          filed_lines: Optional[list] = None) -> List[TBRecord]:
        rows = []
        for r in raw_tb_rows:
            debit = float(r.get("debit", 0.0) or 0.0)
            credit = float(r.get("credit", 0.0) or 0.0)
            opening = r.get("opening")
            opening = float(opening) if isinstance(opening, (int, float)) and opening == opening else None  # NaN -> None
            movement = float(r.get("net", debit - credit) or (debit - credit))
            gl_opening = r.get("gl_opening")
            gl_opening = float(gl_opening) if isinstance(gl_opening, (int, float)) and gl_opening == gl_opening else None
            rows.append({
                "name": str(r.get("raw_account_name", "")).strip(),
                "account_type": r["account_type"].strip() if isinstance(r.get("account_type"), str) and r["account_type"].strip() else None,
                "debit": debit,
                "credit": credit,
                "opening": opening,
                "net": round(movement + (opening or 0.0), 2),  # closing balance
                "gl_opening": gl_opening,                         # closing TB: the part that is last year's (ledger)
                "firm_code": firm_code_of(r.get("firm_code")),     # the client TB's own firm code column, if any
            })
        MappingService._keep_client_codes(engagement_id, rows, db)

        mappings = MappingService._map_rows(rows, db, engagement_id, filed_lines=filed_lines)

        records = []
        for row, mapping in zip(rows, mappings):
            rec = TBRecord(
                engagement_id=engagement_id,
                raw_account_name=row["name"],
                debit_amount=row["debit"],
                credit_amount=row["credit"],
                net_amount=row["net"],
                opening_amount=row["opening"],
                source_account_type=row["account_type"],
                **mapping,
            )
            records.append(rec)
            db.add(rec)

        MappingService._roll_forward_fixed_asset_openings(engagement_id, records, db)
        MappingService._split_closing_fixed_asset_openings(
            engagement_id, [(rec, row["gl_opening"]) for rec, row in zip(records, rows)], records, db)
        MappingService.close_pl_openings(engagement_id, records, db)

        if not commit:  # the caller saves everything together (upload: all or nothing)
            db.flush()
            return records
        db.commit()
        for rec in records:
            db.refresh(rec)
        return records

    @staticmethod
    def _keep_client_codes(engagement_id: str, rows: List[Dict[str, Any]], db: Session) -> None:
        """The firm codes the client's TB gives its accounts, kept for the job (a re-run of the coding reads them)."""
        db.query(TBClientCode).filter(TBClientCode.engagement_id == engagement_id).delete()
        for row in rows:
            if row.get("firm_code") is not None and row["name"]:
                db.add(TBClientCode(engagement_id=engagement_id, raw_account_name=row["name"][:255],
                                    firm_code=row["firm_code"]))

    @staticmethod
    def _client_codes(engagement_id: Optional[str], db: Session) -> Dict[str, int]:
        """{account name: the firm code the client's TB gave it} for the job."""
        if not engagement_id:
            return {}
        return {r.raw_account_name: r.firm_code for r in
                db.query(TBClientCode).filter(TBClientCode.engagement_id == engagement_id).all()}

    @staticmethod
    def remap_existing_records(engagement_id: str, db: Session) -> List[TBRecord]:
        existing_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id)).scalars().all()
        rows = [{
            "name": rec.raw_account_name,
            "account_type": rec.source_account_type,
            "net": float(rec.net_amount or 0.0),
        } for rec in existing_records]

        # Last year's filed TB (stored with the files) gives each account last year's code
        from backend.app.services.review.last_year import prior_lines
        eng = db.get(ClientEngagement, engagement_id)
        filed = prior_lines(eng, db) if eng is not None else []
        for rec, mapping in zip(existing_records, MappingService._map_rows(rows, db, engagement_id, filed_lines=filed)):
            for field, value in mapping.items():
                setattr(rec, field, value)

        db.commit()
        for rec in existing_records:
            db.refresh(rec)
        return existing_records

    @staticmethod
    def resolve_account_mapping(raw_account_name: str, db: Session, engagement_id: Optional[str] = None) -> Dict[str, Any]:
        return MappingService._map_rows([{"name": raw_account_name, "account_type": None, "net": 0.0}], db, engagement_id)[0]

    @staticmethod
    def _map_rows(rows: List[Dict[str, Any]], db: Session, engagement_id: Optional[str] = None,
                  filed_lines: Optional[list] = None) -> List[Dict[str, Any]]:
        """Return one mapping dict (std_code, std_name, mapping_status, confidence_score, match_source, mapping_reason) per row."""
        all_coas = db.execute(select(MasterCOA)).scalars().all()
        coa_by_code = {c.std_code: c for c in all_coas}
        owner = MappingService._owner_of(engagement_id, db)
        # The firm's remembered codes, whoever in the firm confirmed them (the latest confirmation wins)
        mem_by_name = {m.client_account_name.lower().strip(): m for m in db.execute(
            select(MappingMemory).order_by(MappingMemory.confirmed_at)).scalars().all()}

        trust_client_codes = MappingService._client_uses_firm_codes([r["name"] for r in rows], coa_by_code)

        # 0. This client's own code from last year comes first: each client stays consistent with its previous year,
        #    whatever the firm default or another client's choice
        last_year = MappingService.last_year_codes(engagement_id, db) if engagement_id else {}

        # 0b. With no last year in the app, last year's filed TB in the firm's codes: each account takes the code its
        #     balance had last year, found by its opening balance and name
        filed_codes = (MappingService._filed_codes(rows, filed_lines, engagement_id, db, coa_by_code)
                       if filed_lines and engagement_id and not last_year else {})

        own_name = MappingService._client_name_key(engagement_id, db)

        # The firm's habits: names it has coded the same way on several clients' working papers
        from backend.app.services.mapping.firm_examples import habits, name_key
        firm_habits = habits(db)

        results: List[Optional[Dict[str, Any]]] = []
        from backend.app.services.mapping.mapping_parts.code_in_name import code_in_name, double_coded, zero_is_sales
        double = double_coded(r["name"] for r in rows)
        # The client's TB gives the firm code itself ('Taxcalc Code' / 'Final code' column): that is the firm's coding
        # of the account, so it comes before every guess (guessed codes can swap the openings of similar accounts)
        kept_codes = MappingService._client_codes(engagement_id, db)
        own_codes: Dict[int, Dict[str, Any]] = {}
        for i, row in enumerate(rows):
            fc = row.get("firm_code") if row.get("firm_code") is not None else kept_codes.get(row["name"])
            if fc is None or fc not in coa_by_code:
                continue
            reason = (f"The client's trial balance gives the firm code {fc:04d} for this account "
                      f"({coa_by_code[fc].std_name}).")
            # Directors' pay is shown on its own (CA 2006 s412): a director's pay account the client coded as staff
            # pay goes to the directors' twin (3000 -> 3010 ...), as the accountant does
            twin = DIRECTOR_TWIN.get(fc)
            if twin in coa_by_code and DIRECTOR_PAY.search(row["name"]):
                reason += f" Its name says director's pay, so it goes to {twin:04d} {coa_by_code[twin].std_name}."
                fc = twin
            own_codes[i] = {"std_code": fc, "std_name": coa_by_code[fc].std_name, "mapping_status": "MATCHED",
                            "confidence_score": 0.99, "match_source": "CLIENT_FIRM_CODE", "mapping_reason": reason}
        for i, row in enumerate(rows):
            if i in own_codes:
                results.append(dict(own_codes[i]))
                continue
            # A balance sheet firm code in the name wins, after an accountant's confirmation and last year
            if not mem_by_name.get(row["name"].lower().strip()) and not last_year.get(account_key(row["name"])):
                by_code = (code_in_name(row["name"], coa_by_code, trust_client_codes, row.get("account_type"))
                           or zero_is_sales(row["name"], float(row.get("net") or 0.0), coa_by_code, double))
                if by_code:
                    results.append(by_code)
                    continue
            if own_name and 4800 in coa_by_code and MappingService._is_own_name_account(row["name"], own_name):
                results.append({"std_code": 4800, "std_name": coa_by_code[4800].std_name, "mapping_status": "MATCHED",
                                "confidence_score": 0.95, "match_source": "RULE",
                                "mapping_reason": "Named after the company itself (with an account number): its bank account."})
                continue
            bank = MappingService._bank_account_code(row["name"], own_name)
            if bank is not None and bank in coa_by_code and not mem_by_name.get(row["name"].lower().strip()) \
                    and MappingService._class_matches(row.get("account_type"), coa_by_code[bank]):
                results.append({"std_code": bank, "std_name": coa_by_code[bank].std_name, "mapping_status": "MATCHED",
                                "confidence_score": 0.9, "match_source": "RULE",
                                "mapping_reason": "Named like one of the client's own bank accounts (the company's name, a "
                                                  "masked account number or a deposit / current account)."})
                continue
            prior = last_year.get(account_key(row["name"]))
            if prior and prior[0] in coa_by_code and MappingService._class_matches(row.get("account_type"), coa_by_code[prior[0]]):
                results.append({"std_code": prior[0], "std_name": coa_by_code[prior[0]].std_name, "mapping_status": "MATCHED",
                                "confidence_score": 1.0, "match_source": "LAST_YEAR",
                                "mapping_reason": f"Same code as last year (year end {prior[1]:%d/%m/%Y})."})
                continue
            # A firm habit comes before the general naming rules (an accountant's own confirmation still comes first)
            habit = firm_habits.get(name_key(row["name"]))
            if (habit and habit[0] in coa_by_code and not mem_by_name.get(row["name"].lower().strip())
                    and MappingService._class_matches(row.get("account_type"), coa_by_code[habit[0]])):
                results.append({"std_code": habit[0], "std_name": coa_by_code[habit[0]].std_name,
                                "mapping_status": "MATCHED", "confidence_score": 0.97, "match_source": "FIRM_HABIT",
                                "mapping_reason": f"The firm's habit: coded {habit[0]:04d} on {habit[1]} clients' "
                                                  f"working papers."})
                continue
            result = MappingService._resolve_by_rules(row["name"], coa_by_code, mem_by_name, trust_client_codes)
            if result and not MappingService._class_matches(row.get("account_type"), coa_by_code.get(result["std_code"])):
                result = None  # Rule contradicts the client's own account type, let the AI decide
            results.append(result)

        # 5. The firm's account rules (Account rules page): the accountant's own choice beats an earlier AI guess
        firm_rules = load_rules(db, owner)
        for i, r in enumerate(results):
            if r is None:
                results[i] = MappingService._firm_default(rows[i]["name"], coa_by_code, firm_rules)

        # 5b. This client's earlier AI answers
        company = MappingService._company_of(engagement_id, db)
        notebook = MappingService._notebook(company, db) if company else {}
        for i, r in enumerate(results):
            if r is None:
                results[i] = MappingService._from_notebook(notebook.get(account_key(rows[i]["name"])), rows[i], coa_by_code)

        # 6. AI for accounts this client has never had answered; the answers are saved for next time
        pending = [i for i, r in enumerate(results) if r is None]
        if pending:
            samples = MappingService._gl_samples(engagement_id, db) if engagement_id else {}
            from backend.app.services.mapping.past_choices import pool_for
            past = pool_for(db, owner, exclude_engagement=engagement_id)
            ai_results = MappingService._resolve_by_ai([rows[i] for i in pending], samples, all_coas, coa_by_code, past)
            for i, (r, model) in zip(pending, ai_results):
                results[i] = r
                if company and model:
                    MappingService._save_to_notebook(company, rows[i], r, model, notebook, db)
        MappingService._separate_bank_accounts(results, coa_by_code)
        MappingService._use_filed_codes(rows, results, filed_codes, mem_by_name, coa_by_code)
        MappingService._purchases_to_additions(rows, results, coa_by_code)
        MappingService._freight_to_cost_of_sales(rows, results, coa_by_code)
        MappingService._cost_of_sales_twin(rows, results, coa_by_code)
        MappingService._company_balances_not_trade(rows, results, coa_by_code)
        MappingService._depreciation_by_class(rows, results, coa_by_code)
        MappingService._depreciation_not_amortisation(rows, results, coa_by_code)
        MappingService._depreciation_credits_to_balance_sheet(rows, results, coa_by_code)
        for i, own in own_codes.items():         # the client's own firm code is not second-guessed by the checks above
            results[i] = dict(own)
        MappingService._either_side(rows, results, coa_by_code)
        MappingService._flag_wrong_side(rows, results, coa_by_code)
        MappingService._flag_same_name(rows, results)
        if engagement_id:
            MappingService._flag_transfer_accounts(engagement_id, rows, results, coa_by_code, db)
        return results

    @staticmethod
    def confirm_and_save_mapping(raw_account_name: str, std_code: int, db: Session,
                                 owner_user_id: Optional[int] = None) -> Optional[MappingMemory]:
        if std_code == SUSPENSE_CODE:
            return None     # suspense is "not decided yet": never remembered for other clients
        clean_raw = raw_account_name.strip().lower()
        # One remembered code per account name for the whole firm
        stmt_mem = select(MappingMemory).where(MappingMemory.client_account_name == clean_raw).order_by(
            MappingMemory.confirmed_at.desc())
        mem = db.execute(stmt_mem).scalars().first()
        if mem:
            mem.std_code = std_code
            mem.match_source = "USER_CONFIRMED"
            mem.confidence_score = 1.0
        else:
            mem = MappingMemory(
                owner_user_id=owner_user_id,
                client_account_name=clean_raw,
                std_code=std_code,
                match_source="USER_CONFIRMED",
                confidence_score=1.0
            )
            db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem


mapping_service = MappingService()
