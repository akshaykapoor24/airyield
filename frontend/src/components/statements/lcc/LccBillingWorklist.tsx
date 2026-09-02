"use client";

// "Who do we bill for this row?" — the review step between importing an LCC statement
// and sending it to billing.
//
// An LCC export names no customer, only a passenger, so the resolver matches that
// passenger against the Customer master and everything it could not settle lands here.
// In practice most rows land here: a retail LCC file's passengers rarely appear in the
// Customer master at all, which is why the batch default is the primary path and the
// per-row picker is the exception.
//
// Two badge columns, because there are two questions and settling one does not settle
// the other. MATCH is "does this row have a party?"; BILLING is "has it reached billing,
// and does billing still agree with it?" A row can be "Set by you" and "Ready to send"
// at the same time, and the pair that matters most is "In billing" versus "Re-send" —
// the second means an invoice run would use a party this row no longer names.
//
// Bucket chips + reason grouping follow the deal-upload review table and the BSP
// commission gaps tab — the reason strings are identical per gap type on purpose, so
// 108 passengers collapse into a handful of groups instead of 108 rows of one.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Info, Loader2, Lock, RefreshCw, Search, Send, X,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import LccPartyPicker, { PartyOption } from "./LccPartyPicker";

const PAGE = 50;
const MAX_SELECTION = 500;      // matches MAX_SEND_ROWS on the API

const SELECT_CLS =
  "px-2 py-1.5 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";
const TEXT_CLS =
  "pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-52 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";

type Row = {
  id: number;
  passenger: string | null;
  record_locator: string | null;
  transaction_date: string | null;
  departure_date: string | null;
  total: number | null;
  base_fare: number | null;
  bill_kind: "sale" | "refund" | "payment" | null;
  bill_status: string;
  bill_customer_type: string | null;
  bill_customer_id: number | null;
  bill_corporate_id: number | null;
  party_name: string | null;
  bill_match_reason: string | null;
  projected_ticket_id: number | null;
  // Where the row has got to on its way into billing — see services/lcc_billing_projection.
  billing_state: string;
  billing_id: number | null;
  /** The party currently ON the ticket. Sent only for a stale row, where it differs. */
  billed_party_name: string | null;
  sendable: boolean;
};

type Gap = { status: string; reason: string | null; count: number; sample_passengers: string[] };

type Summary = {
  billable_rows: number; resolved_rows: number; unresolved_rows: number;
  projected_rows: number; resolution_status: string;
  summary: Record<string, number>; state_counts: Record<string, number>;
  customers_in_scope: number;
};

const STATUS_STYLE: Record<string, string> = {
  resolved:      "bg-emerald-50 text-emerald-700 border-emerald-200",
  defaulted:     "bg-sky-50 text-sky-700 border-sky-200",
  overridden:    "bg-violet-50 text-violet-700 border-violet-200",
  ambiguous:     "bg-red-50 text-red-700 border-red-200",
  initials_only: "bg-amber-50 text-amber-700 border-amber-200",
  unresolved:    "bg-slate-50 text-slate-500 border-slate-200",
  excluded:      "bg-slate-50 text-slate-400 border-slate-200",
};
const STATUS_LABEL: Record<string, string> = {
  resolved: "Matched", defaulted: "Default party", overridden: "Set by you",
  ambiguous: "Several match", initials_only: "Initials only",
  unresolved: "No match", excluded: "Payment movement",
};

const BILL_STATE_STYLE: Record<string, string> = {
  invoiced:     "bg-blue-50 text-blue-700 border-blue-200",
  sent:         "bg-emerald-50 text-emerald-700 border-emerald-200",
  stale:        "bg-orange-50 text-orange-700 border-orange-200",
  withdrawn:    "bg-red-50 text-red-700 border-red-200",
  ready:        "bg-white text-slate-600 border-slate-200",
  no_party:     "bg-amber-50 text-amber-700 border-amber-200",
  not_billable: "bg-slate-50 text-slate-400 border-slate-200",
};
const BILL_STATE_LABEL: Record<string, string> = {
  invoiced: "On an invoice", sent: "In billing", stale: "Re-send",
  withdrawn: "Party removed", ready: "Ready to send",
  no_party: "Needs a party", not_billable: "Not billable",
};

