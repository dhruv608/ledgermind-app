"""An individual's Self Assessment job: one person, one tax year (6 April to 5 April).

  sources          JSON list of the kinds of income the person has (SOURCES): the workspace shows a page for each
  first_return     1 when the firm has no return of theirs from last year (nothing to use as the checklist)
  company_engagement_id  their company, when they are a director of a client of the firm (dividends, salary, loan)
  utr / ni_number  optional; never shown in full on screen"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text

from backend.app.core.database import Base, create_table

TAX_YEARS = ("2025-26", "2024-25")
SOURCES = ("EMPLOYMENT", "SELF_EMPLOYMENT", "PROPERTY", "SAVINGS", "DIVIDENDS", "PENSIONS", "FOREIGN", "CAPITAL_GAINS")


class SAJob(Base):
    __tablename__ = "sa_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    person_name = Column(String(255), nullable=False)
    tax_year = Column(String(7), nullable=False)               # "2025-26"
    sources = Column(Text, nullable=False, default="[]")        # JSON list of SOURCES
    first_return = Column(Integer, nullable=False, default=0)
    # No foreign key: deleting the company leaves the person's return (shown with no company)
    company_engagement_id = Column(String(36), nullable=True)
    utr = Column(String(20), nullable=True)
    ni_number = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SADocument(Base):
    """One file of a Self Assessment job, as read (R-IN-01..07).

      kind    P60, P45, PAYSLIP, P11D, BANK_STATEMENT, MORTGAGE_INTEREST, LETTING_STATEMENT, INTEREST_STATEMENT,
              DIVIDEND_VOUCHER, PENSION_STATEMENT, TAX_CALCULATION, INVOICE, WORKING_PAPER, OTHER
      status  READ (figures taken), CHECK (read, a person must look: readers disagree, a check failed), UNREADABLE
              (password, damaged, a format not read), DUPLICATE (same file again), OTHER_YEAR (outside the tax year),
              FILED (kept, no figures read from this kind yet)
      fields  JSON: what was read (a P60's pay and tax in this employment, PAYE reference, tax code...)"""
    __tablename__ = "sa_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(500), nullable=False)          # inside an archive: 'archive.zip/folder/file.pdf'
    sha256 = Column(String(64), nullable=False)
    size = Column(Integer, nullable=False, default=0)
    storage_key = Column(String(500), nullable=True)
    kind = Column(String(30), nullable=False, default="OTHER")
    status = Column(String(20), nullable=False, default="FILED")
    tax_year = Column(String(7), nullable=True)               # the year the document is for, when it says
    fields = Column(Text, nullable=True)                      # JSON
    note = Column(Text, nullable=True)                        # why CHECK / UNREADABLE / OTHER_YEAR, in plain words
    read_by = Column(String(100), nullable=True)              # 'text' or the AI model(s) that read it
    created_at = Column(DateTime, default=datetime.utcnow)


class SALine(Base):
    """One figure on the return: a P60's pay and tax, an account's interest, a dividend, a pension, a Gift Aid
    payment... read from a document (doc_id, auto) or entered by the accountant. The tax calculation adds them up
    (sa/income); a line left out (include 0) stays visible with its reason.

      source  EMPLOYMENT, SELF_EMPLOYMENT, PROPERTY, SAVINGS, DIVIDENDS, PENSIONS, FOREIGN, RELIEFS
      kind    P60 / PAY, PROFIT, INTEREST / ISA, DIVIDEND, STATE_PENSION / PENSION / BENEFIT, INCOME,
              GIFT_AID / PENSION_RAS / SALARY_SACRIFICE (RELIEFS: amounts as paid, net)
      share   the person's share of a joint item (0.5 for a joint account unless evidence says otherwise)"""
    __tablename__ = "sa_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(20), nullable=False)
    kind = Column(String(20), nullable=False)
    label = Column(String(255), nullable=False, default="")
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    tax_paid = Column(Numeric(14, 2), nullable=False, default=0)
    share = Column(Numeric(5, 4), nullable=False, default=1)
    extra = Column(Numeric(14, 2), nullable=True)            # PROPERTY: residential finance costs for the 20% credit
    include = Column(Integer, nullable=False, default=1)
    doc_id = Column(Integer, nullable=True)
    auto = Column(Integer, nullable=False, default=0)        # made from a document (removed with it)
    note = Column(Text, nullable=True)
    paid_on = Column(String(10), nullable=True)              # a dividend's or interest's date, YYYY-MM-DD
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SAProperty(Base):
    """One let property (SA105). share: the person's share of its income and costs (spouses 50/50 unless a Form 17
    declaration, ITA 2007 s836-837). use_allowance: the £1,000 property allowance instead of the expenses.
    losses_bf / finance_bf: the person's UK property losses and unused residential finance costs from last year
    (the UK property business is one business: they are kept on the first property)."""
    __tablename__ = "sa_properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    share = Column(Numeric(5, 4), nullable=False, default=1)
    use_allowance = Column(Integer, nullable=False, default=0)
    losses_bf = Column(Numeric(14, 2), nullable=False, default=0)
    finance_bf = Column(Numeric(14, 2), nullable=False, default=0)
    owner = Column(String(8), nullable=False, default="SOLE")   # SOLE, SPOUSE (joint with a spouse), JOINT, COMPANY
    kind = Column(String(12), nullable=False, default="RESIDENTIAL")  # RESIDENTIAL or COMMERCIAL (finance costs rule)
    let_from = Column(String(10), nullable=True)                # letting started (in the year: a new source)
    let_to = Column(String(10), nullable=True)                  # letting ended
    ended = Column(String(10), nullable=True)                   # why it ended: SOLD, MOVED_IN, OTHER
    own_home = Column(String(8), nullable=True)                 # ROOM (a lodger in the client's home), FORMER (was their home)
    rent_a_room = Column(String(12), nullable=True)             # the accountant's choice: RENT_A_ROOM or ACTUAL
    country = Column(String(3), nullable=True)                  # empty: in the UK (SA105); else abroad (SA106 F4-F5)
    foreign_tax = Column(Numeric(14, 2), nullable=False, default=0)   # the person's foreign tax on its income, in £
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SAPropertyItem(Base):
    """A dated amount of a property, as the firm's working paper has them month by month: rent received, or a cost
    under its SA105 heading (property.py HEADINGS). Amounts are the whole property's; the share is applied once."""
    __tablename__ = "sa_property_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("sa_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), nullable=False, index=True)
    on = Column(String(10), nullable=True)                    # YYYY-MM-DD
    description = Column(String(255), nullable=False, default="")
    heading = Column(String(20), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    doc_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SABusiness(Base):
    """One self-employment (SA103). Income and costs are items under the SA103 headings (trade.py HEADINGS), each with
    the part not allowed for tax. Simplified expenses (use of home by hours, mileage) are worked out from the hours
    and miles; capital allowances are entered as worked out, or as allowance lines (allowances.py)."""
    __tablename__ = "sa_businesses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    period_start = Column(String(10), nullable=True)
    period_end = Column(String(10), nullable=True)
    cash_basis = Column(Integer, nullable=False, default=1)          # the default from 2024-25 (ITTOIA s25A)
    use_trading_allowance = Column(Integer, nullable=False, default=0)
    home_hours = Column(Integer, nullable=True)                        # hours a month worked at home (flat rate)
    home_months = Column(Integer, nullable=True)                       # months worked at home in the year
    car_miles = Column(Integer, nullable=True)                         # business miles by car or van (flat rate)
    motorcycle_miles = Column(Integer, nullable=True)
    capital_allowances = Column(Numeric(14, 2), nullable=False, default=0)
    balancing_charges = Column(Numeric(14, 2), nullable=False, default=0)
    losses_bf = Column(Numeric(14, 2), nullable=False, default=0)
    cis_deducted = Column(Numeric(14, 2), nullable=False, default=0)   # CIS tax taken off by contractors
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SABusinessItem(Base):
    """An amount of a business under its SA103 heading: turnover, other income, or a cost with the part disallowed."""
    __tablename__ = "sa_business_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    business_id = Column(Integer, ForeignKey("sa_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), nullable=False, index=True)
    heading = Column(String(24), nullable=False)
    description = Column(String(255), nullable=False, default="")
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    disallowed = Column(Numeric(14, 2), nullable=False, default=0)
    doc_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SAAllowance(Base):
    """A capital allowance line of a business (allowances.py): the kind, the qualifying cost or pool value brought
    forward plus additions less disposals, and the private use part. When a business has lines, their total replaces
    the single capital allowances figure."""
    __tablename__ = "sa_allowances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    business_id = Column(Integer, ForeignKey("sa_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(12), nullable=False)
    description = Column(String(255), nullable=False, default="")
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    private_use = Column(Numeric(5, 4), nullable=False, default=0)        # 0.25 for 25% private use
    created_at = Column(DateTime, default=datetime.utcnow)


