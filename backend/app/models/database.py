import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean, DateTime, Date, ForeignKey, Numeric, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base

class MasterCOA(Base):
    __tablename__ = "master_coa"

    std_code = Column(Integer, primary_key=True, index=True)
    std_name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=True)
    financial_class = Column(String(50), nullable=True)  # Balance Sheet / Profit and Loss
    normal_balance = Column(String(10), nullable=True)   # Debit / Credit
    lead_schedule_ref = Column(String(20), nullable=True) # E1, H2, K2, J2, V1, P1, etc.
    sub_tags = Column(Text, nullable=True)                # Comma-separated or JSON list of synonyms & sub-tags
    is_extended = Column(Boolean, default=False, nullable=False)  # False = firm standard list (COA_Standard); True = rest of the full TaxCalc chart
    created_at = Column(DateTime, default=datetime.utcnow)

class MappingMemory(Base):
    __tablename__ = "mapping_memory"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # who confirmed it (the memory is the whole firm's)
    client_account_name = Column(String(255), index=True, nullable=False)
    std_code = Column(Integer, ForeignKey("master_coa.std_code"), nullable=False)
    match_source = Column(String(50), default="RULE_EXACT") # USER_CONFIRMED (the only value set now)
    confidence_score = Column(Float, default=1.0)
    confirmed_at = Column(DateTime, default=datetime.utcnow)

class User(Base):
    """Someone who can sign in (one account for now; staff accounts later). The password is stored only as a hash."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class UserSession(Base):
    """A signed-in browser. Only a hash of the cookie's token is stored, so a copy of the database cannot sign in."""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class FirmMappingRule(Base):
    """The firm's own choices: an account whose name contains these words goes to this code (Account rules page).
    The first active rule that matches wins; an account set by an accountant keeps its code."""
    __tablename__ = "firm_mapping_rules"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # who added it (the rules are the whole firm's)
    words = Column(Text, nullable=False)            # comma separated, e.g. "christmas party, staff party"
    except_words = Column(Text, nullable=True)      # comma separated: not when the name also contains one of these
    std_code = Column(Integer, ForeignKey("master_coa.std_code"), nullable=False)
    note = Column(Text, nullable=True)
    position = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ClientAccountMapping(Base):
    """The AI's answer for one account of one client, reused on re-uploads and next year so answers don't change."""
    __tablename__ = "client_account_mappings"
    __table_args__ = (UniqueConstraint("company_key", "account_key", name="uq_client_account_mapping"),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_key = Column(String(255), nullable=False, index=True)   # client_identity.company_key(client name)
    account_key = Column(String(255), nullable=False)               # the client's account name, lower case
    account_type = Column(String(100), nullable=True)               # type in the client's software when answered
    std_code = Column(Integer, ForeignKey("master_coa.std_code"), nullable=False)
    mapping_status = Column(String(50), nullable=False)             # AI_SUGGESTED / NEEDS_REVIEW
    confidence_score = Column(Float, default=0.0)
    mapping_reason = Column(String(500), nullable=True)
    model = Column(String(100), nullable=True)                      # Bedrock model that answered
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ClientEngagement(Base):
    __tablename__ = "client_engagements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_name = Column(String(255), nullable=False)
    period_end_date = Column(Date, nullable=False)
    prior_period_end_date = Column(Date, nullable=True)
    source_system = Column(String(50), nullable=False)  # XERO, QUICKBOOKS, CSV
    status = Column(String(50), default="UPLOADED")     # unused (progress comes from the workbook and review); kept in the table
    diagnostics_passed = Column(Boolean, default=False)          # unused (the workbook carries its own QA result); kept in the table
    created_at = Column(DateTime, default=datetime.utcnow)
    data_changed_at = Column(DateTime, nullable=True)  # mappings, setup, journals, VAT or payroll last changed
    review_run_at = Column(DateTime, nullable=True)    # the full review (with the tax computation) last ran
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)   # whose client this is

    # Relationships
    tb_records = relationship("TBRecord", back_populates="engagement", cascade="all, delete-orphan")
    audit_findings = relationship("AuditFinding", back_populates="engagement", cascade="all, delete-orphan")
    workpapers = relationship("GeneratedWorkpaper", back_populates="engagement", cascade="all, delete-orphan")
    gl_transactions = relationship("GLTransaction", back_populates="engagement", cascade="all, delete-orphan")
    profile = relationship("ClientProfile", back_populates="engagement", uselist=False, cascade="all, delete-orphan")
    journals = relationship("ProposedJournal", back_populates="engagement", cascade="all, delete-orphan")
    supplementary_docs = relationship("SupplementaryDocument", back_populates="engagement", cascade="all, delete-orphan")
    vat_100_records = relationship("VAT100Record", back_populates="engagement", cascade="all, delete-orphan")
    fixed_asset_records = relationship("FixedAssetRecord", back_populates="engagement", cascade="all, delete-orphan")
    payroll_records = relationship("PayrollP32Record", back_populates="engagement", cascade="all, delete-orphan")

