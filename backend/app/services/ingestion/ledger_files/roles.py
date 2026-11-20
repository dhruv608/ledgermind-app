"""What each uploaded file (or tab of a combined workbook) is: trial balance, general ledger, customer or supplier
balances; and the company name and period end in its heading."""

import io
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backend.app.services.ingestion.ledger_files.common import (
    AP_WORDS, AR_WORDS, REPORT_TITLES, UNKNOWN, parse_period_end,
)


class FileRoles:
    """What each uploaded file (or tab of a combined workbook) is: trial balance, general ledger, customer or supplier
    balances; and the company name and period end in its heading. Mixed into IngestionService."""

    @staticmethod
    def _split_combined(files_data: List[Tuple[str, bytes]]) -> Optional[List[Tuple[str, bytes]]]:
        """One workbook holding the TB, ledger and reports as tabs: one file per tab; otherwise None."""
        if len(files_data) != 1:
            return None
        fname, fbytes = files_data[0]
        if not fname.lower().endswith((".xlsx", ".xls")):
            return None
        xl = pd.ExcelFile(io.BytesIO(fbytes))
        if len(xl.sheet_names) < 2:
            return None
        roles = [FileRoles._content_role(s, xl.parse(s, header=None, nrows=15)) for s in xl.sheet_names]
        if sum(1 for r in roles if r in ("TB", "GL")) < 1 and not any(
                s.lower() in ["ttb movement", "general ledger detail", "ttb", "general ledger", "trial balance"] for s in xl.sheet_names):
            return None
        out = []
        for s in xl.sheet_names:
            buf = io.BytesIO()
            xl.parse(s, header=None).to_excel(buf, index=False, header=False)
            out.append((f"{s}.xlsx", buf.getvalue()))
        return out

    @staticmethod
    def identify_files(files_data: List[Tuple[str, bytes]]) -> List[Dict[str, str]]:
        """What each uploaded file is: [{filename, role, how}], role TB/GL/AR/AP or UNKNOWN. Read from the content
        first (the title and the column headings), the file name only when the content does not say."""
        out = []
        for fname, fbytes in files_data:
            fl = fname.lower()
            if not fl.endswith((".xlsx", ".xls", ".csv")):
                out.append({"filename": fname, "role": UNKNOWN, "how": "not an Excel or CSV file"})
                continue
            try:
                if fl.endswith(".csv"):
                    first = pd.read_csv(io.BytesIO(fbytes), header=None, nrows=15)
                    sheet = ""
                else:
                    xl = pd.ExcelFile(io.BytesIO(fbytes))
                    sheet = xl.sheet_names[0]
                    first = xl.parse(sheet, header=None, nrows=15)
            except Exception:
                out.append({"filename": fname, "role": UNKNOWN, "how": "the file could not be opened"})
                continue
            role = FileRoles._content_role(sheet, first)
            if role:
                out.append({"filename": fname, "role": role, "how": "content"})
                continue
            role = FileRoles._name_role(fname, sheet)
            out.append({"filename": fname, "role": role or UNKNOWN, "how": "file name" if role else "nothing in it says"})
        return out

    @staticmethod
    def _content_role(sheet_name: str, first_rows: pd.DataFrame) -> Optional[str]:
        """What the report is, from its title and column headings (sheet name and first rows), or None."""
        cells = [str(v).strip().lower() for v in first_rows.values.flatten() if pd.notna(v) and str(v).strip()]
        text = f"{(sheet_name or '').lower()} " + " ".join(cells)
        # Report titles (QuickBooks and Xero names for the same reports)
        if AR_WORDS.search(text) or "a/r ageing" in text or "a/r aging" in text:
            return "AR"
        if AP_WORDS.search(text) or "a/p ageing" in text or "a/p aging" in text:
            return "AP"
        if re.search(r"general ledger|nominal ledger|transaction detail by account|account transactions|transaction list by", text):
            return "GL"
        if "trial balance" in text or re.search(r"(^|\s)ttb(\s|$)", text):
            return "TB"
        # No title: the column headings. A ledger has a date column with transaction columns; a trial balance has
        # debit and credit columns and no dates
        for _, row in first_rows.iterrows():
            heads = {str(v).strip().lower() for v in row if pd.notna(v)}
            if not heads:
                continue
            has_date = any(h in ("date", "transaction date", "posting date") for h in heads)
            if has_date and heads & {"split", "num", "transaction type", "description", "reference", "source", "memo/description",
                                     "account", "contact", "name"}:
                return "GL"
            if {"debit", "credit"} <= heads and not has_date:
                return "TB"
        return None

    @staticmethod
    def _name_role(filename: str, sheet_name: str = "") -> Optional[str]:
        """What the report is from the file or tab name, or None ('TB.xlsx', 'Client AR', 'General Ledger')."""
        for raw in (filename, sheet_name or ""):
            name = re.sub(r"\.(xlsx|xls|csv)$", "", raw.lower())
            words = re.split(r"[\s_\-.()]+", name)
            if "trial" in name or "ttb" in words or "tb" in words:
                return "TB"
            if "general" in name or "ledger" in name or "gl" in words:
                return "GL"
            if "receivable" in name or "debtor" in name or "a_r" in name or "ar" in words or AR_WORDS.search(name):
                return "AR"
            if "payable" in name or "creditor" in name or "a_p" in name or "ap" in words or AP_WORDS.search(name):
                return "AP"
        return None

    @staticmethod
    def _classify_file_role(filename: str, xl: Optional[pd.ExcelFile]) -> str:
        """TB, GL, AR, AP or UNKNOWN for one file (content first, then name)."""
        sheet = xl.sheet_names[0] if xl is not None and xl.sheet_names else ""
        if xl is not None and sheet:
            try:
                role = FileRoles._content_role(sheet, xl.parse(sheet, header=None, nrows=15))
                if role:
                    return role
            except Exception:
                pass
        return FileRoles._name_role(filename, sheet) or UNKNOWN

    @staticmethod
    def _extract_header_metadata(raw_df: pd.DataFrame) -> Tuple[Optional[str], Optional[date]]:
        client_name = None
        period_end = None

        for i in range(min(8, len(raw_df))):
            row_vals = [str(v).strip() for v in raw_df.iloc[i].values if pd.notna(v) and str(v).strip() != ""]
            if not row_vals:
                continue
            row_str = " ".join(row_vals)
            first_val = row_vals[0].strip()

            is_title = any(t in first_val.lower() for t in REPORT_TITLES)

            # Period end from title lines only; column header rows (e.g. last year's '30 Sept 2024' column) are ignored
            row_lower = row_str.lower()
            is_column_header = any(k in row_lower for k in ("debit", "credit", "account", "balance b/f"))
            row_date = None if is_column_header else parse_period_end(row_str)
            date_matches = [row_date] if row_date else []
            if row_date and period_end is None:
                period_end = row_date

            # If client_name not found yet and not a known report title or pure date
            if not client_name and not is_title and not date_matches:
                cleaned = re.sub(r"^(client|company|organisation|organization|name)\s*(name)?\s*:\s*", "", first_val, flags=re.IGNORECASE).strip()
                if cleaned and len(cleaned) > 2 and not any(k in cleaned.lower() for k in ["page", "date", "account", "debit", "credit", "ageing", "period", "total"]):
                    client_name = cleaned

        return client_name, period_end
