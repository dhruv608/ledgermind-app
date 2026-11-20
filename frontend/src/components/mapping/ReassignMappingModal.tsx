"use client";

import { Search, X, Check, ArrowRight, RotateCcw } from "lucide-react";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { CATEGORY_GROUPS } from "@/components/mapping/reassign/categories";
import { ReassignMappingModalProps, useReassignMapping } from "@/components/mapping/reassign/useReassignMapping";
import { ReassignConfirmOverlay, ResetConfirmOverlay } from "@/components/mapping/reassign/ConfirmOverlays";

export function ReassignMappingModal({
  isOpen,
  onClose,
  record,
  onMappingUpdated,
  engagementId,
}: ReassignMappingModalProps) {
  const {
    coaList, isLoading, isSaving, isResetting, searchQuery, setSearchQuery, selectedCategory, setSelectedCategory,
    pendingItem, setPendingItem, isConfirmingReset, setIsConfirmingReset, currentCOAItem, filteredCOA,
    handleInitiateSelect, handleConfirmReassign, handleConfirmResetToAI,
  } = useReassignMapping({ isOpen, onClose, record, onMappingUpdated, engagementId });

  if (!isOpen || !record) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4">
      {/* Main Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
        onClick={isSaving || isResetting ? undefined : onClose}
      />

      {/* Main Modal Dialog */}
      <div
        className="relative z-50 w-full max-w-xl rounded-2xl bg-white border border-slate-200 shadow-2xl transition-all animate-in zoom-in-95 duration-200 flex flex-col max-h-[88vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-slate-100 bg-slate-50/80">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-teal-700 bg-teal-100/70 px-2 py-0.5 rounded-md">
                  Change code
                </span>
                <span className="text-xs text-slate-400">•</span>
                <span className="text-xs text-slate-500 font-mono font-medium">{coaList.length || ""} codes in the chart</span>
              </div>
              <h3 className="text-base font-bold text-slate-900 mt-1 line-clamp-1">
                {record.raw_account_name}
              </h3>
            </div>

            <button
              onClick={onClose}
              disabled={isSaving || isResetting}
              className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Current Selection & Revert to AI Button */}
          <div className="mt-3.5 p-3 rounded-xl bg-white border border-slate-200 shadow-2xs flex items-center justify-between gap-3">
            <div className="flex items-center space-x-2.5 min-w-0">
              <span className="font-mono font-bold text-xs px-2.5 py-1 rounded-lg bg-teal-50 border border-teal-200 text-teal-900 shrink-0 shadow-2xs">
                {record.std_code ?? "—"}
              </span>
              <div className="min-w-0">
                <p className="text-xs font-bold text-slate-800 truncate">
                  {record.std_name || "Unassigned"}
                </p>
                <p className="text-[11px] text-slate-400 truncate">
                  {currentCOAItem?.category || "Current code"}
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setIsConfirmingReset(true)}
              disabled={isResetting || isSaving}
              className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-teal-800 bg-teal-50/80 hover:bg-teal-100 border border-teal-200 transition cursor-pointer shrink-0"
              title="Go back to the code first suggested for this account"
            >
              <RotateCcw className="w-3.5 h-3.5 text-teal-700" />
              <span>Back to suggestion</span>
            </button>
          </div>

          {/* Search Box */}
          <div className="relative mt-3">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              autoFocus
              placeholder="Type a code or name, Enter picks the top one (e.g. 4800, wages)"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                // Enter picks the top result (a confirm step still follows)
                if (e.key === "Enter" && searchQuery.trim() && filteredCOA.length > 0) {
                  e.preventDefault();
                  handleInitiateSelect(filteredCOA[0]);
                }
              }}
              className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-slate-200 bg-white shadow-2xs focus:outline-hidden focus:ring-2 focus:ring-teal-600/20 focus:border-teal-600 font-sans"
            />
          </div>

          {/* Category Filter Pills */}
          <div className="mt-2.5 flex items-center space-x-1.5 overflow-x-auto pb-1 scrollbar-none text-xs">
            {CATEGORY_GROUPS.map((group) => {
              const isActive = selectedCategory === group.id && !searchQuery.trim();
              return (
                <button
                  key={group.id}
                  type="button"
                  onClick={() => {
                    setSelectedCategory(group.id);
                    setSearchQuery("");
                  }}
                  className={`px-2.5 py-1 rounded-lg font-medium whitespace-nowrap text-[11px] transition cursor-pointer ${
                    isActive
                      ? "bg-teal-700 text-white shadow-xs"
                      : "bg-white text-slate-600 border border-slate-200/80 hover:bg-slate-100"
                  }`}
                >
                  {group.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Counter Strip */}
        <div className="px-4 py-1.5 bg-slate-50 border-b border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
          <span>
            Showing <strong className="text-slate-800">{filteredCOA.length}</strong> {filteredCOA.length === 1 ? "code" : "codes"}
          </span>
          {selectedCategory !== "ALL" && (
            <button
              onClick={() => setSelectedCategory("ALL")}
              className="text-teal-700 hover:text-teal-800 font-medium cursor-pointer"
            >
              Show all codes
            </button>
          )}
        </div>

        {/* Account Code List */}
        <div className="flex-1 overflow-y-auto p-2 sm:p-3 divide-y divide-slate-100">
          {isLoading ? (
            <SkeletonRows rows={8} columns={2} label="Loading the chart of accounts" />
          ) : filteredCOA.length === 0 ? (
            <div className="text-center py-12 text-slate-400 text-xs">
              <p>No matching nominal codes found for &quot;{searchQuery}&quot;.</p>
              {selectedCategory !== "ALL" && (
                <button
                  onClick={() => setSelectedCategory("ALL")}
                  className="mt-2 text-xs text-teal-700 underline font-medium cursor-pointer"
                >
                  Search across all categories
                </button>
              )}
            </div>
          ) : (
            filteredCOA.map((item) => {
              const isCurrent = record.std_code === item.std_code;
              return (
                <button
                  key={item.std_code}
                  type="button"
                  disabled={isSaving || isResetting}
                  onClick={() => handleInitiateSelect(item)}
                  className={`w-full p-2.5 rounded-xl text-left transition cursor-pointer flex items-center justify-between group ${
                    isCurrent
                      ? "bg-teal-50/90 border border-teal-200/90 text-teal-950 font-medium"
                      : "hover:bg-slate-50 text-slate-700"
                  }`}
                >
                  <div className="flex items-center space-x-2.5 min-w-0">
                    <span
                      className={`font-mono font-bold text-xs px-2 py-1 rounded-md border shadow-2xs shrink-0 ${
                        isCurrent
                          ? "bg-white border-teal-300 text-teal-900"
                          : "bg-white border-slate-200 text-slate-800 group-hover:border-teal-300 group-hover:text-teal-900"
                      }`}
                    >
                      {item.std_code}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs truncate font-medium group-hover:text-slate-900">
                        {item.std_name}
                      </p>
                      {item.category && (
                        <p className="text-[11px] text-slate-400 truncate">
                          {item.category}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 shrink-0 ml-2">
                    {isCurrent ? (
                      <span className="text-[11px] font-semibold text-teal-800 flex items-center space-x-1">
                        <Check className="w-3.5 h-3.5" />
                        <span>{record.mapping_status === "MATCHED" ? "Current" : "Current: click to confirm"}</span>
                      </span>
                    ) : (
                      <span className="text-[11px] text-slate-400 group-hover:text-teal-700 flex items-center space-x-1 font-medium">
                        <span>Select</span>
                        <ArrowRight className="w-3 h-3 transition group-hover:translate-x-0.5" />
                      </span>
                    )}
                  </div>
                </button>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-100 bg-slate-50/60 flex items-center justify-between text-[11px] text-slate-500">
          <span>Pick the right code. You confirm it before anything changes.</span>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 cursor-pointer font-medium"
          >
            Cancel
          </button>
        </div>
      </div>

      {/* Confirmation Dialog Overlay for Code Reassignment */}
      {pendingItem && (
        <ReassignConfirmOverlay
          record={record}
          pendingItem={pendingItem}
          isSaving={isSaving}
          setPendingItem={setPendingItem}
          handleConfirmReassign={handleConfirmReassign}
        />
      )}

      {/* Confirmation Dialog Overlay for Reset to AI */}
      {isConfirmingReset && (
        <ResetConfirmOverlay
          record={record}
          isResetting={isResetting}
          setIsConfirmingReset={setIsConfirmingReset}
          handleConfirmResetToAI={handleConfirmResetToAI}
        />
      )}
    </div>
  );
}
