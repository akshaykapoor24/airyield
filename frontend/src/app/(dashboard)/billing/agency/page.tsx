"use client";

// Invoicing → Agency Invoicing. A picker, the twin of Customer and Corporate Invoicing
// (components/party/PartyDirectory.tsx in billing mode): every agency onboarded in
// User master → Agency Master, with how many of its tickets are waiting to be billed.
// Click one to open its workspace at /billing/agency/{id} — Sold Tickets and Billing
// Info. Adding or editing agencies lives in Agency Master, not here.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Building2, RefreshCw, Search, X } from "lucide-react";
import api from "@/lib/api";
import Pagination from "@/components/ui/Pagination";

const PAGE_SIZES = [50, 100, 200];    // the list endpoint allows up to 1000
const AGENCY_MASTER_HREF = "/user-master/agency-master";

const SELECT_CLS =
  "px-2 py-1.5 border border-gray-200 rounded-lg text-xs bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40";

type TicketState = "any" | "unbilled" | "has" | "none";
const DEFAULT_TICKET_STATE: TicketState = "unbilled";

/** One row of GET /agency-billings/ — an Agency Master row and its ticket counts. */
type AgencyListItem = {
  id: number;
  name: string;
  branch_code: string;
  branch_name: string | null;
  city: string | null;
  state: string | null;
  channels: string;             // GDS | LCC | BOTH
  gst_number: string | null;
  pan_number: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  customer_code: string | null;
  account_code: string | null;
  is_active: boolean;
  ticket_count: number;
  unbilled_ticket_count: number;
};

const COLUMNS = ["AGENCY", "BRANCH", "CHANNELS", "CONTACT", "GST / PAN", "TICKETS"];
const COLUMN_HINTS: Record<string, string> = {
  TICKETS: "Unbilled / total tickets tagged to this agency — the same tickets its Sold Tickets tab shows.",
};

const CELL = "px-3 py-2.5 align-middle";
const SUBLINE = "text-[10px] text-gray-400 mt-0.5";
const DASH = <span className="text-[11px] text-gray-300">—</span>;

