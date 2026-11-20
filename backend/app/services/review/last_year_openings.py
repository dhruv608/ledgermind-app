"""Opening balances from last year's TB: which lines open on which account, and last year's TB added to this year's
job."""

import io
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import account_name_keys
from backend.app.services.review.last_year_common import SHARE_CAPITAL_NAME, TB_PRIOR, chart_names, logger, pick_account
from backend.app.services.review.last_year_read import firm_coded_lines, prior_lines



def openings_from_prior_names(tb_df: pd.DataFrame, prior_df: pd.DataFrame,
                              chart: Dict[int, str]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Last year's TB in the client's own names (a Xero / QuickBooks / Sage export, no firm codes) as this year's
    opening balances, matched by account name, for a TB of the year's movements with no opening lines in the ledger.
    Returns ({this year's account: opening}, {last year's account with no line this year: opening}); the mapping
    then closes last year's P&L into the profit and loss reserve, as with a ledger's opening lines.
    Nothing when: last year's TB is in the firm's codes and balances (applied by code after the mapping), this
    year's TB already holds last year's balances (unchanged ones, share capital say, repeat to the penny), or last
    year's lines do not add up to zero (opening balances that would unbalance this year's TB)."""
    coded = firm_coded_lines(prior_df, chart)
    if coded and abs(sum(line.amount for line in coded)) < 1.0:
        return {}, {}
    from backend.app.services.ingestion.ingestion_service import IngestionService
    last: Dict[str, float] = {}
    for _, r in IngestionService._clean_xero_tb(prior_df).iterrows():
        name = str(r["raw_account_name"]).strip()
        amount = float(r["net"] or 0.0)
        if name and abs(amount) >= 0.005:
            last[name] = round(last.get(name, 0.0) + amount, 2)
    if not last or abs(sum(last.values())) >= 1.0:
        if last:
            logger.warning("Last year's TB does not balance (%.2f): not used as opening balances", sum(last.values()))
        return {}, {}
    this_year: Dict[str, float] = {}
    for name, net in zip(tb_df["raw_account_name"], tb_df["net"]):
        for key in account_name_keys(str(name)):
            this_year.setdefault(key, float(net or 0.0))

    # This year's TB holds closing balances (last year's are already in it) when it still shows the share capital,
    # which does not move in a year, under any name ('Share Capital' last year, 'Ordinary Shares' now); a TB of the
    # year's movements leaves it out. With no share capital last year (a company limited by guarantee, an RTM
    # company) the TB holds closing balances when last year's balances repeat in it to the penny; when none does,
    # it is a TB of the year's movements and last year's balances are added
    equity = [name for name, amount in last.items() if abs(amount) >= 1 and SHARE_CAPITAL_NAME.search(name)]
    shown_now = any(abs(float(net or 0.0)) >= 1 and SHARE_CAPITAL_NAME.search(str(name))
                    for name, net in zip(tb_df["raw_account_name"], tb_df["net"]))
    if shown_now:
        return {}, {}
    if not equity:
        def now(name: str) -> Optional[float]:
            return next((this_year[k] for k in account_name_keys(name) if k in this_year), None)
        repeats = sum(1 for name, amount in last.items()
                      if abs(amount) >= 1 and now(name) is not None and abs(now(name) - amount) < 0.01)
        if repeats >= min(2, len(last)):
            return {}, {}
    by_key: Dict[str, str] = {}
    for name in last:
        for key in account_name_keys(name):
            by_key.setdefault(key, name)
    found: Dict[str, float] = {}
    used = set()
    for name in tb_df["raw_account_name"]:
        match = next((by_key[k] for k in account_name_keys(str(name)) if k in by_key and by_key[k] not in used), None)
        if match is not None:
            found[str(name)] = last[match]
            used.add(match)
    not_in_tb = {name: amount for name, amount in last.items() if name not in used}
    logger.info("Last year's TB by account name: %d openings on this year's accounts, %d accounts added", len(found), len(not_in_tb))
    return found, not_in_tb


def lender_unknown(line_name: str, code: int, same: List[TBRecord]) -> bool:
    """Last year's balance on a loan code that this year holds several lenders, when last year's line names none of
    them ('Bank loans', 'Hire purchase less than 1 year') and none of them is the code's plain account: whose balance
    it is cannot be told from the TB, so it is not given to the biggest (that could put a whole balance brought
    forward on a loan taken out this year). It stays on a 'Brought forward' line
    of its own: each lender's share comes from last year's working paper or the lender statements (G4)."""
    from backend.app.services.loans.agreements import name_words
    from backend.app.services.workbook.balance_tabs.common import LOANS_AFTER_1_YEAR, LOANS_WITHIN_1_YEAR
    from backend.app.services.workbook.balance_tabs.loans import _loan_key
    if code not in LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR or len(same) < 2:
        return False
    words = lambda name: name_words(_loan_key(re.sub(r"^(?:\s*\d{3,5}\s*[-:]?)+\s*", "", name or "")))
    if any(not words(t.raw_account_name) for t in same):
        return False                     # the code's plain account ('Bank loans') takes it
    own = words(line_name)
    return not any(own & words(t.raw_account_name) for t in same)


def apply_prior_openings(engagement: ClientEngagement, db: Session) -> int:
    """Last year's closing TB (in the firm's codes) as this year's opening balances, for a TB of the year's movements
    whose ledger has no opening lines: each account's balance becomes movement + opening, as with a ledger's
    'Opening Balance' lines. The opening goes to the biggest account on its code (a loan code's balance that names
    none of its lenders excepted, lender_unknown); a code with no account this year gets a line of its own. Nothing
    is done when the ledger gave openings, or when the TB already holds last year's balances (it repeats unchanged ones, share capital say, to the penny). Returns the number of balances added."""
    from backend.app.models.database import MasterCOA
    records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars().all()
    if not records or any(t.opening_amount is not None for t in records):
        return 0
    lines = [line for line in prior_lines(engagement, db) if abs(line.amount) >= 0.005]
    if abs(sum(line.amount for line in lines)) >= 1.0:
        # A line the TB reads without a code (left out) would unbalance this year's TB: none are used
        logger.warning("Last year's TB in firm codes does not balance: not used as opening balances")
        return 0
    prior: Dict[int, float] = {}
    for line in lines:
        prior[line.code] = round(prior.get(line.code, 0.0) + line.amount, 2)
    if not prior:
        return 0
    this_year: Dict[int, float] = {}
    for t in records:
        if t.std_code is not None:
            this_year[t.std_code] = this_year.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
    if sum(1 for c, v in prior.items() if abs(v) >= 1 and abs(this_year.get(c, 0.0) - v) < 0.01) >= 2:
        return 0
    names = chart_names(db)
    added = 0
    for t in records:
        t.opening_amount = 0.0                  # known: the TB holds movements, openings come from last year's TB
    own_line: Dict[int, TBRecord] = {}              # a code with no account this year: one line of its own
    for line in lines:
        code, amount = line.code, line.amount
        same = [t for t in records if t.std_code == code]
        if same and lender_unknown(line.name, code, same):
            same = []                           # its own 'Brought forward' line: not guessed onto one lender
        if same:
            target = pick_account(line, same)
            target.opening_amount = round(float(target.opening_amount or 0.0) + amount, 2)
            target.net_amount = round(float(target.net_amount or 0.0) + amount, 2)
            target.mapping_reason = (f"{target.mapping_reason or ''} Opening £{amount:,.2f} from last year's TB "
                                     f"({code:04d}).").strip()
        elif code in own_line:
            own_line[code].opening_amount = round(float(own_line[code].opening_amount) + amount, 2)
            own_line[code].net_amount = round(float(own_line[code].net_amount) + amount, 2)
        else:
            if db.get(MasterCOA, code) is None:
                continue
            own_line[code] = TBRecord(
                engagement_id=engagement.id, raw_account_name=f"Brought forward: {names.get(code, code)}",
                std_code=code, std_name=names.get(code), debit_amount=0.0, credit_amount=0.0,
                net_amount=round(amount, 2), opening_amount=round(amount, 2), mapping_status="MATCHED",
                confidence_score=1.0, match_source="ROLL_FORWARD",
                mapping_reason="Last year's closing balance, no movement this year (last year's TB).")
            db.add(own_line[code])
        added += 1
    # Last year's P&L opens this year inside 8000 profit and loss b/fwd, and last year's additions and charge inside
    # the brought-forward fixed asset accounts, as with a ledger's opening lines
    from backend.app.services.mapping.mapping_service import MappingService
    everything = list(records) + list(own_line.values())
    MappingService._roll_forward_fixed_asset_openings(engagement.id, everything, db)
    MappingService.close_pl_openings(engagement.id, everything, db)
    db.commit()
    return added


