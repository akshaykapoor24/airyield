"use client";

import { useState } from "react";
import { FileText, Search, FileSpreadsheet, Loader2 } from "lucide-react";
import api from "@/lib/api";

type Column = { header: string; field: string };
type Row = Record<string, string | number | null> & { id: number };
type Group = { source: string; label: string; columns: Column[]; rows: Row[]; count: number };
type LookupResponse = { query: string[]; airline_type: string; total: number; groups: Group[] };

const AIRLINE_TYPES: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "bsp", label: "BSP" },
  { value: "lcc", label: "LCC" },
  { value: "third-party", label: "Third Party" },
];

function cellText(v: string | number | null): string {
  if (v === null || v === undefined || v === "") return "";
  return String(v);
}

export default function TicketDetailsPage() {
  const [document, setDocument] = useState("");
  const [airlineType, setAirlineType] = useState("all");
  const [data, setData] = useState<LookupResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const search = async () => {
    if (!document.trim()) {
      setError("Enter at least one document or ticket number.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<LookupResponse>("/ticket-details/lookup", {
        params: { document, airline_type: airlineType },
      });
      setData(res.data);
      setSearched(true);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Lookup failed.");
    } finally {
      setLoading(false);
    }
  };

  const exportXlsx = async () => {
    if (!document.trim()) {
      setError("Enter at least one document or ticket number.");
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const res = await api.get("/ticket-details/export", {
        params: { document, airline_type: airlineType },
        responseType: "blob",
      });
      const href = window.URL.createObjectURL(res.data as Blob);
      const a = window.document.createElement("a");
      a.href = href;
      a.download = "ticket-details.xlsx";
      window.document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(href);
    } catch {
      setError("Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    // Enter (without Shift) triggers Search; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      search();
    }
  };

  const groups = data?.groups ?? [];
  const queryLower = (data?.query ?? []).map((q) => q.toLowerCase());

  // The field whose value equals what the user searched — used as each card's headline.
  const findMatch = (r: Row, cols: Column[]): { header: string; field: string; value: string } | null => {
    for (const c of cols) {
      const txt = cellText(r[c.field]);
      if (txt && queryLower.includes(txt.toLowerCase())) return { header: c.header, field: c.field, value: txt };
    }
    return null;
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="mt-0.5 w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
          <FileText className="w-5 h-5 text-[#1e3a5f]" />
        </div>
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Vendors data</p>
          <h1 className="text-xl font-bold text-gray-900">Ticket Details</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Look up a ticket across BSP, LCC and Third Party statements by ticket / document number or PNR.
          </p>
        </div>
      </div>

      {/* Filter card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
        <div>
          <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
            Ticket / Document Number or PNR <span className="text-red-400">*</span>
          </label>
          <textarea
            value={document}
            onChange={(e) => setDocument(e.target.value)}
            onKeyDown={onKeyDown}
            rows={3}
            placeholder="e.g. 4846715082 or 098-4846715082 or a PNR like ZE1JWQ"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50 resize-y"
          />
          <p className="text-[11px] text-gray-400 mt-1 italic">
            Use | (pipe) or a new line to look up more than one. The airline prefix, spaces and
            hyphens are ignored, so 098-4846715082 and 4846715082 find the same ticket.
          </p>
          {/* What each store can be found BY differs, and the difference is not
              guessable: the LCC Detailed standard template has no ticket-number
              column at all, so a ticket number can never match those rows. */}
          <p className="text-[11px] text-gray-400 mt-1">
            <span className="font-semibold text-gray-500">BSP</span> — ticket / document number,
            including conjunction documents, SPDR and RTDN.{" "}
            <span className="font-semibold text-gray-500">LCC Detailed</span> — PNR only.{" "}
            <span className="font-semibold text-gray-500">Flown / CTA-BTA / Third Party</span> —
            ticket number or PNR.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Airline Type</label>
            <select
              value={airlineType}
              onChange={(e) => setAirlineType(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50 min-w-40"
            >
              {AIRLINE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          <button
            onClick={search}
            disabled={loading || !document.trim()}
            className="inline-flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />} Search
          </button>

          <button
            onClick={exportXlsx}
            disabled={exporting || !document.trim()}
            className="inline-flex items-center gap-1.5 border border-emerald-200 text-emerald-700 hover:bg-emerald-50 rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4 text-emerald-600" />} Export
          </button>

          {data && (
            <span className="ml-auto text-[11px] text-gray-400 pb-2">
              {data.total.toLocaleString("en-IN")} match{data.total === 1 ? "" : "es"} across {groups.length} source{groups.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {error && <div className="px-3 py-2 text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg">{error}</div>}
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-20 bg-white rounded-xl border border-gray-100">
          <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      ) : !searched ? (
        <div className="flex flex-col items-center justify-center py-20 bg-white rounded-xl border border-gray-100 text-center">
          <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
            <Search className="w-7 h-7 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">Enter a document / ticket number and Search</p>
          <p className="text-xs text-gray-400 mt-1">Matching tickets from BSP, LCC and Third Party will appear here.</p>
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 bg-white rounded-xl border border-gray-100 text-center">
          <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
            <FileText className="w-7 h-7 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">No tickets found</p>
          <p className="text-xs text-gray-400 mt-1">
            Nothing matched {data?.query.map((q) => `"${q}"`).join(", ")} in {airlineType === "all" ? "any source" : airlineType.toUpperCase()}.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <div key={g.source} className="space-y-3">
              {/* Source heading */}
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-gray-800">{g.label}</h2>
                <span className="bg-[#1e3a5f]/10 text-[#1e3a5f] text-[10px] font-bold px-2 py-0.5 rounded-full">
                  {g.count} ticket{g.count === 1 ? "" : "s"}
                </span>
              </div>

              {/* One detail card per matched ticket */}
              {g.rows.map((r) => {
                const matched = findMatch(r, g.columns);
                const fields = g.columns.filter(
                  (c) => cellText(r[c.field]) !== "" && (!matched || c.field !== matched.field),
                );
                return (
                  <div key={r.id} className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                    {/* Card header: matched identifier + source pill */}
                    <div className="px-5 py-4 bg-gradient-to-r from-[#1e3a5f] to-[#2c4c74] flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[10px] uppercase tracking-widest text-white/60">{matched?.header ?? "Ticket"}</p>
                        <p className="text-xl font-bold text-white truncate">{matched?.value ?? g.label}</p>
                      </div>
                      <span className="shrink-0 inline-flex items-center gap-1 bg-white/15 text-white text-[10px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap">
                        {g.label}
                      </span>
                    </div>

                    {/* Card body: label/value grid of all populated fields */}
                    <div className="px-5 py-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-6 gap-y-4">
                      {fields.map((c) => {
                        const txt = cellText(r[c.field]);
                        return (
                          <div key={c.field} className="min-w-0">
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 truncate" title={c.header}>
                              {c.header}
                            </p>
                            <p className="text-xs text-gray-800 mt-0.5 break-words" title={txt}>{txt}</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
