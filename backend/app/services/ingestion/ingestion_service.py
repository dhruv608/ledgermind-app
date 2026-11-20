"""
Universal Ingestion & Normalization Service
Parses multi-sheet accounting exports from Xero, QuickBooks Online, and multi-file batches.
Extracts Client Name, Period End Date, and standardizes data streams:
- Trial Balance (TTB / TB)
- General Ledger (GL) Line-by-Line Transactions
- Aged Payables / Creditors Listing (AP)
- Aged Receivables / Debtors Listing (AR)

The readers behind it are in ingestion/ledger_files (roles, cleaning, openings), mixed into the service;
shared patterns and helpers in ledger_files/common.py (re-exported here for callers).
"""

import io
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.app.services.ingestion.ledger_files.roles import FileRoles
from backend.app.services.ingestion.ledger_files.cleaning import LedgerCleaning
from backend.app.services.ingestion.ledger_files.openings import OpeningBalances
from backend.app.services.ingestion.ledger_files.common import (
    COMPANY_SUFFIX, FilesNeedRoles, NormalizedEngagementData, PERIOD_ROLE_PRIORITY, REPORT_TITLE_WORDS, ROLES,
    ROLE_LABELS, SKIP, UNKNOWN, parse_period_end, with_formula_values,
)

logger = logging.getLogger(__name__)

__all__ = ["IngestionService", "ingestion_service", "FilesNeedRoles", "parse_period_end", "with_formula_values"]


def readable_amounts(gl_df: pd.DataFrame) -> pd.DataFrame:
    """The ledger's Debit and Credit as numbers. A cell that is not a number (e.g. a letter typed in an amount) reads
    as nil and is logged rather than stopping the upload; the ledger v TB check then shows the difference."""
    if gl_df.empty:
        return gl_df
    attrs = dict(gl_df.attrs)
    for col in ("Debit", "Credit"):
        if col not in gl_df.columns:
            continue
        values = gl_df[col]
        as_text = values.astype(str).str.replace(",", "", regex=False).str.replace("£", "", regex=False).str.strip()
        numbers = pd.to_numeric(as_text.where(values.notna(), None), errors="coerce")
        bad = values.notna() & as_text.ne("") & numbers.isna()
        if bad.any():
            logger.warning("Ledger: %d %s amount(s) not a number, read as nil: %s", int(bad.sum()), col,
                           list(zip(gl_df.loc[bad, "Parent_Account"] if "Parent_Account" in gl_df.columns else [],
                                    values[bad]))[:5])
        gl_df[col] = numbers.fillna(0.0)
    gl_df.attrs.update(attrs)
    return gl_df


