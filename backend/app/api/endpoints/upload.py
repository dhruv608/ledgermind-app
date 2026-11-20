import io
import json
import logging
import re
import pandas as pd
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import List, Optional, Tuple
from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement, TBRecord, AuditFinding, GLTransaction, signed_vat
from backend.app.models.schemas import IngestionResponse, TBRecordSchema, ClientProfileSchema
from backend.app.services.ingestion.ingestion_service import FilesNeedRoles, ingestion_service
from backend.app.services.mapping.mapping_service import mapping_service
from backend.app.services.ingestion.client_identity import find_engagement
from backend.app.core.s3 import s3_service
from backend.app.services.shared.activity import mark_changed
from backend.app.services.bank_only import input_files as raw_input
from backend.app.services.review.last_year import TB_PRIOR

ROLES_FILE = "_roles.json"     # beside the raw files: what each file (or tab) was taken as at upload


def _stored_name(fname: str) -> str:
    """The file name alone (a name sent as '../x' or 'a/b.xlsx' must not reach outside the client's folder)."""
    name = (fname or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name not in ("", ".", "..") else "file.xlsx"


def _final_roles(files_data, chosen) -> dict:
    """What each file (or each tab of one combined workbook, as '<tab>.xlsx') was read as: the accountant's choice,
    else what its content or name says. A tab nothing identifies is skipped."""
    tabs = ingestion_service._split_combined(files_data)
    found = {f["filename"]: f["role"] for f in ingestion_service.identify_files(tabs or files_data)}
    for name, role in (chosen or {}).items():
        if name in found and role in ("TB", "GL", "AR", "AP", "SKIP", TB_PRIOR):
            found[name] = role
    if tabs:
        return {k: ("SKIP" if v == "UNKNOWN" else v) for k, v in found.items()}
    return {_stored_name(k): v for k, v in found.items()}

logger = logging.getLogger(__name__)

LAST_YEAR_NAME = re.compile(r"\blast\b|prior|previous|\bpy\b|comparative|opening", re.I)   # 'Last TB', 'Last year TB'...


def _last_year_tb(found: List[dict], files_data) -> None:
    """Two trial balances: the one with the earlier year end (or named as last year's) is last year's TB."""
    tbs = [f for f in found if f["role"] == "TB"]
    if len(tbs) == 1 and any(f["role"] == "GL" for f in found) and LAST_YEAR_NAME.search(tbs[0]["filename"]):
        # Only last year's TB with the ledger (no TB for this year): it is last year's, and the year's TB is built from
        # the ledger, not last year's balances taken as this year's
        tbs[0]["role"], tbs[0]["how"] = TB_PRIOR, "file name"
        return
    if len(tbs) < 2:
        return
    data = dict(files_data)
    ends = {}
    for f in tbs:
        try:
            name = f["filename"]
            df = (pd.read_csv(io.BytesIO(data[name]), header=None, nrows=15) if name.lower().endswith(".csv")
                  else pd.read_excel(io.BytesIO(data[name]), header=None, nrows=15))
            ends[name] = ingestion_service._extract_header_metadata(df)[1]
        except Exception:
            ends[f["filename"]] = None
    latest = max((d for d in ends.values() if d), default=None)
    # The dates decide when one is earlier; otherwise (no dates, or last year's TB headed with this year's end as
    # its opening position) the name does, as long as it does not name them all
    by_date = any(d and latest and d < latest for d in ends.values())
    named = [f for f in tbs if LAST_YEAR_NAME.search(f["filename"])]
    for f in tbs:
        end = ends.get(f["filename"])
        if (by_date and end and end < latest) or (not by_date and f in named and len(named) < len(tbs)):
            f["role"], f["how"] = TB_PRIOR, "an earlier year end" if end else "file name"

MOVEMENT_TITLE = re.compile(r"\bmovements?\b|\bTTB\b", re.I)       # 'TTB Movement', 'Movement for the year ended ...'
HEADING_CELL = re.compile(r"^\s*(debit|credit|dr|cr|account|code|balance|net)\b", re.I)


def _movement_tb(found: List[dict], files_data) -> None:
    """This year's TB whose title says it holds the year's movements (a TTB, not a closing TB) is shown as one: the
    two are different things."""
    data = dict(files_data)
    for f in found:
        if f["role"] != "TB" or f["filename"] not in data:
            continue
        name = f["filename"]
        try:
            df = (pd.read_csv(io.BytesIO(data[name]), header=None, nrows=6) if name.lower().endswith(".csv")
                  else pd.read_excel(io.BytesIO(data[name]), header=None, nrows=6))
        except Exception:
            continue
        # The title rows only: a closing TB's column headings ('Opening | Movement | Closing') are not its title
        titles = [v for row in df.values if not any(isinstance(c, str) and HEADING_CELL.match(c) for c in row)
                  for v in row]
        if any(isinstance(v, str) and MOVEMENT_TITLE.search(v) for v in titles):
            f["how"] = "the year's movements, a TTB"


def _last_year_end(files_data, chosen, period_end) -> Optional[date]:
    """The date on last year's TB: the end of the period before this one (review/last_year_common.last_year_end)."""
    from backend.app.services.review.last_year_common import last_year_end
    try:
        roles = _final_roles(files_data, chosen)
        prior = next(((n, b) for n, b in files_data if roles.get(_stored_name(n)) == TB_PRIOR), None)
        if prior is None:
            return None
        name, data = prior
        df = (pd.read_csv(io.BytesIO(data), header=None, nrows=15) if name.lower().endswith(".csv")
              else pd.read_excel(io.BytesIO(data), header=None, nrows=15))
    except Exception:
        logger.exception("Last year's TB not read for its date (the period is taken as 12 months)")
        return None
    return last_year_end(df, period_end)


def _prior_tb(files_data, chosen, db: Session) -> Optional[Tuple[str, pd.DataFrame]]:
    """Last year's TB as a sheet of rows, from the files set as last year's TB (last_year_common.prior_tb_frame)."""
    from backend.app.services.review.last_year_common import prior_tb_frame
    roles = _final_roles(files_data, chosen)
    return prior_tb_frame([(n, b) for n, b in files_data if roles.get(_stored_name(n)) == TB_PRIOR], db)


def _filed_lines(files_data, chosen, db: Session) -> list:
    """Last year's TB in the firm's codes (the accountant's filed TB), read from the files before they are kept, so
    the mapping can give each account last year's code. Empty when there is none."""
    from backend.app.services.review.last_year import chart_names, firm_coded_lines
    try:
        prior = _prior_tb(files_data, chosen, db)
        if prior is None:
            return []
        return firm_coded_lines(prior[1], chart_names(db)) or []
    except Exception:
        logger.exception("Last year's TB not read for the mapping (the upload goes on)")
        return []


def _openings_from_last_year_tb(norm_data, files_data, chosen, db: Session) -> None:
    """A TB of the year's movements whose ledger gave no opening lines: last year's TB in the client's own names
    (Xero / QuickBooks / Sage) gives the opening balances, by account name, before the mapping. A TB in the firm's
    codes is applied by code after the mapping (apply_prior_openings)."""
    from backend.app.services.review.last_year import chart_names, openings_from_prior_names
    tb = norm_data.tb_df
    if tb.empty or ("opening" in tb.columns and tb["opening"].notna().any()):
        return
    gl = norm_data.gl_df
    if gl is not None and not gl.empty and gl.attrs.get("opening_balances"):
        return      # the ledger's opening lines already told whether the TB holds movements or closing balances
    try:
        prior = _prior_tb(files_data, chosen, db)
        if prior is None:
            return
        found, extra = openings_from_prior_names(tb, prior[1], chart_names(db))
    except Exception:
        logger.exception("Last year's TB not used for opening balances (the upload goes on)")
        return
    if not found and not extra:
        return
    tb = tb.copy()
    tb["opening"] = [found.get(str(n)) for n in tb["raw_account_name"]]
    if extra:   # last year's balances with no account this year
        tb = pd.concat([tb, pd.DataFrame([{"raw_account_name": acc, "account_type": None, "debit": 0.0, "credit": 0.0,
                                           "net": 0.0, "opening": bal} for acc, bal in extra.items()])], ignore_index=True)
    norm_data.tb_df = tb


router = APIRouter()

def _first_sheets(files_data) -> dict:
    """{name: first sheet, no headings} for each file, or each tab of one combined workbook ('<tab>.xlsx')."""
    out = {}
    for name, data in ingestion_service._split_combined(files_data) or files_data:
        try:
            out[name] = (pd.read_csv(io.BytesIO(data), header=None) if name.lower().endswith(".csv")
                         else pd.read_excel(io.BytesIO(data), header=None))
        except Exception:
            continue
    return out


def _with_layouts(found: List[dict], files_data, request: Request, db: Session) -> None:
    """A TB or ledger the Xero / QuickBooks readers do not know (Sage, or any other layout): the columns to confirm,
    guessed or from a layout saved earlier."""
    from backend.app.services.ingestion import column_layouts
    sheets = None
    owner = getattr(getattr(request.state, "user", None), "id", None)
    for f in found:
        if f["role"] not in ("TB", "GL"):
            continue
        if sheets is None:
            sheets = _first_sheets(files_data)
        raw = sheets.get(f["filename"])
        if raw is None or ingestion_service.reads_as_usual(f["role"], raw):
            continue
        f["layout"] = column_layouts.proposal(f["role"], raw, db, owner)


@router.post("/upload/identify")
def identify_upload_files(request: Request, files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    """What each chosen file is (trial balance, ledger, customer or supplier balances), before uploading: the
    upload screen shows it and lets the accountant correct it. Nothing is saved."""
    files_data = [(f.filename, f.file.read()) for f in files if f.filename]
    # A bank statement with Dext invoice and bill lists (a client with no accounting software): its own tab list
    if raw_input.is_raw_upload(files_data):
        parts = raw_input.identify_parts(files_data)
        # The year end when a file says it ('Year End: 31.03.2026' above the headings); statements rarely do, and the
        # upload screen then asks for it
        year_end = next((raw_input._date(v) for _, ws in raw_input._parts(files_data)
                         if (v := raw_input._title_values(ws).get("year end"))), None)
        # No file says it: the company's accounting reference date on Companies House, for the year the statements
        # cover most of (a suggestion the upload screen fills in for the accountant to check)
        suggested = None
        if year_end is None:
            try:
                raw = raw_input.read_input_files(files_data)
                dates = [b.when for b in raw.bank if b.when]
                if raw.client_name and dates:
                    from backend.app.services.setup.companies_house import year_end_for
                    suggested = year_end_for(raw.client_name, min(dates), max(dates))
            except Exception:
                suggested = None
        return {"combined": len(files_data) == 1 and len(parts) > 1, "raw": True, "workbook": files_data[0][0],
                "files": parts, "year_end": year_end.isoformat() if year_end else None,
                "year_end_suggested": suggested[0].isoformat() if suggested else None,
                "year_end_why": suggested[1] if suggested else ""}
    tabs = ingestion_service._split_combined(files_data)
    if tabs:
        # One row per tab ('<tab>.xlsx'); a tab nothing identifies is left out unless the accountant says otherwise
        found = ingestion_service.identify_files(tabs)
        _last_year_tb(found, tabs)
        _movement_tb(found, tabs)
        for t in found:
            if t["role"] == "UNKNOWN":
                t["role"], t["how"] = "SKIP", "not a TB, ledger or balance report"
        _with_layouts(found, files_data, request, db)
        return {"combined": True, "workbook": files_data[0][0], "files": found}
    found = ingestion_service.identify_files(files_data)
    _last_year_tb(found, files_data)
    _movement_tb(found, files_data)
    _with_layouts(found, files_data, request, db)
    return {"combined": False, "files": found}


@router.get("/upload/progress/{upload_id}")
def upload_progress(upload_id: str):
    """How far an upload has got: {'stage': 1-4 (0 not started), 'stages': [...]}. Only a stage number is kept."""
    from backend.app.services.ingestion.upload_progress import stage_of
    return stage_of(upload_id)


@router.post("/upload", response_model=IngestionResponse)
def upload_financial_files(
    request: Request,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    roles: Optional[str] = Form(None),
    layouts: Optional[str] = Form(None),
    year_end: Optional[str] = Form(None),
    progress_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """roles: what the accountant said each file is, JSON {filename: TB/GL/AR/AP} (from the upload screen).
    progress_id: the screen's id for this upload, to ask how far it has got (GET /upload/progress/{id})."""
    from backend.app.services.ingestion.upload_progress import mark
    mark(progress_id, 1)
    upload_list: List[UploadFile] = []
    if files:
        upload_list.extend(files)
    if file:
        upload_list.append(file)

    if not upload_list:
        raise HTTPException(status_code=400, detail="No files provided for upload")

    # Read all file bytes
    files_data = []
    for f in upload_list:
        if f.filename:
            content = f.file.read()
            if len(content) > 0:
                files_data.append((f.filename, content))

    if not files_data:
        raise HTTPException(status_code=400, detail="Uploaded files were empty.")

    # 1. Parse & Normalize Files (Consolidated or Multi-File)
    try:
        chosen = json.loads(roles) if roles else None
    except ValueError:
        chosen = None
    # A client with no accounting software (bank statement and Dext lists): the books are prepared in the app
    if raw_input.is_raw_upload(files_data) or any(v in raw_input.RAW_ROLES for v in (chosen or {}).values()):
        from backend.app.api.endpoints.books import upload_books_client
        from backend.app.services.bank_only.input_files import _date
        return upload_books_client(request, files_data, chosen, db, year_end=_date(year_end) if year_end else None)
    try:
        # Last year's TB is only kept with the files (for the last year vs this year comparison), not read as this year's
        parse_roles = {k: ("SKIP" if v == TB_PRIOR else v) for k, v in (chosen or {}).items()} or None
        # The columns the accountant confirmed for a TB or ledger in a layout the usual readers do not know
        try:
            confirmed = json.loads(layouts) if layouts else {}
        except ValueError:
            confirmed = {}
        norm_data = ingestion_service.detect_and_parse_files(files_data, roles=parse_roles, layouts=confirmed)
    except FilesNeedRoles as e:
        # Not guessed: the upload screen asks which file is which, then sends the answer back
        raise HTTPException(status_code=422, detail={"message": str(e), "files": e.files})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File parsing error: {str(e)}")
    _openings_from_last_year_tb(norm_data, files_data, chosen, db)
    if norm_data.prior_period_end_date is None:
        # The period starts the day after last year's TB date (a short or long period after a change of year end:
        # last year's TB as of 31 March, period to 30 September = six months)
        norm_data.prior_period_end_date = _last_year_end(files_data, chosen, norm_data.period_end_date)

    # Clean and normalize client name
    cleaned_name = re.sub(
        r"^(client|company|organisation|organization|name)\s*(name)?\s*:\s*",
        "",
        norm_data.client_name,
        flags=re.IGNORECASE
    ).strip()
    norm_data.client_name = cleaned_name

    # 2-5 are one database transaction, saved only at the end: if anything fails, the client's previous upload
    #    (TB, ledger, review findings) is left exactly as it was
    try:
        # 2. Same client and same year end = a re-upload of that year; a new year end = a new engagement,
        #    so last year's journals, VAT returns and workpapers are kept
        owner_id = request.state.user.id
        existing_eng = find_engagement(db, cleaned_name, norm_data.period_end_date, owner_id)
        if existing_eng:
            engagement = existing_eng
            engagement.client_name = cleaned_name
            engagement.period_end_date = norm_data.period_end_date
            engagement.source_system = norm_data.source_system
            engagement.prior_period_end_date = norm_data.prior_period_end_date
            # Replace the previous TB, findings and GL transactions for this engagement
            from backend.app.models.gl_foreign import GLForeign
            db.execute(delete(GLForeign).where(GLForeign.engagement_id == engagement.id))
            from backend.app.models.gl_parties import GLParty
            db.execute(delete(GLParty).where(GLParty.engagement_id == engagement.id))
            db.execute(delete(GLTransaction).where(GLTransaction.engagement_id == engagement.id))
            db.execute(delete(AuditFinding).where(AuditFinding.engagement_id == engagement.id))
            db.execute(delete(TBRecord).where(TBRecord.engagement_id == engagement.id))
        else:
            engagement = ClientEngagement(
                client_name=cleaned_name,
                period_end_date=norm_data.period_end_date,
                prior_period_end_date=norm_data.prior_period_end_date,
                source_system=norm_data.source_system,
                owner_user_id=owner_id,
            )
            db.add(engagement)
            db.flush()

        # 4. GL transactions
        mark(progress_id, 2)
        gl_objects = _gl_records(norm_data.gl_df, engagement.id)
        if gl_objects:
            _save_gl_lines(db, engagement.id, gl_objects)

        # The ledger's opening balances the TB could not take (they do not add up to zero)
        from backend.app.models.gl_openings import GLOpeningBalance
        db.query(GLOpeningBalance).filter(GLOpeningBalance.engagement_id == engagement.id).delete(synchronize_session=False)
        for account, (amount, in_tb) in (norm_data.gl_df.attrs.get("unused_openings") or {}).items():
            if abs(float(amount)) >= 0.005:
                db.add(GLOpeningBalance(engagement_id=engagement.id, account_name=str(account)[:255],
                                        amount=round(float(amount), 2), in_tb=1 if in_tb else 0))

        # 5. Map the trial balance (the AI's GL samples read the lines flushed above)
        mark(progress_id, 3)
        raw_tb_rows = norm_data.tb_df.to_dict(orient="records")
        tb_records = mapping_service.map_engagement_tb(engagement.id, raw_tb_rows, db, commit=False,
                                                       filed_lines=_filed_lines(files_data, chosen, db))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Upload failed; nothing was changed")
        raise HTTPException(status_code=500, detail=f"Upload failed and nothing was changed: {str(e)[:300]}")
    for rec in tb_records:
        db.refresh(rec)
    if confirmed:
        _remember_layouts(confirmed, files_data, request, db)

    # 3. Keep the raw files (ageing reports are read from here) only once the upload has been saved. A re-upload
    #    replaces the earlier files (an old aged debtors report must not stay behind), with what each file was taken as
    if existing_eng:
        mark_changed(db, engagement.id)
    prefix = f"raw_uploads/{engagement.id}/"
    try:
        roles_taken = _final_roles(files_data, chosen)
    except Exception:
        roles_taken = None
    s3_service.delete_prefix(prefix)
    for fname, fbytes in files_data:
        s3_service.upload_file_bytes(fbytes, prefix + _stored_name(fname))
    if roles_taken is not None:
        s3_service.upload_file_bytes(json.dumps(roles_taken).encode(), prefix + ROLES_FILE)

    # 5b. A TB of the year's movements with no opening lines in the ledger: last year's TB gives the openings
    from backend.app.services.review.last_year import apply_prior_openings
    if apply_prior_openings(engagement, db):
        tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars().all()

    # 6. Auto-detect Step 0 Client Profile (Industry, VAT, Payroll, CIS, Materiality)
    mark(progress_id, 4)
    from backend.app.services.setup.profile_service import ProfileService
    profile = ProfileService.auto_detect_profile(db, engagement.id)
    # Now the directors are known: a loan named for someone else is not the director's loan account
    from backend.app.services.mapping.loan_accounts import move_non_director_loans
    if move_non_director_loans(engagement.id, db):
        tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars().all()
    profile_schema = None
    if profile:
        profile_schema = ClientProfileSchema(
            engagement_id=profile.engagement_id,
            industry_code=profile.industry_code or "UNIV",
            is_vat_registered=bool(profile.is_vat_registered),
            vat_scheme=profile.vat_scheme or "STANDARD",
            has_payroll=bool(profile.has_payroll),
            cis_status=profile.cis_status or "NONE",
            directors=json.loads(profile.directors) if profile.directors else [],
            accounting_framework=profile.accounting_framework or "FRS102_1A",
            materiality_threshold=float(profile.materiality_threshold or 0.0),
            capitalisation_threshold=float(profile.capitalisation_threshold or 500.0),
            auto_detected=bool(profile.auto_detected),
            detection_signals=json.loads(profile.detection_signals) if profile.detection_signals else None,
            confirmed_fields=json.loads(profile.confirmed_fields) if profile.confirmed_fields else [],
            properties=json.loads(profile.properties) if profile.properties else [],
            tax_inputs=json.loads(profile.tax_inputs) if profile.tax_inputs else {},
        )

    # Review points come from the review (run once the setup and the accounts are done), not from the upload
    # A new upload of a client whose setup is complete: the checks run again in the background on the new books
    if existing_eng:
        from backend.app.services.checks.runner import start_if_ready
        start_if_ready(db, engagement, "upload", getattr(request.state.user, "id", None))

    tb_net = sum(float(r.net_amount or 0.0) for r in tb_records)

    return IngestionResponse(
        engagement_id=engagement.id,
        client_name=engagement.client_name,
        period_end_date=engagement.period_end_date.strftime("%d/%m/%Y"),
        source_system=engagement.source_system,
        total_tb_rows=len(tb_records),
        total_gl_rows=len(norm_data.gl_df),
        tb_net_balance=round(tb_net, 2),
        tb_records=[TBRecordSchema.model_validate(r) for r in tb_records],
        profile=profile_schema
    )


def _remember_layouts(confirmed: dict, files_data, request: Request, db: Session) -> None:
    """The layouts used in this upload, saved for the firm: the same headings are read without asking next time."""
    from backend.app.services.ingestion import column_layouts
    try:
        sheets = _first_sheets(files_data)
        owner = getattr(getattr(request.state, "user", None), "id", None)
        for name, lay in confirmed.items():
            raw = sheets.get(name)
            if raw is None or lay.get("role") not in ("TB", "GL"):
                continue
            rows = column_layouts._rows(raw.head(250))
            sig = column_layouts.signature(lay["role"], rows, int(lay["header_row"]))
            column_layouts.save_layout(db, owner, lay["role"], sig, int(lay["header_row"]),
                                       {k: int(v) for k, v in lay["mapping"].items()}, lay.get("software") or "OTHER")
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Column layouts not saved (the upload itself is saved)")


# Columns that tag a line to a property, project or site: QuickBooks class / location, Xero tracking categories
TRACKING_COLUMNS = {"tracking", "class", "location", "property", "tracking category", "tracking category 1",
                    "tracking category 2", "tracking option"}


def _gl_records(gl_df: pd.DataFrame, engagement_id: str) -> List[GLTransaction]:
    """GL lines ready to save; text is cut to the column sizes (some ledgers carry whole invoice lines)."""
    records = []
    if gl_df.empty:
        return records
    for _, row in gl_df.iterrows():
        acc = str(row.get("Parent_Account") or row.get("Account") or row.get("Distribution account") or row.get("raw_account_name") or "").strip()
        if not acc or acc.lower() in ["nan", "total"]:
            continue
        raw_date = row.get("Date") or row.get("Transaction date")
        tx_date = None
        if raw_date is None or (not isinstance(raw_date, str) and pd.isna(raw_date)):
            pass            # no date ('NaT' answers .date() with NaT, which would stop the whole upload)
        elif hasattr(raw_date, "date"):
            tx_date = raw_date.date()
        elif isinstance(raw_date, datetime):
            tx_date = raw_date.date()
        elif isinstance(raw_date, str):
            try:
                tx_date = pd.to_datetime(raw_date, dayfirst=True).date()
            except Exception:
                pass

        desc = str(row.get("Description", "")).strip() if pd.notna(row.get("Description")) else ""
        ref = str(row.get("Reference", "") or row.get("No.", "")).strip() if pd.notna(row.get("Reference") or row.get("No.")) else ""
        src = str(row.get("Source", "") or row.get("Transaction type", "")).strip() if pd.notna(row.get("Source") or row.get("Transaction type")) else ""
        debit = float(row.get("Debit", 0.0) or 0.0)
        credit = float(row.get("Credit", 0.0) or 0.0)
        net = float(row.get("Net", debit - credit) or (debit - credit))
        # VAT on the line: Xero 'VAT' + 'VAT Rate Name', QuickBooks 'VAT' (item line only) + 'VAT Code'
        vat_value = row.get("VAT")
        try:
            vat_amount = round(float(vat_value), 2) if vat_value is not None and pd.notna(vat_value) and str(vat_value).strip() else None
        except (TypeError, ValueError):
            vat_amount = None
        vat_code = next((str(row.get(k)).strip() for k in ("VAT Rate Name", "VAT Code")
                         if row.get(k) is not None and pd.notna(row.get(k)) and str(row.get(k)).strip()), None)
        tracking = next((str(v).strip() for k, v in row.items() if str(k).strip().lower() in TRACKING_COLUMNS
                         and pd.notna(v) and str(v).strip() and str(v).strip().lower() != "nan"), "")

        rec = GLTransaction(
            engagement_id=engagement_id,
            raw_account_name=acc[:255],
            transaction_date=tx_date,
            description=desc[:500],
            reference=ref[:255],
            source=src[:100],
            tracking=tracking[:255] or None,
            vat_amount=None if vat_amount is None else signed_vat(vat_amount, debit, credit),
            vat_code=vat_code[:100] if vat_code else None,
            debit_amount=debit,
            credit_amount=credit,
            net_amount=net,
        )
        rec._foreign = _foreign_of(row)
        rec._party = _party_of(row)
        records.append(rec)
    return records


def _foreign_of(row) -> Optional[Tuple[Optional[str], Optional[float], Optional[float]]]:
    """(currency, exchange rate, foreign amount) of a line in another currency, else None (a line in pounds has rate 1
    and no foreign amount, or the ledger has no such columns)."""
    def num(v):
        try:
            return float(str(v).replace(",", "").strip()) if v is not None and pd.notna(v) and str(v).strip() else None
        except (TypeError, ValueError):
            return None
    rate, amount = num(row.get("Exchange Rate")), num(row.get("Foreign Amount"))
    cur = row.get("Currency")
    cur = str(cur).strip().upper()[:10] if cur is not None and pd.notna(cur) and str(cur).strip() else None
    # Pounds: no rate or a rate of 1 (its 'foreign amount' is the same pounds), unless another currency is named
    if (rate is None or abs(rate - 1) < 1e-9) and cur in (None, "GBP"):
        return None
    if rate is None and amount is None:
        return None
    return cur, rate, amount


def _party_of(row) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """(name, split) of a ledger line, when the ledger gives either (QuickBooks 'Name' and 'Split')."""
    def text(v):
        return str(v).strip()[:255] if v is not None and pd.notna(v) and str(v).strip() and str(v).strip().lower() != "nan" else None
    name, split = text(row.get("Name")), text(row.get("Split"))
    return (name, split) if name or split else None


def _save_gl_lines(db: Session, engagement_id: str, gl_objects: List[GLTransaction]) -> None:
    """The ledger lines saved, and beside them each line's foreign currency and its name and split,
    when the ledger gives them."""
    from backend.app.models.gl_foreign import GLForeign
    from backend.app.models.gl_parties import GLParty
    db.query(GLForeign).filter(GLForeign.engagement_id == engagement_id).delete(synchronize_session=False)
    db.query(GLParty).filter(GLParty.engagement_id == engagement_id).delete(synchronize_session=False)
    foreign = [r for r in gl_objects if getattr(r, "_foreign", None)]
    parties = [r for r in gl_objects if getattr(r, "_party", None)]
    if not foreign and not parties:
        db.bulk_save_objects(gl_objects)
        db.flush()
        return
    db.add_all(gl_objects)                          # the lines' ids are needed for the rows beside them
    db.flush()
    db.bulk_save_objects([GLForeign(engagement_id=engagement_id, gl_transaction_id=r.id, currency=r._foreign[0],
                                    exchange_rate=r._foreign[1], foreign_amount=r._foreign[2]) for r in foreign])
    db.bulk_save_objects([GLParty(engagement_id=engagement_id, gl_transaction_id=r.id, name=r._party[0],
                                  split=r._party[1]) for r in parties])
    db.flush()
