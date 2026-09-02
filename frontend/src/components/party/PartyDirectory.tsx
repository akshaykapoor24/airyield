"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import {
  AlertTriangle, ArrowRight, ChevronRight, Edit2, Link2, Plus,
  ReceiptIndianRupee, RefreshCw, Search, Trash2, Upload, X,
} from "lucide-react";
import api from "@/lib/api";
import Pagination from "@/components/ui/Pagination";
import PartyModal from "@/components/party/PartyModal";
import PartyUploadModal from "@/components/party/PartyUploadModal";
import { PARTY_ICON } from "@/components/party/icons";
import {
  PARTY, billingTypeLabel, corporateLabel, corporateTypeLabel,
  markupTypeLabel, markupValueLabel, partyName,
  type Party, type PartyKind, type PartyMode,
} from "@/lib/party";

const PAGE_SIZE = 25;

const SELECT_CLS =
  "px-2 py-1.5 border border-gray-200 rounded-lg text-xs bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40";

type TicketState = "any" | "unbilled" | "has" | "none";

/** What the re-link endpoint reports, for the confirm preview and the result. */
type RelinkResult = {
  scanned: number; linked: number; already_linked: number; unmatched: number;
  company_synced: number; employees_filled: number;
  fields_filled: Record<string, number>; unmatched_companies: string[]; dry_run: boolean;
};

const errText = (e: unknown, fallback: string) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

// The first three columns are what a customer and a corporate disagree about: a
// customer is a person at a company, a corporate is an organisation of some legal
// form, somewhere. The rest — contact, tax ids, markup, billing — is shared.
const LEAD_COLUMNS: Record<PartyKind, string[]> = {
  customer: ["NAME", "CORPORATE", "TITLE"],
  corporate: ["CORPORATE NAME", "TYPE", "CITY"],
};
const TAIL_COLUMNS = ["EMAIL", "PHONE", "GST NO", "PAN NO", "MARKUP TYPE", "MARKUP VALUE", "BILLING"];

/**
 * The customer / corporate list, in one of two modes:
 *
 *   master  — User master. Add, import, edit and delete the parties you work
 *             with; each row offers "Bill" as the way through to Billing.
 *   billing — Billing. A picker: search, click a row, bill it. Deliberately
 *             has no write actions — those live in the master.
 */
