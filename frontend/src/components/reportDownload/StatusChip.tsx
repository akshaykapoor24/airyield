"use client";

// Status of one generated report in the history table. The backend's
// display_status already folds the raw row status and heartbeat age into what the
// user should see (a processing row with no heartbeat for 10 minutes is "stalled"),
// so this only renders it: queue position while waiting, progress while generating,
// and the safe error message behind a click when a build failed.

import { useState } from "react";
import { AlertTriangle, ChevronDown, CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import {
  formatCount, formatServerDay, statusMeta,
  type ExportListItem, type StatusTone,
} from "@/lib/reportDownload";

const TONE_CLASSES: Record<StatusTone, string> = {
  grey: "bg-gray-100 text-gray-600 border-gray-200",
  blue: "bg-blue-50 text-blue-700 border-blue-200",
  amber: "bg-amber-50 text-amber-700 border-amber-200",
  green: "bg-green-50 text-green-700 border-green-200",
  red: "bg-red-50 text-red-700 border-red-200",
};

const CHIP = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold whitespace-nowrap";

export default function StatusChip({ item }: { item: ExportListItem }) {
  const [showError, setShowError] = useState(false);
  const meta = statusMeta(item.display_status);
  const tone = TONE_CLASSES[meta.tone];

  switch (item.display_status) {
    case "waiting": {
      const ahead = item.queue_position;
      return (
        <span className={`${CHIP} ${tone}`} title="Queued. Reports are built one at a time per workspace.">
          <Clock className="w-3 h-3" />
          {meta.label}
          {ahead != null && ` · ${ahead > 0 ? `${formatCount(ahead)} ahead` : "next"}`}
        </span>
      );
    }

    case "generating": {
      const pct = item.estimated_rows > 0
        ? Math.min(100, Math.round((item.processed_rows / item.estimated_rows) * 100))
        : null;
      return (
        <div className="min-w-[150px] space-y-1">
          <span className={`${CHIP} ${tone}`}>
            <Loader2 className="w-3 h-3 animate-spin" />
            {meta.label}{pct != null && ` · ${pct}%`}
          </span>
          {pct != null && (
            <div className="h-1 w-full rounded-full bg-blue-100 overflow-hidden" role="progressbar"
              aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <div className="h-full bg-blue-500 transition-all duration-500" style={{ width: `${pct}%` }} />
            </div>
          )}
          <p className="text-[10px] text-gray-500 leading-tight">
            {formatCount(item.processed_rows)}
            {item.estimated_rows > 0 && ` of ~${formatCount(item.estimated_rows)}`} rows
            {item.stage && <span className="block truncate max-w-[200px]" title={item.stage}>{item.stage}</span>}
          </p>
        </div>
      );
    }

    case "stalled":
      return (
        <div className="space-y-0.5">
          <span className={`${CHIP} ${tone}`}>
            <AlertTriangle className="w-3 h-3" />
            {meta.label}
          </span>
          <p className="text-[10px] text-amber-700/80 leading-tight">No progress for 10 min. Retry to restart it.</p>
        </div>
      );

    case "ready":
      return (
        <div className="space-y-0.5">
          <span className={`${CHIP} ${tone}`}>
            <CheckCircle2 className="w-3 h-3" />
            {meta.label}
          </span>
          {item.expires_at && (
            <p className="text-[10px] text-gray-400 leading-tight">Available until {formatServerDay(item.expires_at)}</p>
          )}
        </div>
      );

    case "failed":
      return (
        <div className="space-y-1 max-w-[260px]">
          <button type="button" onClick={() => setShowError((v) => !v)} aria-expanded={showError}
            title={showError ? "Hide the error" : "Show why it failed"}
            className={`${CHIP} ${tone} cursor-pointer hover:bg-red-100`}>
            <XCircle className="w-3 h-3" />
            {meta.label}
            <ChevronDown className={`w-3 h-3 transition-transform ${showError ? "rotate-180" : ""}`} />
          </button>
          {showError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700 leading-snug">
              {item.error || "The report could not be built."}
              {item.error_code && <span className="block mt-0.5 font-mono text-[10px] text-red-500">{item.error_code}</span>}
            </div>
          )}
        </div>
      );

    default:
      // "expired", and any status a newer backend adds: a plain chip.
      return (
        <span className={`${CHIP} ${tone}`}
          title={item.display_status === "expired" ? "The file was removed after its retention period. Run again to rebuild it." : undefined}>
          {meta.label}
        </span>
      );
  }
}