class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), unique=True, nullable=False)
    industry_code = Column(String(10), default="UNIV")  # CON, RES, MFG, PRP, ECM, PRO, SAAS, RTL, REC, TRN, UNIV
    is_vat_registered = Column(Boolean, default=False)
    vat_scheme = Column(String(50), default="STANDARD")  # STANDARD, CASH, FLAT_RATE, MARGIN
    has_payroll = Column(Boolean, default=False)
    cis_status = Column(String(50), default="NONE")  # NONE, CONTRACTOR, SUBCONTRACTOR, BOTH
    directors = Column(Text, nullable=True)  # JSON array of names
    accounting_framework = Column(String(50), default="FRS102_1A")  # FRS102_1A, FRS105, FULL_FRS102
    materiality_threshold = Column(Numeric(14, 2), default=0.00)
    capitalisation_threshold = Column(Numeric(14, 2), default=500.00)
    auto_detected = Column(Boolean, default=False)
    tax_inputs = Column(Text, nullable=True)  # JSON: corporation tax facts not in the books (see TAX_INPUT_FIELDS)
    properties = Column(Text, nullable=True)  # JSON list: {name, model RENTAL/TRADING, rent_start, words}
    companies_house = Column(Text, nullable=True)  # JSON: company number + directors / shareholders >25% from the register
    setup = Column(Text, nullable=True)  # JSON: the rest of the Engagement Setup (client, vat, payroll, policies, people, materiality, prior year)
    confirmed_fields = Column(Text, nullable=True)  # JSON list of settings saved on the setup screen (auto-detect leaves them)
    detection_signals = Column(Text, nullable=True)  # JSON details of detected signals
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="profile")

class TBRecord(Base):
    __tablename__ = "tb_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False)
    raw_account_name = Column(String(255), nullable=False)
    std_code = Column(Integer, nullable=True)
    std_name = Column(String(255), nullable=True)
    debit_amount = Column(Numeric(14, 2), default=0.00)
    credit_amount = Column(Numeric(14, 2), default=0.00)
    net_amount = Column(Numeric(14, 2), default=0.00) # closing balance (debit positive)
    opening_amount = Column(Numeric(14, 2), nullable=True) # set when the client's TB holds this year's movements only; net = movement + opening
    mapping_status = Column(String(50), default="UNMAPPED") # MATCHED, AI_SUGGESTED, NEEDS_REVIEW
    confidence_score = Column(Float, default=1.0)
    source_account_type = Column(String(100), nullable=True) # Account type from the client's software (e.g. Xero "Revenue")
    match_source = Column(String(50), nullable=True) # MEMORY, CODE_AND_NAME, RULE, COA_NAME, AI
    mapping_reason = Column(Text, nullable=True)

    engagement = relationship("ClientEngagement", back_populates="tb_records")

class AuditFinding(Base):
    __tablename__ = "audit_findings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False)
    stage = Column(String(50), default="STAGE_1_ACCOUNTING") # STAGE_1_ACCOUNTING, STAGE_2_VAT, STAGE_3_CT600
    procedure_ref = Column(String(50), nullable=False) # G1 through G19, V-C01, CT-01, etc.
    procedure_name = Column(String(100), nullable=False)
    severity = Column(String(20), default="MEDIUM")    # CRITICAL, HIGH, MEDIUM, LOW
    source_row_ref = Column(String(100), nullable=True)
    finding_title = Column(String(255), nullable=False)
    finding_details = Column(Text, nullable=False)
    quantified_amount = Column(Numeric(14, 2), default=0.00)
    suggested_journal = Column(Text, nullable=True)
    status = Column(String(50), default="OPEN")        # OPEN, CLEARED
    cleared_note = Column(Text, nullable=True)         # why the accountant cleared it
    cleared_at = Column(DateTime, nullable=True)
    # JSON: the point's figures as a small table for the screen ({"columns": [...], "rows": [{"label", "values",
    # "strong"}]}), written by the check that raises the point (review/point_figures.py); empty for other points
    figures = Column(Text, nullable=True)

    engagement = relationship("ClientEngagement", back_populates="audit_findings")

