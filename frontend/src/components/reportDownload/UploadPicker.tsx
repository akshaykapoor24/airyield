"use client";

// Step 2 of Report download: the uploads that matched the filters, grouped by
// source type, each with a tick. The server decides what is ticked by default and
// what cannot be picked at all (a BSP statement or LCC batch that has not finished
// processing); this table only lets the user override the defaults and explains
// each upload with chips: a likely re-upload, rows whose date could not be read,
// counts that timed out.

import { useMemo } from "react";
import { FileSpreadsheet, FileText, FolderOpen } from "lucide-react";
import {
  formatCount, formatDay, formatServerDay, sortSourceKeys, uploadKey,
  type UploadItem,
} from "@/lib/reportDownload";
import { TriStateCheckbox, checkState } from "@/components/reportDownload/ReportFilters";

const CHIP = "inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium leading-tight";
const GREY_CHIP = `${CHIP} border-gray-200 bg-gray-50 text-gray-500`;
const TH = "px-3 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap";

const COUNTS_UNAVAILABLE = "Row counts unavailable";

/** Why an upload cannot be picked, in the words of its batch status. */
function blockedLabel(status: string | null): string {
  if (status === "failed") return "Processing failed";
  if (status === "staged") return "Not confirmed";
  return "Still processing";
}

function FileIcon({ name }: { name: string | null }) {
  return (name ?? "").toLowerCase().endsWith(".pdf")
    ? <FileText className="w-4 h-4 text-red-400 shrink-0" />
    : <FileSpreadsheet className="w-4 h-4 text-green-500 shrink-0" />;
}