function ChannelPills({ channels }: { channels: string }) {
  return (
    <span className="inline-flex gap-1">
      {(channels === "BOTH" ? ["GDS", "LCC"] : [channels]).map((c) => (
        <span key={c} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
          c === "GDS" ? "bg-sky-50 text-sky-700 border-sky-200" : "bg-violet-50 text-violet-700 border-violet-200"
        }`}>{c}</span>
      ))}
    </span>
  );
}

export default function AgencyBillingPage() {
  const router = useRouter();
  const [agencies, setAgencies] = useState<AgencyListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  // Opens on the agencies with something left to bill — that is the work, as on Customer
  // and Corporate Invoicing. A list that hides rows the moment it opens is how someone
  // concludes an agency has vanished, so the count says "matching" and the empty state
  // names the filter and offers everyone back.
  const [ticketState, setTicketState] = useState<TicketState>(DEFAULT_TICKET_STATE);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Monotonic, so a slow response for an older search cannot paint over a newer one.
  const reqSeq = useRef(0);

  const fetchAgencies = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AgencyListItem[]>("/agency-billings/", {
        params: {
          skip: (page - 1) * pageSize,
          limit: pageSize,
          ...(debounced.trim() ? { search: debounced.trim() } : {}),
          ...(ticketState !== "any" ? { ticket_state: ticketState } : {}),
        },
      });
      if (seq !== reqSeq.current) return;
      setAgencies(res.data);
      const raw = Number(res.headers?.["x-total-count"]);
      setTotal(Number.isFinite(raw) && raw >= 0 ? raw : (page - 1) * pageSize + res.data.length);
    } catch {
      if (seq === reqSeq.current) setError("Failed to load agencies.");
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [page, pageSize, debounced, ticketState]);

  useEffect(() => {
    fetchAgencies();
  }, [fetchAgencies]);

  // Two questions, because the default itself narrows the list. `filtersActive`: is
  // anyone being hidden? — it words the empty state. `filtersChanged`: has the user moved
  // off the default? — only then is there anything for Clear to undo.
  const filtersActive = !!debounced.trim() || ticketState !== "any";
  const filtersChanged = !!debounced.trim() || ticketState !== DEFAULT_TICKET_STATE;
  const clearFilters = () => {
    setSearch(""); setDebounced(""); setTicketState(DEFAULT_TICKET_STATE); setPage(1);
  };
  /** Nothing hidden at all — the empty state's way out, which a reset to the default is not. */
  const showEveryone = () => {
    setSearch(""); setDebounced(""); setTicketState("any"); setPage(1);
  };
  const colCount = COLUMNS.length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Invoicing</p>
          <h1 className="text-xl font-bold text-gray-900">Agency Invoicing</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Pick an agency to bill. Add or edit agencies in Agency Master.
          </p>
        </div>

        <div className="flex gap-2">
          <Link
            href={AGENCY_MASTER_HREF}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
          >
            Agency Master <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <button
            onClick={fetchAgencies}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Search by name, branch, code, GST, email or phone…"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-gray-50"
            />
          </div>

          <select
            value={ticketState}
            onChange={(e) => { setTicketState(e.target.value as TicketState); setPage(1); }}
            className={SELECT_CLS}
            title="Find the agencies that have tickets waiting to be billed"
          >
            <option value="any">All tickets</option>
            <option value="unbilled">Has unbilled</option>
            <option value="has">Has tickets</option>
            <option value="none">No tickets</option>
          </select>

          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            className={SELECT_CLS}
            title="How many to show per page"
          >
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>

          {filtersChanged && (
            <button
              onClick={clearFilters}
              className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-700"
            >
              <X className="w-3 h-3" /> Clear
            </button>
          )}
        </div>

        {error && <div className="px-4 py-3 text-xs text-red-500 bg-red-50 border-b border-red-100">{error}</div>}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {COLUMNS.map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                    title={COLUMN_HINTS[h]}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            {/* Dim rather than blank, so typing in the search box does not strobe. */}
            <tbody className={loading && agencies.length > 0 ? "opacity-50 transition-opacity" : ""}>
              {loading && agencies.length === 0 ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading agencies…
                  </td>
                </tr>
              ) : agencies.length === 0 && filtersActive ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center justify-center text-center">
                      <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                        <Search className="w-7 h-7 text-gray-300" />
                      </div>
                      <p className="text-sm font-medium text-gray-600">
                        {!filtersChanged ? "Nothing left to bill" : "Nothing matches"}
                      </p>
                      <p className="text-xs text-gray-400 mt-1 mb-4">
                        {!filtersChanged
                          ? "No agencies have unbilled tickets right now."
                          : "No agencies match the current search and filters."}
                      </p>
                      <button onClick={showEveryone} className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold px-3.5 py-2 rounded-lg hover:bg-gray-50">
                        <X className="w-3.5 h-3.5" /> Show all agencies
                      </button>
                    </div>
                  </td>
                </tr>
              ) : agencies.length === 0 ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center justify-center text-center">
                      <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                        <Building2 className="w-7 h-7 text-gray-300" />
                      </div>
                      <p className="text-sm font-medium text-gray-600">No agencies yet</p>
                      <p className="text-xs text-gray-400 mt-1 mb-4">Agencies are onboarded in Agency Master.</p>
                      <Link href={AGENCY_MASTER_HREF} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                        Go to Agency Master <ArrowRight className="w-3.5 h-3.5" />
                      </Link>
                    </div>
                  </td>
                </tr>
              ) : (
                agencies.map((a, idx) => (
                  <tr
                    key={a.id}
                    onClick={() => router.push(`/billing/agency/${a.id}`)}
                    className={`border-b border-gray-50 hover:bg-blue-50/40 transition-colors cursor-pointer ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}
                  >
                    <td className={CELL}>
                      <div className="flex items-center gap-1.5">
                        <p className="text-[11px] font-semibold text-gray-800">{a.name}</p>
                        {!a.is_active && (
                          <span className="text-[9px] font-semibold text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">Inactive</span>
                        )}
                      </div>
                      {(a.customer_code || a.account_code) && (
                        <p className={`${SUBLINE} font-mono`}>
                          {[a.customer_code, a.account_code && `A/c ${a.account_code}`].filter(Boolean).join(" · ")}
                        </p>
                      )}
                    </td>
                    <td className={`${CELL} text-[11px] text-gray-600 whitespace-nowrap`}>
                      <p>{a.branch_name || a.city || "—"}</p>
                      <p className={SUBLINE}>{a.branch_code}</p>
                    </td>
                    <td className={CELL}><ChannelPills channels={a.channels} /></td>
                    <td className={`${CELL} text-[11px] text-gray-600`}>
                      {a.contact_email || a.contact_phone ? (
                        <>
                          <p className="truncate max-w-56">{a.contact_email || a.contact_phone}</p>
                          {a.contact_email && a.contact_phone && <p className={SUBLINE}>{a.contact_phone}</p>}
                        </>
                      ) : DASH}
                    </td>
                    <td className={`${CELL} text-[11px] text-gray-600 font-mono`}>
                      {a.gst_number || a.pan_number ? (
                        <>
                          <p>{a.gst_number || a.pan_number}</p>
                          {a.gst_number && a.pan_number && <p className={SUBLINE}>{a.pan_number}</p>}
                        </>
                      ) : DASH}
                    </td>
                    <td className={`${CELL} text-[11px] tabular-nums whitespace-nowrap`}>
                      {a.ticket_count > 0 ? (
                        <>
                          <span className={a.unbilled_ticket_count > 0 ? "font-semibold text-amber-600" : "text-gray-400"}>
                            {a.unbilled_ticket_count}
                          </span>
                          <span className="text-gray-300"> / </span>
                          <span className="text-gray-600">{a.ticket_count}</span>
                        </>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {total > pageSize && (
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={(p) => setPage(p)} />
        )}
      </div>
    </div>
  );
}
