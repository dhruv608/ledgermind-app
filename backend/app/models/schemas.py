from datetime import date, datetime
from typing import List, Optional, Dict, Any
import json
from pydantic import BaseModel, field_validator

class MasterCOASchema(BaseModel):
    std_code: int
    std_name: str
    category: Optional[str] = None
    financial_class: Optional[str] = None
    normal_balance: Optional[str] = None
    lead_schedule_ref: Optional[str] = None
    is_extended: bool = False

    class Config:
        from_attributes = True

class TBRecordSchema(BaseModel):
    id: Optional[int] = None
    raw_account_name: str
    std_code: Optional[int] = None
    std_name: Optional[str] = None
    debit_amount: float = 0.0
    credit_amount: float = 0.0
    net_amount: float = 0.0
    opening_amount: Optional[float] = None
    mapping_status: str = "UNMAPPED" # MATCHED, AI_SUGGESTED, NEEDS_REVIEW
    confidence_score: float = 1.0
    source_account_type: Optional[str] = None
    match_source: Optional[str] = None
    mapping_reason: Optional[str] = None

    class Config:
        from_attributes = True

class ClearFindingRequest(BaseModel):
    note: Optional[str] = None


class AuditFindingSchema(BaseModel):
    id: Optional[int] = None
    stage: Optional[str] = "STAGE_1_ACCOUNTING"
    procedure_ref: str
    procedure_name: str
    severity: str
    source_row_ref: Optional[str] = None
    finding_title: str
    finding_details: str
    quantified_amount: float = 0.0
    suggested_journal: Optional[str] = None
    status: str = "OPEN"
    cleared_note: Optional[str] = None
    cleared_at: Optional[datetime] = None
    # The point's figures as a small table (columns, rows), when its check writes them
    figures: Optional[dict] = None

    @field_validator("figures", mode="before")
    @classmethod
    def _figures(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else None
            except ValueError:
                return None
        return v

    class Config:
        from_attributes = True

class JournalLineSchema(BaseModel):
    line_no: int
    account_code: int
    account_name: Optional[str] = None
    narrative: Optional[str] = None
    debit: float = 0.0
    credit: float = 0.0

    class Config:
        from_attributes = True

class ProposedJournalSchema(BaseModel):
    id: Optional[int] = None
    engagement_id: str
    finding_id: Optional[int] = None
    stage: str = "STAGE_1_ACCOUNTING"
    journal_ref: str
    description: str
    debit_code: int
    debit_name: str
    credit_code: int
    credit_name: str
    amount: float
    status: str = "PROPOSED"
    source: Optional[str] = "REVIEW"
    created_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    lines: List[JournalLineSchema] = []

    class Config:
        from_attributes = True

class ManualJournalLineInput(BaseModel):
    account_code: int
    narrative: Optional[str] = None
    debit: float = 0.0
    credit: float = 0.0

class ManualJournalCreateRequest(BaseModel):
    description: str
    lines: List[ManualJournalLineInput]

class JournalActionRequest(BaseModel):
    journal_id: int
    action: str = "APPROVE" # APPROVE, REJECT

class MappingUpdateRequest(BaseModel):
    raw_account_name: str
    std_code: int
    std_name: Optional[str] = None
    engagement_id: Optional[str] = None     # the client whose account this is (without it: every client's account)

class MappingResetRequest(BaseModel):
    raw_account_name: str
    engagement_id: Optional[str] = None

class MappingConfirmRequest(BaseModel):
    """The accountant agrees with the code already on these accounts of one client."""
    engagement_id: str
    raw_account_names: List[str]

class ClientProfileSchema(BaseModel):
    engagement_id: str
    industry_code: str = "UNIV"
    is_vat_registered: bool = False
    vat_scheme: str = "STANDARD"
    has_payroll: bool = False
    cis_status: str = "NONE"
    directors: Optional[List[str]] = []
    accounting_framework: str = "FRS102_1A"
    materiality_threshold: float = 0.0
    capitalisation_threshold: float = 500.0
    auto_detected: bool = False
    detection_signals: Optional[Dict[str, Any]] = None
    confirmed_fields: List[str] = []
    properties: List[Dict[str, Any]] = []
    tax_inputs: Dict[str, Any] = {}
    companies_house: Dict[str, Any] = {}
    setup: Dict[str, Any] = {}

    class Config:
        from_attributes = True

class IngestionResponse(BaseModel):
    engagement_id: str
    client_name: str
    period_end_date: str
    source_system: str
    total_tb_rows: int
    total_gl_rows: int
    tb_net_balance: float
    tb_records: List[TBRecordSchema]
    profile: Optional[ClientProfileSchema] = None
    latest_workpaper: Optional[Dict[str, Any]] = None   # id, filename, generated_at, is_draft, download_url
    status: Optional[Dict[str, Any]] = None   # review_stale, workbook_stale, review_run_at, data_changed_at, ...

class AuditExecutionResponse(BaseModel):
    engagement_id: str
    total_findings: int
    findings_by_severity: Dict[str, int]
    findings: List[AuditFindingSchema]

class SequentialReviewResponse(BaseModel):
    engagement_id: str
    total_findings: int
    total_journals: int
    stages: Dict[str, int]
    tax_computation: Optional[Dict[str, Any]] = None
    findings: List[AuditFindingSchema] = []
    journals: List[ProposedJournalSchema] = []

class WorkpaperGenerationResponse(BaseModel):
    engagement_id: str
    filename: str
    download_url: str
    file_size_bytes: int
    diagnostics_score: str

class ClientProfileUpdateRequest(BaseModel):
    industry_code: Optional[str] = None
    is_vat_registered: Optional[bool] = None
    vat_scheme: Optional[str] = None
    has_payroll: Optional[bool] = None
    cis_status: Optional[str] = None
    directors: Optional[List[str]] = None
    accounting_framework: Optional[str] = None
    materiality_threshold: Optional[float] = None
    capitalisation_threshold: Optional[float] = None
    properties: Optional[List[Dict[str, Any]]] = None
    tax_inputs: Optional[Dict[str, Any]] = None
    companies_house: Optional[Dict[str, Any]] = None
    setup: Optional[Dict[str, Any]] = None

class SupplementaryDocumentSchema(BaseModel):
    id: int
    engagement_id: str
    doc_type: str
    filename: str
    file_size_bytes: int
    parsed_records_count: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class VAT100RecordSchema(BaseModel):
    id: int
    engagement_id: str
    period_label: str
    period_end: Optional[date] = None
    bfwd_outstanding: Optional[float] = None
    box1_vat_due_sales: float
    box2_vat_due_acquisitions: float
    box3_total_vat_due: float
    box4_vat_reclaimed: float
    box5_net_vat: float
    box6_total_sales_ex_vat: float
    box7_total_purchases_ex_vat: float
    box8_supplies_to_eu: float
    box9_acquisitions_from_eu: float

    class Config:
        from_attributes = True

class VatReturnInput(BaseModel):
    period_end: date
    box1: float = 0.0
    box2: float = 0.0
    box4: float = 0.0
    box6: float = 0.0
    box7: float = 0.0
    box8: float = 0.0
    box9: float = 0.0
    bfwd_outstanding: Optional[float] = None

class VatReturnsSaveRequest(BaseModel):
    returns: List[VatReturnInput]

class FixedAssetRecordSchema(BaseModel):
    id: int
    engagement_id: str
    asset_tag: Optional[str] = None
    description: str
    category: str
    acquisition_date: Optional[date] = None
    cost_bwd: float
    additions: float
    disposals: float
    cost_fwd: float
    depr_rate_method: Optional[str] = None
    depr_bwd: float
    depr_charge: float
    depr_disposals: float
    depr_fwd: float
    nbv: float

    class Config:
        from_attributes = True

class PayrollP32RecordSchema(BaseModel):
    id: int
    engagement_id: str
    tax_month_label: str
    period_end: Optional[date] = None
    employee_name: Optional[str] = None
    student_loan: Optional[float] = None
    gross_pay: float
    tax_deducted: float
    employee_nic: float
    employer_nic: float
    statutory_pay_recovered: float
    net_pay: float
    pension_employee: float
    pension_employer: float
    total_hmrc_due: float

    class Config:
        from_attributes = True

class SupplementaryUploadResponse(BaseModel):
    engagement_id: str
    uploaded_documents: List[SupplementaryDocumentSchema]
    vat_records_count: int
    fixed_asset_records_count: int
    payroll_records_count: int
    # A payroll report or VAT summary for another year than the job's (said straight away on the upload screen)
    warnings: List[str] = []
