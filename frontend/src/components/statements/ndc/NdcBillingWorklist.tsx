"use client";

// "Who do we bill for this ticket?" — the review step between importing an NDC statement
// and sending it to billing.
//
// An NDC export names no customer, only a passenger, so the resolver matches that passenger
// against the Customer master and everything it could not settle lands here. In practice
// most rows land here: an airline export's passengers rarely appear in the Customer master
// at all, which is why the batch default is the primary path and the per-row picker is the
// exception.
//
// A COPY OF LccBillingWorklist, NOT A GENERALISATION OF IT, and deliberately. That screen
// is 865 lines typed to LCC's row shape (`record_locator`, `total`, `base_fare`) and its
// seven billing states. NDC renders a document number, a product and a TXN type, and has
// two states LCC has no concept of — `latched` and `unlatched` — which would turn five
// style/label/hint maps into per-type props and the table into a render-prop framework. Two
// readable files beat one configurable one at this size. `LccPartyPicker` IS shared: it is
// already imported from outside its folder by three other components.
//
// THREE badge columns, because there are three questions and settling one settles neither
// of the others. LATCH is "which ticket does this line's money belong to?"; MATCH is "does
// it have a party?"; BILLING is "has it reached billing, and does billing still agree?"

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Info, Layers, Loader2, Lock, RefreshCw, Search, Send, UserPlus, X,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import LccPartyPicker, { PartyOption } from "@/components/statements/lcc/LccPartyPicker";

// This screen bills to a customer or a corporate only — never to an agency, which is a
// VENDOR here. Naming the two kinds explicitly keeps the picker's generic narrow, so the
// compiler enforces that rather than leaving it to a cast.
type BillingParty = PartyOption<"customer" | "corporate">;

/** The corporate a person in Employee Master works for, held per customer id so the
 *  Corporate column can be answered from the person alone. */
type Employer = { id: number; name: string };

const PAGE = 50;
const MAX_SELECTION = 500;      // matches MAX_SEND_ROWS on the API

const SELECT_CLS =
  "px-2 py-1.5 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";
const TEXT_CLS =
  "pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-56 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";

type Row = {
  id: number;
  passenger: string | null;
  document_no: string | null;
  airline_pnr: string | null;
  product: string | null;
  txn_type: string | null;
  ticket_date: string | null;
  departure_date: string | null;
  /** This row's own signed settled figure, parsed once at resolve time. */
  amount: number | null;
  base_fare: string | null;
  total_tax: string | null;
  bill_kind: "sale" | "refund" | "payment" | null;
  bill_status: string;
  /** How the roll-up placed this line — see services/ndc_billing_projection. */
  bill_latch_status: string | null;
  bill_group_key: string | null;
  is_anchor: boolean;
  /** How many ancillary lines rolled into this one, and for how much. */
  latched_count: number;
  latched_amount: number | null;
  bill_customer_type: string | null;
  bill_customer_id: number | null;
  bill_corporate_id: number | null;
  party_name: string | null;
  bill_match_reason: string | null;
  projected_ticket_id: number | null;
  billing_state: string;
  billing_id: number | null;
  /** The party currently ON the ticket. Sent only for a stale row, where it differs. */
  billed_party_name: string | null;
  sendable: boolean;
};

type PartyGap = { status: string; reason: string | null; count: number; sample_passengers: string[] };
type LatchGap = { latch_status: string; reason: string | null; count: number; sample_pnrs: string[] };
type Gaps = { party: PartyGap[]; latch: LatchGap[] };

type Summary = {
  billable_rows: number; resolved_rows: number; unresolved_rows: number;
  projected_rows: number; projected_tickets: number;
  group_count: number; latched_rows: number; unlatched_rows: number;
  resolution_status: string;
  summary: Record<string, number>;
  latch: Record<string, number>;
  state_counts: Record<string, number>;
  customers_in_scope: number;
  /** Rows carrying the airline's own settled figure. Zero on an upload imported before
   *  `Payment Amount` was a column, whose amounts are derived from Total Fare instead. */
  settled_amount_rows: number;
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
  unresolved: "No match", excluded: "No money moved",
};

const LATCH_STYLE: Record<string, string> = {
  anchor:       "bg-white text-slate-600 border-slate-200",
  latched:      "bg-slate-100 text-slate-500 border-slate-200",
  orphan:       "bg-amber-50 text-amber-700 border-amber-200",
  ambiguous:    "bg-red-50 text-red-700 border-red-200",
  unidentified: "bg-red-50 text-red-700 border-red-200",
};
const LATCH_LABEL: Record<string, string> = {
  anchor: "Ticket", latched: "Rolled up", orphan: "No ticket",
  ambiguous: "Several tickets", unidentified: "Unidentified",
};