const KIND_LABEL: Record<string, string> = { sale: "Charge", refund: "Credit", payment: "Payment" };

const inr = (n: number | null) =>
  n == null ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

function fmtDate(s: string | null) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(); } catch { return s; }
}

const errText = (e: unknown, fallback: string) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

/** Why this row cannot be ticked. Null when it can. */
function whyNotSendable(r: Row): string | null {
  if (r.sendable) return null;
  if (r.billing_state === "not_billable") return "Payment movement — there is no fare to bill.";
  if (r.billing_state === "invoiced") return "Already on an invoice — locked, and re-sending cannot change it.";
  return "No party yet — pick one first.";
}

function billingHint(r: Row): string | undefined {
  switch (r.billing_state) {
    case "stale":
      return `Sent to billing as ${r.billed_party_name || "another party"}, but this row now says `
        + `${r.party_name || "nobody"}. Send it again so billing catches up.`;
    case "invoiced":
      return `On invoice #${r.billing_id}. Locked — re-sending will not change it.`;
    case "withdrawn":
      return "This row is in billing but no longer has a party. Give it one and send again, "
        + "or send the whole upload to take it back out.";
    case "sent":
      return "In billing, and billing agrees with this row.";
    case "ready":
      return "Has a party and is waiting to be sent.";
    default:
      return undefined;
  }
}

