import { AlertTriangle, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  description: string;
  clientName?: string;
  confirmText?: string;
  cancelText?: string;
  isLoading?: boolean;
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  clientName,
  confirmText = "Delete Engagement",
  cancelText = "Cancel",
  isLoading = false,
}: ConfirmDialogProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
        onClick={isLoading ? undefined : onClose}
      />

      {/* Dialog Card */}
      <div
        className="relative z-50 w-full max-w-md rounded-2xl bg-white border border-slate-200 p-5 shadow-2xl transition-all animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close Button top-right */}
        <button
          onClick={onClose}
          disabled={isLoading}
          aria-label="Close dialog"
          className="absolute right-3.5 top-3.5 rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Header with Icon and Title */}
        <div className="flex items-start space-x-3.5 pr-6">
          <div className="w-10 h-10 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600 shrink-0 mt-0.5 shadow-2xs">
            <AlertTriangle className="w-5 h-5" />
          </div>

          <div className="space-y-1 flex-1 min-w-0">
            <h3 className="text-base font-bold text-slate-900 tracking-tight leading-snug">
              {title}
            </h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              {description}
            </p>
          </div>
        </div>

        {/* Client Name Badge */}
        {clientName && (
          <div className="mt-3 ml-13 p-2.5 rounded-lg bg-slate-50 border border-slate-200 text-xs font-semibold text-slate-800 font-mono break-all">
            {clientName}
          </div>
        )}

        {/* Action Buttons */}
        <div className="mt-5 flex items-center justify-end space-x-2 pt-3.5 border-t border-slate-100">
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={isLoading}
            className="h-8 px-3 text-xs rounded-lg cursor-pointer bg-white"
          >
            {cancelText}
          </Button>

          <Button
            variant="destructive"
            size="sm"
            onClick={onConfirm}
            disabled={isLoading}
            className="h-8 px-3.5 text-xs rounded-lg cursor-pointer bg-rose-600 hover:bg-rose-700 text-white font-medium shadow-2xs"
          >
            {isLoading ? "Deleting..." : confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
}
