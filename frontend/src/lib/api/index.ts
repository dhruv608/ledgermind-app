// The server API, one file per area, all exported from "@/lib/api".
export { SetupGapsError, FilesNeedRolesError, BuildBlockedError, getApiBaseUrl, getDownloadUrl, resolveBackendUrl, formatClientName } from "./client";
export type { BooksBankRow, BooksPayment, BooksInvoice, BooksBill, BooksCustomer, BooksQuestion, BooksData, BooksOpeningLine } from "./books";
export type { CisHmrcMonth, CisHmrcScreen, CisCheck, CisChecks } from "./cis";
export type { DataCheck, DataCheckItem, DataCheckStatus, DataCheckAction } from "./datacheck";
export type { FirmDepreciation, ClassRate, DepreciationMethod } from "./firmSettings";
export type { JobQuery, JobQueries, QueryAudience, QueryItem, QueryStatus, QueryUpdate, RaisedQueryIn } from "./queries";
export type { AreaNote, AreaNoteIn } from "./notes";
export type { MemoryEntry } from "./mapping";
export type { EvidenceByArea, EvidenceDoc } from "./evidence";
export type { LedgerViews, LedgerViewLine, LedgerMove, LedgerJournal, ContactLedger, ContactDocument } from "./ledgerViews";
export type { Etb, EtbRow, Reconciliation, Reconciliations, VatProof, VatProofLine, ReconciliationEntry, Rollforward, RollforwardMovement, FixedAssetClass, FixedAssetFigures, FixedAssetSchedule, TradeAdjustment, TradeAdjustments, SalesReconciliation, PayrollSummary, PayrollSummaryFigures, PayrollSummaryTable, BankStatementMatch, StatementLine, AssetRegister, AssetFigures, AssetLine, TaxCalculation, TaxLine, ReservesMovement, ReservesYear, DebtorAgeing, PayrollMonth, PayrollMonths, PayrollSummaryMonth, PayrollTable } from "./reconciliations";
export type { AreaSignoff, CapitalAllowanceAsset, CapitalAllowances, PointSignoff, SignoffRole } from "./review";
export type { Reanalysis, ReanalysisGroup, ReanalysisLine, Mispostings, MispostingGroup, MispostingLine, MispostingMove, MispostingDecision } from "./reanalysis";
export type { CheckRun } from "./checks";
export type { OpeningBalances, OpeningRow } from "./opening";
export type { AdjustmentLine, Adjustments } from "./adjustments";
export type { ScrutinyAccount, ScrutinyAccounts, ScrutinyDecision, ScrutinyFlag, ScrutinyLine, ScrutinyLines } from "./scrutiny";
export type { LastYear } from "./setup";
export type { SaJob, SaJobIn, SaJobStatus, SaFosterView, SaSource, SaDocument, SaDocStatus, SaLine, SaLineIn, SaDividend, SaCalculation, SaBandLine, SaPropertyView, SaBankRent, SaBalanceSheet, SaPropertyRow, SaPropertyItem, SaOverview, SaState, SaTradeView, SaBusinessRow, SaBusinessSettings, SaTradeItem, SaBankBooks, SaBankBookLine, SaLastYear, SaExpectLine, SaExpectIn, SaQuestion, SaSignal, SaQuestions, SaQueryItem, SaQueries, SaBoxRow, SaBoxPage, SaBoxes, SaPackVersion, SaPacks, SaFamily, SaFamilyFacts, SaDisposalKind, SaDisposalIn, SaDisposalRow, SaCapitalGains, SaForeignKind, SaForeignIn, SaForeignRow, SaForeign, SaPropertyFacts } from "./sa";
export type { FileRole, IdentifiedFile, ColumnLayout, ConfirmResult, ConfirmedLayouts } from "./upload";
import { booksApi } from "./books";
import { cisApi } from "./cis";
import { clientsApi } from "./clients";
import { dataCheckApi } from "./datacheck";
import { firmSettingsApi } from "./firmSettings";
import { inputsApi } from "./inputs";
import { mappingApi } from "./mapping";
import { notesApi } from "./notes";
export type { CustomPaper, CustomPaperIn, CustomPaperKind, CustomPaperLine } from "./customPapers";
import { evidenceApi } from "./evidence";
import { customPapersApi } from "./customPapers";
import { jobDetailsApi } from "./jobDetails";
import { stockLinesApi } from "./stockLines";
export type { StockLine, StockLines } from "./stockLines";
export type { JobDetails } from "./jobDetails";
import { ledgerViewsApi } from "./ledgerViews";
import { queriesApi } from "./queries";
import { reanalysisApi } from "./reanalysis";
import { checksApi } from "./checks";
import { openingApi } from "./opening";
import { adjustmentsApi } from "./adjustments";
import { reconciliationsApi } from "./reconciliations";
import { reviewApi } from "./review";
import { saApi } from "./sa";
import { scrutinyApi } from "./scrutiny";
import { setupApi } from "./setup";
import { uploadApi } from "./upload";
import { workbookApi } from "./workbook";

export const api = {
  ...booksApi,
  ...cisApi,
  ...clientsApi,
  ...dataCheckApi,
  ...firmSettingsApi,
  ...inputsApi,
  ...mappingApi,
  ...notesApi,
  ...evidenceApi,
  ...customPapersApi,
  ...jobDetailsApi,
  ...stockLinesApi,
  ...ledgerViewsApi,
  ...queriesApi,
  ...reanalysisApi,
  ...checksApi,
  ...openingApi,
  ...adjustmentsApi,
  ...reconciliationsApi,
  ...reviewApi,
  ...saApi,
  ...scrutinyApi,
  ...setupApi,
  ...uploadApi,
  ...workbookApi,
};