class SABankChoice(Base):
    """The accountant's heading for a bank line, kept by the line's own words (key)."""
    __tablename__ = "sa_bank_choices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False, index=True)
    key = Column(String(40), nullable=False)
    heading = Column(String(24), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)





class SAExpect(Base):
    """One line of this year's checklist: a source, relief or carry-forward from last year's working
    paper, its figure last year, and what this year shows: Continued, Changed, Unknown or New."""
    __tablename__ = "sa_expect"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_id = Column(Integer, nullable=True)                     # last year's working paper it was read from
    source = Column(String(20), nullable=False)                 # EMPLOYMENT, PENSIONS ... RELIEFS, CARRY_FORWARD
    kind = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False, default="")
    ref = Column(String(60), nullable=True)                     # PAYE reference, account
    last_amount = Column(Numeric(14, 2), nullable=True)
    last_tax = Column(Numeric(14, 2), nullable=True)
    ended = Column(String(40), nullable=True)                   # left the job / stopped last year: nothing expected
    note = Column(Text, nullable=True)
    status = Column(String(12), nullable=True)                  # CONTINUED / CHANGED / UNKNOWN / NEW / ENDED
    answer = Column(Text, nullable=True)                        # the client's or accountant's answer
    auto = Column(Integer, nullable=False, default=1)           # 1: read from the working paper; 0: added by hand
    agreed = Column(Integer, nullable=False, default=1)         # 0: the two readers read it differently: to check
    hand = Column(Integer, nullable=False, default=0)           # 1: the status was set by the accountant
    created_at = Column(DateTime, default=datetime.utcnow)



