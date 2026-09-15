"use client";

// Generated reports: the caller's own report jobs, newest first. The page owns the
// list and its polling (it has to re-arm it after Generate and Retry); this table
// renders it and runs the per-row actions, keeping each action's busy state and
// error next to the row the user clicked.

import { useState, type ReactNode } from "react";
import { AlertCircle, Download, History, RefreshCw, Repeat, RotateCcw, Trash2 } from "lucide-react";
import StatusChip from "@/components/reportDownload/StatusChip";
import {
  BASIS_LABELS, apiErrorMessage, formatBytes, formatCount, formatDay, formatTimestamp,
  getDownloadUrl, resolveApiUrl, sourceLabel, statusMeta,
  type DateBasis, type ExportListItem, type ExportPage,
} from "@/lib/reportDownload";

type Action = "download" | "retry" | "run-again" | "delete";

const ACTION_FAILED: Record<Action, string> = {
  "download": "The file could not be downloaded. Please try again.",
  "retry": "The report could not be retried. Please try again.",
  "run-again": "The report's filters could not be loaded. Please try again.",
  "delete": "The report could not be deleted. Please try again.",
};

const TH = "px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap";
const ICON_BTN = "p-1.5 hover:bg-gray-100 rounded-lg text-gray-500 hover:text-[#1e3a5f] disabled:opacity-40 disabled:cursor-not-allowed";
const MAX_SOURCE_CHIPS = 3;

function SourceChips({ keys }: { keys: string[] }) {
  const shown = keys.slice(0, MAX_SOURCE_CHIPS);
  const hidden = keys.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1 max-w-[220px]" title={keys.map(sourceLabel).join(", ")}>
      {shown.map((k) => (
        <span key={k} className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold bg-slate-100 text-slate-600 whitespace-nowrap">
          {sourceLabel(k)}
        </span>
      ))}
      {hidden > 0 && (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold bg-slate-50 text-slate-400">+{hidden}</span>
      )}
    </div>
  );
}