export default function PartyDirectory({ kind, mode }: { kind: PartyKind; mode: PartyMode }) {
  const cfg = PARTY[kind];
  const Icon = PARTY_ICON[kind];
  const isMaster = mode === "master";
  const isCorporate = kind === "corporate";
  // TICKETS shows in both modes. On a master it tells you who has work outstanding; on
  // the billing picker it is the reason you are there at all — you are choosing whom to
  // bill, and this is the column that says who has anything to bill.
  const columns = useMemo(
    () => [...LEAD_COLUMNS[kind], ...TAIL_COLUMNS, "TICKETS"],
    [kind],
  );
  // User master calls a customer an Employee; Billing calls them a Customer.
  // Same rows, two contexts — see PartyConfig in lib/party.ts.
  const one = isMaster ? cfg.masterSingular : cfg.singular;
  const many = isMaster ? cfg.masterPlural : cfg.plural;
  const router = useRouter();

  const [parties, setParties] = useState<Party[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [ticketState, setTicketState] = useState<TicketState>("any");
  const [corporate, setCorporate] = useState("");        // "" | "none" | "<id>"
  const [corpOptions, setCorpOptions] = useState<Party[]>([]);
  const [page, setPage] = useState(1);
  const [showAdd, setShowAdd] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [editTarget, setEditTarget] = useState<Party | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Party | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [relinkOpen, setRelinkOpen] = useState(false);

  // Search, filters and paging are all server-side now. They used to run in the browser
  // over a single limit=500 fetch, which meant a workspace's 501st row could not be
  // found at all — it was never sent.
  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Monotonic, not a boolean: with the search debounced, a slow "RAV" response would
  // otherwise land after a fast "RAVI" and paint the wrong rows under the newer text.
  const reqSeq = useRef(0);

  const fetchParties = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Party[]>(`/${cfg.resource}/`, {
        params: {
          skip: (page - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
          ...(debounced.trim() ? { search: debounced.trim() } : {}),
          ...(ticketState !== "any" ? { ticket_state: ticketState } : {}),
          ...(!isCorporate && corporate ? { corporate } : {}),
        },
      });
      if (seq !== reqSeq.current) return;      // a newer request already landed
      setParties(res.data);
      // Falls back to "this page and no more" if the header is ever missing, so a CORS
      // misconfiguration degrades to a short pager rather than a silently wrong count.
      const raw = Number(res.headers?.["x-total-count"]);
      setTotal(Number.isFinite(raw) && raw >= 0 ? raw : (page - 1) * PAGE_SIZE + res.data.length);
    } catch {
      if (seq === reqSeq.current) setError(`Failed to load ${many.toLowerCase()}.`);
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [cfg.resource, many, page, debounced, ticketState, corporate, isCorporate]);

  useEffect(() => {
    fetchParties();
  }, [fetchParties]);

  // The corporate filter's options — for the people lists, where "which company does
  // this person work for" is a question. A failed load just leaves the filter offering
  // All / Not linked, which is still useful.
  useEffect(() => {
    if (isCorporate) return;
    let cancelled = false;
    api.get<Party[]>("/corporates/", { params: { limit: 1000 } })
      .then(({ data }) => { if (!cancelled) setCorpOptions(data.filter((c) => c.is_active)); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [isCorporate]);

  const filtersActive = !!debounced.trim() || ticketState !== "any" || !!corporate;
  const clearFilters = () => {
    setSearch(""); setDebounced(""); setTicketState("any"); setCorporate(""); setPage(1);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/${cfg.resource}/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchParties();
    } catch {
      alert(`Failed to delete ${one.toLowerCase()}.`);
    } finally {
      setDeleting(false);
    }
  };

  const colCount = columns.length + (isMaster ? 1 : 0);

  const crossLink = isMaster
    ? { href: cfg.billingHref, label: cfg.billingLabel }
    : { href: cfg.masterHref, label: cfg.masterLabel };

  return (
    <div className="space-y-4">
      {/* In master mode the User Master layout supplies the heading, so only the
          action row is rendered here. Billing owns its own page header. */}
      <div className="flex items-start justify-between">
        {isMaster ? (
          <p className="text-xs text-gray-500 self-center">
            {total} {total === 1 ? one.toLowerCase() : many.toLowerCase()}
            {filtersActive && " matching"}
          </p>
        ) : (
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Billing</p>
            <h1 className="text-xl font-bold text-gray-900">{cfg.billingLabel}</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Pick a {cfg.singular.toLowerCase()} to bill. Add or edit {cfg.masterPlural.toLowerCase()} in {cfg.masterLabel}.
            </p>
          </div>
        )}

        <div className="flex gap-2">
          <Link
            href={crossLink.href}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
          >
            {crossLink.label} <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <button
            onClick={fetchParties}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {isMaster && (
            <>
              {/* Deliberately NOT folded into Refresh above. Refresh is idempotent and
                  read-only, runs on every mount, and its icon-only presentation says so;
                  this rewrites every employee row and can change what future invoices
                  charge. A button that writes should say what it writes. */}
              <button
                onClick={() => setRelinkOpen(true)}
                className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
                title="Link employees to their corporate by company name, and fill in any terms they are missing"
              >
                <Link2 className="w-3.5 h-3.5" /> Link Employees
              </button>
              <button
                onClick={() => setShowUpload(true)}
                className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
              >
                <Upload className="w-3.5 h-3.5" /> Upload Excel
              </button>
              <button
                onClick={() => setShowAdd(true)}
                className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" /> Add {one}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder={
                isCorporate
                  ? "Search by name, city, email or phone…"
                  : "Search by name, company, email or phone…"
              }
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-gray-50"
            />
          </div>

          {/* Defaults to "All" on purpose, in both modes. A picker that silently hides
              rows the moment it opens is how someone concludes a customer has vanished. */}
          <select
            value={ticketState}
            onChange={(e) => { setTicketState(e.target.value as TicketState); setPage(1); }}
            className={SELECT_CLS}
            title="Find the parties that have tickets waiting to be billed"
          >
            <option value="any">All tickets</option>
            <option value="unbilled">Has unbilled</option>
            <option value="has">Has tickets</option>
            <option value="none">No tickets</option>
          </select>

          {!isCorporate && (
            <select
              value={corporate}
              onChange={(e) => { setCorporate(e.target.value); setPage(1); }}
              className={SELECT_CLS}
            >
              <option value="">All companies</option>
              {/* Doubles as the way to find the rows an import failed to match. */}
              <option value="none">Not linked</option>
              {corpOptions.map((c) => (
                <option key={c.id} value={String(c.id)}>{corporateLabel(c)}</option>
              ))}
            </select>
          )}

          {filtersActive && (
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
                {[...columns, ...(isMaster ? ["ACTIONS"] : [])].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                    title={h === "TICKETS"
                      ? "Unbilled / total tickets linked to this party. Tickets nobody has claimed, which Billing matches by passenger name, are not counted here."
                      : undefined}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            {/* Dim rather than blank, so typing in the search box does not strobe. */}
            <tbody className={loading && parties.length > 0 ? "opacity-50 transition-opacity" : ""}>
              {loading && parties.length === 0 ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading {many.toLowerCase()}…
                  </td>
                </tr>
              ) : parties.length === 0 && filtersActive ? (
                // "None yet" would be a lie when a search simply matched nothing.
                <tr>
                  <td colSpan={colCount} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center justify-center text-center">
                      <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                        <Search className="w-7 h-7 text-gray-300" />
                      </div>
                      <p className="text-sm font-medium text-gray-600">Nothing matches</p>
                      <p className="text-xs text-gray-400 mt-1 mb-4">
                        No {many.toLowerCase()} match the current search and filters.
                      </p>
                      <button onClick={clearFilters} className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold px-3.5 py-2 rounded-lg hover:bg-gray-50">
                        <X className="w-3.5 h-3.5" /> Clear filters
                      </button>
                    </div>
                  </td>
                </tr>
              ) : parties.length === 0 ? (
                <tr>
                  <td colSpan={colCount} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center justify-center text-center">
                      <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                        <Icon className="w-7 h-7 text-gray-300" />
                      </div>
                      <p className="text-sm font-medium text-gray-600">No {many.toLowerCase()} yet</p>
                      {isMaster ? (
                        <>
                          <p className="text-xs text-gray-400 mt-1 mb-4">
                            Add a {one.toLowerCase()} manually or import from Excel.
                          </p>
                          <div className="flex gap-2">
                            <button onClick={() => setShowAdd(true)} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                              <Plus className="w-3.5 h-3.5" /> Add {one}
                            </button>
                            <button onClick={() => setShowUpload(true)} className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold px-3.5 py-2 rounded-lg hover:bg-gray-50">
                              <Upload className="w-3.5 h-3.5" /> Upload Excel
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <p className="text-xs text-gray-400 mt-1 mb-4">
                            {cfg.masterPlural} are added in {cfg.masterLabel}.
                          </p>
                          <Link href={cfg.masterHref} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                            Go to {cfg.masterLabel} <ArrowRight className="w-3.5 h-3.5" />
                          </Link>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                parties.map((p, idx) => (
                  <tr
                    key={p.id}
                    onClick={() => (isMaster ? setEditTarget(p) : router.push(cfg.detailHref(p.id)))}
                    className={`border-b border-gray-50 hover:bg-blue-50/40 transition-colors group cursor-pointer ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-[12px] text-gray-800">{partyName(p)}</span>
                        {!isMaster && <ChevronRight className="w-3 h-3 text-gray-300 group-hover:text-[#1e3a5f]" />}
                      </div>
                    </td>
                    {isCorporate ? (
                      <>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{corporateTypeLabel(p.corporate_type)}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{p.city ?? "—"}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2 text-[11px] text-gray-600">
                          {p.company ? (
                            p.company
                          ) : (
                            // No employer is a real answer here, not missing data.
                            <span className="text-gray-400">Individual / Direct</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{p.title ?? "—"}</td>
                      </>
                    )}
                    <td className="px-3 py-2 text-[11px] text-gray-500">{p.email ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{p.phone ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">
                      {p.gst_registered ? (p.gst_no ?? "—") : <span className="text-gray-400">Unregistered</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{p.pan_no ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{markupTypeLabel(p)}</td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-700">{markupValueLabel(p)}</td>
                    <td className="px-3 py-2">
                      {p.billing_type ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-100">
                          {billingTypeLabel(p)}
                        </span>
                      ) : (
                        <span className="text-[11px] text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] tabular-nums whitespace-nowrap">
                      {(p.ticket_count ?? 0) > 0 ? (
                        <>
                          <span className={(p.unbilled_ticket_count ?? 0) > 0
                            ? "font-semibold text-amber-600" : "text-gray-400"}>
                            {p.unbilled_ticket_count ?? 0}
                          </span>
                          <span className="text-gray-300"> / </span>
                          <span className="text-gray-600">{p.ticket_count}</span>
                        </>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                    {isMaster && (
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => router.push(cfg.detailHref(p.id))}
                            className="p-1.5 hover:bg-green-50 rounded-lg"
                            title={`Bill this ${cfg.singular.toLowerCase()}`}
                          >
                            <ReceiptIndianRupee className="w-3.5 h-3.5 text-green-600" />
                          </button>
                          <button onClick={() => setEditTarget(p)} className="p-1.5 hover:bg-blue-50 rounded-lg" title="Edit">
                            <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                          </button>
                          <button onClick={() => setDeleteTarget(p)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete">
                            <Trash2 className="w-3.5 h-3.5 text-red-400" />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {total > PAGE_SIZE && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={(p) => setPage(p)} />
        )}
      </div>

      {relinkOpen && (
        <RelinkModal onClose={() => setRelinkOpen(false)} onDone={fetchParties} />
      )}

      {showAdd && <PartyModal kind={kind} onClose={() => setShowAdd(false)} onSaved={fetchParties} />}
      {showUpload && <PartyUploadModal kind={kind} onClose={() => setShowUpload(false)} onSaved={fetchParties} />}
      {editTarget && <PartyModal kind={kind} party={editTarget} onClose={() => setEditTarget(null)} onSaved={fetchParties} />}

      {deleteTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-red-500" />
                </div>
                <h2 className="text-sm font-bold text-gray-900">Delete {one}</h2>
              </div>
              <button onClick={() => setDeleteTarget(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-4">
              <p className="text-sm text-gray-600">
                Are you sure you want to delete{" "}
                <span className="font-semibold text-gray-900">{partyName(deleteTarget)}</span>? This action cannot be
                undone, and any saved billings for this {one.toLowerCase()} will be deleted with it.
              </p>
            </div>
            <div className="px-6 pb-5 flex gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Link employees to their corporate by company name, and fill in the terms they are
 * missing. Runs against `customers` whichever master you press it from — a corporate has
 * no parent to inherit from, and importing corporates AFTER employees is exactly when
 * someone standing on Corporate Master wants this.
 *
 * Opens on a dry run, so the confirmation states the REAL numbers rather than a guess.
 */
function RelinkModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [preview, setPreview] = useState<RelinkResult | null>(null);
  const [result, setResult] = useState<RelinkResult | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.post<RelinkResult>("/customers/relink-corporates", { dry_run: true })
      .then(({ data }) => { if (!cancelled) setPreview(data); })
      .catch((e) => { if (!cancelled) setError(errText(e, "Could not work out what would change.")); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, []);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post<RelinkResult>("/customers/relink-corporates", { dry_run: false });
      setResult(data);
      toast.success(
        `${data.linked} linked, ${data.employees_filled} given their corporate's terms.`,
      );
      onDone();
    } catch (e) {
      setError(errText(e, "Could not link the employees."));
    } finally {
      setBusy(false);
    }
  };

  const shown = result ?? preview;
  const nothingToDo = !!preview && preview.linked === 0 && preview.employees_filled === 0;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Link2 className="w-4 h-4 text-blue-600" />
            </div>
            <h2 className="text-sm font-bold text-gray-900">
              {result ? "Employees linked" : "Link employees to their corporates"}
            </h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{error}</p>
          )}

          {!result && (
            <p className="text-sm text-gray-600">
              Every employee whose Company name matches a corporate — ignoring case and
              surrounding spaces — is linked to it. Blank markup, billing type, GST, PAN,
              phone and email are then filled in from that corporate.{" "}
              <span className="font-semibold text-gray-900">
                Nothing you have already filled in is changed.
              </span>
            </p>
          )}

          {busy && !shown && <p className="text-xs text-gray-400">Working out what would change…</p>}

          {shown && (
            <div className="rounded-lg border border-gray-100 bg-gray-50/60 px-3.5 py-3 text-xs text-gray-600 space-y-1">
              <p><span className="font-semibold text-gray-900">{shown.scanned}</span> employees checked.</p>
              <p><span className="font-semibold text-gray-900">{shown.linked}</span> {result ? "linked" : "would be linked"} to a corporate.</p>
              <p><span className="font-semibold text-gray-900">{shown.employees_filled}</span> {result ? "given" : "would be given"} their corporate&apos;s terms.</p>
              {shown.company_synced > 0 && (
                <p><span className="font-semibold text-gray-900">{shown.company_synced}</span> company {shown.company_synced === 1 ? "name" : "names"} re-spelled to match.</p>
              )}
              <p className="text-gray-400">{shown.unmatched} name no corporate on file.</p>
            </div>
          )}

          {!result && !busy && !nothingToDo && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
              Employees who were on no markup will start billing at their corporate&apos;s
              markup. That is the point of this — but it changes what their next invoice charges.
            </p>
          )}

          {shown && shown.unmatched_companies.length > 0 && (
            <div className="text-xs">
              <p className="text-gray-500 mb-1">
                No corporate on file is named{shown.unmatched_companies.length > 1 ? " any of" : ""}:
              </p>
              <p className="text-gray-700 break-words">{shown.unmatched_companies.join(", ")}</p>
              <p className="text-[11px] text-gray-400 mt-1">
                Add them in Corporate Master, then run this again.
              </p>
            </div>
          )}

          {nothingToDo && !result && (
            <p className="text-xs text-gray-500">
              Everything is already linked and on its corporate&apos;s terms. There is nothing to do.
            </p>
          )}
        </div>

        <div className="px-6 pb-5 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={run}
              disabled={busy || !preview || nothingToDo}
              className="flex-1 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            >
              {busy ? "Working…" : preview ? `Link ${preview.linked} employees` : "Link"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