def _add_books_opening_tb(engagement: ClientEngagement, name: str, data: bytes, db: Session) -> Dict[str, Any]:
    """A Bank + Dext / bank-only client: kept with its statements as last year's closing TB, and the books' trial
    balance made again with it (lines with only a name get their codes as on upload)."""
    import json
    from backend.app.core.s3 import s3_service
    from backend.app.services.bank_only import books as raw_books
    from backend.app.services.bank_only.input_files import OPENING_TB, read_input_files
    probe = read_input_files([(name, data)], {name: OPENING_TB})
    if not probe.opening_tb and not probe.opening_uncoded:
        return {"error": f"No balances could be read from {name}: it needs a heading row with the account (code or "
                         f"name), Debit and Credit."}
    prefix = f"raw_uploads/{engagement.id}/"
    stored = name.replace("\\", "/").rsplit("/", 1)[-1] or "last_year_tb.xlsx"
    try:
        roles = json.loads((s3_service.download_file_bytes(prefix + raw_books.ROLES_FILE) or b"{}").decode())
    except ValueError:
        roles = {}
    # One closing TB: an earlier one is set aside
    roles = {k: ("SKIP" if v == OPENING_TB else v) for k, v in roles.items()}
    s3_service.upload_file_bytes(data, prefix + stored)
    roles[stored] = OPENING_TB
    s3_service.upload_file_bytes(json.dumps(roles).encode(), prefix + raw_books.ROLES_FILE)
    try:
        raw_books.make_trial_balance(engagement, db)
    except ValueError as e:
        return {"error": f"Last year's TB was kept, but {e}: check it on the Books tab."}
    return {"added": len(probe.opening_tb) + len(probe.opening_uncoded), "how": "into the books"}