class IngestionService(FileRoles, LedgerCleaning, OpeningBalances):
    @staticmethod
    def detect_and_parse(file_bytes: bytes, filename: str) -> NormalizedEngagementData:
        """Parses a single file (consolidated multi-tab workbook or standalone file)."""
        return IngestionService.detect_and_parse_files([(filename, file_bytes)])

    @staticmethod
    def detect_and_parse_files(files_data: List[Tuple[str, bytes]], roles: Optional[Dict[str, str]] = None,
                               _tabs: bool = False,
                               layouts: Optional[Dict[str, Dict[str, Any]]] = None) -> NormalizedEngagementData:
        """
        Parses 1 consolidated file OR multiple separate files (2, 3, or 4 files)
        for a single client engagement. roles: what the accountant said a file (or a tab of a combined
        workbook, as '<tab>.xlsx') is ({name: TB/GL/AR/AP/SKIP}), used before anything the app works out. Raises
        FilesNeedRoles when a file cannot be identified or two files (or tabs) look like the same report.
        layouts: {name: {header_row, mapping, software}} for a TB or ledger read by the columns the accountant
        confirmed (column_layouts: Sage, or any layout the Xero/QuickBooks readers do not know).
        """
        layouts = layouts or {}
        if not files_data:
            raise ValueError("No files provided for ingestion.")
        roles = {k: v for k, v in (roles or {}).items() if v in ROLES or v == SKIP}
        if not _tabs:
            files_data = [(n, with_formula_values(n, b)) for n, b in files_data]

        # One combined workbook: each tab is read as its own file. A tab that is none of the four is left out;
        # two tabs that look like the same report are asked about, like separate files
        tabs = None if _tabs else IngestionService._split_combined(files_data)
        if tabs:
            return IngestionService.detect_and_parse_files(tabs, roles=roles, _tabs=True, layouts=layouts)

        # Multi-file batch (or single sheet file)
        classified_files: Dict[str, Tuple[str, bytes, Optional[pd.ExcelFile]]] = {}
        gl_parts: List[Tuple[str, bytes, Optional[pd.ExcelFile]]] = []      # the ledger's files, in upload order
        identified = {f["filename"]: f for f in IngestionService.identify_files(files_data)}
        for name, role in roles.items():
            if name in identified:
                identified[name] = {"filename": name, "role": role, "how": "chosen"}
        for f in identified.values():
            if _tabs and f["role"] == UNKNOWN:
                f["role"] = SKIP            # a tab nothing identifies (notes, workings) is simply not read
        found = list(identified.values())
        unknown = [f["filename"] for f in found if f["role"] == UNKNOWN]
        seen: Dict[str, List[str]] = {}
        for f in found:
            if f["role"] in ROLES:
                seen.setdefault(f["role"], []).append(f["filename"])
        # Several ledger files are the parts of one ledger (a quarter or month each), read together below
        twice = {r: n for r, n in seen.items() if len(n) > 1 and r != "GL"}
        if unknown or twice:
            parts = []
            if unknown:
                parts.append(f"could not tell what {', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'}")
            for r, n in twice.items():
                shown = [x[:-5] if _tabs and x.endswith(".xlsx") else x for x in n]
                parts.append(f"{' and '.join(shown)} both look like the {ROLE_LABELS[r].lower()}")
            what = "tab" if _tabs else "file"
            raise FilesNeedRoles(found, f"Please say what each {what} is: " + "; ".join(parts) + ".")
        client_candidates: List[Tuple[str, str]] = []      # (name, role of the file it came from)
        period_by_role: Dict[str, date] = {}
        source_system = "XERO"

        for fname, fbytes in files_data:
            fname_lower = fname.lower()
            if not (fname_lower.endswith(".xlsx") or fname_lower.endswith(".xls") or fname_lower.endswith(".csv")):
                continue

            try:
                xl = pd.ExcelFile(io.BytesIO(fbytes)) if not fname_lower.endswith(".csv") else None
            except Exception:
                continue

            # What the file is (checked above: every file known, no report twice); tabs of a combined workbook
            # that are none of the four are skipped, and a second tab of the same kind does not replace the first
            role = identified.get(fname, {}).get("role", UNKNOWN)
            if role == "GL":
                gl_parts.append((fname, fbytes, xl))
            if role not in ROLES or role in classified_files:
                continue
            classified_files[role] = (fname, fbytes, xl)

            # Extract metadata
            try:
                first_df = xl.parse(xl.sheet_names[0], header=None) if xl else pd.read_csv(io.BytesIO(fbytes), header=None)
                c_name, p_end = IngestionService._extract_header_metadata(first_df)
                if c_name:
                    client_candidates.append((c_name, role))
                if p_end and role not in period_by_role:
                    period_by_role[role] = p_end

                # Check source system markers
                raw_text = " ".join([str(v) for v in first_df.iloc[:10].values.flatten() if pd.notna(v)]).lower()
                if "distribution account" in raw_text or "a/p ageing" in raw_text or "split" in raw_text:
                    source_system = "QUICKBOOKS"
                elif "debit - year to date" in raw_text or "payable invoice" in raw_text or "xero" in raw_text:
                    source_system = "XERO"
            except Exception:
                pass

        # Resolve Client Name
        client_name = "Client Company Ltd"
        if client_candidates:
            # The company name, not a report title: a name with 'Ltd' / 'Limited' first, then the trial balance's,
            # then the one most files agree on, then the longest
            from collections import Counter as _Counter
            names = [(n, r) for n, r in client_candidates
                     if COMPANY_SUFFIX.search(n) or not REPORT_TITLE_WORDS.search(n)] or client_candidates
            agree = _Counter(n.lower() for n, _ in names)
            client_name = max(names, key=lambda nr: (bool(COMPANY_SUFFIX.search(nr[0])), nr[1] == "TB",
                                                      agree[nr[0].lower()], len(nr[0])))[0]
        else:
            # Fallback to filename prefix
            first_fname = files_data[0][0]
            clean_name = re.sub(r"[-_](trial|balance|general|ledger|aged|payables|receivables|summary|detail).*", "", first_fname, flags=re.IGNORECASE).strip()
            if clean_name:
                client_name = clean_name.replace("_", " ")

        # Resolve Period End Date
        # The date most of the files agree on (a typo in one title, e.g. the TB saying 2025 while the ledger and the
        # balance reports say 2026, loses); on a tie the TB's date wins, then the ledger's
        from collections import Counter
        votes = Counter(period_by_role.values())
        top = max(votes.values()) if votes else 0
        period_end = next((period_by_role[r] for r in PERIOD_ROLE_PRIORITY
                           if r in period_by_role and votes[period_by_role[r]] == top), None)
        if period_end is None:
            period_end = next(iter(period_by_role.values()), date(2026, 6, 30))

        # A TB or ledger read by its confirmed columns carries the software it came from (Sage, or another)
        from backend.app.services.ingestion import column_layouts
        used = [layouts[f[0]] for r, f in classified_files.items() if r in ("TB", "GL") and f[0] in layouts]
        if used:
            source_system = next((u.get("software") for u in used if u.get("software") == "SAGE"), "OTHER")

        from backend.app.services.ingestion.ledger_files.gl_parts import read_parts

        def read_gl(name: str, xl: pd.ExcelFile) -> pd.DataFrame:
            """One ledger file, by the columns the accountant confirmed or the software's own layout."""
            raw_gl = xl.parse(xl.sheet_names[0], header=None)
            lay = layouts.get(name)
            return (column_layouts.read_gl(raw_gl, int(lay["header_row"]), {k: int(v) for k, v in lay["mapping"].items()})
                    if lay else IngestionService._clean_universal_gl(raw_gl, source_system))

        # 1. Parse Trial Balance (Required)
        tb_df = pd.DataFrame()
        if "TB" in classified_files:
            tb_name, _, xl = classified_files["TB"]
            if xl:
                raw_tb = xl.parse(xl.sheet_names[0], header=None)
                lay = layouts.get(tb_name)
                tb_df = (column_layouts.read_tb(raw_tb, int(lay["header_row"]), {k: int(v) for k, v in lay["mapping"].items()})
                         if lay else IngestionService._clean_xero_tb(raw_tb))
        elif len(files_data) == 1 and "GL" not in classified_files:
            # If only 1 file and not tagged, parse first sheet as TB (a ledger alone is made into a TB below, one line
            # per account; read as a TB, every ledger line would become an account)
            _, _, xl = list(classified_files.values())[0]
            if xl:
                raw_tb = xl.parse(xl.sheet_names[0], header=None)
                tb_df = IngestionService._clean_xero_tb(raw_tb)

        if tb_df.empty and "GL" in classified_files:
            # No trial balance for the year (only the ledger and last year's filed TB): the ledger's accounts are the
            # TB, each with the year's movement; the openings come from last year's TB as for any movement TB
            # (the TB is optional, used only to match)
            gl_first = readable_amounts(read_parts(gl_parts, read_gl, period_end))
            if not gl_first.empty:
                tb_df = IngestionService._tb_from_gl(gl_first)
        if tb_df.empty:
            raise ValueError("No valid Trial Balance schedule found in the uploaded files. Please ensure a Trial Balance file is included.")
        amounts = [c for c in ("debit", "credit", "net", "opening") if c in tb_df.columns]
        if amounts and float(tb_df[amounts].fillna(0).abs().to_numpy().sum()) < 0.005:
            raise ValueError("Every amount in the trial balance reads as 0. If the file shows amounts in Excel, open it, "
                             "save it (Ctrl+S) and upload it again.")

        # 2. Parse General Ledger (Optional / Recommended)
        gl_df = pd.DataFrame()
        if "GL" in classified_files:
            gl_df = readable_amounts(read_parts(gl_parts, read_gl, period_end))
            if not gl_df.empty:
                if source_system == "QUICKBOOKS" and not gl_df.attrs.get("explicit_sides"):
                    gl_df = IngestionService._orient_quickbooks_gl(gl_df, tb_df)
                tb_df = IngestionService._name_tb_accounts_from_gl(tb_df, gl_df)
                opening, not_in_tb = IngestionService._opening_balances_for_movement_tb(tb_df, gl_df)
                if abs(sum(opening.values()) + sum(not_in_tb.values())) >= 1.0:
                    # Opening balances that do not add up to zero (their sides could not be worked out) would
                    # unbalance a TB that balances: the TB is kept as uploaded
                    logger.warning("Ledger opening balances do not add up to zero (%.2f): not used",
                                   sum(opening.values()) + sum(not_in_tb.values()))
                    # Kept aside: the loans tab still shows each loan's balance brought forward from them
                    gl_df.attrs["unused_openings"] = {**{a: (b, True) for a, b in opening.items()},
                                                      **{a: (b, False) for a, b in not_in_tb.items()}}
                    opening, not_in_tb = {}, {}
                tb_df["opening"] = [opening.get(name) for name in tb_df["raw_account_name"]]
                if not opening and not gl_df.attrs.get("unused_openings"):
                    # A closing TB: its balances already hold last year's. The ledger's beginning balance of each
                    # account says how much of it is last year's (an additions account QuickBooks never empties)
                    held = IngestionService._closing_tb_gl_openings(tb_df, gl_df)
                    tb_df["gl_opening"] = [held.get(name) for name in tb_df["raw_account_name"]]
                if not_in_tb:  # accounts with an opening balance but no movement this year
                    extra = pd.DataFrame([{"raw_account_name": acc, "account_type": None, "debit": 0.0, "credit": 0.0, "net": 0.0, "opening": bal}
                                          for acc, bal in not_in_tb.items()])
                    tb_df = pd.concat([tb_df, extra], ignore_index=True)

        # 3. Parse Aged Payables (Optional)
        ap_df = None
        if "AP" in classified_files:
            _, _, xl = classified_files["AP"]
            if xl:
                ap_df = xl.parse(xl.sheet_names[0])

        # 4. Parse Aged Receivables (Optional)
        ar_df = None
        if "AR" in classified_files:
            _, _, xl = classified_files["AR"]
            if xl:
                ar_df = xl.parse(xl.sheet_names[0])

        return NormalizedEngagementData(
            client_name=client_name,
            period_end_date=period_end,
            source_system=source_system,
            tb_df=tb_df,
            gl_df=gl_df,
            ap_df=ap_df,
            ar_df=ar_df
        )

    @staticmethod
    def reads_as_usual(role: str, raw: pd.DataFrame) -> bool:
        """True when the Xero / QuickBooks reader knows this TB or ledger's layout: its heading row is found and, for a
        ledger, nearly every line gets its account. Otherwise the upload screen asks which column is what."""
        if role == "TB":
            for i in range(min(15, len(raw))):
                vals = [str(v).lower() for v in raw.iloc[i].values if pd.notna(v)]
                if any("account" in v or "name" in v for v in vals) and any(
                        w in v for v in vals for w in ("debit", "credit", "balance", "check", "ytd")):
                    return True
            return False
        if role == "GL":
            try:
                gl = IngestionService._clean_universal_gl(raw.head(600), "XERO")
            except Exception:
                return False
            if gl.empty or "Parent_Account" not in gl.columns:
                return False
            named = gl["Parent_Account"].astype(str).str.strip().ne("").mean()
            return bool(named >= 0.9)
        return True

    # Single-file entry points kept for older callers
    @staticmethod
    def _parse_xero(xl: pd.ExcelFile, sheet_names: List[str], filename: str) -> NormalizedEngagementData:
        return IngestionService.detect_and_parse_files([(filename, xl.io.getvalue() if hasattr(xl.io, "getvalue") else b"")])

    @staticmethod
    def _parse_quickbooks(xl: pd.ExcelFile, sheet_names: List[str], filename: str) -> NormalizedEngagementData:
        return IngestionService.detect_and_parse_files([(filename, xl.io.getvalue() if hasattr(xl.io, "getvalue") else b"")])


ingestion_service = IngestionService()
