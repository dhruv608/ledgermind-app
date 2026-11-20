"""Mapping by AI for accounts no rule places: the batch call, ledger samples for context, and the options offered on
screen."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.bedrock import bedrock_ai
from backend.app.models.database import GLTransaction, MasterCOA, TBRecord
from backend.app.services.mapping.mapping_parts.common import (
    AI_AUTO_ACCEPT_CONFIDENCE, AI_BATCH_SIZE, AI_PARALLEL_CALLS, SECTIONS_BY_ACCOUNT_TYPE, SUSPENSE_CODE,
)
from backend.app.services.mapping.mapping_parts.rules import RuleMapping

# No code found: a current asset goes to other debtors, a liability to other creditors
OTHER_DEBTORS, OTHER_CREDITORS = 4420, 5350
UNCODED_ASSET_TYPES = {"current asset", "current assets", "prepayment", "accounts receivable", "accounts receivable (a/r)"}
UNCODED_LIABILITY_TYPES = {"current liability", "current liabilities", "liability", "accounts payable",
                           "accounts payable (a/p)"}
PLACED = {OTHER_DEBTORS: "Placed in other debtors (a current asset with no code found), for review.",
          OTHER_CREDITORS: "Placed in other creditors (a liability with no code found), for review."}

logger = logging.getLogger("backend.app.services.mapping.mapping_service")   # the service's own log name


class AiMapping:
    """Mapping by AI for accounts no rule places: the batch call, ledger samples for context, and the options offered
    on screen. Mixed into MappingService."""

    @staticmethod
    def _resolve_by_ai(rows: List[Dict[str, Any]], samples: Dict[str, List[str]], all_coas: List[MasterCOA],
                       coa_by_code: Dict[int, MasterCOA], past=None) -> List[Tuple[Dict[str, Any], Optional[str]]]:
        """One (mapping, model) per row; model is None when the AI gave no usable answer.
        The AI chooses from the firm standard list only (extended codes are used when the client's own codes are
        firm codes), and only from the sections that fit the account type in the client's software."""
        standard = sorted((c for c in all_coas if not c.is_extended), key=lambda c: c.std_code)
        accounts = [{
            "name": r["name"],
            "account_type": r.get("account_type"),
            "net": r.get("net", 0.0),
            "samples": AiMapping._samples_for(r["name"], samples),
            # the firm's codes for similar accounts on its other clients
            "examples": past.similar(r["name"]) if past is not None else [],
        } for r in rows]

        # Accounts with the same allowed sections share a chart; batches never mix charts
        groups: Dict[Optional[frozenset], List[int]] = {}
        for idx, acc in enumerate(accounts):
            groups.setdefault(AiMapping._sections_for_type(acc["account_type"]), []).append(idx)
        jobs = []  # (row indexes, chart text)
        for sections, idxs in groups.items():
            chart = [c for c in standard if sections is None or c.category in sections or c.std_code == SUSPENSE_CODE]
            chart_text = "\n".join(f"{c.std_code:04d} | {c.std_name} | {c.category} | {c.financial_class}" for c in chart)
            jobs += [(idxs[i:i + AI_BATCH_SIZE], chart_text) for i in range(0, len(idxs), AI_BATCH_SIZE)]

        def run_batch(job) -> Dict[Any, Any]:
            idxs, chart_text = job
            try:
                return {int(a["i"]): a for a in bedrock_ai.map_accounts_batch([accounts[i] for i in idxs], chart_text) if "i" in a}
            except Exception as e:
                logger.warning("AI mapping batch failed: %s", e)
                return {"error": str(e)[:200]}

        with ThreadPoolExecutor(max_workers=AI_PARALLEL_CALLS) as pool:
            job_answers = list(pool.map(run_batch, jobs))

        results: List[Optional[Tuple[Dict[str, Any], Optional[str]]]] = [None] * len(accounts)
        for (idxs, _), answers in zip(jobs, job_answers):
            for i, idx in enumerate(idxs):
                acc = accounts[idx]
                answer = answers.get(i)
                mapping = AiMapping._ai_answer_to_mapping(acc, answer, answers.get("error"), coa_by_code)
                # Saved when the AI really answered with a chart code (suspense included); not when the call
                # failed or the code was invalid, so those are asked again next time
                chosen = str((answer or {}).get("code", "")).strip()
                usable = answer is not None and chosen.isdigit() and int(chosen) == mapping["std_code"]
                results[idx] = (mapping, answer.get("model") if usable else None)
        return results

    @staticmethod
    def suggest_options(engagement_id: str, raw_account_name: str, db: Session) -> List[Dict[str, Any]]:
        """The AI's top 3 firm codes for one account of this client (asked on demand from the review screen)."""
        from backend.app.core.bedrock import map_account_options
        record = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id,
                                                   TBRecord.raw_account_name == raw_account_name)).scalars().first()
        if record is None:
            return []
        all_coas = db.execute(select(MasterCOA)).scalars().all()
        coa_by_code = {c.std_code: c for c in all_coas}
        sections = AiMapping._sections_for_type(record.source_account_type)
        chart = [c for c in sorted(all_coas, key=lambda c: c.std_code)
                 if not c.is_extended and (sections is None or c.category in sections or c.std_code == SUSPENSE_CODE)]
        chart_text = "\n".join(f"{c.std_code:04d} | {c.std_name} | {c.category} | {c.financial_class}" for c in chart)
        samples = AiMapping._samples_for(raw_account_name, AiMapping._gl_samples(engagement_id, db))
        answers = map_account_options({"name": raw_account_name, "account_type": record.source_account_type,
                                       "net": float(record.net_amount or 0.0), "samples": samples}, chart_text)
        options, seen = [], set()
        for a in answers:
            code = str(a.get("code", "")).strip()
            if not code.isdigit() or int(code) not in coa_by_code or int(code) in seen:
                continue
            seen.add(int(code))
            options.append({"std_code": int(code), "std_name": coa_by_code[int(code)].std_name,
                            "confidence": max(0.0, min(1.0, float(a.get("confidence", 0.0)))),
                            "reason": str(a.get("reason", ""))[:200]})
        return options

    @staticmethod
    def _sections_for_type(account_type: Optional[str]) -> Optional[frozenset]:
        """Firm chart sections that fit the account type in the client's software; None = unknown, send them all."""
        if not isinstance(account_type, str) or not account_type.strip():
            return None
        return SECTIONS_BY_ACCOUNT_TYPE.get(account_type.strip().lower())

    @staticmethod
    def _uncoded_home(acc: Dict[str, Any], coa_by_code: Dict[int, MasterCOA]) -> int:
        """Where an account goes when no code is found: a current asset (by the client's software type) to other
        debtors, a liability to other creditors, anything else to suspense (a debit with no type could be a cost)."""
        kind = str(acc.get("account_type") or "").strip().lower()
        if kind in UNCODED_ASSET_TYPES and OTHER_DEBTORS in coa_by_code:
            return OTHER_DEBTORS
        if kind in UNCODED_LIABILITY_TYPES and OTHER_CREDITORS in coa_by_code:
            return OTHER_CREDITORS
        return SUSPENSE_CODE

    @staticmethod
    def _ai_answer_to_mapping(acc: Dict[str, Any], answer: Optional[Dict[str, Any]], error: Optional[str], coa_by_code: Dict[int, MasterCOA]) -> Dict[str, Any]:
        def needs_review(code: int, confidence: float, reason: str) -> Dict[str, Any]:
            return {
                "std_code": code,
                "std_name": coa_by_code[code].std_name if code in coa_by_code else "Suspense account",
                "mapping_status": "NEEDS_REVIEW",
                "confidence_score": confidence,
                "match_source": "AI",
                "mapping_reason": reason,
            }

        if answer is None:
            home = AiMapping._uncoded_home(acc, coa_by_code)
            return needs_review(home, 0.0, f"AI could not map this account ({error or 'no answer returned'}). "
                                           f"{PLACED.get(home, 'Placed in suspense.')}")

        try:
            code = int(str(answer.get("code")).strip())
            confidence = max(0.0, min(1.0, float(answer.get("confidence", 0.0))))
        except (TypeError, ValueError):
            home = AiMapping._uncoded_home(acc, coa_by_code)
            return needs_review(home, 0.0, f"AI returned an invalid answer. {PLACED.get(home, 'Placed in suspense.')}")

        reason = str(answer.get("reason") or "").strip()
        if code not in coa_by_code:
            home = AiMapping._uncoded_home(acc, coa_by_code)
            return needs_review(home, 0.0, f"AI suggested code {code}, which is not in the firm chart. "
                                           f"{PLACED.get(home, 'Placed in suspense.')}")

        if not RuleMapping._class_matches(acc.get("account_type"), coa_by_code[code]):
            return needs_review(code, confidence, f"Check: client software says '{acc['account_type']}' but AI chose a {coa_by_code[code].financial_class} account. {reason}")

        if confidence < AI_AUTO_ACCEPT_CONFIDENCE:
            return needs_review(code, confidence, f"AI is not confident. {reason}")

        return {
            "std_code": code,
            "std_name": coa_by_code[code].std_name,
            "mapping_status": "AI_SUGGESTED",
            "confidence_score": confidence,
            "match_source": "AI",
            "mapping_reason": reason,
        }

    @staticmethod
    def _gl_samples(engagement_id: str, db: Session, per_account: int = 3) -> Dict[str, List[str]]:
        rows = db.execute(
            select(GLTransaction.raw_account_name, GLTransaction.description)
            .where(GLTransaction.engagement_id == engagement_id, GLTransaction.description.isnot(None), GLTransaction.description != "")
        ).all()
        samples: Dict[str, List[str]] = {}
        for acc, desc in rows:
            bucket = samples.setdefault(acc.lower().strip(), [])
            if len(bucket) < per_account and desc not in bucket:
                bucket.append(desc[:80])
        return samples

    @staticmethod
    def _samples_for(raw_name: str, samples: Dict[str, List[str]]) -> List[str]:
        lower = raw_name.lower().strip()
        for key in (lower, re.sub(r"^\d+[\s\-_:]+", "", lower).strip(), lower.split(":")[-1].strip()):
            if key in samples:
                return samples[key]
        return []