export default function UploadPicker({
  uploads, selected, onChange,
}: {
  uploads: UploadItem[];
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
}) {
  const groups = useMemo(() => {
    const byType = new Map<string, UploadItem[]>();
    for (const u of uploads) {
      const list = byType.get(u.source_type);
      if (list) list.push(u); else byType.set(u.source_type, [u]);
    }
    return sortSourceKeys(byType.keys()).map((type) => {
      const items = byType.get(type) ?? [];
      return {
        type,
        label: items[0]?.label ?? type,
        category: items[0]?.category ?? "",
        items,
        pickable: items.filter((u) => u.selectable).map((u) => uploadKey(u.source_type, u.upload_id)),
      };
    });
  }, [uploads]);

  // The duplicate chip names the newer upload by file and date; it is usually in
  // the same list, so look its date up there.
  const byKey = useMemo(
    () => new Map(uploads.map((u) => [uploadKey(u.source_type, u.upload_id), u] as const)),
    [uploads],
  );

  const allPickable = useMemo(() => groups.flatMap((g) => g.pickable), [groups]);
  const tickedCount = allPickable.filter((k) => selected.has(k)).length;

  const setKeys = (keys: readonly string[], on: boolean) => {
    const next = new Set(selected);
    for (const k of keys) {
      if (on) next.add(k); else next.delete(k);
    }
    onChange(next);
  };

  if (uploads.length === 0) {
    return (
      <section className="bg-white rounded-xl border border-gray-200 flex flex-col items-center justify-center py-14 px-5 text-center">
        <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
          <FolderOpen className="w-7 h-7 text-gray-300" />
        </div>
        <p className="text-sm font-medium text-gray-600">No uploads match</p>
        <p className="text-xs text-gray-400 mt-1 max-w-md">
          Try a wider period, the Upload date basis, or more source types.
        </p>
      </section>
    );
  }

  return (
    <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
          {formatCount(uploads.length)} matching {uploads.length === 1 ? "upload" : "uploads"} · {formatCount(tickedCount)} ticked
        </p>
        <div className="flex items-center gap-3 text-[11px] font-semibold">
          <button type="button" onClick={() => setKeys(allPickable, true)} disabled={tickedCount === allPickable.length}
            className="text-[#1e3a5f] hover:underline disabled:text-gray-300 disabled:no-underline">Tick all</button>
          <button type="button" onClick={() => setKeys(allPickable, false)} disabled={tickedCount === 0}
            className="text-gray-500 hover:underline disabled:text-gray-300 disabled:no-underline">Untick all</button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px]">
          <thead>
            <tr style={{ background: "#1e3a5f" }}>
              <th className={`${TH} w-8`}><span className="sr-only">Include</span></th>
              <th className={TH}>File</th>
              <th className={TH}>Reference</th>
              <th className={TH}>Uploaded</th>
              <th className={`${TH} text-right`}>Rows in period / total</th>
              <th className={TH}>Dates</th>
              <th className={TH}>Notes</th>
            </tr>
          </thead>
          {groups.map((g) => {
            const groupTicked = g.pickable.filter((k) => selected.has(k)).length;
            return (
              <tbody key={g.type} className="divide-y divide-gray-100 border-b border-gray-200 last:border-b-0">
                <tr className="bg-slate-50">
                  <td className="px-3 py-2">
                    <TriStateCheckbox state={checkState(g.pickable, selected)} disabled={g.pickable.length === 0}
                      label={`Tick every ${g.label} upload`} onChange={(on) => setKeys(g.pickable, on)} />
                  </td>
                  <td colSpan={6} className="px-3 py-2">
                    <span className="text-xs font-semibold text-gray-800">{g.label}</span>
                    {g.category && <span className="ml-2 text-[10px] uppercase tracking-wide text-gray-400">{g.category}</span>}
                    <span className="ml-3 text-[11px] text-gray-500">
                      {formatCount(groupTicked)} of {formatCount(g.items.length)} {g.items.length === 1 ? "file" : "files"}
                    </span>
                  </td>
                </tr>
                {g.items.map((u) => {
                  const key = uploadKey(u.source_type, u.upload_id);
                  const checked = u.selectable && selected.has(key);
                  const countsUnavailable = u.rows_in_period == null && u.rows_undated == null;
                  const dup = u.possible_duplicate_of;
                  const dupDate = dup ? byKey.get(uploadKey(u.source_type, dup.upload_id))?.uploaded_at ?? null : null;
                  // The server words the timeout as a note too; show it once.
                  const notes = u.notes.filter((n) => !(countsUnavailable && n.trim().toLowerCase() === COUNTS_UNAVAILABLE.toLowerCase()));
                  return (
                    <tr key={key} className={`transition-colors ${
                      !u.selectable ? "opacity-60" : checked ? "bg-blue-50/40" : "hover:bg-blue-50/30"
                    }`}>
                      <td className="px-3 py-2 align-top">
                        <input type="checkbox" checked={checked} disabled={!u.selectable}
                          onChange={(e) => setKeys([key], e.target.checked)}
                          aria-label={`Include ${u.file_name ?? u.upload_id}`}
                          className="mt-0.5 w-3.5 h-3.5 accent-[#1e3a5f] cursor-pointer disabled:cursor-not-allowed" />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <div className="flex items-center gap-2 min-w-0">
                          <FileIcon name={u.file_name} />
                          <span className="text-xs font-medium text-gray-800 truncate max-w-[240px]" title={u.file_name ?? u.upload_id}>
                            {u.file_name || "Untitled upload"}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2 align-top text-xs text-gray-600 truncate max-w-[160px]" title={u.reference ?? undefined}>
                        {u.reference || "—"}
                      </td>
                      <td className="px-3 py-2 align-top text-xs text-gray-500 whitespace-nowrap">{formatServerDay(u.uploaded_at)}</td>
                      <td className="px-3 py-2 align-top text-xs text-gray-700 text-right tabular-nums whitespace-nowrap">
                        {u.rows_in_period == null ? "—" : formatCount(u.rows_in_period)}
                        <span className="text-gray-400"> / {formatCount(u.total_rows)}</span>
                      </td>
                      <td className="px-3 py-2 align-top text-xs text-gray-500 whitespace-nowrap">
                        {!u.date_min && !u.date_max ? "—"
                          : u.date_min === u.date_max ? formatDay(u.date_min)
                          : `${formatDay(u.date_min)} – ${formatDay(u.date_max)}`}
                      </td>
                      <td className="px-3 py-2 align-top">
                        <div className="flex flex-wrap gap-1 max-w-[320px]">
                          {!u.selectable && (
                            <span className={`${CHIP} border-red-200 bg-red-50 text-red-600`}
                              title="Only fully processed uploads can go into a report. Try again once it finishes.">
                              {blockedLabel(u.status)}
                            </span>
                          )}
                          {dup && (
                            <span className={`${CHIP} border-amber-200 bg-amber-50 text-amber-700`}
                              title="Same file name, or the same row count and date range, as a newer upload. If both are included, rows found in both count once, from the newer upload.">
                              Possible duplicate of {dup.file_name || "a newer upload"}{dupDate && ` (${formatServerDay(dupDate)})`}
                            </span>
                          )}
                          {(u.rows_undated ?? 0) > 0 && (
                            <span className={GREY_CHIP}
                              title="Included and flagged DATE_UNREADABLE unless you exclude undated rows.">
                              {formatCount(u.rows_undated ?? 0)} {u.rows_undated === 1 ? "row" : "rows"} without a readable date
                            </span>
                          )}
                          {countsUnavailable && (
                            <span className={GREY_CHIP} title="Counting this type took too long. The whole upload is estimated instead.">
                              {COUNTS_UNAVAILABLE}
                            </span>
                          )}
                          {notes.map((n, i) => <span key={`${i}:${n}`} className={GREY_CHIP}>{n}</span>)}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            );
          })}
        </table>
      </div>
    </section>
  );
}