const BILL_STATE_STYLE: Record<string, string> = {
  invoiced:     "bg-blue-50 text-blue-700 border-blue-200",
  sent:         "bg-emerald-50 text-emerald-700 border-emerald-200",
  stale:        "bg-orange-50 text-orange-700 border-orange-200",
  withdrawn:    "bg-red-50 text-red-700 border-red-200",
  ready:        "bg-white text-slate-600 border-slate-200",
  no_party:     "bg-amber-50 text-amber-700 border-amber-200",
  latched:      "bg-slate-100 text-slate-500 border-slate-200",
  unlatched:    "bg-amber-50 text-amber-700 border-amber-200",
  not_billable: "bg-slate-50 text-slate-400 border-slate-200",
};
const BILL_STATE_LABEL: Record<string, string> = {
  invoiced: "On an invoice", sent: "In billing", stale: "Re-send",
  withdrawn: "Party removed", ready: "Ready to send", no_party: "Needs a party",
  latched: "On its ticket", unlatched: "Needs a ticket", not_billable: "Not billable",
};

const KIND_LABEL: Record<string, string> = { sale: "Charge", refund: "Credit", payment: "No movement" };

const inr = (n: number | null) =>
  n == null ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

function fmtDate(s: string | null) {
  if (!s) return "—";
  try {
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString();
  } catch { return s; }
}

const errText = (e: unknown, fallback: string) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

/** Why this row cannot be ticked. Null when it can. */
function whyNotSendable(r: Row): string | null {
  if (r.sendable) return null;
  if (r.billing_state === "not_billable") return "No money moved on this row.";
  if (r.billing_state === "latched")
    return "Its money is billed on the ticket it rolled into — that line is what you send.";
  if (r.billing_state === "unlatched")
    return "No ticket to attach this to. Pick a party to bill it on its own line.";
  if (r.billing_state === "invoiced") return "Already on an invoice — locked, and re-sending cannot change it.";
  if (r.billing_state === "sent")
    return "Already in billing. Change who it is billed to from Billing → Sold Tickets.";
  if (r.billing_state === "withdrawn")
    return "In billing but no longer has a party. Send the whole upload to take it back out.";
  return "No party yet — pick one first.";
}

/** In billing, so this screen no longer owns its party — the ticket is what billing reads.
 *  A latched row is locked too: its money is on the anchor's ticket, so re-pointing it here
 *  would change nothing anyone bills. The server refuses both. */
const locked = (r: Row) => r.projected_ticket_id != null || r.bill_latch_status === "latched";

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
      return "In billing. Change who it is billed to from Billing → Sold Tickets.";
    case "latched":
      return "Billed on the ticket this line rolled into, so it has no invoice line of its own.";
    case "unlatched":
      return r.bill_match_reason
        ?? "No ticket in this upload shares this line's PNR and passenger.";
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

