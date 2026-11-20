"""A trial balance built from the ledger, account names from the ledger, and opening balances when the TB is a movement
TB or the GL carries openings."""

import logging
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backend.app.services.mapping.chart_lookup import account_name_keys
from backend.app.services.ingestion.ledger_files.common import LEDGER_DIFFERENCE

CODE_IN_NAME = re.compile(r"\s*(\d{4})\b(?![./-]\d)")   # '5310 Corporation tax', not '2024/25' or '01.04'

logger = logging.getLogger("backend.app.services.ingestion.ingestion_service")   # the service's own log name


class OpeningBalances:
    """A trial balance built from the ledger, account names from the ledger, and opening balances when the TB is a
    movement TB or the GL carries openings. Mixed into IngestionService."""

    @staticmethod
    def _tb_from_gl(gl_df: pd.DataFrame) -> pd.DataFrame:
        """A trial balance of the year's movements from the ledger: one line per account, its debits less its credits."""
        if gl_df.empty or "Parent_Account" not in gl_df.columns:
            return pd.DataFrame()
        moves = (gl_df["Debit"].astype(float) - gl_df["Credit"].astype(float)).groupby(gl_df["Parent_Account"]).sum()
        rows = [{"raw_account_name": acc, "account_type": None, "debit": round(max(net, 0.0), 2),
                 "credit": round(max(-net, 0.0), 2), "net": round(net, 2)}
                for acc, net in moves.items() if str(acc).strip() and abs(net) >= 0.005]
        # A ledger export that does not balance (a rounding or system account left out of it): the difference on one
        # suspense line, so the year's accounts still build and the difference is there to clear, not hidden
        gap = round(sum(r["net"] for r in rows), 2)
        if abs(gap) >= 0.005:
            rows.append({"raw_account_name": LEDGER_DIFFERENCE, "account_type": None, "debit": round(max(-gap, 0.0), 2),
                         "credit": round(max(gap, 0.0), 2), "net": -gap})
        out = pd.DataFrame(rows)
        out.attrs["from_gl"] = True
        return out

    @staticmethod
    def _name_tb_accounts_from_gl(tb_df: pd.DataFrame, gl_df: pd.DataFrame) -> pd.DataFrame:
        """Give TB sub-accounts their parent's name from the ledger. A TB may list a sub-account only by its own
        name ('J Smith' twice: once under Sales, once under Sub-Contractors) while the ledger names it in full
        ('Sales:J Smith'). The ledger account with the same name and the same amount is the one."""
        if tb_df.empty or gl_df.empty or "Parent_Account" not in gl_df.columns:
            return tb_df
        movement = (gl_df["Debit"].astype(float) - gl_df["Credit"].astype(float)).groupby(gl_df["Parent_Account"]).sum()
        opening = gl_df.attrs.get("opening_balances") or {}
        accounts = set(movement.index) | set(opening)
        by_leaf: Dict[str, List[str]] = {}
        for acc in accounts:
            if ":" in acc:
                by_leaf.setdefault(acc.split(":")[-1].strip().lower(), []).append(acc)
        if not by_leaf:
            return tb_df

        used = set()
        names = []
        for name, net in zip(tb_df["raw_account_name"], tb_df["net"]):
            full = str(name).strip()
            # A repeated name made unique by the export ('Rent (2)', 'Other debtors (1)'): the ledger's own name
            leaf = re.sub(r"\s*\(\d{1,2}\)$", "", full).lower()
            stripped = full.lower() not in by_leaf
            candidates = [] if full in accounts else [a for a in by_leaf.get(full.lower()) or by_leaf.get(leaf, [])
                                                      if a not in used]
            # Found only without its '(2)': the amount must agree too
            if len(candidates) > 1 or (candidates and stripped):
                candidates = [a for a in candidates
                              if min(abs(movement.get(a, 0.0) - float(net or 0)),
                                     abs(movement.get(a, 0.0) + opening.get(a, 0.0) - float(net or 0))) < 0.02]
            if len(candidates) == 1:
                full = candidates[0]
                used.add(full)
            names.append(full)
        tb_df = tb_df.copy()
        tb_df["raw_account_name"] = names
        return tb_df

    @staticmethod
    def _opening_balances_for_movement_tb(tb_df: pd.DataFrame, gl_df: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Some trial balances hold only this year's movements, with the opening balances in the GL's
        'Opening Balance' lines (the firm's ETB is opening + movement + journals). Decide which kind this TB is
        by testing balance-sheet accounts that have an opening balance:
          TB = movement            -> movement TB: return ({TB account: opening}, {GL-only account: opening})
          TB = opening + movement  -> closing TB:  return ({}, {}) (the TB already includes the opening)"""
        opening = gl_df.attrs.get("opening_balances") or {}
        if tb_df.empty or gl_df.empty or not opening or "Parent_Account" not in gl_df.columns:
            return {}, {}

        movement_by_key: Dict[str, float] = {}
        movements = (gl_df["Debit"].astype(float) - gl_df["Credit"].astype(float)).groupby(gl_df["Parent_Account"]).sum()
        for account, mv in movements.items():
            for key in account_name_keys(account):
                movement_by_key.setdefault(key, float(mv))
        opening_by_key: Dict[str, float] = {}
        for account, bal in opening.items():
            for key in account_name_keys(account):
                opening_by_key.setdefault(key, float(bal))

        found: Dict[str, float] = {}
        movement_votes = closing_votes = 0
        for _, t in tb_df.iterrows():
            name = t["raw_account_name"]
            keys = account_name_keys(name)
            # The exact name first: two accounts can differ only in capitals ('Bank interest received' and
            # 'Bank Interest Received'), and each has its own opening
            op = float(opening[name]) if name in opening else next((opening_by_key[k] for k in keys if k in opening_by_key), 0.0)
            if abs(op) < 0.01:
                continue
            mv = float(movements[name]) if name in movements.index else next((movement_by_key[k] for k in keys if k in movement_by_key), 0.0)
            tb_net = float(t["net"] or 0.0)
            tolerance = max(1.0, abs(tb_net) * 0.005)
            if abs(tb_net - mv) <= tolerance:
                movement_votes += 1
            elif abs(tb_net - (mv + op)) <= tolerance:
                closing_votes += 1
            found[name] = round(op, 2)

        if movement_votes >= 2 and movement_votes > closing_votes:
            tb_keys = set().union(*(account_name_keys(n) for n in tb_df["raw_account_name"]))
            not_in_tb = {acc: round(float(bal), 2) for acc, bal in opening.items()
                         if abs(bal) >= 0.01 and not (set(account_name_keys(acc)) & tb_keys)}
            logger.info("TB holds movements only (%d accounts agree); %d opening balances from the GL, %d accounts added",
                        movement_votes, len(found), len(not_in_tb))
            return found, not_in_tb
        return {}, {}

    @staticmethod
    def _closing_tb_gl_openings(tb_df: pd.DataFrame, gl_df: pd.DataFrame) -> Dict[str, float]:
        """For a closing TB: each account's beginning balance in the ledger, where the TB balance is that beginning
        balance plus the year's ledger lines (so the TB is known to include it). Used to keep last year's balance on
        a fixed asset additions / depreciation charge account out of this year's figures."""
        opening = gl_df.attrs.get("opening_balances") or {}
        if tb_df.empty or gl_df.empty or not opening or "Parent_Account" not in gl_df.columns:
            return {}
        movements = (gl_df["Debit"].astype(float) - gl_df["Credit"].astype(float)).groupby(gl_df["Parent_Account"]).sum()
        opening_by_key: Dict[str, float] = {}
        for account, bal in opening.items():
            for key in account_name_keys(account):
                opening_by_key.setdefault(key, float(bal))
        movement_by_key: Dict[str, float] = {}
        for account, mv in movements.items():
            for key in account_name_keys(account):
                movement_by_key.setdefault(key, float(mv))
        held: Dict[str, float] = {}
        for _, t in tb_df.iterrows():
            name = t["raw_account_name"]
            keys = account_name_keys(name)
            op = float(opening[name]) if name in opening else next((opening_by_key[k] for k in keys if k in opening_by_key), 0.0)
            if abs(op) < 0.01:
                continue
            mv = float(movements[name]) if name in movements.index else next((movement_by_key[k] for k in keys if k in movement_by_key), 0.0)
            tb_net = float(t["net"] or 0.0)
            if abs(tb_net - (mv + op)) <= max(1.0, abs(tb_net) * 0.005):
                held[name] = round(op, 2)
        return held

    @staticmethod
    def _chart_sides(accounts) -> Dict[str, Optional[str]]:
        """The chart's normal side ('Debit' / 'Credit') of the firm code an account's name starts with, if any."""
        coded = {}
        for account in accounts:
            m = CODE_IN_NAME.match(str(account).split(":")[-1])
            if m:
                coded[account] = int(m.group(1))
        if not coded:
            return {}
        try:
            from backend.app.core.database import SessionLocal
            from backend.app.models.database import MasterCOA
            db = SessionLocal()
            try:
                normal = {c.std_code: c.normal_balance for c in
                          db.query(MasterCOA).filter(MasterCOA.std_code.in_(set(coded.values()))).all()}
            finally:
                db.close()
        except Exception:                       # no chart to hand: nothing decided
            return {}
        return {a: normal.get(code) for a, code in coded.items()}

    @staticmethod
    def _orient_quickbooks_gl(gl_df: pd.DataFrame, tb_df: pd.DataFrame) -> pd.DataFrame:
        """QuickBooks GL amounts mean 'this account's balance went up', not 'debit'.
        For each account, opening balance + movement must equal the TB closing balance; where it only
        agrees with the sign reversed, the account's natural balance is a credit and its lines are flipped."""
        if gl_df.empty or "Parent_Account" not in gl_df.columns or tb_df.empty:
            return gl_df

        opening = gl_df.attrs.get("opening_balances", {})
        tb_net: Dict[str, float] = {}
        for _, t in tb_df.iterrows():
            for key in account_name_keys(t["raw_account_name"]):
                tb_net.setdefault(key, float(t["net"] or 0.0))

        movement = (gl_df["Debit"].astype(float) - gl_df["Credit"].astype(float)).groupby(gl_df["Parent_Account"]).sum()
        credit_natural, unresolved = set(), []
        for account, mv in movement.items():
            tb_closing = next((tb_net[k] for k in account_name_keys(account) if k in tb_net), None)
            if tb_closing is None:
                unresolved.append(account)
                continue
            closing = opening.get(account, 0.0) + mv
            tolerance = max(1.0, abs(tb_closing) * 0.005)
            if abs(closing - tb_closing) <= tolerance:
                continue
            if abs(closing + tb_closing) <= tolerance:
                credit_natural.add(account)
            # A TB of the year's movements (a TTB) holds the movement alone, so an account with an opening balance
            # is judged on its movement (otherwise its liabilities come out reversed)
            elif abs(mv) >= 0.005 and abs(mv - tb_closing) <= tolerance:
                continue
            elif abs(mv) >= 0.005 and abs(mv + tb_closing) <= tolerance:
                credit_natural.add(account)
            else:
                unresolved.append(account)

        # Not in the TB: the account's type decides (QuickBooks gives liability, equity and income amounts in their
        # natural sign): an account named with a firm code takes that code's normal side from the chart
        # ('5310 Corporation tax' is a credit, '3010 Directors' salaries' a debit); one with no code is left as read
        sides = OpeningBalances._chart_sides(unresolved)
        for account in list(unresolved):
            if sides.get(account) is not None:
                if sides[account] == "Credit":
                    credit_natural.add(account)
                unresolved.remove(account)
        flip = gl_df["Parent_Account"].isin(credit_natural)
        # A copy: when every line flips, the selection is a view of the same block and the swap would overwrite itself
        gl_df.loc[flip, ["Debit", "Credit"]] = gl_df.loc[flip, ["Credit", "Debit"]].to_numpy(copy=True)
        # Opening balances in the same debit-positive convention as the lines
        gl_df.attrs["opening_balances"] = {acc: (-bal if acc in credit_natural else bal) for acc, bal in opening.items()}
        if unresolved:
            logger.warning("QuickBooks GL: could not confirm the sign of %d account(s) against the TB: %s", len(unresolved), unresolved[:10])
        return gl_df
