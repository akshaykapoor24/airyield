"use client";

import { useRef, useState } from "react";
import { X, FileText, FileSpreadsheet, CheckCircle2, UploadCloud } from "lucide-react";
import toast from "react-hot-toast";

/**
 * One drag-and-drop slot for one file.
 *
 * Extracted from BspUploadWizard, which needed two of them (a Summary PDF and a
 * Detailed PDF) and is still the only reason a component like this exists rather than
 * inline markup. The LCC wizard now needs two as well — an airline that splits its
 * statement into an account file and a passenger file — so the markup lives here once
 * instead of being copied a third time.
 *
 * `accept` is what makes it reusable across the two: the BSP wizard takes PDFs, the
 * LCC wizard spreadsheets. Extensions AND MIME types are both matched, because
 * Windows reports a .xls as `application/octet-stream` and a MIME-only check rejects
 * a perfectly good file.
 */
export type DropzoneAccept = "pdf" | "spreadsheet";

const ACCEPT: Record<DropzoneAccept, { attr: string; exts: RegExp; hint: string }> = {
  pdf: { attr: ".pdf,application/pdf", exts: /\.pdf$/i, hint: "PDF only" },
  spreadsheet: {
    attr: ".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv",
    exts: /\.(xlsx|xls|csv)$/i,
    hint: ".xlsx, .xls, .csv",
  },
};

export default function Dropzone({
  file, onPick, label, accept = "spreadsheet", note, compact = false,
}: {
  file: File | null;
  onPick: (f: File | null) => void;
  label: string;
  accept?: DropzoneAccept;
  /** One line under the label saying what this slot is for. */
  note?: string;
  compact?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const cfg = ACCEPT[accept];

  const pick = (f: File | null) => {
    if (f && !cfg.exts.test(f.name)) {
      toast.error(`Choose a ${cfg.hint} file.`);
      return;
    }
    onPick(f);
  };

  const Icon = accept === "pdf" ? FileText : FileSpreadsheet;

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0] ?? null); }}
      onClick={() => !file && inputRef.current?.click()}
      className={`rounded-xl border-2 border-dashed text-center transition-colors ${compact ? "p-4" : "p-6"} ${
        dragging
          ? "border-blue-500 bg-blue-50"
          : file
            ? "border-emerald-200 bg-emerald-50/40"
            : "border-slate-200 bg-slate-50/60 hover:border-slate-300 cursor-pointer"
      }`}
    >
      {file ? (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-white p-3 shadow-sm">
          <div className="w-9 h-9 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
            <Icon className="w-5 h-5 text-emerald-600" />
          </div>
          <div className="min-w-0 flex-1 text-left">
            <p className="text-xs font-semibold text-slate-800 truncate" title={file.name}>{file.name}</p>
            <p className="text-[11px] text-slate-500">{(file.size / 1024).toFixed(0)} KB</p>
          </div>
          <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
          <button
            onClick={(e) => { e.stopPropagation(); onPick(null); }}
            className="p-1 rounded text-slate-400 hover:text-red-500 shrink-0"
            aria-label="Remove file"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <>
          <div className={`rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-2 ${compact ? "w-9 h-9" : "w-11 h-11"}`}>
            <UploadCloud className={compact ? "w-5 h-5 text-blue-600" : "w-6 h-6 text-blue-600"} />
          </div>
          <p className="text-sm font-medium text-slate-700">{label}</p>
          {note && <p className="text-[11px] text-slate-500 mt-0.5">{note}</p>}
          <p className="text-xs text-slate-400 mt-0.5">Drag &amp; drop or click to browse · {cfg.hint}</p>
        </>
      )}
      <input
        ref={inputRef} type="file" accept={cfg.attr} className="hidden"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}