export default function NdcBillingWorklist({
  apiBase, batchId, fileName, resolutionStatus, onBack, onChanged,
}: {
  apiBase: string;
  batchId: string;
  fileName: string | null;
  /** The batch's resolution_status when it was opened. Decides whether opening the screen
   *  is allowed to run the matcher — see the mount effect. */
  resolutionStatus: string;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [gaps, setGaps] = useState<Gaps>({ party: [], latch: [] });
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [billState, setBillState] = useState("");
  const [latchFilter, setLatchFilter] = useState("");
  const [search, setSearch] = useState("");
  // One ticket per line by default: a latched row's money is already on its anchor's line,
  // so showing both reads as double-counting. This opens them up.
  const [showRolledUp, setShowRolledUp] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [showGaps, setShowGaps] = useState(false);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectAllMode, setSelectAllMode] = useState(false);

  const [parties, setParties] = useState<BillingParty[]>([]);
  const [defaultPick, setDefaultPick] = useState<number | null>(null);
  const [defaultKind, setDefaultKind] = useState<"customer" | "corporate" | null>(null);
  const [bulkPick, setBulkPick] = useState<number | null>(null);
  const [bulkKind, setBulkKind] = useState<"customer" | "corporate" | null>(null);
  const [employerOf, setEmployerOf] = useState<Map<number, Employer>>(new Map());

  // Both masters, loaded whole and filtered in the browser — the same thing every other
  // party picker in the app does.
  const loadParties = useCallback(() => {
    return Promise.allSettled([
      api.get<{ id: number; first_name: string; last_name: string | null; company: string | null; corporate_id: number | null }[]>("/customers/", { params: { limit: 1000 } }),
      api.get<{ id: number; company: string | null }[]>("/corporates/", { params: { limit: 1000 } }),
    ]).then(([cu, co]) => {
      const out: BillingParty[] = [];
      const corpName = new Map<number, string>();
      if (co.status === "fulfilled") {
        for (const x of co.value.data) {
          if (x.company) {
            corpName.set(x.id, x.company);
            out.push({ value: x.id, label: x.company, kind: "corporate", sublabel: "Corporate" });
          }
        }
      }
      const employers = new Map<number, Employer>();
      if (cu.status === "fulfilled") {
        for (const x of cu.value.data) {
          const name = `${x.first_name} ${x.last_name ?? ""}`.trim();
          if (!name) continue;
          out.push({ value: x.id, label: name, kind: "customer", sublabel: x.company ?? undefined });
          if (x.corporate_id) {
            employers.set(x.id, { id: x.corporate_id, name: corpName.get(x.corporate_id) ?? x.company ?? "their corporate" });
          }
        }
      }
      setParties(out);
      setEmployerOf(employers);
    });
    // A callback rather than an inline effect body: adding a passenger to the
    // Employee Master has to make them appear in this picker straight away, and
    // nothing here ever re-read /customers/ before.
  }, []);

  useEffect(() => { void loadParties(); }, [loadParties]);

  const rowParams = useCallback(() => ({
    ...(filter ? { status: filter } : {}),
    ...(billState ? { billing_state: billState } : {}),
    ...(latchFilter ? { latch: latchFilter } : {}),
    ...(search.trim() ? { q: search.trim() } : {}),
    ...(showRolledUp ? { include_latched: true } : {}),
  }), [filter, billState, latchFilter, search, showRolledUp]);

  // A monotonic sequence, not a boolean: with the search debounced, a slow "RAV" response
  // would otherwise land after a fast "RAVI" one and paint the wrong rows under the newer
  // text.
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
        api.get<Gaps>(`${apiBase}/batches/${batchId}/billing-gaps`),
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
        `${data.group_count.toLocaleString()} tickets from ${data.billable_rows.toLocaleString()} lines; `
        + `${data.resolved_rows.toLocaleString()} have a party.`
        + (data.latched_rows ? ` ${data.latched_rows.toLocaleString()} ancillary lines rolled up.` : "")
        + (staleNow ? ` ${staleNow.toLocaleString()} already in billing now need re-sending.` : ""),
      );
      await Promise.all([load(0), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not resolve customers.")); }
    finally { setBusy(null); }
  }, [apiBase, batchId, load, refreshSummary, onChanged]);

  // Matching is a WRITE — it re-groups as well as re-matches. Running it just because
  // someone opened the screen would re-stamp every non-overridden row, and on an upload
  // already sent to billing that can silently re-point a row billing is using. So it runs
  // only on the genuine first open, which is the case the uploads list labels "Set up
  // billing"; every later visit just reads the summary, and Re-match stays a deliberate
  // button.
  const openedOnce = useRef(false);
  useEffect(() => {
    if (openedOnce.current) return;
    openedOnce.current = true;
    if (resolutionStatus === "none") resolve(); else refreshSummary();
  }, [resolutionStatus, resolve, refreshSummary]);

  // Page 1 whenever the filters change, debounced so typing is one request per pause.
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

  // Paging KEEPS the selection — ticking rows across pages is the point, ids are stable,
  // and silently dropping ticks loses work invisibly. The action bar always states the
  // count, which is what makes that safe.
  const goToPage = (off: number) => load(off);

  /** The party payload for a picked option.
   *
   *  WHO FLEW and WHO PAYS are separate answers, and the server stores whatever pair it is
   *  given rather than inferring one from the other. Picking a person who has an employer
   *  therefore defaults to billing that employer — which is what Employee Master's link
   *  means — while still naming the person, so the row records who travelled. */
  const partyBody = useCallback((opt: BillingParty | null, direct = false) => {
    if (!opt) return {};
    if (opt.kind === "corporate") return { customer_type: "corporate", corporate_id: opt.value };
    const employer = employerOf.get(opt.value);
    return employer && !direct
      ? { customer_type: "corporate", customer_id: opt.value, corporate_id: employer.id }
      : { customer_type: "direct", customer_id: opt.value };
  }, [employerOf]);

  const applyDefault = async () => {
    if (!defaultPick || !defaultKind) { toast.error("Pick a customer or corporate first."); return; }
    setBusy("default");
    try {
      const { data } = await api.patch<{ rows_updated: number }>(
        `${apiBase}/batches/${batchId}/billing-default`,
        partyBody({ value: defaultPick, kind: defaultKind, label: "" }),
      );
      toast.success(`${data.rows_updated.toLocaleString()} lines billed to this party.`);
      await Promise.all([load(0), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not set the default party.")); }
    finally { setBusy(null); }
  };

  const setRowParty = async (row: Row, opt: BillingParty | null, direct = false) => {
    try {
      await api.patch(`${apiBase}/rows/${row.id}/billing-party`, partyBody(opt, direct));
      await Promise.all([load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not set the party for this row.")); }
  };

  /** Switch a row that already names a person between billing their employer and billing
   *  them directly. Leaves WHO FLEW alone; only the payer changes. */
  const setRowPayer = async (row: Row, mode: "corporate" | "direct") => {
    if (!row.bill_customer_id) return;
    const opt = parties.find(p => p.kind === "customer" && p.value === row.bill_customer_id) ?? null;
    if (!opt) return;
    await setRowParty(row, opt, mode === "direct");
  };

  /** Add this row's passenger to the Employee Master under the corporate already
   *  picked for them, and bill the row to that new employee. The twin of the LCC
   *  worklist's button; the server shares the creation rule with it. */
  const addToMaster = async (row: Row) => {
    setBusy(`emp-${row.id}`);
    try {
      const { data } = await api.post<{ passenger: string; company: string; inherited: string[] }>(
        `${apiBase}/rows/${row.id}/create-employee`, {},
      );
      toast.success(
        `${data.passenger} added to Employee Master under ${data.company}.`
        + (data.inherited.length ? ` Took ${data.inherited.length} settings from the corporate.` : ""),
      );
      await Promise.all([loadParties(), load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not add this passenger to Employee Master.")); }
    finally { setBusy(null); }
  };

  /** The same for the ticked rows. The server skips what it cannot add and says why,
   *  rather than refusing the whole selection for one name already on file. */
  const addSelectedToMaster = async () => {
    setBusy("emp-bulk");
    try {
      const { data } = await api.post<{
        created_count: number; skipped_count: number;
        skipped: { passenger: string | null; reason: string }[];
      }>(`${apiBase}/batches/${batchId}/create-employees`, { row_ids: [...selected] });

      if (data.created_count) {
        toast.success(`${data.created_count.toLocaleString()} added to Employee Master.`);
      }
      if (data.skipped_count) {
        // Named, not just counted — "12 skipped" tells the user nothing to act on.
        const first = data.skipped[0];
        toast(
          `${data.skipped_count.toLocaleString()} skipped`
          + (first ? ` — e.g. ${first.passenger ?? "a row"}: ${first.reason}` : "."),
          { icon: "⚠️", duration: 8000 },
        );
      }
      await Promise.all([loadParties(), load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not add the selected passengers.")); }
    finally { setBusy(null); }
  };

  /** Needs a corporate to file them under and nobody already named. `locked` covers
   *  both NDC-only refusals: a row already in billing, and one latched to another
   *  ticket — a latched line has no invoice of its own to bill anyone for. */
  const canAddToMaster = (r: Row) =>
    !!r.passenger && !!r.bill_corporate_id && !r.bill_customer_id
    && r.bill_kind !== "payment" && !locked(r);

  const addableSelected = rows.filter(r => selected.has(r.id) && canAddToMaster(r)).length;

  const applyBulkParty = async () => {
    if (!bulkPick || !bulkKind) { toast.error("Pick a customer or corporate first."); return; }
    setBusy("bulk");
    try {
      const { data } = await api.patch<{
        rows_updated: number; skipped_payments: number;
        skipped_latched: number; skipped_in_billing: number;
      }>(`${apiBase}/batches/${batchId}/billing-party-bulk`, {
        row_ids: [...selected],
        ...partyBody({ value: bulkPick, kind: bulkKind, label: "" }),
      });
      toast.success(
        `${data.rows_updated.toLocaleString()} lines billed to this party.`
        + (data.skipped_latched ? ` ${data.skipped_latched} rolled-up lines skipped.` : "")
        + (data.skipped_in_billing ? ` ${data.skipped_in_billing} already in billing.` : "")
        + (data.skipped_payments ? ` ${data.skipped_payments} with no money movement skipped.` : ""),
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
        deleted: number; regrouped: number; skipped_billed: number; skipped_no_party: number;
        skipped_not_billable: number; skipped_unlatched: number; latched_rolled_up: number;
        unclassified_ancillaries: number; duplicate_ticket_numbers: number;
        projected_tickets: number;
      }>(`${apiBase}/batches/${batchId}/send-to-billing`, ids ? { row_ids: ids } : {});
      const bits = [
        data.created ? `${data.created} ticket${data.created === 1 ? "" : "s"} added` : null,
        data.updated ? `${data.updated} updated` : null,
        data.deleted ? `${data.deleted} removed` : null,
        data.latched_rolled_up ? `${data.latched_rolled_up} ancillary lines rolled in` : null,
        data.skipped_billed ? `${data.skipped_billed} already on an invoice, left alone` : null,
        data.skipped_no_party ? `${data.skipped_no_party} skipped — no party` : null,
        data.skipped_unlatched ? `${data.skipped_unlatched} skipped — no ticket to attach to` : null,
        data.skipped_not_billable ? `${data.skipped_not_billable} skipped — no money moved` : null,
      ].filter(Boolean);
      toast.success(
        (data.scoped ? `Sent ${data.requested.toLocaleString()} selected tickets` : "Sent to billing")
        + ` — ${bits.join(", ") || "nothing to do"}.`,
      );
      // Worth saying out loud rather than discovering on an invoice: NDC carries a real
      // ticket number, so re-uploading one file can put the same number in billing twice.
      if (data.duplicate_ticket_numbers) {
        toast(`${data.duplicate_ticket_numbers} ticket numbers appear more than once in this upload — check before invoicing.`,
              { icon: "⚠️", duration: 8000 });
      }
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

  // setSelectAllMode is called beside the updater, never inside it: a state updater has to
  // stay pure, and React runs it twice in development to prove it.
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
  const unlatched = summary?.unlatched_rows ?? 0;
  const gapRows = gaps.party.reduce((n, g) => n + g.count, 0);
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + rows.length, total);
  const hasFilters = !!(search || filter || billState || latchFilter);
  const overCap = selected.size > MAX_SELECTION;
  const derivedAmounts = !!summary && summary.settled_amount_rows === 0 && summary.billable_rows > 0;

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
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
            title="Re-groups the ancillaries and re-matches every passenger. Your own picks survive.">
            {busy === "resolve" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Re-match
          </button>
          {/* Only when the selection actually contains rows that can be filed — a
              disabled button the user cannot explain is worse than no button. */}
          {addableSelected > 0 && (
            <button onClick={addSelectedToMaster} disabled={!!busy}
              title="Add each selected passenger to Employee Master under the corporate picked for their row"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-700 border border-emerald-200 bg-emerald-50 rounded-lg hover:bg-emerald-100 disabled:opacity-50">
              {busy === "emp-bulk" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UserPlus className="w-3.5 h-3.5" />}
              Add {addableSelected.toLocaleString()} to Employee Master
            </button>
          )}
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

      {/* Buckets. "Tickets" is first because it is the number that differs from the file's
          row count and the one an invoice is counted in. */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
        <Chip label="Tickets" value={summary?.group_count ?? 0} tone="bg-white border-slate-200 text-slate-700"
              hint="One per document number and direction. A seat sold with a ticket is rolled into it, not counted again." />
        <Chip label="Billable lines" value={summary?.billable_rows ?? 0} tone="bg-white border-slate-200 text-slate-700"
              hint="Charges and credits, excluding the lines rolled up into another ticket and the ones where no money moved." />
        <Chip label="Have a party" value={summary?.resolved_rows ?? 0} tone="bg-emerald-50 border-emerald-200 text-emerald-700" />
        <Chip label="Need a look" value={needALook} tone="bg-amber-50 border-amber-200 text-amber-700"
              hint="Several customers share the name, or only initials were given. Never guessed." />
        <Chip label="No match" value={s.unresolved ?? 0} tone="bg-slate-50 border-slate-200 text-slate-600"
              hint="No customer in your master has this passenger's name. Use the default party below." />
        <Chip label="In billing" value={summary?.projected_tickets ?? 0} tone="bg-sky-50 border-sky-200 text-sky-700"
              hint="Tickets projected into billing from this upload." />
      </div>

      {summary && summary.customers_in_scope === 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>Your Customer master is empty, so no passenger can match. Add customers under
            User master → Employee Master, or bill the whole upload to one party below.</span>
        </div>
      )}

      {/* An upload imported before `Payment Amount` was a column. Its amounts are derived
          from Total Fare, which is right for a sale and a magnitude for a refund. */}
      {derivedAmounts && (
        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 mb-3 text-xs text-slate-600">
          <Info className="w-4 h-4 shrink-0 mt-0.5 text-slate-400" />
          <span>This upload predates the settled-amount column, so amounts are derived from
            Total Fare and signed from the transaction type. Re-upload the file to bill the
            airline&apos;s own settled figures.</span>
        </div>
      )}

      {/* Real money with nowhere to go. Louder than a chip because leaving it is a choice. */}
      {unlatched > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
          <Layers className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {unlatched.toLocaleString()} ancillary line{unlatched === 1 ? "" : "s"} name no ticket, and
            no flight line in this upload shares their PNR and passenger. Pick a party on each to
            bill it on its own line, or leave them out.{" "}
            <button onClick={() => { setLatchFilter("unlatched"); setBillState(""); }}
              className="font-semibold underline hover:no-underline">
              Show them
            </button>
          </span>
        </div>
      )}

      {/* The one thing on this screen that can put a wrong party on an invoice. */}
      {needResend > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 mb-3 text-xs text-orange-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {needResend.toLocaleString()} tickets are already in billing but no longer match what
            this statement says — billing would use the old party. Send them again to catch it up.
            Tickets already on an invoice are locked and will not change.{" "}
            <button onClick={() => { setBillState("stale"); setLatchFilter(""); }}
              className="font-semibold underline hover:no-underline">
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
            An airline export&apos;s passengers rarely appear in your Customer master, so this is usually the quickest route.
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Passenger, PNR or ticket no" className={TEXT_CLS} />
        </div>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className={SELECT_CLS}>
          <option value="">Any match status</option>
          <option value="unresolved">No match</option>
          <option value="ambiguous">Several match</option>
          <option value="initials_only">Initials only</option>
          <option value="defaulted">Default party</option>
          <option value="overridden">Set by you</option>
          <option value="resolved">Matched</option>
          <option value="excluded">No money moved</option>
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
          <option value="unlatched">Needs a ticket</option>
          <option value="latched">Rolled up</option>
          <option value="not_billable">Not billable</option>
        </select>
        <select value={latchFilter} onChange={(e) => setLatchFilter(e.target.value)} className={SELECT_CLS}>
          <option value="">Any line type</option>
          <option value="anchor">Tickets</option>
          <option value="latched">Rolled-up ancillaries</option>
          <option value="unlatched">Unattached ancillaries</option>
          <option value="orphan">No matching ticket</option>
          <option value="ambiguous">Several matching tickets</option>
        </select>
        <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 cursor-pointer"
               title="Show the ancillary lines that were rolled into a ticket. Their money is already on that ticket's line.">
          <input type="checkbox" checked={showRolledUp}
            onChange={(e) => setShowRolledUp(e.target.checked)}
            className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
          Show rolled-up lines
        </label>
        {hasFilters && (
          <button onClick={() => { setSearch(""); setFilter(""); setBillState(""); setLatchFilter(""); }}
            className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-700">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
        {(gaps.party.length > 0 || gaps.latch.length > 0) && (
          <button onClick={() => setShowGaps(true)}
            className="ml-auto inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 hover:text-blue-600">
            <Info className="w-3.5 h-3.5" />
            Why {gapRows.toLocaleString()} lines aren&apos;t ready
          </button>
        )}
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-blue-200 bg-blue-50/60 px-3.5 py-2.5 mb-2">
          <span className="text-xs font-semibold text-blue-800">
            {selected.size.toLocaleString()} line{selected.size === 1 ? "" : "s"} selected
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
          {selected.size.toLocaleString()} lines selected — act on at most {MAX_SELECTION.toLocaleString()} at
          a time, or use Send to billing for the whole upload.
        </div>
      )}

      {allOnPageSelected && total > rows.length && !selectAllMode && (
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 mb-2 text-xs text-slate-600">
          All {sendableOnPage.length.toLocaleString()} sendable lines on this page are ticked.{" "}
          <button onClick={selectAllMatching} className="font-semibold text-blue-600 hover:underline">
            Select every matching line instead
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
                    aria-label="Select every sendable line on this page"
                    className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                </th>
                <th className="text-left px-3 py-2.5 font-semibold">Passenger</th>
                <th className="text-left px-3 py-2.5 font-semibold">Ticket no</th>
                <th className="text-left px-3 py-2.5 font-semibold">PNR</th>
                <th className="text-left px-3 py-2.5 font-semibold">Issued</th>
                <th className="text-left px-3 py-2.5 font-semibold">Kind</th>
                <th className="text-right px-3 py-2.5 font-semibold">Amount</th>
                <th className="text-left px-3 py-2.5 font-semibold">Line</th>
                <th className="text-left px-3 py-2.5 font-semibold">Match</th>
                <th className="text-left px-3 py-2.5 font-semibold">Billing</th>
                <th className="text-left px-3 py-2.5 font-semibold w-[220px]">Bill to</th>
                <th className="text-left px-3 py-2.5 font-semibold w-[200px]">Corporate</th>
              </tr>
            </thead>
            {/* Dim rather than blank, so typing in the search box does not strobe. */}
            <tbody className={`divide-y divide-slate-100 ${loading && rows.length > 0 ? "opacity-50 transition-opacity" : ""}`}>
              {loading && rows.length === 0 ? (
                <tr><td colSpan={12} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={12} className="px-3 py-10 text-center text-slate-400">
                  {hasFilters ? "No lines match what you are looking for." : "No lines in this bucket."}
                </td></tr>
              ) : rows.map((r) => {
                const blocked = whyNotSendable(r);
                const isLatched = r.bill_latch_status === "latched";
                return (
                <tr key={r.id} className={`hover:bg-slate-50/60 ${selected.has(r.id) ? "bg-blue-50/50" : ""} ${r.bill_kind === "payment" || isLatched ? "opacity-60" : ""}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id)}
                      disabled={!!blocked} title={blocked ?? undefined}
                      aria-label={`Select ${r.passenger || "line"}`}
                      className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                  </td>
                  <td className="px-3 py-2 text-slate-700 truncate max-w-[170px]" title={r.passenger ?? undefined}>
                    {r.passenger || "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-500 font-mono text-[11px] whitespace-nowrap">
                    {r.document_no || <span className="text-slate-300">none</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-500 font-mono text-[11px]">{r.airline_pnr || "—"}</td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDate(r.ticket_date)}</td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap" title={r.txn_type ?? undefined}>
                    {KIND_LABEL[r.bill_kind ?? ""] ?? "—"}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${(r.amount ?? 0) < 0 ? "text-red-600" : "text-slate-700"}`}>
                    {r.amount == null ? (
                      // A cell that would not parse. Shown as unknown rather than zero — a
                      // total silently short by one line is the failure to avoid.
                      <span className="text-amber-600" title="This row's amount could not be read from the file.">—</span>
                    ) : inr(r.amount)}
                    {/* What rolled into this ticket, so the line reconciles on screen. */}
                    {r.latched_count > 0 && (
                      <span className="block text-[10px] text-slate-400"
                            title="Ancillary lines rolled into this ticket. Their money is inside the amount above.">
                        +{r.latched_count} ancillar{r.latched_count === 1 ? "y" : "ies"}
                        {r.latched_amount != null && ` · ${inr(r.latched_amount)}`}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium ${LATCH_STYLE[r.bill_latch_status ?? ""] ?? LATCH_STYLE.anchor}`}
                          title={r.product ? `${r.product}${r.txn_type ? ` · ${r.txn_type}` : ""}` : undefined}>
                      {isLatched && <Layers className="w-2.5 h-2.5" />}
                      {LATCH_LABEL[r.bill_latch_status ?? ""] ?? "Ticket"}
                    </span>
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
                    ) : isLatched ? (
                      // Its party follows the ticket it rolled into; changing it here would
                      // change nothing anyone bills.
                      <span className="text-[11px] text-slate-400" title="Billed on the ticket this line rolled into.">
                        {r.party_name || "on its ticket"}
                      </span>
                    ) : (
                      <LccPartyPicker
                        size="sm"
                        options={parties}
                        disabled={locked(r)}
                        // WHO FLEW, whenever the row names anyone — a row billed to an
                        // employer still knows its passenger, and showing the company here
                        // would hide the very thing this column is for.
                        value={r.bill_customer_id ?? r.bill_corporate_id}
                        // Ids repeat across the two masters, so name the list this id
                        // belongs to or corporate #7 answers for customer #7.
                        valueKind={r.bill_customer_id ? "customer" : "corporate"}
                        onChange={(opt) => setRowParty(r, opt)}
                        placeholder="Pick a party…"
                      />
                    )}
                  </td>

                  {/* WHO PAYS. Separate from who flew because they are separate answers: an
                      employee's ticket is normally billed to their employer, but the same
                      person can be billed directly, and the row has to be able to say
                      which. */}
                  <td className="px-3 py-2">
                    {r.bill_kind === "payment" || isLatched ? (
                      <span className="text-[11px] text-slate-400">—</span>
                    ) : !r.bill_customer_id ? (
                      // A company billed with nobody named is exactly where this
                      // passenger is missing from the master, so that is where the
                      // offer to add them belongs.
                      canAddToMaster(r) ? (
                        <button onClick={() => addToMaster(r)} disabled={!!busy}
                          title={`Add ${r.passenger} to Employee Master under this company`}
                          className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 hover:text-emerald-800 disabled:opacity-50">
                          {busy === `emp-${r.id}`
                            ? <Loader2 className="w-3 h-3 animate-spin" />
                            : <UserPlus className="w-3 h-3" />}
                          Add to Employee Master
                        </button>
                      ) : (
                        <span className="text-[11px] text-slate-400">
                          {r.bill_corporate_id ? "Billed to the company" : "—"}
                        </span>
                      )
                    ) : employerOf.has(r.bill_customer_id) ? (
                      <select
                        className={SELECT_CLS + " w-full disabled:bg-slate-50 disabled:text-slate-400"}
                        value={r.bill_corporate_id ? "corporate" : "direct"}
                        disabled={locked(r)}
                        onChange={(e) => setRowPayer(r, e.target.value as "corporate" | "direct")}
                        title={locked(r)
                          ? "Already in billing — change this from Billing → Sold Tickets."
                          : r.bill_corporate_id
                            ? "The company pays — this ticket shows in Corporate Billing"
                            : "The passenger pays — this ticket shows in Customer Billing"}
                      >
                        <option value="corporate">
                          {employerOf.get(r.bill_customer_id)?.name ?? "Their corporate"}
                        </option>
                        <option value="direct">Direct</option>
                      </select>
                    ) : (
                      <span className="text-[11px] text-slate-400" title="This person has no corporate in Employee Master">
                        Direct
                      </span>
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

      {/* Two sections, because the two problems need different things from the user: one is
          "we do not know who to bill" and is fixed with a picker; the other is "we do not
          know which ticket this belongs to" and is fixed by accepting it as its own line or
          leaving it out. */}
      {showGaps && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
             onClick={() => setShowGaps(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-2.5 px-5 pt-5 pb-3">
              <Info className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-sm font-semibold text-slate-800">Why these lines aren&apos;t ready</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Grouped by the reason. Pick a party on the line itself, or bill them all to one party.
                </p>
              </div>
              <button onClick={() => setShowGaps(false)}
                className="ml-auto p-1 text-slate-400 hover:text-slate-700">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="max-h-[60vh] overflow-y-auto border-t border-slate-100">
              {gaps.party.length > 0 && (
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400 sticky top-0">
                    <tr>
                      <th className="text-left px-4 py-2 font-semibold">No party</th>
                      <th className="text-left px-4 py-2 font-semibold">Why</th>
                      <th className="text-right px-4 py-2 font-semibold">Lines</th>
                      <th className="text-left px-4 py-2 font-semibold">For example</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {gaps.party.map((g, i) => (
                      <tr key={i}>
                        <td className="px-4 py-2">
                          <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${STATUS_STYLE[g.status] ?? STATUS_STYLE.unresolved}`}>
                            {STATUS_LABEL[g.status] ?? g.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-slate-600">{g.reason ?? "—"}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-slate-700">{g.count.toLocaleString()}</td>
                        <td className="px-4 py-2 text-slate-400 truncate max-w-[260px]">{g.sample_passengers.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {gaps.latch.length > 0 && (
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 border-y border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="text-left px-4 py-2 font-semibold">No ticket</th>
                      <th className="text-left px-4 py-2 font-semibold">Why</th>
                      <th className="text-right px-4 py-2 font-semibold">Lines</th>
                      <th className="text-left px-4 py-2 font-semibold">PNRs</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {gaps.latch.map((g, i) => (
                      <tr key={i}>
                        <td className="px-4 py-2">
                          <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${LATCH_STYLE[g.latch_status] ?? LATCH_STYLE.orphan}`}>
                            {LATCH_LABEL[g.latch_status] ?? g.latch_status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-slate-600">{g.reason ?? "—"}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-slate-700">{g.count.toLocaleString()}</td>
                        <td className="px-4 py-2 text-slate-400 font-mono truncate max-w-[260px]">{g.sample_pnrs.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
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
