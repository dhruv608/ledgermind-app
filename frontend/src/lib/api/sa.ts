// Self Assessment: an individual's personal tax return for a tax year (backend/app/sa).
// The client is split by area in ./sa/; this file joins it back into one saApi.
import { saJobsApi } from "./sa/jobs";
import { saDocumentsApi } from "./sa/documents";
import { saIncomeApi } from "./sa/income";
import { saPropertyApi } from "./sa/property";
import { saTradeApi } from "./sa/trade";
import { saQuestionsApi } from "./sa/questions";
import { saGainsApi } from "./sa/gains";
import { saFamilyApi } from "./sa/family";
import { saPackApi } from "./sa/pack";

export type {
  SaSource, SaJob, SaJobStatus, SaFosterView, SaJobIn, SaDocStatus,
  SaDocument, SaLine, SaLineIn, SaDividend, SaBandLine, SaCalculation,
  SaPropertyItem, SaPropertyRow, SaPropertyFacts, SaPropertyView, SaBankRent, SaTradeItem,
  SaBusinessSettings, SaBusinessRow, SaBalanceSheet, SaAllowanceLine, SaTradeView, SaBankBookLine,
  SaBankBooks, SaExpectLine, SaLastYear, SaExpectIn, SaQuestion, SaSignal,
  SaQuestions, SaQueryItem, SaQueries, SaForeignKind, SaForeignIn, SaForeignRow,
  SaForeign, SaDisposalKind, SaDisposalIn, SaDisposalRow, SaCapitalGains, SaFamilyFacts,
  SaFamily, SaPackVersion, SaPacks, SaBoxRow, SaBoxPage, SaBoxes,
  SaState, SaOverview,
} from "./sa/types";

export const saApi = {
  ...saJobsApi,
  ...saDocumentsApi,
  ...saIncomeApi,
  ...saPropertyApi,
  ...saTradeApi,
  ...saQuestionsApi,
  ...saGainsApi,
  ...saFamilyApi,
  ...saPackApi,
};