export default function ReportHistory({
  page, loading, error, offset, pageSize, onPageChange, onRefresh, onRetry, onRunAgain, onDelete,
}: {
  page: ExportPage | null;
  loading: boolean;
  error: string | null;
  offset: number;
  pageSize: number;
  onPageChange: (offset: number) => void;
  onRefresh: () => void;
  onRetry: (item: ExportListItem) => Promise<void>;
  onRunAgain: (item: ExportListItem) => Promise<void>;
  onDelete: (item: ExportListItem) => Promise<void>;
}) {
  const [busy, setBusy] = useState<{ id: number; action: Action } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const run = async (item: ExportListItem, action: Action, fn: () => Promise<void>) => {
    setBusy({ id: item.id, action });
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(apiErrorMessage(e, ACTION_FAILED[action]));
    } finally {
      setBusy(null);
    }
  };

  const download = (item: ExportListItem) => run(item, "download", async () => {
    const { url } = await getDownloadUrl(item.id);
    // A navigation, not fetch + blob: the file can be large and the browser streams
    // it straight to disk. The URL carries a short-lived token or GCS signature.
    window.location.assign(resolveApiUrl(url));
  });

  const remove = (item: ExportListItem) => {
    const running = statusMeta(item.display_status).active;
    const question = running
      ? "Delete this report? It stops being generated, and this cannot be undone."
      : "Delete this report and its file? This cannot be undone.";
    if (!window.confirm(question)) return;
    void run(item, "delete", () => onDelete(item));
  };

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const isBusy = (item: ExportListItem, action: Action) => busy?.id === item.id && busy.action === action;
  const spinnerOr = (item: ExportListItem, action: Action, icon: ReactNode) =>
    isBusy(item, action) ? <RefreshCw className="w-4 h-4 animate-spin" /> : icon;

  return (
    <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
          Generated reports{total > 0 && ` · ${formatCount(total)}`}
        </p>
        <button type="button" onClick={onRefresh} disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 bg-white hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {(error || actionError) && (
        <div className="m-4 flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700" role="alert">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span className="flex-1">
            {actionError ?? error}
            {error && !actionError && (
              <span className="block text-xs text-red-600/80 mt-0.5">Status updates are paused.</span>
            )}
          </span>
          {error && !actionError && (
            <button type="button" onClick={onRefresh} className="text-xs font-semibold underline hover:text-red-900">Try again</button>
          )}
          {actionError && (
            <button type="button" onClick={() => setActionError(null)} className="text-xs font-semibold underline hover:text-red-900">Dismiss</button>
          )}
        </div>
      )}

      {loading && !page ? (
        <div className="flex items-center justify-center py-14">
          <div className="text-center space-y-3">
            <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto" />
            <p className="text-sm text-gray-500">Loading reports…</p>
          </div>
        </div>
      ) : items.length === 0 ? (
        !error && (
          <div className="flex flex-col items-center justify-center py-14 px-5 text-center">
            <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
              <History className="w-7 h-7 text-gray-300" />
            </div>
            <p className="text-sm font-medium text-gray-600">No reports yet</p>
            <p className="text-xs text-gray-400 mt-1">Reports you generate appear here with their progress, ready to download.</p>
          </div>
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px]">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                <th className={TH}>Report</th>
                <th className={TH}>Sources</th>
                <th className={TH}>Requested</th>
                <th className={TH}>Status</th>
                <th className={`${TH} text-right`}>Rows (Combined)</th>
                <th className={`${TH} text-right`}>Size</th>
                <th className={`${TH} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item) => {
                const status = item.display_status;
                const rowBusy = busy?.id === item.id;
                return (
                  <tr key={item.id} className="hover:bg-blue-50/30 transition-colors align-top">
                    <td className="px-4 py-2.5">
                      <p className="text-sm font-medium text-gray-800 truncate max-w-[260px]" title={item.title ?? undefined}>
                        {item.title || `Report #${item.id}`}
                      </p>
                      <p className="text-[11px] text-gray-500 whitespace-nowrap">
                        {formatDay(item.date_from)} – {formatDay(item.date_to)}
                      </p>
                      <p className="text-[10px] text-gray-400">{BASIS_LABELS[item.basis as DateBasis] ?? item.basis}</p>
                    </td>
                    <td className="px-4 py-2.5"><SourceChips keys={item.source_types} /></td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">{formatTimestamp(item.created_at)}</td>
                    <td className="px-4 py-2.5"><StatusChip item={item} /></td>
                    <td className="px-4 py-2.5 text-xs text-gray-700 text-right tabular-nums">
                      {item.combined_rows == null ? "—" : formatCount(item.combined_rows)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 text-right whitespace-nowrap">{formatBytes(item.file_size)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        {status === "ready" && (
                          <button type="button" onClick={() => void download(item)} disabled={rowBusy}
                            title="Download the Excel workbook"
                            className="flex items-center gap-1 px-2.5 py-1.5 mr-1 rounded-lg text-xs font-semibold text-white bg-[#1e3a5f] hover:bg-[#16304f] disabled:opacity-50">
                            {isBusy(item, "download") ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                            Download
                          </button>
                        )}
                        {(status === "failed" || status === "stalled") && (
                          <button type="button" onClick={() => void run(item, "retry", () => onRetry(item))} disabled={rowBusy}
                            title="Retry this report" aria-label="Retry" className={ICON_BTN}>
                            {spinnerOr(item, "retry", <RotateCcw className="w-4 h-4" />)}
                          </button>
                        )}
                        <button type="button" onClick={() => void run(item, "run-again", () => onRunAgain(item))} disabled={rowBusy}
                          title="Run again: load this report's period, sources and ticks into the form" aria-label="Run again"
                          className={ICON_BTN}>
                          {spinnerOr(item, "run-again", <Repeat className="w-4 h-4" />)}
                        </button>
                        <button type="button" onClick={() => remove(item)} disabled={rowBusy}
                          title="Delete this report" aria-label="Delete"
                          className={`${ICON_BTN} hover:text-red-600`}>
                          {spinnerOr(item, "delete", <Trash2 className="w-4 h-4" />)}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {total > pageSize && (
        <div className="px-5 py-2.5 border-t border-gray-100 flex items-center justify-between gap-2 text-xs text-gray-500">
          <span className="tabular-nums">
            {formatCount(offset + 1)}–{formatCount(Math.min(offset + items.length, total))} of {formatCount(total)}
          </span>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => onPageChange(Math.max(0, offset - pageSize))} disabled={offset === 0}
              className="px-2.5 py-1 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40">Previous</button>
            <button type="button" onClick={() => onPageChange(offset + pageSize)} disabled={offset + pageSize >= total}
              className="px-2.5 py-1 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </section>
  );
}
