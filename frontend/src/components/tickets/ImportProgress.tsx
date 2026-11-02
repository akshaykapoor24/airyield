"use client";

// Internal Statement's upload: the worker reading the file or saving the statement
// (lib/ticketImport.ts). The page polls the job and swaps this for the review, or the done
// screen, when the worker is through.

import { ArrowLeft, RefreshCw } from "lucide-react";
import { importPhaseText, importProgress, type ImportJob } from "@/lib/ticketImport";

export default function ImportProgress({ job, title, note, onBack, backLabel = "Back" }: {
  job: ImportJob;
  title: string;
  /** What happens if the user leaves the page. */
  note?: string;
  onBack?: () => void;
  backLabel?: string;
}) {
  const pct = importProgress(job);
  return (
    <div className="max-w-xl mx-auto py-12">
      <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-3">
          <RefreshCw className="w-5 h-5 text-blue-500 animate-spin shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-800">{title}</p>
            <p className="text-xs text-gray-500 truncate" title={job.file_name}>{job.file_name}</p>
          </div>
        </div>
        <div className="h-2 w-full bg-blue-100 rounded-full overflow-hidden">
          {pct == null
            ? <div className="h-full w-full bg-blue-400/70 animate-pulse" />
            : <div className="h-full bg-blue-500 transition-all duration-500" style={{ width: `${pct}%` }} />}
        </div>
        <p className="text-xs text-gray-600 flex items-center justify-between gap-3">
          <span>{importPhaseText(job)}</span>
          {pct != null && <span className="tabular-nums text-gray-400">{pct}%</span>}
        </p>
        {job.phase === "queued" && job.queued_for > 20 && (
          <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Still waiting for the background worker to pick this up. If it doesn&apos;t start, the import
            worker isn&apos;t running — it consumes the Celery queue <code>imports</code>.
          </p>
        )}
        {note && <p className="text-[11px] text-gray-400">{note}</p>}
        {onBack && (
          <button type="button" onClick={onBack}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            <ArrowLeft className="w-3.5 h-3.5" /> {backLabel}
          </button>
        )}
      </div>
    </div>
  );
}
