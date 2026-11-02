"use client";

// Internal Statement's review grid for a file of any size (lib/ticketImport.ts). The lines stay
// on the server: a page of them is fetched at a time, a tab or a search is asked of the server,
// and an edit saves that one line — so a lakh-line file reviews as easily as a hundred lines.
//
// A cell is saved when it loses focus. A removed line is kept, under "Removed", and can be put
// back; it is not saved with the statement.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, RefreshCw, RotateCcw, Search, Trash2, X } from "lucide-react";
import type { ReviewColGroup, TicketRow } from "@/lib/ticketFields";
import { importApi, type ImportRow, type ImportSummary, type ImportView } from "@/lib/ticketImport";

const PAGE = 100;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}/;

const TABS: { view: ImportView; label: string; count: (s: ImportSummary) => number; tone: string }[] = [
  { view: "all",        label: "All rows",        count: s => s.kept,                  tone: "text-gray-700" },
  { view: "duplicates", label: "Duplicates",      count: s => s.duplicates.duplicates, tone: "text-amber-700" },
  { view: "dates",      label: "Dates not read",  count: s => s.bad_dates,             tone: "text-orange-700" },
  { view: "long",       label: "Too long",        count: s => s.too_long,              tone: "text-red-700" },
  { view: "edited",     label: "Edited",          count: s => s.edited,                tone: "text-blue-700" },
  { view: "removed",    label: "Removed",         count: s => s.removed,               tone: "text-gray-500" },
];

function apiDetail(e: unknown): string | null {
  const m = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof m === "string" ? m : null;
}

type Cell = string | number | null | undefined;
const text = (v: Cell) => (v == null ? "" : String(v));

