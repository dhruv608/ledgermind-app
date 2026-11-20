// The two confirm steps of the change-code modal: change to the picked code, or go back to the AI's code.
import { Check, Loader2, RotateCcw, ArrowRightLeft } from "lucide-react";
import { TBRecord } from "@/types/engagement";
import { MasterCOAItem } from "@/components/mapping/reassign/categories";

export function ReassignConfirmOverlay({
  record,
  pendingItem,
  isSaving,
  setPendingItem,
  handleConfirmReassign,
}: {
  record: TBRecord;
  pendingItem: MasterCOAItem;
  isSaving: boolean;
  setPendingItem: (item: MasterCOAItem | null) => void;
  handleConfirmReassign: () => void;
}) {
  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs animate-in fade-in duration-150">
      <div
        className="w-full max-w-md bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden animate-in zoom-in-95 duration-150 p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-xl bg-teal-100 flex items-center justify-center shrink-0">
            <ArrowRightLeft className="w-5 h-5 text-teal-700" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-900">Change this account&apos;s code?</h4>
            <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
              The account moves to the new code below.
            </p>
          </div>
        </div>

        <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200/80 space-y-2.5">
          <div>
            <span className="text-[11px] uppercase font-bold text-slate-400 tracking-wider">Client Account</span>
            <p className="text-xs font-bold text-slate-900 mt-0.5 break-words">
              {record.raw_account_name}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-200 text-xs">
            <div className="bg-white p-2.5 rounded-lg border border-slate-200 shadow-2xs">
              <span className="text-[11px] text-slate-400 font-bold block uppercase">Current Code</span>
              <p className="font-mono font-bold text-slate-700 mt-1">{record.std_code ?? "—"}</p>
              <p className="text-[11px] text-slate-600 truncate mt-0.5">{record.std_name || "Unassigned"}</p>
            </div>

            <div className="bg-teal-50/80 p-2.5 rounded-lg border border-teal-200 shadow-2xs">
              <span className="text-[11px] text-teal-800 font-bold block uppercase">New Code</span>
              <p className="font-mono font-bold text-teal-950 mt-1">{pendingItem.std_code}</p>
              <p className="text-[11px] text-teal-900 font-medium truncate mt-0.5">{pendingItem.std_name}</p>
            </div>
          </div>

          <p className="text-[11px] text-slate-500 leading-relaxed pt-1">
            The working papers use the new code, and the firm memory remembers it for the next client with this
            account name.
          </p>
        </div>

        <div className="flex items-center justify-end space-x-2 pt-1">
          <button
            type="button"
            disabled={isSaving}
            onClick={() => setPendingItem(null)}
            className="px-3.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 rounded-xl hover:bg-slate-100 transition cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isSaving}
            onClick={handleConfirmReassign}
            className="px-4 py-2 text-xs font-bold text-white bg-teal-700 hover:bg-teal-800 rounded-xl shadow-xs transition flex items-center space-x-1.5 cursor-pointer disabled:opacity-50"
          >
            {isSaving ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Updating...</span>
              </>
            ) : (
              <>
                <Check className="w-3.5 h-3.5" />
                <span>Change the code</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ResetConfirmOverlay({
  record,
  isResetting,
  setIsConfirmingReset,
  handleConfirmResetToAI,
}: {
  record: TBRecord;
  isResetting: boolean;
  setIsConfirmingReset: (on: boolean) => void;
  handleConfirmResetToAI: () => void;
}) {
  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs animate-in fade-in duration-150">
      <div
        className="w-full max-w-md bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden animate-in zoom-in-95 duration-150 p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-xl bg-teal-100 flex items-center justify-center shrink-0">
            <RotateCcw className="w-5 h-5 text-teal-700" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-900">Go back to the suggested code?</h4>
            <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
              <strong className="text-slate-800">{record.raw_account_name}</strong> goes back to the code first suggested for it.
            </p>
          </div>
        </div>

        <div className="bg-slate-50 rounded-xl p-3 border border-slate-200 text-xs text-slate-600 leading-relaxed">
          The code you chose for this account is forgotten, also in the firm memory.
        </div>

        <div className="flex items-center justify-end space-x-2 pt-1">
          <button
            type="button"
            disabled={isResetting}
            onClick={() => setIsConfirmingReset(false)}
            className="px-3.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 rounded-xl hover:bg-slate-100 transition cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isResetting}
            onClick={handleConfirmResetToAI}
            className="px-4 py-2 text-xs font-bold text-white bg-teal-700 hover:bg-teal-800 rounded-xl shadow-xs transition flex items-center space-x-1.5 cursor-pointer disabled:opacity-50"
          >
            {isResetting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Resetting...</span>
              </>
            ) : (
              <>
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Yes, go back</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