class SAAnswer(Base):
    """An answer kept for a job: a yearly yes/no question ('q:sold'), or what was done with a sign of new income in the
    bank ('s:dividend:acme'): asked or dismissed."""
    __tablename__ = "sa_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(120), nullable=False)
    value = Column(String(20), nullable=True)                   # YES / NO / ASKED / DISMISSED
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SAReading(Base):
    """A file being read in the background (an upload answers at once; the screen asks until it is done): one row per
    file sent, finished when its documents are in, with the error if the reading failed. A new table, so the live
    database needs no column change."""
    __tablename__ = "sa_reading"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False, default="")
    finished = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)


class SAPayments(Base):
    """What the person has already paid towards the year and their NI choice, one row per job: the payments on account
    already made for this tax year (from the HMRC statement, R-FAM-03: they come off the 31 January payment), and
    voluntary Class 2 on profits under the small profits threshold (R-NIC-01)."""
    __tablename__ = "sa_payments"

    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), primary_key=True)
    poa_paid = Column(Numeric(14, 2), nullable=False, default=0)
    class2_voluntary = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SAFosterYear(Base):
    """Foster, kinship or shared-lives care for the year (R-SP-01), one row per job: the receipts when typed (else from
    the council's letter), how many carers share the household's fixed amount, and the method chosen when the receipts
    are over the limit (SIMPLIFIED or ACTUAL, with the actual costs)."""
    __tablename__ = "sa_foster_year"

    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), primary_key=True)
    receipts = Column(Numeric(14, 2), nullable=True)
    carers = Column(Integer, nullable=False, default=1)
    method = Column(String(12), nullable=True)
    actual_costs = Column(Numeric(14, 2), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SAFosterPlacement(Base):
    """A person cared for in the year (R-SP-01): their age band and the weeks (a part week a full week), from the
    placement dates."""
    __tablename__ = "sa_foster_placements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(120), nullable=False, default="")
    band = Column(String(12), nullable=False)                   # UNDER_11, ELEVEN_PLUS, ADULT
    weeks = Column(Integer, nullable=False, default=52)
    created_at = Column(DateTime, default=datetime.utcnow)


class SAFamily(Base):
    """The family and loan facts of a return (R-FAM-01, 02, 04; SA100 page TR5), one row per job.

      higher_income   ME (the person has the higher adjusted net income, or no partner), PARTNER (the partner pays
                      any Child Benefit charge), empty: not asked yet
      marriage        TRANSFERRED (this person gives £1,260 of allowance), RECEIVED (their spouse gives it to them)
      loan_plans      'PLAN_1,PLAN_2' ...; postgraduate 1 when a postgraduate loan is in repayment
      studying        1: still studying or not yet due to repay: nothing charged (R-FAM-02)"""
    __tablename__ = "sa_family"

    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), primary_key=True)
    child_benefit = Column(Numeric(14, 2), nullable=True)
    children = Column(Integer, nullable=True)
    cb_stopped = Column(String(10), nullable=True)
    higher_income = Column(String(10), nullable=True)
    marriage = Column(String(12), nullable=True)
    spouse_name = Column(String(255), nullable=True)
    loan_plans = Column(String(60), nullable=True)
    postgraduate = Column(Integer, nullable=False, default=0)
    studying = Column(Integer, nullable=False, default=0)
    sl_deducted = Column(Numeric(14, 2), nullable=True)
    pgl_deducted = Column(Numeric(14, 2), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SADisposal(Base):
    """One disposal for capital gains (SA108). Amounts are the whole asset's; share is the person's part.

      kind           RESIDENTIAL (UK or overseas homes), CRYPTO, OTHER (other property and assets), LISTED, UNLISTED
      contract_date  the date of disposal: the unconditional contract (TCGA s28); completion starts the 60 days
      main_home_months  months it was the person's only or main home (private residence relief), before the final
                     9 months, which always count when it was ever the main home (s223)
      rtt_gain / rtt_tax  the gain reported and the tax paid on a 60-day UK property return (SA108 boxes 9 and 10)"""
    __tablename__ = "sa_disposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(12), nullable=False)
    name = Column(String(255), nullable=False, default="")
    acquired = Column(String(10), nullable=True)
    contract_date = Column(String(10), nullable=True)
    completion_date = Column(String(10), nullable=True)
    proceeds = Column(Numeric(14, 2), nullable=False, default=0)
    cost = Column(Numeric(14, 2), nullable=False, default=0)
    costs = Column(Numeric(14, 2), nullable=False, default=0)            # buying and selling costs (fees, SDLT)
    improvements = Column(Numeric(14, 2), nullable=False, default=0)
    share = Column(Numeric(5, 4), nullable=False, default=1)
    uk = Column(Integer, nullable=False, default=1)
    main_home_months = Column(Integer, nullable=True)
    badr = Column(Integer, nullable=False, default=0)                     # Business Asset Disposal Relief claimed
    negligible = Column(Integer, nullable=False, default=0)               # a negligible value claim (R-SA108-04)
    rtt_date = Column(String(10), nullable=True)                          # the 60-day return was sent on
    rtt_gain = Column(Numeric(14, 2), nullable=True)
    rtt_tax = Column(Numeric(14, 2), nullable=True)
    doc_id = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SAForeign(Base):
    """One foreign source (SA106 pages F2-F3), in pounds: the gross amount before foreign tax and the foreign tax.

      kind    INTEREST (savings rates), DIVIDEND (dividend rates), PENSION (90% taxable, ITEPA s575), BENEFIT, OTHER
      claim   1: claim Foreign Tax Credit Relief (the credit is the lower of the foreign tax the treaty allows and
              the UK tax on this income); 0: the foreign tax is deducted from the income instead"""
    __tablename__ = "sa_foreign"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    country = Column(String(3), nullable=False)
    kind = Column(String(10), nullable=False)
    payer = Column(String(255), nullable=False, default="")
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    foreign_tax = Column(Numeric(14, 2), nullable=False, default=0)
    share = Column(Numeric(5, 4), nullable=False, default=1)
    claim = Column(Integer, nullable=False, default=1)
    doc_id = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SAShareTrade(Base):
    """A trade in a holding of shares or cryptoassets (sharematch.py): BUY (cost with fees), SELL (proceeds net of
    fees), or POOL (the section 104 pool brought forward: quantity and cost)."""
    __tablename__ = "sa_share_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    holding = Column(String(255), nullable=False)
    kind = Column(String(12), nullable=False, default="LISTED")      # LISTED, UNLISTED, CRYPTO
    on = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False, default=0)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    doc_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SACapital(Base):
    """A return's capital losses brought forward from earlier years (used only down to the annual exempt amount)."""
    __tablename__ = "sa_capital"

    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), primary_key=True)
    losses_bf = Column(Numeric(14, 2), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SAPack(Base):
    """A working paper pack as produced (R-OUT-02): every version kept as made, never changed, with its note.

      kind    FINAL (no Block open, R-OUT-01) or DRAFT (for review while Blocks are open; marked on every sheet)"""
    __tablename__ = "sa_packs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    kind = Column(String(10), nullable=False)
    note = Column(Text, nullable=True)
    blocks = Column(Integer, nullable=False, default=0)
    balance = Column(Numeric(14, 2), nullable=True)             # the balance to pay in this version
    storage_key = Column(String(500), nullable=True)
    size = Column(Integer, nullable=False, default=0)
    made_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# New tables only: created on first use, leaving every existing table as it is
create_table(SAJob.__table__)
create_table(SABusiness.__table__)
create_table(SABusinessItem.__table__)
create_table(SADocument.__table__)
create_table(SALine.__table__)
create_table(SAProperty.__table__)
create_table(SAPropertyItem.__table__)
create_table(SABankChoice.__table__)
create_table(SAExpect.__table__)
create_table(SAAnswer.__table__)
create_table(SAPayments.__table__)
create_table(SAFosterYear.__table__)
create_table(SAFosterPlacement.__table__)
create_table(SAPack.__table__)
create_table(SAFamily.__table__)
create_table(SADisposal.__table__)
create_table(SACapital.__table__)
create_table(SAForeign.__table__)
create_table(SAAllowance.__table__)
create_table(SAShareTrade.__table__)
create_table(SAReading.__table__)