class ProposedJournal(Base):
    __tablename__ = "proposed_journals"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    finding_id = Column(Integer, nullable=True)
    stage = Column(String(50), default="STAGE_1_ACCOUNTING") # STAGE_1_ACCOUNTING, STAGE_2_VAT, STAGE_3_CT600
    journal_ref = Column(String(50), nullable=False)        # e.g. "AJ01", "AJ02"
    description = Column(String(255), nullable=False)
    debit_code = Column(Integer, nullable=False)
    debit_name = Column(String(255), nullable=False)
    credit_code = Column(Integer, nullable=False)
    credit_name = Column(String(255), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False, default=0.00)
    status = Column(String(50), default="PROPOSED")         # PROPOSED, APPROVED, REJECTED
    source = Column(String(20), default="REVIEW")           # REVIEW (proposed by the review engine) or MANUAL (entered by an accountant)
    created_at = Column(DateTime, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)

    engagement = relationship("ClientEngagement", back_populates="journals")
    # Any number of lines; review-engine journals have none and use debit/credit code + amount
    lines = relationship("JournalLine", back_populates="journal", cascade="all, delete-orphan", order_by="JournalLine.line_no")

class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    journal_id = Column(Integer, ForeignKey("proposed_journals.id"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    account_code = Column(Integer, nullable=False)
    account_name = Column(String(255), nullable=True)
    narrative = Column(String(255), nullable=True)
    debit = Column(Numeric(14, 2), default=0.00)
    credit = Column(Numeric(14, 2), default=0.00)

    journal = relationship("ProposedJournal", back_populates="lines")

class GeneratedWorkpaper(Base):
    __tablename__ = "generated_workpapers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    diagnostics_score = Column(String(50), default="10/10 PASS")
    generated_at = Column(DateTime, default=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="workpapers")

class GLTransaction(Base):
    __tablename__ = "gl_transactions"
    __table_args__ = (
        Index("idx_gl_eng_acc", "engagement_id", "raw_account_name"),
        Index("idx_gl_eng_date", "engagement_id", "transaction_date"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    raw_account_name = Column(String(255), nullable=False, index=True)
    transaction_date = Column(Date, nullable=True)
    description = Column(String(500), nullable=True)
    reference = Column(String(255), nullable=True)
    source = Column(String(100), nullable=True)
    vat_amount = Column(Numeric(14, 2), nullable=True)  # VAT on this line (same sign as the line), when the ledger has it
    vat_code = Column(String(100), nullable=True)       # VAT rate / code name, e.g. "20% (VAT on Income)", "20.0% S"
    tracking = Column(String(255), nullable=True)  # QuickBooks class / location, Xero tracking (e.g. the property)
    debit_amount = Column(Numeric(14, 2), default=0.00)
    credit_amount = Column(Numeric(14, 2), default=0.00)
    net_amount = Column(Numeric(14, 2), default=0.00)
    created_at = Column(DateTime, default=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="gl_transactions")

    @property
    def signed_vat(self) -> float:
        """The line's VAT with the line's sign (a credit's VAT is -), as vat_amount should hold it."""
        return signed_vat(self.vat_amount, self.debit_amount, self.credit_amount)


def signed_vat(vat, debit, credit) -> float:
    """VAT on a ledger line with the line's sign. Xero signs its VAT column; QuickBooks does not (a sale, a credit of
    175.00, shows VAT 35.00), and read as signed every sale's VAT was taken off the output VAT: Box 1 against the
    ledger out by twice the sales VAT. A positive VAT on a credit line is that; any other is left as it is."""
    v = float(vat or 0.0)
    if v > 0 and float(credit or 0) - float(debit or 0) > 0:
        return -v
    return v

class SupplementaryDocument(Base):
    __tablename__ = "supplementary_documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    doc_type = Column(String(50), nullable=False) # VAT_100, FIXED_ASSET_REGISTER, PAYROLL_P32, AP_LISTING, AR_LISTING
    filename = Column(String(255), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    parsed_records_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="supplementary_docs")

class VAT100Record(Base):
    __tablename__ = "vat_100_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    period_label = Column(String(100), nullable=False) # e.g. "Q1 2024", "Annual Summary"
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    box1_vat_due_sales = Column(Numeric(14, 2), default=0.00)
    box2_vat_due_acquisitions = Column(Numeric(14, 2), default=0.00)
    box3_total_vat_due = Column(Numeric(14, 2), default=0.00)
    box4_vat_reclaimed = Column(Numeric(14, 2), default=0.00)
    box5_net_vat = Column(Numeric(14, 2), default=0.00)
    box6_total_sales_ex_vat = Column(Numeric(14, 2), default=0.00)
    box7_total_purchases_ex_vat = Column(Numeric(14, 2), default=0.00)
    box8_supplies_to_eu = Column(Numeric(14, 2), default=0.00)
    box9_acquisitions_from_eu = Column(Numeric(14, 2), default=0.00)
    bfwd_outstanding = Column(Numeric(14, 2), nullable=True)  # last year's return still unpaid at the year start
    created_at = Column(DateTime, default=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="vat_100_records")

class FixedAssetRecord(Base):
    __tablename__ = "fixed_asset_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    asset_tag = Column(String(100), nullable=True)
    description = Column(String(255), nullable=False)
    category = Column(String(100), default="General Equipment") # Plant & Machinery, Computer Equip, Motor Vehicles, Fixtures & Fittings
    acquisition_date = Column(Date, nullable=True)
    cost_bwd = Column(Numeric(14, 2), default=0.00)
    additions = Column(Numeric(14, 2), default=0.00)
    disposals = Column(Numeric(14, 2), default=0.00)
    cost_fwd = Column(Numeric(14, 2), default=0.00)
    depr_rate_method = Column(String(100), nullable=True) # e.g. 20% SL, 25% RB
    depr_bwd = Column(Numeric(14, 2), default=0.00)
    depr_charge = Column(Numeric(14, 2), default=0.00)
    depr_disposals = Column(Numeric(14, 2), default=0.00)
    depr_fwd = Column(Numeric(14, 2), default=0.00)
    nbv = Column(Numeric(14, 2), default=0.00)
    # The Asset Register screen: residual value and useful life in years (nullable)
    residual_value = Column(Numeric(14, 2), nullable=True)
    useful_life_years = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="fixed_asset_records")

class PayrollP32Record(Base):
    __tablename__ = "payroll_p32_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    tax_month_label = Column(String(100), nullable=False) # e.g. "Month 1", "Month 12", "Annual Summary"
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    employee_name = Column(String(255), nullable=True)  # one row per employee per pay period (BrightPay report)
    student_loan = Column(Numeric(14, 2), default=0.00)
    gross_pay = Column(Numeric(14, 2), default=0.00)
    tax_deducted = Column(Numeric(14, 2), default=0.00)
    employee_nic = Column(Numeric(14, 2), default=0.00)
    employer_nic = Column(Numeric(14, 2), default=0.00)
    statutory_pay_recovered = Column(Numeric(14, 2), default=0.00)
    net_pay = Column(Numeric(14, 2), default=0.00)
    pension_employee = Column(Numeric(14, 2), default=0.00)
    pension_employer = Column(Numeric(14, 2), default=0.00)
    total_hmrc_due = Column(Numeric(14, 2), default=0.00)
    created_at = Column(DateTime, default=datetime.utcnow)

    engagement = relationship("ClientEngagement", back_populates="payroll_records")


# Columns added to tables made before them (nullable, nothing else changes): before any query reads the models
from backend.app.core.database import add_columns as _add_columns  # noqa: E402
_add_columns("fixed_asset_records", {"residual_value": "NUMERIC(14, 2)", "useful_life_years": "FLOAT"})
_add_columns("audit_findings", {"figures": "TEXT"})
