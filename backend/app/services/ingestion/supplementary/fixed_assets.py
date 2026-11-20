"""Fixed asset registers: a register file, last year's WP 'C1-1-FA detail' tab rolled forward, a summary by class, or
an old-style FAR sheet."""

import io
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models.database import FixedAssetRecord, SupplementaryDocument
from backend.app.services.ingestion.supplementary.common import FAR_SHEET, GROUP_HEADING, MONTH_HEADING


class FixedAssetParsing:
    """Fixed asset registers: a register file, last year's WP 'C1-1-FA detail' tab rolled forward, a summary by class,
    or an old-style FAR sheet. Mixed into SupplementaryParserService."""

    @classmethod
    def _far_sheet_rows(cls, filename: str, content: bytes) -> List[List[str]]:
        """The rows of a workbook's fixed asset tab (named like 'C1-1-FA detail') that carries the register's headings;
        empty when there is none."""
        if filename.lower().endswith(".csv"):
            return []
        try:
            book = pd.ExcelFile(io.BytesIO(content))
        except Exception:
            return []
        for name in book.sheet_names:
            if not FAR_SHEET.search(name):
                continue
            try:
                df = book.parse(name, header=None)
            except Exception:
                continue
            rows = [["" if pd.isna(v) else str(v) for v in r] for r in df.values.tolist()]
            if cls._far_headers(rows):
                return rows
        return []

    @staticmethod
    def _register_year_end(rows: List[List[str]], heads: List[int]) -> Optional[date]:
        """The register's own year end: the latest date heading its NBV columns ('2025-03-31 | 2024-03-31')."""
        found = []
        for h in heads:
            for cell in rows[h]:
                m = re.match(r"^((19|20)\d\d)-(\d\d)-(\d\d)", cell.strip())
                if m:
                    try:
                        found.append(date(int(m.group(1)), int(m.group(3)), int(m.group(4))))
                    except ValueError:
                        pass
        return max(found) if found else None

    @staticmethod
    def _roll_forward(a: "FixedAssetRecord") -> Optional["FixedAssetRecord"]:
        """Last year's register line as this year's: cost and depreciation brought forward are
        last year's carried forward, rate and method kept; this year's additions, disposals and charge are left to the
        year (the charge is worked by the asset's rate: yearend_journals.far_depreciation). An asset gone last year
        (nothing carried forward) is dropped."""
        cost = float(a.cost_fwd or 0) or (float(a.cost_bwd or 0) + float(a.additions or 0) - float(a.disposals or 0))
        dep = float(a.depr_fwd or 0) or (float(a.depr_bwd or 0) + float(a.depr_charge or 0) - float(a.depr_disposals or 0))
        if abs(cost) < 0.005:
            return None
        a.cost_bwd, a.additions, a.disposals, a.cost_fwd = round(cost, 2), 0, 0, round(cost, 2)
        a.depr_bwd, a.depr_charge, a.depr_disposals, a.depr_fwd = round(dep, 2), 0, 0, 0
        a.nbv = round(cost - dep, 2)
        return a

    @staticmethod
    def _far_columns(row: List[str]) -> Dict[str, int]:
        """Column of each figure in the firm's FAR headings: 'Date | Detail | B/Fwd | Addition | Disposals | C/fwd |
        B/fwd | Charge | Disposal | C/Fwd | NBV | NBV'. Cost comes first, then depreciation, then this year's and
        last year's NBV, so a heading seen twice is the cost one the first time."""
        cols: Dict[str, int] = {}
        for i, cell in enumerate(row):
            # The charge split by month ('B/Fwd | Oct | Nov | ... | Sep | 2026-01-01 | Disposal | C/Fwd'):
            # each month column between the depreciation brought forward and carried forward, added up as the charge
            if ("depr_bwd" in cols and "depr_fwd" not in cols and "depr_charge" not in cols
                    and (MONTH_HEADING.match(cell.strip()) or re.match(r"^(19|20)\d\d-\d\d-\d\d", cell.strip()))):
                cols[f"month{i}"] = i
                continue
            # The NBV columns headed by their year or year-end date ('2025', '31/12/2025') once the cost and
            # depreciation columns are seen ('NBV' itself sits on the row above)
            if ("depr_charge" in cols or "depr_fwd" in cols) and re.match(r"^(19|20)\d\d(\.0+)?$|^(19|20)\d\d-\d\d-\d\d", cell.strip()):
                cols.setdefault("nbv" if "nbv" not in cols else "nbv_last", i)
                continue
            h = re.sub(r"[^a-z/ ]", "", cell.lower()).strip()
            h = re.sub(r"\s+", " ", h)
            if not h:
                continue
            # LedgerMind's own C1-1-FA detail headings (last year's workbook carried forward)
            own = {"cost b/fwd": "cost_bwd", "cost c/fwd": "cost_fwd", "depn b/fwd": "depr_bwd",
                   "depn c/fwd": "depr_fwd", "depn on disposal": "depr_disposals", "nbv this year": "nbv",
                   "nbv last year": "nbv_last"}
            if h in own:
                cols.setdefault(own[h], i)
                continue
            if h == "date" or h.startswith("date "):
                cols.setdefault("date", i)
            elif h.startswith(("detail", "description", "asset", "particulars", "item")):
                cols.setdefault("detail", i)
            elif h.startswith(("deprn rate", "depreciation rate", "rate")):
                cols.setdefault("rate", i)
            elif h in ("slm/rbm", "rbm/slm", "method", "slm/rb", "basis"):
                cols.setdefault("method", i)
            elif h.startswith("elimination"):
                cols.setdefault("depr_disposals", i)
            elif h.startswith("residual"):
                cols.setdefault("residual", i)       # 'Residual Value'
            elif h.startswith("useful life") or h in ("life", "life years", "useful life years"):
                cols.setdefault("life", i)
            elif h in ("net book value", "net book values"):
                cols.setdefault("nbv" if "nbv" not in cols else "nbv_last", i)
            elif h == "cost" and "cost_bwd" not in cols and "date" in cols:
                cols["cost_bwd"] = i                 # 'Date | Cost | Addition | ...': the cost brought forward
            elif h in ("depreciation", "depreciation charge", "depreciation for the year") and "depr_bwd" in cols:
                cols.setdefault("depr_charge", i)    # '... | Balance b/f | Depreciation | Elimination | ...'
            elif h in ("b/fwd", "b/cwd", "bfwd", "b/f", "brought forward", "opening", "opening balance", "balance b/f",
                       "balance b/fwd"):
                # ('Opening | Additions | ... | B/Fwd | Charge': the cost column may be headed 'Opening')
                # cost, then depreciation, then the NBV columns (this year's first, whatever their labels say)
                cols.setdefault("cost_bwd" if "cost_bwd" not in cols else "depr_bwd" if "depr_bwd" not in cols
                                else "nbv" if "nbv" not in cols else "nbv_last", i)
            elif h.startswith("addition"):
                cols.setdefault("additions", i)
            elif h.startswith("disposal"):
                cols.setdefault("disposals" if "disposals" not in cols else "depr_disposals", i)
            elif h in ("c/fwd", "cfwd", "c/f", "carried forward", "balance c/f", "balance c/fwd"):
                cols.setdefault("cost_fwd" if "cost_fwd" not in cols else "depr_fwd" if "depr_fwd" not in cols
                                else "nbv" if "nbv" not in cols else "nbv_last", i)
            elif h.startswith("charge"):
                cols.setdefault("depr_charge", i)
            elif h == "nbv":
                cols.setdefault("nbv" if "nbv" not in cols else "nbv_last", i)
        # No heading over the descriptions ('Date | | | Cost'): the column after the date
        if "date" in cols and "detail" not in cols and "cost_bwd" in cols and cols["cost_bwd"] > cols["date"] + 1                 and not row[cols["date"] + 1].strip():
            cols["detail"] = cols["date"] + 1
        return cols

    @classmethod
    def _far_summary(cls, rows: List[List[str]]) -> Optional[Tuple[int, Dict[int, str]]]:
        """The register as a summary: a 'Description' row naming one
        asset class per column, then rows 'Cost b/f, Additions, Disposals, Cost c/f, Depreciation b/f, Charge,
        Elimination, Depreciation c/f, NBV'. The heading row and its class columns ('Total ...' left out), or None."""
        for h, row in enumerate(rows[:30]):
            if not row or not row[0].strip().lower().startswith("description"):
                continue
            classes = {j: c.strip() for j, c in enumerate(row) if j > 0 and c.strip() and not c.strip().lower().startswith("total")}
            labels = " ".join(r[0].lower() for r in rows[h + 1:h + 16] if r)
            if classes and "addition" in labels and "charge" in labels and "nbv" in labels:
                return h, classes
        return None

    @classmethod
    def _parse_far_summary(cls, engagement_id: str, rows: List[List[str]], db: Session) -> int:
        """One record per asset class of a summary register. The rows are read in order: 'c/f' is cost until the
        depreciation brought forward row, depreciation after it (some registers label both 'Cost c/f'); the first NBV row is
        this year's."""
        found = cls._far_summary(rows)
        if not found:
            return 0
        h, classes = found

        def amount(text: str) -> float:
            text = (text or "").replace("£", "").replace(",", "").strip()
            try:
                return float(text) if text and text != "-" else 0.0
            except ValueError:
                return 0.0

        values = {j: {k: 0.0 for k in ("cost_bwd", "additions", "disposals", "cost_fwd", "depr_bwd", "depr_charge",
                                       "depr_disposals", "depr_fwd", "nbv")} for j in classes}
        in_depreciation, nbv_seen = False, False
        for row in rows[h + 1:h + 25]:
            label = (row[0] if row else "").strip().lower()
            if not label:
                continue
            if label.startswith("nbv") or "net book value" in label:
                if nbv_seen:
                    break                                  # last year's NBV
                key, nbv_seen = "nbv", True
            elif label.startswith(("dep", "acc")) and re.search(r"b/?\s?f|brought|as on", label):
                key, in_depreciation = "depr_bwd", True
            elif "charge" in label:
                key, in_depreciation = "depr_charge", True
            elif label.startswith(("elimination", "eliminations")) or (in_depreciation and "disposal" in label):
                key = "depr_disposals"
            elif "addition" in label:
                key = "additions"
            elif "disposal" in label:
                key = "disposals"
            elif re.search(r"c/?\s?f|carried", label):
                key = "depr_fwd" if in_depreciation else "cost_fwd"
            elif label.startswith("cost") or re.search(r"b/?\s?f|brought", label):
                key = "cost_bwd"
            else:
                continue
            for j in classes:
                if j < len(row):
                    values[j][key] = round(amount(row[j]), 2)
        assets = [FixedAssetRecord(engagement_id=engagement_id, description=f"{name} (register total)"[:255],
                                   category=name[:100], acquisition_date=None, depr_rate_method=None, **values[j])
                  for j, name in classes.items() if any(abs(v) >= 0.005 for v in values[j].values())]
        if not assets:
            return 0
        db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement_id).delete(synchronize_session=False)
        db.query(SupplementaryDocument).filter(SupplementaryDocument.engagement_id == engagement_id,
                                               SupplementaryDocument.doc_type == "FIXED_ASSET_REGISTER").delete(synchronize_session=False)
        db.add_all(assets)
        db.commit()
        return len(assets)

    @classmethod
    def _far_blank(cls, rows: List[List[str]]) -> bool:
        """A fixed asset register template with no figures: every number under the first headings is nil."""
        heads = cls._far_headers(rows)
        if not heads:
            return False
        for row in rows[heads[0] + 1:]:
            # Each class's heading rows ('Plant | Cost | Depreciation | 2025 | 2024') hold years, not figures
            if any(re.match(r"^(cost|depreciation|nbv|net book value|date)\b", (c or "").strip(), re.I) for c in row):
                continue
            for c in row:
                text = (c or "").replace("£", "").replace(",", "").strip()
                try:
                    if abs(float(text)) >= 0.005:
                        return False
                except ValueError:
                    continue
        return True

    @classmethod
    def _far_headers(cls, rows: List[List[str]]) -> List[int]:
        out = []
        for i, row in enumerate(rows):
            cols = cls._far_columns(row)
            if {"detail", "cost_bwd", "nbv"} <= set(cols) and ("depr_charge" in cols or any(k.startswith("month") for k in cols)):
                out.append(i)
        return out

    @classmethod
    def _parse_far_schedule(cls, engagement_id: str, rows: List[List[str]], db: Session, last_year: bool = False) -> int:
        """The firm's fixed asset register: for each class ('Motor Vehicle -20%SLM' above its headings) one row per
        asset, then the class total (skipped). The client has one register: a new upload replaces the earlier one."""
        def amount(text: str) -> float:
            text = (text or "").replace("£", "").replace(",", "").strip()
            try:
                return float(text) if text and text != "-" else 0.0
            except ValueError:
                return 0.0

        heads = cls._far_headers(rows)
        assets = []
        for n, h in enumerate(heads):
            cols = cls._far_columns(rows[h])
            # The class name is the nearest text above the headings in the first column ('Motor Vehicle -20%SLM'),
            # else the nearest row's first text in another column ('| Plant & Machinery |'), not a group heading
            def first_text(r: int) -> str:
                cells = [c.strip() for c in rows[r] if c.strip()]
                if not cells or GROUP_HEADING.match(cells[0]) or re.match(r"^\d", cells[0]):
                    return ""
                return cells[0]
            def class_name(r: int) -> str:
                lead = rows[r][0].strip() if rows[r] else ""
                if lead and GROUP_HEADING.match(lead):
                    return ""
                return lead if lead and not re.match(r"^\d", lead) else first_text(r)
            title = next((class_name(r) for r in range(h - 1, max(h - 4, -1), -1) if class_name(r)), "")
            rate = re.search(r"(\d+(?:\.\d+)?)\s*%\s*([A-Za-z]+)?", title)
            category = re.sub(r"[-@\s]*\d+(?:\.\d+)?\s*%.*$", "", title).strip(" -@") or "Fixed assets"
            method = f"{rate.group(1)}% {rate.group(2) or ''}".strip() if rate else None
            end = heads[n + 1] if n + 1 < len(heads) else len(rows)
            # A register titled only 'Tangible FAR' names each class on a row of its own under the headings
            # ('Equipments, Furniture and Fixtures'): that row's text is the class of the assets below it
            generic = bool(re.search(r"\bfar\b|fixed asset|tangi\w*|register", category, re.I)) or category == "Fixed assets"
            for row in rows[h + 1:end]:
                cell = lambda key: row[cols[key]].strip() if key in cols and cols[key] < len(row) else ""
                detail = cell("detail")
                if generic and detail and not cell("date") and not any(
                        amount(c) for j, c in enumerate(row) if j != cols["detail"]):
                    # Its rate in the name too ('Equipments, Furniture & Fittings-20% RBM')
                    sub_rate = re.search(r"(\d+(?:\.\d+)?)\s*%\s*([A-Za-z]+)?", detail)
                    category = (re.sub(r"[-@\s]*\d+(?:\.\d+)?\s*%.*$", "", detail).strip(" -@:") or detail)[:100]
                    method = f"{sub_rate.group(1)}% {sub_rate.group(2) or ''}".strip() if sub_rate else method
                    continue
                # A dated row with figures but no description is still an asset; a total row has no date
                if not detail and re.match(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}", cell("date")):
                    detail = f"(no description, {cell('date').replace(' 00:00:00', '')})"
                # A total row, whatever it is called ('Total', 'Grand total', 'Gross Total', 'Net total', 'Total motor
                # vehicles'), adds up the rows above: never an asset
                if not detail or re.match(r"((grand|gross|net|sub)[\s-]*)?totals?\b", detail, re.I):
                    continue
                values = {k: round(amount(cell(k)), 2) for k in ("cost_bwd", "additions", "disposals", "cost_fwd",
                                                                   "depr_bwd", "depr_charge", "depr_disposals", "depr_fwd", "nbv")}
                if "depr_charge" not in cols:
                    values["depr_charge"] = round(sum(amount(cell(k)) for k in cols if k.startswith("month")), 2)
                if not any(abs(v) >= 0.005 for v in values.values()):
                    continue
                # A rate per asset ('0.2' + 'RBM') when the register gives one, else the class's
                row_method = method
                rate_text = cell("rate")
                if rate_text and amount(rate_text):
                    pct = amount(rate_text) * (100 if amount(rate_text) <= 1 else 1)
                    row_method = f"{pct:g}% {cell('method')}".strip()
                when = None
                if cell("date"):
                    try:
                        when = pd.to_datetime(cell("date")).date()
                    except (ValueError, TypeError):
                        when = None
                assets.append(FixedAssetRecord(engagement_id=engagement_id, description=detail[:255],
                                               category=category[:100], acquisition_date=when,
                                               depr_rate_method=row_method, **values,
                                               residual_value=round(amount(cell("residual")), 2) if cell("residual") else None,
                                               useful_life_years=amount(cell("life")) or None if cell("life") else None))
        if not assets:
            return 0
        # Last year's register (its NBV heading a year end before this job's: last year's final WP): rolled forward
        from backend.app.models.database import ClientEngagement
        eng = db.get(ClientEngagement, engagement_id)
        # The NBV columns dated ('2025-03-31'), else the tab's own year end line ('Y.E : 30.11.2025', on older papers
        # whose NBV columns say only '2025 | 2024')
        from backend.app.services.ingestion.last_year_adjustments import _year_end
        register_end = cls._register_year_end(rows, heads) or _year_end(rows[:8])
        if last_year or (eng is not None and register_end is not None
                         and (eng.period_end_date - register_end).days >= 300):
            assets = [a for a in (cls._roll_forward(a) for a in assets) if a is not None]
            if not assets:
                return 0
        db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement_id).delete(synchronize_session=False)
        db.query(SupplementaryDocument).filter(SupplementaryDocument.engagement_id == engagement_id,
                                               SupplementaryDocument.doc_type == "FIXED_ASSET_REGISTER").delete(synchronize_session=False)
        db.add_all(assets)
        db.commit()
        return len(assets)

    @classmethod
    def _parse_far(cls, engagement_id: str, df: pd.DataFrame, db: Session) -> int:
        """Reads a plain fixed asset register by its column names. The client has one register: a new upload replaces
        the earlier one."""
        records_added = 0
        db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement_id).delete(synchronize_session=False)
        db.query(SupplementaryDocument).filter(SupplementaryDocument.engagement_id == engagement_id,
                                               SupplementaryDocument.doc_type == "FIXED_ASSET_REGISTER").delete(synchronize_session=False)
        
        # Try to find header row containing description, cost, nbv
        header_idx = -1
        for idx, row in df.iterrows():
            row_str = " ".join([str(v).lower() for v in row.values if pd.notna(v)])
            if any(k in row_str for k in ["description", "asset name", "cost", "additions", "nbv"]):
                header_idx = idx
                break
        
        if header_idx != -1:
            df.columns = [str(c).strip().lower() for c in df.iloc[header_idx]]
            data_df = df.iloc[header_idx + 1:].copy()
        else:
            data_df = df.copy()

        for _, row in data_df.iterrows():
            desc = ""
            for col in data_df.columns:
                col_name = str(col).lower()
                if any(k in col_name for k in ["desc", "name", "asset", "item"]):
                    if pd.notna(row[col]) and str(row[col]).strip() != "":
                        desc = str(row[col]).strip()
                        break
            
            if not desc or "total" in desc.lower():
                continue

            # Extract numeric amounts
            def get_num(patterns: List[str]) -> float:
                for col in data_df.columns:
                    col_name = str(col).lower()
                    if any(p in col_name for p in patterns):
                        val = row[col]
                        if pd.notna(val):
                            try:
                                return float(str(val).replace("£", "").replace(",", "").strip())
                            except ValueError:
                                pass
                return 0.0

            cost_bwd = get_num(["cost b", "cost brought", "opening cost"])
            additions = get_num(["addition", "acquired", "purchase"])
            disposals = get_num(["disposal", "sale", "scrapped"])
            cost_fwd = get_num(["cost c", "cost carried", "closing cost"]) or (cost_bwd + additions - disposals)
            depr_charge = get_num(["depreciation charge", "charge for year", "current depr"])
            nbv = get_num(["nbv", "net book", "carrying value"]) or max(0.0, cost_fwd - depr_charge)

            far_rec = FixedAssetRecord(
                engagement_id=engagement_id,
                description=desc,
                category="General Equipment",
                cost_bwd=cost_bwd,
                additions=additions,
                disposals=disposals,
                cost_fwd=cost_fwd,
                depr_charge=depr_charge,
                nbv=nbv,
            )
            db.add(far_rec)
            records_added += 1

        db.commit()
        return records_added