def _balances(prior_df: pd.DataFrame) -> bool:
    """Last year's TB in the client's own names adds up to nil (debits = credits), as a closing TB must."""
    from backend.app.services.ingestion.ingestion_service import IngestionService
    try:
        lines = IngestionService._clean_xero_tb(prior_df)
    except Exception:
        return False
    nets = [float(v or 0.0) for v in lines["net"]] if "net" in lines else []
    return bool(nets) and any(abs(v) >= 0.005 for v in nets) and abs(sum(nets)) < 1.0


def add_last_year_tb(engagement: ClientEngagement, name: str, data: bytes, db: Session) -> Dict[str, Any]:
    """Last year's TB uploaded inside the client, after the upload: kept with the client's files (as the upload keeps
    it) and used for the opening balances, by firm code or by account name. The accounts keep their codes (nothing is
    mapped again); last year's balances with no account this year are added and mapped. Refused when the TB already
    has opening balances. Returns {added, how} or {error}."""
    import json
    from backend.app.core.s3 import s3_service
    from backend.app.services.mapping.mapping_service import MappingService
    records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    if not records:
        return {"error": "Upload this year's trial balance first."}
    prefix = f"raw_uploads/{engagement.id}/"
    try:
        roles = json.loads((s3_service.download_file_bytes(prefix + "_roles.json") or b"{}").decode())
    except ValueError:
        roles = {}
    if any(t.opening_amount is not None and abs(float(t.opening_amount or 0)) >= 0.005 for t in records):
        for k, r in list(roles.items()):
            if r == TB_PRIOR:
                roles[k] = "SKIP"                # the new file is last year's TB from now on
        # Openings set from a last-year TB say so on the account ('Opening £... from last year's TB'); a ledger's own
        # openings do not
        from_prior = any("from last year's TB" in (t.mapping_reason or "") for t in records)
        if not from_prior:
            # The ledger gives this TB its openings: they stay. The file is still kept as last year's filed TB, which
            # the ETB's opening column and its checks read (e.g. a file missed at the start and sent later)
            stored = name.replace("\\", "/").rsplit("/", 1)[-1] or "last_year_tb.xlsx"
            s3_service.upload_file_bytes(data, prefix + stored)
            roles[stored] = TB_PRIOR
            s3_service.upload_file_bytes(json.dumps(roles).encode(), prefix + "_roles.json")
            return {"added": 0, "how": "kept as last year's filed TB for the ETB opening (the ledger's openings stay)"}
        # The openings came from last year's TB uploaded before (a wrong file, or one missed and sent now): this one
        # replaces it, its openings taken back out and the accounts it alone added removed
        for t in records:
            only_last_year = (t.match_source == "ROLL_FORWARD" or (not float(t.debit_amount or 0) and not float(t.credit_amount or 0)
                              and t.opening_amount is not None and abs(float(t.net_amount or 0) - float(t.opening_amount or 0)) < 0.005
                              and abs(float(t.opening_amount or 0)) >= 0.005))
            if only_last_year:
                db.delete(t)                    # an account only last year's TB gave (no movement this year)
            else:
                # net = movement + opening: the old opening taken back out
                t.net_amount = round(float(t.net_amount or 0) - float(t.opening_amount or 0), 2)
                t.opening_amount = None
        db.flush()
        s3_service.upload_file_bytes(json.dumps(roles).encode(), prefix + "_roles.json")
        records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    from backend.app.services.bank_only.books import is_books_client
    if is_books_client(engagement):
        return _add_books_opening_tb(engagement, name, data, db)
    try:
        # As the upload reads it: a plain TB, or last year's working paper by its ETB final balances (not its first
        # sheet, the index)
        from backend.app.services.review.last_year_common import prior_tb_frame
        frame = prior_tb_frame([(name, data)], db)
        df = frame[1] if frame else (pd.read_csv(io.BytesIO(data), header=None) if name.lower().endswith(".csv")
                                     else pd.read_excel(io.BytesIO(data), header=None))
    except Exception:
        return {"error": f"{name} could not be read as a spreadsheet."}
    if engagement.prior_period_end_date is None:
        # Its date is the end of the period before this one (a short period after a change of year end)
        from backend.app.services.review.last_year_common import last_year_end
        engagement.prior_period_end_date = last_year_end(df, engagement.period_end_date)

    # Kept with the client's files, as last year's TB (the review's last year comparison reads it from there)
    prefix = f"raw_uploads/{engagement.id}/"
    stored = name.replace("\\", "/").rsplit("/", 1)[-1] or "last_year_tb.xlsx"
    s3_service.upload_file_bytes(data, prefix + stored)
    try:
        roles = json.loads((s3_service.download_file_bytes(prefix + "_roles.json") or b"{}").decode())
    except ValueError:
        roles = {}
    roles[stored] = TB_PRIOR
    s3_service.upload_file_bytes(json.dumps(roles).encode(), prefix + "_roles.json")

    # 1. In the firm's codes: by code, as at upload
    lines = prior_lines(engagement, db)
    if lines:
        added = apply_prior_openings(engagement, db)
        if added:
            return {"added": added, "how": "by firm code"}
        # Not used for the openings because this year's TB holds closing balances already (it repeats last year's):
        # kept as last year's filed TB for the ETB opening column and the opening checks, as a TB by account name is.
        # Not an error; only a TB that does not balance is
        if abs(sum(line.amount for line in lines)) < 1.0:
            return {"added": 0, "how": "kept as last year's filed TB for the opening checks (this year's TB holds "
                                       "closing balances, so the openings come from it and the ledger)"}
        return {"error": "Last year's TB in the firm's codes was not used: its debits and credits do not agree. Check "
                         "the file is last year's closing TB and upload it again."}

    # 2. In the client's own names: matched to this year's accounts by name
    tb = pd.DataFrame([{"raw_account_name": t.raw_account_name, "net": float(t.net_amount or 0)} for t in records])
    found, extra = openings_from_prior_names(tb, df, chart_names(db))
    if not found and not extra:
        # This year's TB holds closing balances (the usual pair: a closing TB and last year's): the openings come from
        # the TB less the ledger, and last year's TB, kept above, is the filed TB the ETB's opening column and the Data
        # check's opening checks read. Not an error (refusing would push the accountant to build a movement TB by
        # hand). Only one that does not balance is refused.
        if _balances(df):
            return {"added": 0, "how": "kept as last year's filed TB for the opening checks (this year's TB holds "
                                       "closing balances, so the openings come from it and the ledger)"}
        return {"error": "Last year's TB was not used: its debits and credits do not agree. Check the file is last "
                         "year's closing TB (one balance column) and upload it again."}
    by_name: Dict[str, List[TBRecord]] = {}
    for t in records:
        by_name.setdefault(t.raw_account_name, []).append(t)
    for t in records:
        t.opening_amount = 0.0            # known now: this year's TB holds movements
    for acc, amount in found.items():
        target = (by_name.get(acc) or [None])[0]
        if target is None:
            continue
        target.opening_amount = round(amount, 2)
        target.net_amount = round(float(target.net_amount or 0) + amount, 2)
        target.mapping_reason = f"{target.mapping_reason or ''} Opening £{amount:,.2f} from last year's TB.".strip()
    rows = [{"name": acc, "account_type": None, "debit": 0.0, "credit": 0.0, "opening": amount, "net": amount}
            for acc, amount in extra.items()]
    new = []
    for row, mapping in zip(rows, MappingService._map_rows(rows, db, str(engagement.id)) if rows else []):
        rec = TBRecord(engagement_id=engagement.id, raw_account_name=row["name"], debit_amount=0.0, credit_amount=0.0,
                       net_amount=round(row["net"], 2), opening_amount=round(row["opening"], 2), **mapping)
        db.add(rec)
        new.append(rec)
    everything = records + new
    MappingService._roll_forward_fixed_asset_openings(engagement.id, everything, db)
    MappingService.close_pl_openings(engagement.id, everything, db)
    db.commit()
    return {"added": len(found) + len(extra), "how": "by account name"}
