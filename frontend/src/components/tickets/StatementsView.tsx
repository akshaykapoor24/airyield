"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Upload, RefreshCw, FileSpreadsheet, ChevronRight,
  Building2, Calendar, Hash, AlertCircle, Search, X, FilePlus, SquarePen, Download, Trash2,
} from "lucide-react";
import api from "@/lib/api";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { CUSTOMER_TYPE_BADGE, CUSTOMER_TYPE_LABEL } from "@/lib/customerType";
import { MANUAL_ENTRY_FILE_NAME, type StatementType } from "@/lib/ticketFields";
import { CUSTOMER_STATEMENT_BASE, STATEMENT_ENTRY_BASE } from "@/lib/statementSection";

export type TicketStatement = {
  batch_id:        string;
  statement_name:  string | null;
  statement_type:  StatementType;
  agency:          string;
  valid_from:      string;
  valid_to:        string;
  file_name:       string;
  ticket_count:    number;
  created_by_name: string | null;
  created_at:      string;
  // Who the tickets were sold to. Null on statements filed before customer
  // tagging existed, and on any filed through Internal Statement, which asks
  // for a vendor rather than a customer.
  customer_type:   "agency" | "corporate" | "direct" | null;
};

function formatDate(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const formatDateTime = formatDate;

function TypeBadge({ type }: { type: StatementType }) {
  return type === "AIRLINE"
    ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700 uppercase tracking-wide">Airline</span>
    : <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-700 uppercase tracking-wide">B2B</span>;
}

/** The CUSTOMER type. "Untagged" is not a failure state to hide: those rows
 *  cannot be priced by the customer commission run until someone says who they
 *  were sold to, so saying so is the useful thing. */
function CustomerBadge({ type }: { type: TicketStatement["customer_type"] }) {
  if (!type) {
    return <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold bg-gray-100 text-gray-500 uppercase tracking-wide">Untagged</span>;
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide border ${CUSTOMER_TYPE_BADGE[type]}`}>
      {CUSTOMER_TYPE_LABEL[type]}
    </span>
  );
}

/** Statement-wise view — one row per upload/creation batch.
 *  `showCustomer` swaps the vendor Type badge for the CUSTOMER type, which is
 *  what the Customer-data view of the same rows is actually about. */
/** Customer data → Statement tabs. Agency = B2B, corporate = B2E (Corporate), direct. */
export type StatementCustomerType = "agency" | "corporate" | "direct";
const CUSTOMER_TAB_LABEL: Record<StatementCustomerType, string> = {
  agency: "B2B", corporate: "Corporate", direct: "Direct",
};

export default function StatementsView({
  onLoaded, showCustomer, customerType, apiBase = "/tickets", drillIn = true, entryOverride,
  excludeManual = false, detailBaseOverride, allowDelete = false,
}: {
  onLoaded?: (n: number) => void;
  showCustomer?: boolean;
  /** Customer data → Statement tab: show only this customer type's statements, with the
   *  tab's own Template / Upload Statement actions — the layout Vendors data → Statements
   *  uses. Statements can only be ADDED by upload here; tickets are not punched in by hand. */
  customerType?: StatementCustomerType;
  /** "/internal-tickets" for Internal Statement's own tables. */
  apiBase?: string;
  /** Rows open the statement's tickets. Off where that screen does not exist yet. */
  drillIn?: boolean;
  /** Base for the empty state's Upload / Create links ("/internal-statement"). */
  entryOverride?: string;
  /** Leave out statements made by hand-punching ("Manual Entry") — Internal Statement
   *  lists only UPLOADED statements; its punched tickets live in its All tickets tab. */
  excludeManual?: boolean;
  /** Where a row opens, when not the Customer data / /tickets detail screen. */
  detailBaseOverride?: string;
  /** A delete button per row — the statement and every ticket under it. */
  allowDelete?: boolean;
}) {
  // Keep the drill-in inside whichever section the list is rendered in — both
  // routes render the same detail screen over the same rows.
  const detailBase = detailBaseOverride ?? (showCustomer ? "/customers/statements" : "/tickets");
  // Customer data uploads in its own section (/customers/statements/upload); creating a
  // single ticket stays in the sidebar's Internal Statement module.
  const entryBase = entryOverride ?? (showCustomer ? CUSTOMER_STATEMENT_BASE : "/tickets");
  const router = useRouter();
  const [statements, setStatements] = useState<TicketStatement[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [filterName,   setFilterName]   = useState("");
  const [filterAgency, setFilterAgency] = useState("");
  // "" = no filter. Holds a StatementType in vendor mode, a CustomerType or
  // "untagged" in customer mode.
  const [filterType,   setFilterType]   = useState<string>("");
  const [filterFrom,   setFilterFrom]   = useState("");
  const [filterTo,     setFilterTo]     = useState("");
  const [downloading,  setDownloading]  = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TicketStatement | null>(null);
  const linkRef = useRef<HTMLAnchorElement>(null);

  // The customer statement template — the same ticket template the upload wizard maps
  // automatically, named for the tab it was downloaded from.
  const downloadTemplate = async () => {
    if (!customerType) return;
    setDownloading(true);
    try {
      const resp = await api.get("/tickets/template/download?type=b2b", { responseType: "blob" });
      const url = URL.createObjectURL(resp.data as Blob);
      const a = linkRef.current!;
      a.href = url;
      a.download = `${CUSTOMER_TAB_LABEL[customerType].toLowerCase()}_statement_template.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Failed to download the template.");
    } finally {
      setDownloading(false);
    }
  };

  const fetchStatements = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: all } = await api.get<TicketStatement[]>(`${apiBase}/statements`);
      const data = excludeManual ? all.filter((s) => s.file_name !== MANUAL_ENTRY_FILE_NAME) : all;
      setStatements(data);
      onLoaded?.(data.length);
    } catch {
      setError("Failed to load ticket statements. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatements(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const allAgencies = Array.from(new Set(statements.map(s => s.agency))).sort();

  const filtered = statements.filter(s => {
    if (filterName && !(s.statement_name ?? "").toLowerCase().includes(filterName.toLowerCase())) return false;
    if (filterAgency && s.agency !== filterAgency) return false;
    // In customer mode this select filters the CUSTOMER type; "untagged" is a
    // real, selectable state, since those rows are the ones needing attention.
    // A tab fixes the customer type; the type select is hidden then.
    if (customerType && s.customer_type !== customerType) return false;
    if (filterType && !customerType) {
      if (showCustomer) {
        if (filterType === "untagged" ? s.customer_type != null : s.customer_type !== filterType) return false;
      } else if (s.statement_type !== filterType) return false;
    }
    if (filterFrom && s.valid_to < filterFrom) return false;
    if (filterTo   && s.valid_from > filterTo)   return false;
    return true;
  });

  const hasFilter = filterName || filterAgency || filterType || filterFrom || filterTo;

  return (
    <div className="space-y-5">
      {/* filter bar — refresh lives here so the toolbar is one row, not two */}
      <div className="flex items-center gap-2 flex-wrap">
      <a ref={linkRef} className="hidden" />
      {customerType && (
        <span className="px-3 py-2 rounded-lg border border-gray-200 bg-white text-[11px] text-gray-500 uppercase tracking-wide">
          Uploads <span className="ml-1.5 text-sm font-bold text-gray-900 normal-case">{statements.filter(s => s.customer_type === customerType).length}</span>
        </span>
      )}
      {!loading && !error && statements.length > 0 && (
        <>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input
            type="text" placeholder="Search statement name…"
            value={filterName} onChange={e => setFilterName(e.target.value)}
            className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-52"
          />
        </div>

        {/* Type filter — not on a customer-type tab, which already is one */}
        {!customerType && <select
          value={filterType} onChange={e => setFilterType(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white"
        >
          {showCustomer ? (
            <>
              <option value="">All Customer Types</option>
              <option value="agency">B2B (Agency)</option>
              <option value="corporate">B2E (Corporate)</option>
              <option value="direct">Direct Customer</option>
              <option value="untagged">Untagged</option>
            </>
          ) : (
            <>
              <option value="">All Types</option>
              <option value="B2B">B2B</option>
              <option value="AIRLINE">Airline</option>
            </>
          )}
        </select>}

        {/* Agency filter — derived from loaded data */}
        <select
          value={filterAgency} onChange={e => setFilterAgency(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white"
        >
          <option value="">{showCustomer ? "All Customers" : "All Agencies"}</option>
          {allAgencies.map(a => <option key={a} value={a}>{a}</option>)}
        </select>

        <input type="date" value={filterFrom} onChange={e => setFilterFrom(e.target.value)}
          title="Valid from" className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        <span className="text-xs text-gray-400">–</span>
        <input type="date" value={filterTo} onChange={e => setFilterTo(e.target.value)}
          title="Valid to" className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />

        {hasFilter && (
          <button
            onClick={() => { setFilterName(""); setFilterAgency(""); setFilterType(""); setFilterFrom(""); setFilterTo(""); }}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-400" title="Clear filters"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        </>
      )}
        <button
          onClick={fetchStatements}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
        {customerType && (
          <>
            <button
              onClick={downloadTemplate}
              disabled={downloading}
              className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            >
              <Download className="w-3.5 h-3.5" /> {downloading ? "Downloading…" : "Template"}
            </button>
            <Link
              href={`${entryBase}/upload?customer_type=${customerType}`}
              className="flex items-center gap-1.5 px-3 py-2 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f]"
            >
              <Upload className="w-3.5 h-3.5" /> Upload Statement
            </Link>
          </>
        )}
      </div>

      {/* Statements filed before customer tagging, or through Internal Statement, belong
          to no tab — say so rather than let them vanish. */}
      {customerType && !loading && statements.some(s => s.customer_type == null) && (
        <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          {statements.filter(s => s.customer_type == null).length} statement(s) have no customer type (filed
          before customer tagging, or through Internal Statement), so they appear on no tab. Their tickets
          are still listed under All tickets.
        </p>
      )}

      {/* error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* loading */}
      {loading && (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3">
            <RefreshCw className="w-7 h-7 text-blue-400 animate-spin mx-auto" />
            <p className="text-sm text-gray-500">Loading statements…</p>
          </div>
        </div>
      )}

      {/* empty state */}
      {!loading && !error && (customerType ? filtered.length === 0 && !hasFilter : statements.length === 0) && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <FileSpreadsheet className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">
            {customerType ? `No ${CUSTOMER_TAB_LABEL[customerType]} statements yet` : "No ticket statements yet"}
          </p>
          <p className="text-xs text-gray-400 mt-1 mb-5">
            {customerType ? "Download the template, fill it in and upload it with Upload Statement." : "Upload a supplier statement, or punch tickets in by hand"}
          </p>
          {!customerType && <div className="flex items-center gap-3">
            <Link
              href={`${entryBase}/upload`}
              className="flex items-center gap-2 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#16304f]"
            >
              <Upload className="w-4 h-4" /> Upload Statement
            </Link>
            <Link
              href={`${entryOverride ?? (showCustomer ? STATEMENT_ENTRY_BASE : entryBase)}/create`}
              className="flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50"
            >
              <FilePlus className="w-4 h-4" /> Create Ticket
            </Link>
          </div>}
        </div>
      )}

      {/* statements table */}
      {!loading && !error && (customerType ? filtered.length > 0 || hasFilter : statements.length > 0) && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {/* summary bar */}
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              {filtered.length === statements.length
                ? `${statements.length} Statement${statements.length !== 1 ? "s" : ""}`
                : `${filtered.length} of ${statements.length} Statements`}
            </p>
            <p className="text-xs text-gray-400">Click a row to view tickets</p>
          </div>

          <table className="w-full">
            <thead>
              <tr style={{background:"#1e3a5f"}}>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">{showCustomer ? "Customer Type" : "Type"}</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Statement Name</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><Building2 className="w-3.5 h-3.5" /> {showCustomer ? "Customer" : "Agency"}</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><Calendar className="w-3.5 h-3.5" /> Valid Period</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Source</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><Hash className="w-3.5 h-3.5" /> Tickets</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded By</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-xs text-gray-400">
                    No statements match the current filters.
                  </td>
                </tr>
              ) : filtered.map(stmt => (
                <tr
                  key={stmt.batch_id}
                  onClick={drillIn ? () => router.push(`${detailBase}/${stmt.batch_id}`) : undefined}
                  className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                >
                  {/* Type badge */}
                  <td className="px-4 py-2">
                    {showCustomer
                      ? <CustomerBadge type={stmt.customer_type} />
                      : <TypeBadge type={stmt.statement_type ?? "B2B"} />}
                  </td>

                  {/* Statement Name */}
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                        <FileSpreadsheet className="w-4 h-4 text-blue-500" />
                      </div>
                      <p className="text-sm font-semibold text-gray-800 group-hover:text-[#1e3a5f]">
                        {stmt.statement_name ?? `${stmt.statement_type} · ${stmt.agency}`}
                      </p>
                    </div>
                  </td>

                  {/* Agency */}
                  <td className="px-4 py-2">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 border border-indigo-100 text-xs font-medium text-indigo-700">
                      <Building2 className="w-3 h-3" />
                      {stmt.agency}
                    </span>
                  </td>

                  {/* Valid Period */}
                  <td className="px-4 py-2">
                    <div className="text-xs text-gray-700">
                      <span className="font-medium">{formatDate(stmt.valid_from)}</span>
                      <span className="text-gray-400 mx-1.5">→</span>
                      <span className="font-medium">{formatDate(stmt.valid_to)}</span>
                    </div>
                  </td>

                  {/* Source — manual statements carry no file */}
                  <td className="px-4 py-2">
                    {stmt.file_name === MANUAL_ENTRY_FILE_NAME ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 whitespace-nowrap">
                        <SquarePen className="w-3 h-3" /> Manually punched
                      </span>
                    ) : (
                      <span className="text-xs text-gray-500 truncate max-w-40 block" title={stmt.file_name}>
                        {stmt.file_name}
                      </span>
                    )}
                  </td>

                  {/* Ticket count */}
                  <td className="px-4 py-2">
                    <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-[#1e3a5f]/10 text-[#1e3a5f] text-xs font-semibold">
                      {stmt.ticket_count.toLocaleString()}
                    </span>
                  </td>

                  {/* Uploaded By */}
                  <td className="px-4 py-2 text-xs text-gray-600 font-medium">
                    {stmt.created_by_name || "—"}
                  </td>

                  {/* Created */}
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {formatDateTime(stmt.created_at)}
                  </td>

                  {/* Delete (where the caller allows it) + arrow */}
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {allowDelete && (
                      <button
                        type="button"
                        title="Delete this statement and its tickets"
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget(stmt); }}
                        className="p-1.5 mr-1 rounded-md text-gray-300 hover:text-red-600 hover:bg-red-50 transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                    <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-[#1e3a5f] transition-colors inline" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete statement?"
          confirmLabel={`Delete statement and ${deleteTarget.ticket_count} ticket${deleteTarget.ticket_count !== 1 ? "s" : ""}`}
          onClose={() => setDeleteTarget(null)}
          onConfirm={async () => {
            await api.delete(`${apiBase}/statements/${deleteTarget.batch_id}`);
            setStatements((prev) => {
              const next = prev.filter((s) => s.batch_id !== deleteTarget.batch_id);
              onLoaded?.(next.length);
              return next;
            });
            setDeleteTarget(null);
          }}
        >
          <p>
            <b>{deleteTarget.statement_name || deleteTarget.agency}</b>
            {deleteTarget.file_name !== MANUAL_ENTRY_FILE_NAME && <> ({deleteTarget.file_name})</>} and all{" "}
            <b>{deleteTarget.ticket_count}</b> ticket{deleteTarget.ticket_count !== 1 ? "s" : ""} loaded with it
            will be permanently deleted. This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