function Chip({ label, value, tone, hint }: {
  label: string; value: number; tone: string; hint?: string;
}) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${tone}`} title={hint}>
      <p className="text-[10px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-sm font-bold tabular-nums">{value.toLocaleString()}</p>
    </div>
  );
}

export default function LccBillingWorklist({
  apiBase, batchId, fileName, resolutionStatus, onBack, onChanged,
}: {
  apiBase: string;
  batchId: string;
  fileName: string | null;
  /** The batch's resolution_status when it was opened. Decides whether opening the
   *  screen is allowed to run the matcher — see the mount effect. */
  resolutionStatus: string;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<string>("");
  const [billState, setBillState] = useState<string>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  // The reason breakdown is a reference table, not a working one — you read it once to
  // understand the file and then want it gone. Behind a button, so the rows you actually
  // have to act on start near the top of the screen instead of below a second table.
  const [showGaps, setShowGaps] = useState(false);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectAllMode, setSelectAllMode] = useState(false);

  const [parties, setParties] = useState<PartyOption[]>([]);
  const [defaultPick, setDefaultPick] = useState<number | null>(null);
  const [defaultKind, setDefaultKind] = useState<"customer" | "corporate" | null>(null);
  const [bulkPick, setBulkPick] = useState<number | null>(null);
  const [bulkKind, setBulkKind] = useState<"customer" | "corporate" | null>(null);

  // Both masters, loaded whole and filtered in the browser — the same thing every
  // other party picker in the app does (CustomerPartyPanel, TicketFilingCard).
  useEffect(() => {
    Promise.allSettled([
      api.get<{ id: number; first_name: string; last_name: string | null; company: string | null }[]>("/customers/", { params: { limit: 1000 } }),
      api.get<{ id: number; company: string | null }[]>("/corporates/", { params: { limit: 1000 } }),
    ]).then(([cu, co]) => {
      const out: PartyOption[] = [];
      if (co.status === "fulfilled") {
        for (const x of co.value.data) {
          if (x.company) out.push({ value: x.id, label: x.company, kind: "corporate", sublabel: "Corporate" });
        }
      }
      if (cu.status === "fulfilled") {
        for (const x of cu.value.data) {
          const name = `${x.first_name} ${x.last_name ?? ""}`.trim();
          if (name) out.push({ value: x.id, label: name, kind: "customer", sublabel: x.company ?? undefined });
        }
      }
      setParties(out);
    });
  }, []);

  const rowParams = useCallback(() => ({
    ...(filter ? { status: filter } : {}),
    ...(billState ? { billing_state: billState } : {}),
    ...(search.trim() ? { q: search.trim() } : {}),
  }), [filter, billState, search]);

  // A monotonic sequence, not a boolean: with the search debounced, a slow "RAV"
  // response would otherwise land after a fast "RAVI" one and paint the wrong rows
  // under the newer text. Copied from LccDetailedView's records grid.
  const reqSeq = useRef(0);

  const load = useCallback(async (off = 0) => {
    const seq = ++reqSeq.current;
    setLoading(true);
    try {
      const { data } = await api.get<{ total: number; rows: Row[] }>(
        `${apiBase}/batches/${batchId}/billing-rows`,
        { params: { offset: off, limit: PAGE, ...rowParams() } },
      );
      if (seq !== reqSeq.current) return;      // a newer request already landed
      setRows(data.rows); setTotal(data.total); setOffset(off);
    } catch (e) {
      if (seq === reqSeq.current) toast.error(errText(e, "Failed to load the worklist."));
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [apiBase, batchId, rowParams]);

  /** The header, read-only. Never re-matches — see the mount effect. */
  const refreshSummary = useCallback(async () => {
    try {
      const [s, g] = await Promise.all([
        api.get<Summary>(`${apiBase}/batches/${batchId}/billing-summary`),
        api.get<Gap[]>(`${apiBase}/batches/${batchId}/billing-gaps`),
      ]);
      setSummary(s.data); setGaps(g.data);
    } catch { /* the chips keep their last good values */ }
  }, [apiBase, batchId]);

  const resolve = useCallback(async () => {
    setBusy("resolve");
    try {
      const { data } = await api.post<Summary>(`${apiBase}/batches/${batchId}/resolve-customers`, {});
      const staleNow = (data.state_counts?.stale ?? 0) + (data.state_counts?.withdrawn ?? 0);
      toast.success(
        `${data.resolved_rows.toLocaleString()} of ${data.billable_rows.toLocaleString()} rows have a party.`
        + (staleNow ? ` ${staleNow.toLocaleString()} already in billing now need re-sending.` : ""),
      );
      await Promise.all([load(0), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not resolve customers.")); }
    finally { setBusy(null); }
  }, [apiBase, batchId, load, refreshSummary, onChanged]);

  // Matching is a WRITE. Running it just because someone opened the screen would
  // re-stamp every non-overridden row — and on an upload already sent to billing that
  // can silently re-point a row billing is using. So it runs only on the genuine first
  // open, which is the same case the uploads list labels "Set up billing"; every later
  // visit just reads the summary, and Re-match stays there as a deliberate button.
  const openedOnce = useRef(false);
  useEffect(() => {
    if (openedOnce.current) return;
    openedOnce.current = true;
    if (resolutionStatus === "none") resolve(); else refreshSummary();
  }, [resolutionStatus, resolve, refreshSummary]);

  // Page 1 whenever the filters change, debounced so typing is one request per pause.
  // Every filter/search change funnels through here, so there is no call site left that
  // could reload without also clearing a selection that now means something else.
  const skipDebounce = useRef(true);
  useEffect(() => {
    const delay = skipDebounce.current ? 0 : 250;
    skipDebounce.current = false;
    const t = setTimeout(() => {
      setSelected(new Set()); setSelectAllMode(false);
      load(0);
    }, delay);
    return () => clearTimeout(t);
  }, [load]);

  // Paging KEEPS the selection — unlike the commission worklist, which clears it. Ticking
  // rows across pages is the whole point here (152 rows over four pages), ids are stable,
  // and silently dropping ticks loses work invisibly. The action bar always states the
  // count, which is what makes that safe.
  const goToPage = (off: number) => load(off);

  const applyDefault = async () => {
    if (!defaultPick || !defaultKind) { toast.error("Pick a customer or corporate first."); return; }
    setBusy("default");
    try {
      const { data } = await api.patch<{ rows_updated: number }>(
        `${apiBase}/batches/${batchId}/billing-default`,
        defaultKind === "corporate"
          ? { customer_type: "corporate", corporate_id: defaultPick }
          : { customer_type: "direct", customer_id: defaultPick },
      );
      toast.success(`${data.rows_updated.toLocaleString()} rows billed to this party.`);
      // No re-resolve: the endpoint has already stamped DEFAULTED onto exactly the rows
      // the matcher could not place. Sequential, and page 1, because a mass re-stamp
      // makes wherever you were standing meaningless.
      await Promise.all([load(0), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not set the default party.")); }
    finally { setBusy(null); }
  };

  const setRowParty = async (row: Row, opt: PartyOption | null) => {
    try {
      await api.patch(`${apiBase}/rows/${row.id}/billing-party`, opt
        ? (opt.kind === "corporate"
            ? { customer_type: "corporate", corporate_id: opt.value }
            : { customer_type: "direct", customer_id: opt.value })
        : {});
      await Promise.all([load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not set the party for this row.")); }
  };

  const applyBulkParty = async () => {
    if (!bulkPick || !bulkKind) { toast.error("Pick a customer or corporate first."); return; }
    setBusy("bulk");
    try {
      const { data } = await api.patch<{ rows_updated: number; skipped_payments: number }>(
        `${apiBase}/batches/${batchId}/billing-party-bulk`,
        {
          row_ids: [...selected],
          ...(bulkKind === "corporate"
            ? { customer_type: "corporate", corporate_id: bulkPick }
            : { customer_type: "direct", customer_id: bulkPick }),
        },
      );
      toast.success(
        `${data.rows_updated.toLocaleString()} rows billed to this party.`
        + (data.skipped_payments ? ` ${data.skipped_payments} payment movements skipped.` : ""),
      );
      setBulkPick(null); setBulkKind(null);
      await Promise.all([load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not bill the selected rows.")); }
    finally { setBusy(null); }
  };

  /** No ids → the whole upload, synced. Ids → just those, added and never removed. */
  const sendToBilling = async (ids?: number[]) => {
    setBusy("send");
    try {
      const { data } = await api.post<{
        scoped: boolean; requested: number; created: number; updated: number;
        deleted: number; skipped_billed: number; skipped_no_party: number;
        skipped_not_billable: number;
      }>(`${apiBase}/batches/${batchId}/send-to-billing`, ids ? { row_ids: ids } : {});
      const bits = [
        data.created ? `${data.created} added` : null,
        data.updated ? `${data.updated} updated` : null,
        data.deleted ? `${data.deleted} removed` : null,
        data.skipped_billed ? `${data.skipped_billed} already on an invoice, left alone` : null,
        data.skipped_no_party ? `${data.skipped_no_party} skipped — no party` : null,
        data.skipped_not_billable ? `${data.skipped_not_billable} skipped — payment movements` : null,
      ].filter(Boolean);
      toast.success(
        (data.scoped ? `Sent ${data.requested.toLocaleString()} selected rows` : "Sent to billing")
        + ` — ${bits.join(", ") || "nothing to do"}.`,
      );
      // A sent row has changed state, so a surviving tick would only invite a re-send.
      setSelected(new Set()); setSelectAllMode(false);
      await Promise.all([load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not send to billing.")); }
    finally { setBusy(null); }
  };

  const selectAllMatching = async () => {
    try {
      const { data } = await api.get<{ ids: number[]; total: number; truncated: boolean }>(
        `${apiBase}/batches/${batchId}/billing-rows`,
        { params: { ...rowParams(), billing_state: billState || "sendable", ids_only: true } },
      );
      setSelected(new Set(data.ids));
      setSelectAllMode(true);
      if (data.truncated) {
        toast(`Selected the first ${data.ids.length.toLocaleString()} of ${data.total.toLocaleString()} — send these, then select the rest.`);
      }
    } catch (e) { toast.error(errText(e, "Could not select the matching rows.")); }
  };

  // setSelectAllMode is called beside the updater, never inside it: a state updater has
  // to stay pure, and React runs it twice in development to prove it.
  const toggleRow = (id: number) => {
    setSelectAllMode(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const sendableOnPage = rows.filter((r) => r.sendable);
  const allOnPageSelected = sendableOnPage.length > 0 && sendableOnPage.every((r) => selected.has(r.id));
  const toggleAllOnPage = () => {
    setSelectAllMode(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) sendableOnPage.forEach((r) => next.delete(r.id));
      else sendableOnPage.forEach((r) => next.add(r.id));
      return next;
    });
  };
  const clearSelection = () => { setSelected(new Set()); setSelectAllMode(false); };

  const s = summary?.summary ?? {};
  const sc = summary?.state_counts ?? {};
  const needALook = (s.ambiguous ?? 0) + (s.initials_only ?? 0);
  const needResend = (sc.stale ?? 0) + (sc.withdrawn ?? 0);
  const gapRows = gaps.reduce((n, g) => n + g.count, 0);
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + rows.length, total);
  const hasFilters = !!(search || filter || billState);
  const overCap = selected.size > MAX_SELECTION;

  return (
    <div>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <button onClick={onBack} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to uploads
        </button>
        <span className="text-slate-300">|</span>
        <h3 className="text-sm font-semibold text-slate-800 truncate max-w-[320px]" title={fileName ?? undefined}>
          Billing · {fileName || "upload"}
        </h3>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={resolve} disabled={!!busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50">
            {busy === "resolve" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Re-match
          </button>
          {selected.size > 0 ? (
            <button onClick={() => sendToBilling([...selected])} disabled={!!busy || overCap}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
              {busy === "send" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              Send selected ({selected.size.toLocaleString()})
            </button>
          ) : (
            <button onClick={() => sendToBilling()} disabled={!!busy || !summary?.resolved_rows}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
              {busy === "send" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              Send to billing
            </button>
          )}
        </div>
      </div>

      {/* Buckets. "Need a look" is split out from "No match" because they have
          different fixes: one is a choice between candidates, the other has none. */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">
        <Chip label="Billable rows" value={summary?.billable_rows ?? 0} tone="bg-white border-slate-200 text-slate-700"
              hint="Charges and credits. Payment movements are excluded — they carry no fare." />
        <Chip label="Have a party" value={summary?.resolved_rows ?? 0} tone="bg-emerald-50 border-emerald-200 text-emerald-700" />
        <Chip label="Need a look" value={needALook} tone="bg-amber-50 border-amber-200 text-amber-700"
              hint="Several customers share the name, or only initials were given. Never guessed." />
        <Chip label="No match" value={s.unresolved ?? 0} tone="bg-slate-50 border-slate-200 text-slate-600"
              hint="No customer in your master has this passenger's name. Use the default party below." />
        <Chip label="In billing" value={sc.sent ?? 0} tone="bg-sky-50 border-sky-200 text-sky-700"
              hint="Rows projected into billing whose party still agrees with this statement." />
      </div>

      {summary && summary.customers_in_scope === 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>Your Customer master is empty, so no passenger can match. Add customers under
            User master → Employee Master, or bill the whole upload to one party below.</span>
        </div>
      )}

      {/* The one thing on this screen that can put a wrong party on an invoice. */}
      {needResend > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 mb-3 text-xs text-orange-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {needResend.toLocaleString()} rows are already in billing but no longer match what this
            statement says — billing would use the old party. Send them again to catch it up.
            Rows already on an invoice are locked and will not change.{" "}
            <button onClick={() => setBillState("stale")} className="font-semibold underline hover:no-underline">
              Show them
            </button>
          </span>
        </div>
      )}

      {/* The batch default. Named plainly as the primary path, because it is. */}
      <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-3.5 py-3 mb-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-xs font-semibold text-slate-700">Bill everything unmatched to</span>
          <div className="min-w-[260px]">
            <LccPartyPicker
              options={parties}
              value={defaultPick}
              onChange={(o) => { setDefaultPick(o?.value ?? null); setDefaultKind(o?.kind ?? null); }}
            />
          </div>
          <button onClick={applyDefault} disabled={!!busy || !defaultPick}
            className="px-3 py-1.5 text-xs font-semibold text-white bg-slate-700 rounded-lg hover:bg-slate-800 disabled:opacity-40">
            {busy === "default" ? "Applying…" : "Apply"}
          </button>
          <span className="text-[11px] text-slate-400">
            An LCC file&apos;s passengers rarely appear in your Customer master, so this is usually the quickest route.
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Passenger or PNR" className={TEXT_CLS} />
        </div>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className={SELECT_CLS}>
          <option value="">Any match status</option>
          <option value="unresolved">No match</option>
          <option value="ambiguous">Several match</option>
          <option value="initials_only">Initials only</option>
          <option value="defaulted">Default party</option>
          <option value="overridden">Set by you</option>
          <option value="resolved">Matched</option>
          <option value="excluded">Payment movements</option>
        </select>
        <select value={billState} onChange={(e) => setBillState(e.target.value)} className={SELECT_CLS}>
          <option value="">Any billing state</option>
          <option value="sendable">Can be sent</option>
          <option value="ready">Ready to send</option>
          <option value="sent">In billing</option>
          <option value="stale">Needs re-sending</option>
          <option value="withdrawn">Party removed</option>
          <option value="invoiced">On an invoice</option>
          <option value="no_party">Needs a party</option>
          <option value="not_billable">Not billable</option>
        </select>
        {hasFilters && (
          <button onClick={() => { setSearch(""); setFilter(""); setBillState(""); }}
            className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-700">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
        {gaps.length > 0 && (
          <button onClick={() => setShowGaps(true)}
            className="ml-auto inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 hover:text-blue-600">
            <Info className="w-3.5 h-3.5" />
            Why {gapRows.toLocaleString()} rows didn&apos;t match
          </button>
        )}
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-blue-200 bg-blue-50/60 px-3.5 py-2.5 mb-2">
          <span className="text-xs font-semibold text-blue-800">
            {selected.size.toLocaleString()} row{selected.size === 1 ? "" : "s"} selected
            {selectAllMode ? " across every page" : ""}
          </span>
          <div className="min-w-[220px]">
            <LccPartyPicker
              size="sm"
              options={parties}
              value={bulkPick}
              placeholder="Bill selected to…"
              onChange={(o) => { setBulkPick(o?.value ?? null); setBulkKind(o?.kind ?? null); }}
            />
          </div>
          <button onClick={applyBulkParty} disabled={!!busy || !bulkPick || overCap}
            className="px-3 py-1.5 text-xs font-semibold text-white bg-slate-700 rounded-lg hover:bg-slate-800 disabled:opacity-40">
            {busy === "bulk" ? "Applying…" : "Apply"}
          </button>
          <button onClick={clearSelection} className="ml-auto text-[11px] text-slate-500 hover:text-slate-800">
            Clear selection
          </button>
        </div>
      )}

      {overCap && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-2 text-xs text-amber-700">
          {selected.size.toLocaleString()} rows selected — act on at most {MAX_SELECTION.toLocaleString()} at
          a time, or use Send to billing for the whole upload.
        </div>
      )}

      {allOnPageSelected && total > rows.length && !selectAllMode && (
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 mb-2 text-xs text-slate-600">
          All {sendableOnPage.length.toLocaleString()} sendable rows on this page are ticked.{" "}
          <button onClick={selectAllMatching} className="font-semibold text-blue-600 hover:underline">
            Select every matching row instead
          </button>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2.5 w-8">
                  <input type="checkbox" checked={allOnPageSelected} onChange={toggleAllOnPage}
                    disabled={sendableOnPage.length === 0}
                    aria-label="Select every sendable row on this page"
                    className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                </th>
                <th className="text-left px-3 py-2.5 font-semibold">Passenger</th>
                <th className="text-left px-3 py-2.5 font-semibold">PNR</th>
                <th className="text-left px-3 py-2.5 font-semibold">Date</th>
                <th className="text-left px-3 py-2.5 font-semibold">Kind</th>
                <th className="text-right px-3 py-2.5 font-semibold">Amount</th>
                <th className="text-left px-3 py-2.5 font-semibold">Match</th>
                <th className="text-left px-3 py-2.5 font-semibold">Billing</th>
                <th className="text-left px-3 py-2.5 font-semibold w-[260px]">Bill to</th>
              </tr>
            </thead>
            {/* Dim rather than blank, so typing in the search box does not strobe. */}
            <tbody className={`divide-y divide-slate-100 ${loading && rows.length > 0 ? "opacity-50 transition-opacity" : ""}`}>
              {loading && rows.length === 0 ? (
                <tr><td colSpan={9} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={9} className="px-3 py-10 text-center text-slate-400">
                  {hasFilters ? "No rows match what you are looking for." : "No rows in this bucket."}
                </td></tr>
              ) : rows.map((r) => {
                const blocked = whyNotSendable(r);
                return (
                <tr key={r.id} className={`hover:bg-slate-50/60 ${selected.has(r.id) ? "bg-blue-50/50" : ""} ${r.bill_kind === "payment" ? "opacity-55" : ""}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id)}
                      disabled={!!blocked} title={blocked ?? undefined}
                      aria-label={`Select ${r.passenger || "row"}`}
                      className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                  </td>
                  <td className="px-3 py-2 text-slate-700 truncate max-w-[180px]" title={r.passenger ?? undefined}>{r.passenger || "—"}</td>
                  <td className="px-3 py-2 text-slate-500 font-mono text-[11px]">{r.record_locator || "—"}</td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDate(r.transaction_date)}</td>
                  <td className="px-3 py-2 text-slate-500">{KIND_LABEL[r.bill_kind ?? ""] ?? "—"}</td>
                  <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${(r.total ?? 0) < 0 ? "text-red-600" : "text-slate-700"}`}>
                    {inr(r.total)}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${STATUS_STYLE[r.bill_status] ?? STATUS_STYLE.unresolved}`}
                          title={r.bill_match_reason ?? undefined}>
                      {STATUS_LABEL[r.bill_status] ?? r.bill_status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium ${BILL_STATE_STYLE[r.billing_state] ?? BILL_STATE_STYLE.ready}`}
                          title={billingHint(r)}>
                      {r.billing_state === "invoiced" && <Lock className="w-2.5 h-2.5" />}
                      {BILL_STATE_LABEL[r.billing_state] ?? r.billing_state}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {r.bill_kind === "payment" ? (
                      <span className="text-[11px] text-slate-400">Not billable</span>
                    ) : (
                      <LccPartyPicker
                        size="sm"
                        options={parties}
                        value={r.bill_customer_type === "corporate" ? r.bill_corporate_id : r.bill_customer_id}
                        onChange={(opt) => setRowParty(r, opt)}
                        placeholder="Pick a party…"
                      />
                    )}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {total > 0 && (
          <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500">
            <span>Showing {start.toLocaleString()}–{end.toLocaleString()} of {total.toLocaleString()}</span>
            <div className="flex items-center gap-1">
              <button disabled={offset === 0 || loading} onClick={() => goToPage(Math.max(0, offset - PAGE))}
                className="px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Prev</button>
              <button disabled={offset + PAGE >= total || loading} onClick={() => goToPage(offset + PAGE)}
                className="px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>

      {/* Why the resolver could not settle a party, grouped by reason. It collapses only
          because bill_match_reason is identical per gap type — see customer_resolver. */}
      {showGaps && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
             onClick={() => setShowGaps(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-2.5 px-5 pt-5 pb-3">
              <Info className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-sm font-semibold text-slate-800">
                  Why {gapRows.toLocaleString()} rows didn&apos;t match
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Every row the matcher could not settle to a party, grouped by the reason.
                  Pick a party on the row itself, or bill them all to one party.
                </p>
              </div>
              <button onClick={() => setShowGaps(false)}
                className="ml-auto p-1 text-slate-400 hover:text-slate-700">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="max-h-[60vh] overflow-y-auto border-t border-slate-100">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400 sticky top-0">
                  <tr>
                    <th className="text-left px-4 py-2 font-semibold">Status</th>
                    <th className="text-left px-4 py-2 font-semibold">Why</th>
                    <th className="text-right px-4 py-2 font-semibold">Rows</th>
                    <th className="text-left px-4 py-2 font-semibold">For example</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {gaps.map((g, i) => (
                    <tr key={i}>
                      <td className="px-4 py-2">
                        <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${STATUS_STYLE[g.status] ?? STATUS_STYLE.unresolved}`}>
                          {STATUS_LABEL[g.status] ?? g.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-slate-600">{g.reason ?? "—"}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-slate-700">{g.count.toLocaleString()}</td>
                      <td className="px-4 py-2 text-slate-400 truncate max-w-[280px]">{g.sample_passengers.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-end px-5 py-3 border-t border-slate-100">
              <button onClick={() => setShowGaps(false)}
                className="px-4 py-1.5 text-xs font-semibold text-white bg-slate-700 rounded-lg hover:bg-slate-800">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