export default function ImportReviewGrid({
  apiBase, importId, colGroups, summary, duplicateLabel,
  view, onView, search, onSearch, reloadKey, onChanged, onError,
}: {
  apiBase: string;
  importId: string;
  colGroups: ReviewColGroup[];
  summary: ImportSummary;
  /** Where a duplicate's ticket is already loaded, in words. */
  duplicateLabel: (batchId: string) => string;
  view: ImportView;
  onView: (v: ImportView) => void;
  search: string;
  onSearch: (q: string) => void;
  /** Bumped when the file has been read again: back to the first page. */
  reloadKey: number;
  /** A line changed — the summary above the grid is counted again. */
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const client = useMemo(() => importApi(apiBase), [apiBase]);
  const allCols = useMemo(() => colGroups.flatMap(g => g.cols), [colGroups]);
  const colType = useMemo(() => Object.fromEntries(allCols.map(c => [c.key, c.type])), [allCols]);

  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkKey, setBulkKey] = useState("");
  const [bulkValue, setBulkValue] = useState("");
  const [busy, setBusy] = useState(false);
  // What the server holds for each line on the page — an edit is a cell that differs from it.
  const saved = useRef(new Map<number, TicketRow>());

  // The search box answers as the user stops typing; "Show rows" on a supplier sets it from above.
  const [typed, setTyped] = useState(search);
  useEffect(() => { setTyped(search); }, [search]);
  useEffect(() => {
    if (typed === search) return;
    const t = setTimeout(() => onSearch(typed), 350);
    return () => clearTimeout(t);
  }, [typed, search, onSearch]);

  useEffect(() => { setPage(0); setSelected(new Set()); }, [view, search, reloadKey]);

  const seq = useRef(0);
  const load = useCallback(async () => {
    const n = ++seq.current;
    setLoading(true);
    try {
      const data = await client.rows(importId, { view, q: search, page, size: PAGE });
      if (n !== seq.current) return;
      setRows(data.rows);
      setTotal(data.total);
      saved.current = new Map(data.rows.map(r => [r.row_no, r.data]));
    } catch (e) {
      if (n === seq.current) onError(apiDetail(e) ?? "Could not load the rows.");
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, [client, importId, view, search, page, onError]);
  useEffect(() => { void load(); }, [load, reloadKey]);

  const put = (u: ImportRow) => {
    saved.current.set(u.row_no, u.data);
    setRows(prev => prev.map(r => (r.row_no === u.row_no ? u : r)));
  };
  const drop = (rowNos: number[]) => {
    const gone = new Set(rowNos);
    setRows(prev => prev.filter(r => !gone.has(r.row_no)));
    setTotal(t => Math.max(0, t - rowNos.length));
    setSelected(prev => new Set([...prev].filter(n => !gone.has(n))));
  };

  // ── One cell ───────────────────────────────────────────────────────────────
  const type = (rowNo: number, key: string, value: string) =>
    setRows(prev => prev.map(r => (r.row_no === rowNo ? { ...r, data: { ...r.data, [key]: value } } : r)));
  const commit = async (rowNo: number, key: string) => {
    const row = rows.find(r => r.row_no === rowNo);
    const before = saved.current.get(rowNo);
    if (!row || !before) return;
    const now = text((row.data as Record<string, Cell>)[key]);
    if (now === text((before as Record<string, Cell>)[key])) return;
    const value = now.trim() === "" ? null : colType[key] === "number" ? Number(now) : now;
    if (typeof value === "number" && Number.isNaN(value)) {
      onError(`“${now}” is not a number.`);
      setRows(prev => prev.map(r => (r.row_no === rowNo ? { ...r, data: before } : r)));
      return;
    }
    try {
      put(await client.edit(importId, rowNo, { values: { [key]: value } }));
      onChanged();
    } catch (e) {
      onError(apiDetail(e) ?? "Could not save that change.");
      setRows(prev => prev.map(r => (r.row_no === rowNo ? { ...r, data: before } : r)));
    }
  };

  // ── Lines ──────────────────────────────────────────────────────────────────
  const setExcluded = async (rowNos: number[], excluded: boolean) => {
    if (!rowNos.length) return;
    setBusy(true);
    try {
      if (rowNos.length === 1) await client.edit(importId, rowNos[0], { excluded });
      else await client.bulk(importId, rowNos, { excluded });
      drop(rowNos);
      onChanged();
    } catch (e) {
      onError(apiDetail(e) ?? "Could not change those rows.");
    } finally {
      setBusy(false);
    }
  };
  const applyBulk = async () => {
    if (!bulkKey || bulkValue === "" || !selected.size) return;
    const value = colType[bulkKey] === "number" ? Number(bulkValue) : bulkValue;
    setBusy(true);
    try {
      for (const u of await client.bulk(importId, [...selected], { values: { [bulkKey]: value } })) put(u);
      setBulkValue("");
      onChanged();
    } catch (e) {
      onError(apiDetail(e) ?? "Could not change those rows.");
    } finally {
      setBusy(false);
    }
  };
  // A new line is saved at the end of the file; it is shown at the top of this page to fill in.
  const addRow = async () => {
    setBusy(true);
    try {
      const r = await client.addRow(importId);
      saved.current.set(r.row_no, r.data);
      setRows(prev => [r, ...prev]);
      setTotal(t => t + 1);
      onChanged();
    } catch (e) {
      onError(apiDetail(e) ?? "Could not add a row.");
    } finally {
      setBusy(false);
    }
  };

  const pages = Math.max(1, Math.ceil(total / PAGE));
  const current = Math.min(page, pages - 1);
  const pageNos = rows.map(r => r.row_no);
  const allSelected = pageNos.length > 0 && pageNos.every(n => selected.has(n));
  const someSelected = pageNos.some(n => selected.has(n));
  const removedView = view === "removed";
  const inp = "w-full bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 min-w-[72px]";

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      {/* Tabs, search */}
      <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2 flex-wrap">
        <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide mr-1">Review &amp; Edit</h2>
        {TABS.filter(t => t.view === "all" || t.view === view || t.count(summary) > 0).map(t => (
          <button key={t.view} type="button" onClick={() => onView(t.view)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
              view === t.view ? "bg-[#1e3a5f] text-white border-[#1e3a5f]" : `bg-white border-gray-200 hover:bg-gray-50 ${t.tone}`}`}>
            {t.label} <span className="tabular-nums opacity-80">{t.count(summary).toLocaleString("en-IN")}</span>
          </button>
        ))}
        <div className="relative ml-auto w-full sm:w-72">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input type="text" value={typed} onChange={e => setTyped(e.target.value)}
            placeholder="Search ticket, passenger, supplier, any value…"
            className="w-full pl-8 pr-7 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
          {typed && (
            <button type="button" onClick={() => { setTyped(""); onSearch(""); }} title="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 hover:bg-gray-100 rounded">
              <X className="w-3 h-3 text-gray-500" />
            </button>
          )}
        </div>
      </div>

      {/* The selected lines */}
      {selected.size > 0 && (
        <div className="px-4 py-2 border-b border-gray-100 flex items-center gap-2 flex-wrap bg-blue-50/40">
          <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-[11px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap">
            ● {selected.size} row{selected.size !== 1 ? "s" : ""} selected
          </span>
          {!removedView && (<>
            <select value={bulkKey} onChange={e => { setBulkKey(e.target.value); setBulkValue(""); }}
              className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-700 bg-white">
              <option value="">Column to edit…</option>
              {colGroups.map(g => (
                <optgroup key={g.label} label={g.label}>
                  {g.cols.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
                </optgroup>
              ))}
            </select>
            {bulkKey && (
              <input type={colType[bulkKey] === "date" ? "date" : colType[bulkKey] === "number" ? "number" : "text"}
                value={bulkValue} onChange={e => setBulkValue(e.target.value)} placeholder="Enter value…"
                className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 w-36 bg-white" />
            )}
            <button type="button" onClick={() => void applyBulk()} disabled={busy || !bulkKey || bulkValue === ""}
              className="px-3 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 whitespace-nowrap">
              Apply to {selected.size} row{selected.size !== 1 ? "s" : ""}
            </button>
          </>)}
          <button type="button" onClick={() => void setExcluded([...selected], !removedView)} disabled={busy}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg border whitespace-nowrap disabled:opacity-40 ${
              removedView ? "border-blue-200 text-blue-700 hover:bg-blue-50" : "border-red-200 text-red-600 hover:bg-red-50"}`}>
            {removedView ? "Put back" : "Remove"} {selected.size} row{selected.size !== 1 ? "s" : ""}
          </button>
          <button type="button" onClick={() => setSelected(new Set())}
            className="px-3 py-1.5 border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-50 whitespace-nowrap">
            Deselect all
          </button>
        </div>
      )}

      <div className="overflow-x-auto relative">
        {loading && (
          <div className="absolute inset-0 bg-white/50 flex items-start justify-center pt-10 z-20">
            <RefreshCw className="w-5 h-5 text-blue-500 animate-spin" />
          </div>
        )}
        <table className="w-full min-w-max border-collapse">
          <thead>
            <tr>
              <th className="px-2 py-2 sticky left-0 z-10" style={{ background: "#1e3a5f" }}>
                <input type="checkbox" checked={allSelected}
                  ref={el => { if (el) el.indeterminate = !allSelected && someSelected; }}
                  onChange={() => setSelected(prev => {
                    const next = new Set(prev);
                    pageNos.forEach(n => (allSelected ? next.delete(n) : next.add(n)));
                    return next;
                  })}
                  className="accent-blue-400 cursor-pointer" title={allSelected ? "Deselect this page" : "Select this page"} />
              </th>
              <th className="px-2 py-2 text-[10px] text-white font-bold sticky left-9 z-10 whitespace-nowrap" style={{ background: "#1e3a5f" }}>Row</th>
              <th rowSpan={2} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{ background: "#1e3a5f" }}>Type</th>
              {colGroups.map(g => (
                <th key={g.label} colSpan={g.cols.length} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{ background: g.color }}>
                  {g.label}
                </th>
              ))}
              <th className="px-2 py-2" style={{ background: "#1e3a5f" }} />
            </tr>
            <tr style={{ background: "#2d4f7c" }}>
              <th className="px-2 py-1.5 sticky left-0 z-10" style={{ background: "#2d4f7c" }} />
              <th className="px-2 py-1.5 sticky left-9 z-10" style={{ background: "#2d4f7c" }} />
              {allCols.map(c => (
                <th key={c.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{c.label}</th>
              ))}
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={allCols.length + 4} className="px-4 py-10 text-center text-xs text-gray-400">
                {loading ? "Loading…" : search ? "No rows match the search." : removedView ? "No rows removed." : "No rows here."}
              </td></tr>
            ) : rows.map(row => {
              const isSelected = selected.has(row.row_no);
              const dup = row.duplicate_of;
              const data = row.data as Record<string, Cell>;
              return (
                <tr key={row.row_no} title={dup ? `Duplicate — already in ${duplicateLabel(dup)}. Not saved.` : undefined}
                  className={`border-b border-gray-100 group ${isSelected ? "bg-blue-50" : dup ? "bg-gray-50 text-gray-400 opacity-60" : "hover:bg-blue-50/20"}`}>
                  <td className={`px-2 py-1.5 sticky left-0 ${isSelected ? "bg-blue-50" : "bg-white group-hover:bg-blue-50/20"}`}>
                    <input type="checkbox" checked={isSelected} className="accent-blue-500 cursor-pointer"
                      onChange={() => setSelected(prev => {
                        const next = new Set(prev);
                        if (next.has(row.row_no)) next.delete(row.row_no); else next.add(row.row_no);
                        return next;
                      })} />
                  </td>
                  <td className={`px-2 py-1.5 text-[10px] text-gray-400 sticky left-9 tabular-nums ${isSelected ? "bg-blue-50" : "bg-white group-hover:bg-blue-50/20"}`}>
                    {row.row_no.toLocaleString("en-IN")}{row.edited && <span className="text-blue-500" title="Edited"> •</span>}
                  </td>
                  <td className="px-2 py-1.5 border-l border-gray-100 whitespace-nowrap">
                    {dup ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-200">Duplicate</span>
                      : row.too_long ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 text-red-700 border border-red-200">Too long</span>
                      : row.bad_date ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-orange-50 text-orange-700 border border-orange-200">Check date</span>
                      : <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-500">Normal</span>}
                  </td>
                  {allCols.map(col => {
                    const val = text(data[col.key]);
                    const limit = summary.limits[col.key];
                    const long = !!limit && val.length > limit;
                    const unread = col.type === "date" && val !== "" && !ISO_DAY.test(val);
                    const mark = long ? "ring-1 ring-red-400 bg-red-50" : unread ? "ring-1 ring-orange-300 bg-orange-50" : "";
                    const tip = long ? `${val.length} characters — this field holds ${limit}. Shorten it to save.`
                      : unread ? "Not read as a date in the format chosen — set it, or it saves as written." : undefined;
                    const common = {
                      className: `${inp} ${mark}`, title: tip, disabled: removedView,
                      onBlur: () => void commit(row.row_no, col.key),
                      onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === "Enter") e.currentTarget.blur(); },
                      onChange: (e: React.ChangeEvent<HTMLInputElement>) => type(row.row_no, col.key, e.target.value),
                    };
                    return (
                      <td key={col.key} className="px-1 py-1 border-l border-gray-100">
                        {col.type === "date" && !unread
                          ? <input type="date" value={val} {...common}
                              onClick={e => { try { (e.target as HTMLInputElement).showPicker(); } catch { /* not supported */ } }} />
                          : <input type={col.type === "number" ? "number" : "text"} value={val} placeholder="—" {...common} />}
                      </td>
                    );
                  })}
                  <td className="px-2 py-1.5">
                    <button type="button" onClick={() => void setExcluded([row.row_no], !removedView)} disabled={busy}
                      title={removedView ? "Put this row back" : "Remove this row — it is not saved"}
                      className={`opacity-0 group-hover:opacity-100 p-1 rounded ${removedView ? "hover:bg-blue-50 text-blue-500" : "hover:bg-red-50 text-red-400"}`}>
                      {removedView ? <RotateCcw className="w-3.5 h-3.5" /> : <Trash2 className="w-3.5 h-3.5" />}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="px-4 py-2.5 border-t border-gray-100 flex items-center gap-3 flex-wrap">
        {!removedView && (
          <button type="button" onClick={() => void addRow()} disabled={busy}
            className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline disabled:opacity-50">
            <Plus className="w-3.5 h-3.5" /> Add row manually
          </button>
        )}
        <span className="text-[10px] text-gray-400">A change is saved when you leave the cell.</span>
        {total > 0 && (
          <div className="ml-auto flex items-center gap-2 text-[11px] text-gray-500">
            <span>
              Rows {(current * PAGE + 1).toLocaleString("en-IN")}–{Math.min((current + 1) * PAGE, total).toLocaleString("en-IN")}
              {" "}of {total.toLocaleString("en-IN")}
            </span>
            {pages > 1 && (<>
              <button type="button" onClick={() => setPage(0)} disabled={current === 0}
                className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">«</button>
              <button type="button" onClick={() => setPage(current - 1)} disabled={current === 0}
                className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">‹ Prev</button>
              <span>Page {current + 1} of {pages.toLocaleString("en-IN")}</span>
              <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pages - 1}
                className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">Next ›</button>
              <button type="button" onClick={() => setPage(pages - 1)} disabled={current >= pages - 1}
                className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">»</button>
            </>)}
          </div>
        )}
      </div>
    </div>
  );
}
