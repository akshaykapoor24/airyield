"use client";

// An in-app confirmation popup — the replacement for the browser's `confirm()`, which
// drops down from the top of the window as "localhost:3000 says …", cannot be styled,
// and cannot show what is about to be affected.
//
// The action runs INSIDE the dialog: it stays open with a spinner while the request is in
// flight and shows the error in place if it fails, instead of closing first and throwing
// an `alert()` afterwards. It closes itself only when the action succeeds.
//
// Styled to match components/userMaster/shared.tsx::ModalShell, so it reads as part of
// the same app as the forms it sits beside.

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { apiError } from "@/components/userMaster/shared";

export default function ConfirmDialog({
  title, children, confirmLabel = "Delete", onConfirm, onClose, danger = true,
}: {
  title: string;
  /** What will happen — say exactly what goes, so nobody has to guess. */
  children: React.ReactNode;
  confirmLabel?: string;
  /** Runs the action. Throw (or reject) to keep the dialog open with the error shown. */
  onConfirm: () => Promise<void>;
  onClose: () => void;
  /** Red confirm button and warning icon. On by default: this is mostly for deletes. */
  danger?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Escape cancels — but not mid-request, when the outcome is not known yet.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const confirm = async () => {
    setBusy(true); setError("");
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setError(apiError(e));
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-[60] p-4"
      onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}
      role="presentation"
    >
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-dialog-title"
        className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 id="confirm-dialog-title" className="text-sm font-bold text-gray-900 flex items-center gap-2">
            {danger && <AlertTriangle className="w-4 h-4 text-red-500" />}
            {title}
          </h2>
          <button onClick={onClose} disabled={busy} className="p-1.5 hover:bg-gray-100 rounded-lg disabled:opacity-40" aria-label="Close">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3 text-xs text-gray-600">
          {children}
          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>

        <div className="flex gap-3 px-6 pb-5">
          <button onClick={onClose} disabled={busy} autoFocus
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            Cancel
          </button>
          <button onClick={confirm} disabled={busy}
            className={`flex-1 flex items-center justify-center gap-1.5 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-60 ${
              danger ? "bg-red-600 hover:bg-red-700" : "bg-[#1e4d8c] hover:bg-[#1a3f7a]"
            }`}>
            {busy && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
