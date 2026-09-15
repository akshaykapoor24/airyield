"use client";

// "Who do we bill for this booking?" — the review step between importing an aggregator
// statement (MakeMyTrip, TBO) and sending it to billing.
//
// An aggregator export names no customer, only a passenger, so the resolver matches that
// passenger against the Customer master and everything it could not settle lands here. In
// practice most rows land here, which is why the batch default is the primary path.
//
// A COPY OF NdcBillingWorklist, NOT A GENERALISATION OF IT, and the same deliberate choice
// that screen made of LccBillingWorklist. Dropped from it: the Line column and its two
// filters, the "show rolled-up lines" toggle, the "+N ancillaries" sub-line and the whole
// latch half of the gaps modal — an aggregator booking IS one line and one ticket, so there
// is nothing to latch. `LccPartyPicker` IS shared, as it is by three other screens.
//
// WHAT THIS SCREEN HAS THAT NEITHER OF THE OTHERS DOES: a CATEGORY column, and a coverage
// story. One file carries Hotel, Flight, Train, Bus and Car bookings, and EVERY category
// becomes a billing line priced at the party's markup for that category. What does not bill
// — a pending payment, a cancellation the vendor fully refunded, a product with no billing
// category — is shown, dimmed, with the reason and the amount on it, and three separate
// surfaces (the chips, the banner, the gaps modal) state the denominator. TBO's cancellation
// and refund-memo lines bill as CREDITS, so they carry a red Credit tag rather than a status.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Info, Loader2, Lock, RefreshCw, Search, Send, UserPlus, X,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import LccPartyPicker, { PartyOption } from "@/components/statements/lcc/LccPartyPicker";
import CategoryBadge, { categoryLabel } from "@/components/billing/CategoryBadge";
import PaxCell from "@/components/statements/PaxCell";

// This screen bills to a customer or a corporate only — never to an agency, which is a
// VENDOR here.
type BillingParty = PartyOption<"customer" | "corporate">;

/** The corporate a person in Employee Master works for, held per customer id. */
type Employer = { id: number; name: string };

const PAGE = 50;
const MAX_SELECTION = 500;      // matches MAX_SEND_ROWS on the API

const SELECT_CLS =
  "px-2 py-1.5 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";
const TEXT_CLS =
  "pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-56 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";

type Row = {
  id: number;
  /** Already stripped of TBO's "X 1" pax suffix by the API; `passenger_raw` is the cell. */
  passenger: string | null;
  passenger_raw: string | null;
  product_type: string | null;
  /** The markup category slug this row bills under — null when the product names none. */
  category: string | null;
  category_label: string | null;
  /** "Trident Chennai · Chennai · 23 Sep → 27 Sep 2026 · 4 nights" — what it carries into billing. */
  service_summary: string | null;
  /** "SM", "MZ", "RM" … — TBO's invoice series, which is what makes a line a credit. */
  invoice_series: string | null;
  booking_status: string | null;
  booking_ref: string | null;
  pnr: string | null;
  vendor: string | null;
  booked_date: string | null;
  travel_date: string | null;
  /** This row's own signed settled figure, parsed once at resolve time. Present even on a
   *  row that will never be billed — that is what lets the gaps view show the money. */
  amount: number | null;
  bill_kind: string | null;
  bill_status: string;
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
  /** Passengers this booking bills for — a fixed markup is multiplied by it. */
  pax_count: number;
  /** "file" (read off the statement), "default" (the file said nothing usable → 1), "user". */
  pax_source: string;
  /** What the statement itself says, so an edited figure can show what it replaced. */
  pax_in_file: number;
  /** The pax on the ticket already in billing, or null when not sent. */
  ticket_pax_count: number | null;
};

type PartyGap = { status: string; reason: string | null; count: number; sample_passengers: string[] };
type ExcludedGap = {
  bill_kind: string; product: string | null; reason: string | null;
  count: number; amount: number; sample_refs: string[];
};
type Gaps = { party: PartyGap[]; excluded: ExcludedGap[] };

type Summary = {
  billable_rows: number; resolved_rows: number; unresolved_rows: number;
  projected_rows: number; projected_tickets: number;
  resolution_status: string;
  summary: Record<string, number>;
  state_counts: Record<string, number>;
  customers_in_scope: number;
  /** The coverage figures. Every screen that shows a numerator shows these too. */
  total_rows: number;
  not_billable_rows: number;
  kind_counts: Record<string, number>;
  product_counts: Record<string, number>;
  /** The billable rows per markup category, with their net money (credits included). */
  category_counts: Record<string, CategoryCount>;
  credit_rows: number;
  /** Rows still carrying the flights-only verdict from before every category billed. */
  needs_rematch: number;
  /** Cancelled bookings that still bill the charge the vendor kept — worth a look. */
  cancelled_positive_rows: number;
};

type CategoryCount = { label: string; rows: number; amount: number; credit_rows: number };

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
  unresolved: "No match", excluded: "Not billable",
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
  withdrawn: "Party removed", ready: "Ready to send", no_party: "Needs a party",
  not_billable: "Not billable",
};

/** Mirrors services/tp_api_billing_projection's BILL_KINDS. */
const KIND_LABEL: Record<string, string> = {
  sale: "Charge", refund: "Credit",
  no_category: "No billing category", pending: "Payment pending",
  cancelled: "Cancelled — nothing to bill", needs_review: "Refund to review",
  no_amount: "No amount",
  not_flight: "Needs Re-match",   // legacy verdict from before every category billed
};

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
  // The row's own reason, which names the product — far better than a generic sentence.
  if (r.billing_state === "not_billable") {
    return r.bill_match_reason ?? "This row is not billed from here.";
  }
  if (r.billing_state === "invoiced") return "Already on an invoice — locked, and re-sending cannot change it.";
  if (r.billing_state === "sent")
    return "Already in billing. Change who it is billed to from Billing → Sold Tickets.";
  if (r.billing_state === "withdrawn")
    return "In billing but no longer has a party. Send the whole upload to take it back out.";
  return "No party yet — pick one first.";
}

/** In billing, so this screen no longer owns its party — the ticket is what billing reads. */
const locked = (r: Row) => r.projected_ticket_id != null;
const notBillable = (r: Row) => r.billing_state === "not_billable";

function billingHint(r: Row): string | undefined {
  switch (r.billing_state) {
    case "stale":
      if (r.ticket_pax_count != null && r.ticket_pax_count !== r.pax_count && !r.billed_party_name) {
        return `Sent to billing with ${r.ticket_pax_count} pax, but this row now says ${r.pax_count}. `
          + "Send it again so the markup is charged for the right number of passengers.";
      }
      return `Sent to billing as ${r.billed_party_name || "another party"}, but this row now says `
        + `${r.party_name || "nobody"}. Send it again so billing catches up.`;
    case "invoiced":
      return `On invoice #${r.billing_id}. Locked — re-sending will not change it.`;
    case "withdrawn":
      return "This row is in billing but no longer has a party. Give it one and send again, "
        + "or send the whole upload to take it back out.";
    case "sent":
      return "In billing. Change who it is billed to from Billing → Sold Tickets.";
    case "not_billable":
      return r.bill_match_reason ?? undefined;
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

export default function TpApiBillingWorklist({
  apiBase, batchId, fileName, resolutionStatus, rowCount, onBack, onChanged,
}: {
  apiBase: string;
  batchId: string;
  fileName: string | null;
  /** The batch's resolution_status when it was opened. Decides whether opening the screen
   *  is allowed to run the matcher — see the mount effect. */
  resolutionStatus: string;
  /** The upload's row count, so the coverage line can be drawn before the first summary
   *  lands. The summary's own `total_rows` supersedes it. */
  rowCount?: number;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [gaps, setGaps] = useState<Gaps>({ party: [], excluded: [] });
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [billState, setBillState] = useState("");
  const [productFilter, setProductFilter] = useState("");
  // A markup category slug, set from the category strip. Separate from `productFilter`,
  // which is the file's own product text ("Flight") and also reaches uncategorised rows.
  const [categoryFilter, setCategoryFilter] = useState("");
  const [search, setSearch] = useState("");
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
  }, []);

  useEffect(() => { void loadParties(); }, [loadParties]);

  const rowParams = useCallback(() => ({
    ...(filter ? { status: filter } : {}),
    ...(billState ? { billing_state: billState } : {}),
    ...(productFilter ? { product: productFilter } : {}),
    ...(categoryFilter ? { category: categoryFilter } : {}),
    ...(search.trim() ? { q: search.trim() } : {}),
  }), [filter, billState, productFilter, categoryFilter, search]);

  // A monotonic sequence, not a boolean: with the search debounced, a slow "RAV" response
  // would otherwise land after a fast "RAVI" one and paint the wrong rows.
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
        `${data.billable_rows.toLocaleString()} of ${data.total_rows.toLocaleString()} rows can be billed`
        + (data.credit_rows ? ` (${data.credit_rows.toLocaleString()} credits)` : "")
        + `; ${data.resolved_rows.toLocaleString()} have a party.`
        + (data.not_billable_rows ? ` ${data.not_billable_rows.toLocaleString()} cannot be billed.` : "")
        + (staleNow ? ` ${staleNow.toLocaleString()} already in billing now need re-sending.` : ""),
      );
      await Promise.all([load(0), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not resolve customers.")); }
    finally { setBusy(null); }
  }, [apiBase, batchId, load, refreshSummary, onChanged]);

  // Matching is a WRITE — it re-classifies as well as re-matches. Running it just because
  // someone opened the screen would re-stamp every non-overridden row, and on an upload
  // already sent to billing that can silently re-point a row billing is using. So it runs
  // only on the genuine first open, which the uploads list labels "Set up billing".
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

  // Paging KEEPS the selection — ticking rows across pages is the point, and the action bar
  // always states the count, which is what makes that safe.
  const goToPage = (off: number) => load(off);

  /** The party payload for a picked option. WHO FLEW and WHO PAYS are separate answers. */
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
      toast.success(`${data.rows_updated.toLocaleString()} bookings billed to this party.`);
      await Promise.all([load(0), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not set the default party.")); }
    finally { setBusy(null); }
  };

  /** A number corrects the row's pax; null puts it back on the statement's own figure. */
  const setRowPax = async (row: Row, pax: number | null) => {
    try {
      await api.patch(`${apiBase}/rows/${row.id}/pax-count`, { pax_count: pax });
      await load(offset);
    } catch (e) { toast.error(errText(e, "Could not change the pax count.")); }
  };

  const setRowParty = async (row: Row, opt: BillingParty | null, direct = false) => {
    try {
      await api.patch(`${apiBase}/rows/${row.id}/billing-party`, partyBody(opt, direct));
      await Promise.all([load(offset), refreshSummary()]);
      onChanged();
    } catch (e) { toast.error(errText(e, "Could not set the party for this row.")); }
  };

  /** Switch a row between billing the person's employer and billing them directly. */
  const setRowPayer = async (row: Row, mode: "corporate" | "direct") => {
    if (!row.bill_customer_id) return;
    const opt = parties.find(p => p.kind === "customer" && p.value === row.bill_customer_id) ?? null;
    if (!opt) return;
    await setRowParty(row, opt, mode === "direct");
  };

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

  /** Needs a corporate to file them under and nobody already named. */
  const canAddToMaster = (r: Row) =>
    !!r.passenger && !!r.bill_corporate_id && !r.bill_customer_id
    && !notBillable(r) && !locked(r);

  const addableSelected = rows.filter(r => selected.has(r.id) && canAddToMaster(r)).length;

  const applyBulkParty = async () => {
    if (!bulkPick || !bulkKind) { toast.error("Pick a customer or corporate first."); return; }
    setBusy("bulk");
    try {
      const { data } = await api.patch<{
        rows_updated: number; skipped_not_billable: number; skipped_in_billing: number;
      }>(`${apiBase}/batches/${batchId}/billing-party-bulk`, {
        row_ids: [...selected],
        ...partyBody({ value: bulkPick, kind: bulkKind, label: "" }),
      });
      toast.success(
        `${data.rows_updated.toLocaleString()} bookings billed to this party.`
        + (data.skipped_in_billing ? ` ${data.skipped_in_billing} already in billing.` : "")
        + (data.skipped_not_billable ? ` ${data.skipped_not_billable} not billable, skipped.` : ""),
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
        skipped_not_billable: number; skipped_by_reason: Record<string, number>;
        sent_by_category: Record<string, number>; credits: number;
        projected_tickets: number;
      }>(`${apiBase}/batches/${batchId}/send-to-billing`, ids ? { row_ids: ids } : {});
      // "40 train, 5 hotel" — which billing lines each category produced.
      const perCategory = Object.entries(data.sent_by_category ?? {})
        .map(([c, n]) => `${n} ${categoryLabel(c).toLowerCase()}`).join(", ");
      const bits = [
        data.created ? `${data.created} line${data.created === 1 ? "" : "s"} added` : null,
        data.updated ? `${data.updated} updated` : null,
        data.deleted ? `${data.deleted} removed` : null,
        data.skipped_billed ? `${data.skipped_billed} already on an invoice, left alone` : null,
        data.skipped_no_party ? `${data.skipped_no_party} skipped — no party` : null,
      ].filter(Boolean);
      toast.success(
        (data.scoped ? `Sent ${data.requested.toLocaleString()} selected rows` : "Sent to billing")
        + ` — ${bits.join(", ") || "nothing to do"}.`
        + (perCategory ? ` In billing now: ${perCategory}` : "")
        + (data.credits ? ` (${data.credits} credit${data.credits === 1 ? "" : "s"}).` : perCategory ? "." : ""),
        { duration: 6000 },
      );
      // NEVER a bare success on a multi-product file. Per reason, not a lump sum: "3 payment
      // pending" is actionable in a way "3 skipped" is not.
      const why = Object.entries(data.skipped_by_reason ?? {})
        .map(([k, n]) => `${n} ${(KIND_LABEL[k] ?? k).toLowerCase()}`);
      if (why.length) {
        toast(`${data.skipped_not_billable} rows not billed: ${why.join(", ")}.`,
              { icon: "ℹ️", duration: 7000 });
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

  // No "Need a look" chip here, unlike NDC: the six slots go to the coverage story instead
  // (Rows / Billable / Credits / Not billable), which is this type's real question. The
  // ambiguous and initials-only rows are still reachable — through the Match filter, and
  // through the party section of the gaps modal the button below links to.
  const sc = summary?.state_counts ?? {};
  const needResend = (sc.stale ?? 0) + (sc.withdrawn ?? 0);
  const gapRows = gaps.party.reduce((n, g) => n + g.count, 0);
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + rows.length, total);
  const hasFilters = !!(search || filter || billState || productFilter || categoryFilter);
  const overCap = selected.size > MAX_SELECTION;
  const totalRows = summary?.total_rows ?? rowCount ?? 0;
  const notBillableRows = summary?.not_billable_rows ?? 0;
  const vendor = rows.find((r) => r.vendor)?.vendor ?? null;
  // The products actually excluded, with their money — the banner's own summary of the
  // gaps modal, so the number is visible without opening anything.
  const excludedBits = gaps.excluded
    .filter((g) => g.count > 0)
    .map((g) => `${g.count} ${(KIND_LABEL[g.bill_kind] ?? g.bill_kind).toLowerCase()}`
      + (g.product ? ` ${g.product.toLowerCase()}` : "")
      + (g.amount ? ` · ${inr(g.amount)}` : ""));
  const categoryStrip = Object.entries(summary?.category_counts ?? {});
  const needsRematch = summary?.needs_rematch ?? 0;

  return (
    <div>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <button onClick={onBack} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to uploads
        </button>
        <span className="text-slate-300">|</span>
        <h3 className="text-sm font-semibold text-slate-800 truncate max-w-[320px]" title={fileName ?? undefined}>
          Billing · {fileName || "upload"}
          {/* One file is one vendor, so it belongs here rather than in a column. */}
          {vendor && <span className="font-normal text-slate-400"> · {vendor}</span>}
        </h3>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={resolve} disabled={!!busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
            title="Re-reads every row's product and amount and re-matches every passenger. Your own picks survive.">
            {busy === "resolve" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Re-match
          </button>
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

      {/* An upload classified before every category billed. Its hotel and train rows still
          carry the old "not a flight" verdict, and only a Re-match (a write, and the user's
          call) re-reads them. Amber and first, because until then this screen understates
          what the file can bill. */}
      {needsRematch > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-800">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            <strong>{needsRematch.toLocaleString()} row{needsRematch === 1 ? " was" : "s were"} classified
              before hotels, trains, buses and cars became billable.</strong>{" "}
            Re-match to bill them at each party&apos;s category markup — parties you picked by hand are kept.{" "}
            <button onClick={resolve} disabled={!!busy} className="font-semibold underline hover:no-underline disabled:opacity-50">
              Re-match now
            </button>
          </span>
        </div>
      )}

      {/* Six chips, and the first exists to keep every other number honest: a multi-product
          file rarely bills every line it carries. */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-2">
        <Chip label="Rows" value={totalRows} tone="bg-white border-slate-200 text-slate-700"
              hint="Every line in this upload, whatever the product." />
        <Chip label="Billable" value={summary?.billable_rows ?? 0} tone="bg-white border-slate-200 text-slate-700"
              hint="Flight, hotel, train, bus and car lines that settled — sales and credits." />
        <Chip label="Have a party" value={summary?.resolved_rows ?? 0} tone="bg-emerald-50 border-emerald-200 text-emerald-700" />
        <Chip label="Credits" value={summary?.credit_rows ?? 0} tone="bg-red-50 border-red-200 text-red-700"
              hint="Cancellations and refunds. They bill as negative lines to the same party, reversing markup and GST." />
        <Chip label="Not billable" value={notBillableRows} tone="bg-slate-50 border-slate-200 text-slate-500"
              hint="Pending payments, cancellations with nothing to bill, refunds to review, and lines with no category or amount." />
        <Chip label="In billing" value={summary?.projected_tickets ?? 0} tone="bg-sky-50 border-sky-200 text-sky-700"
              hint="Lines sent to Corporate / Customer billing from this upload." />
      </div>

      {/* What each category bills, net of its credits — the markup each line gets is the
          party's for that category, so this is the split the invoices will follow. */}
      {categoryStrip.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {categoryStrip.map(([slug, c]) => (
            <button key={slug} type="button"
              onClick={() => setCategoryFilter((cur) => (cur === slug ? "" : slug))}
              aria-pressed={categoryFilter === slug}
              title={`${c.rows} billable ${c.label.toLowerCase()} line${c.rows === 1 ? "" : "s"}`
                + (c.credit_rows ? `, ${c.credit_rows} of them credits` : "")
                + `. Net of credits. Click to show only ${c.label.toLowerCase()} rows.`}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] text-slate-600 ${
                categoryFilter === slug ? "border-blue-400 bg-blue-50/60" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <CategoryBadge category={slug} />
              <span className="tabular-nums font-semibold text-slate-800">{c.rows.toLocaleString()}</span>
              <span className="tabular-nums text-slate-400">· {inr(c.amount)}</span>
              {c.credit_rows > 0 && (
                <span className="text-[10px] text-red-600">{c.credit_rows} credit{c.credit_rows === 1 ? "" : "s"}</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* THE COVERAGE BANNER. Slate, not amber: this is the shape of the file, not a
          failure. It is always rendered when anything is out, because a numerator with no
          denominator is how "2 tickets in billing" comes to read as "all of it". */}
      {notBillableRows > needsRematch && totalRows > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 mb-3 text-xs text-slate-600">
          <Info className="w-4 h-4 shrink-0 mt-0.5 text-slate-400" />
          <span>
            <strong className="text-slate-800">
              {(summary?.billable_rows ?? 0).toLocaleString()} of {totalRows.toLocaleString()} rows
              in this upload can be billed.
            </strong>{" "}
            The other {notBillableRows.toLocaleString()}
            {excludedBits.length > 0 && ` (${excludedBits.join(", ")})`} stay on the statement
            and are not invoiced from here.{" "}
            <button onClick={() => setShowGaps(true)} className="font-semibold underline hover:no-underline">
              See why each is out
            </button>
          </span>
        </div>
      )}

      {summary && summary.customers_in_scope === 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>Your Customer master is empty, so no passenger can match. Add customers under
            User master → Employee Master, or bill the whole upload to one party below.</span>
        </div>
      )}

      {/* A cancelled booking that still bills: the vendor kept a cancellation charge, and
          Total Paid − Refund is what is owed. Not an error, but nothing else on the screen
          would surface it before it reached an invoice. */}
      {!!summary?.cancelled_positive_rows && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {summary.cancelled_positive_rows.toLocaleString()} cancelled booking
            {summary.cancelled_positive_rows === 1 ? "" : "s"} still bill the cancellation charge
            the vendor kept (Total Paid − Refund) — check these before invoicing.
          </span>
        </div>
      )}

      {/* The one thing on this screen that can put a wrong party on an invoice. */}
      {needResend > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 mb-3 text-xs text-orange-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {needResend.toLocaleString()} bookings are already in billing but no longer match what
            this statement says — billing would use the old party. Send them again to catch it up.
            Tickets already on an invoice are locked and will not change.{" "}
            <button onClick={() => { setBillState("stale"); setProductFilter(""); setCategoryFilter(""); }}
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
            Every billable row with no party is stamped, whatever its category — rows you
            already set, and rows that cannot be billed, are left alone.
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Passenger, booking ref or PNR" className={TEXT_CLS} />
        </div>
        {/* This screen's own filter, and the one a user reaches for first on a mixed file. */}
        <select value={productFilter} onChange={(e) => setProductFilter(e.target.value)} className={SELECT_CLS}>
          <option value="">Any category</option>
          {Object.keys(summary?.product_counts ?? {})
            .filter((p) => p !== "—")
            .map((p) => (
              <option key={p} value={p}>{p} ({summary?.product_counts[p]})</option>
            ))}
        </select>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className={SELECT_CLS}>
          <option value="">Any match status</option>
          <option value="unresolved">No match</option>
          <option value="ambiguous">Several match</option>
          <option value="initials_only">Initials only</option>
          <option value="defaulted">Default party</option>
          <option value="overridden">Set by you</option>
          <option value="resolved">Matched</option>
          <option value="excluded">Not billable</option>
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
          <button onClick={() => { setSearch(""); setFilter(""); setBillState(""); setProductFilter(""); setCategoryFilter(""); }}
            className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-700">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
        {(gaps.party.length > 0 || gaps.excluded.length > 0) && (
          <button onClick={() => setShowGaps(true)}
            className="ml-auto inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 hover:text-blue-600">
            <Info className="w-3.5 h-3.5" />
            Why {(gapRows + notBillableRows).toLocaleString()} rows aren&apos;t billed
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
                <th className="text-left px-3 py-2.5 font-semibold">Category</th>
                <th className="text-left px-3 py-2.5 font-semibold">Passenger</th>
                <th className="text-left px-3 py-2.5 font-semibold"
                    title="Passengers on the booking. A fixed markup is charged per passenger.">Pax</th>
                <th className="text-left px-3 py-2.5 font-semibold">Booking ref</th>
                <th className="text-left px-3 py-2.5 font-semibold">PNR</th>
                <th className="text-left px-3 py-2.5 font-semibold">Booked</th>
                <th className="text-left px-3 py-2.5 font-semibold">Travel</th>
                <th className="text-left px-3 py-2.5 font-semibold">Status</th>
                <th className="text-right px-3 py-2.5 font-semibold">Amount</th>
                <th className="text-left px-3 py-2.5 font-semibold">Match</th>
                <th className="text-left px-3 py-2.5 font-semibold">Billing</th>
                <th className="text-left px-3 py-2.5 font-semibold w-[220px]">Bill to</th>
                <th className="text-left px-3 py-2.5 font-semibold w-[200px]">Corporate</th>
              </tr>
            </thead>
            {/* Dim rather than blank, so typing in the search box does not strobe. */}
            <tbody className={`divide-y divide-slate-100 ${loading && rows.length > 0 ? "opacity-50 transition-opacity" : ""}`}>
              {loading && rows.length === 0 ? (
                <tr><td colSpan={14} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={14} className="px-3 py-10 text-center text-slate-400">
                  {hasFilters ? "No rows match what you are looking for." : "No rows in this bucket."}
                </td></tr>
              ) : rows.map((r) => {
                const blocked = whyNotSendable(r);
                const out = notBillable(r);
                return (
                <tr key={r.id} className={`hover:bg-slate-50/60 ${selected.has(r.id) ? "bg-blue-50/50" : ""} ${out ? "opacity-60" : ""}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleRow(r.id)}
                      disabled={!!blocked} title={blocked ?? undefined}
                      aria-label={`Select ${r.passenger || "row"}`}
                      className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                  </td>
                  {/* This screen's answer to NDC's Line column: which markup category the row
                      bills under — and, on a credit, that it reduces the bill. */}
                  <td className="px-3 py-2 whitespace-nowrap">
                    <CategoryBadge category={r.category}
                      title={r.category
                        ? `Billed at the party's ${categoryLabel(r.category).toLowerCase()} markup.`
                        : `${r.product_type || "This row"} has no billing category.`} />
                    {r.bill_kind === "refund" && (
                      <span className="ml-1 inline-flex px-1 py-0.5 rounded border border-red-200 bg-red-50 text-[9px] font-semibold uppercase text-red-600"
                        title={r.invoice_series
                          ? `A credit: ${r.invoice_series}/ is ${r.vendor ?? "the vendor"}'s cancellation / refund series. It bills as a negative line.`
                          : "A credit — it bills as a negative line to the same party."}>
                        Credit
                      </span>
                    )}
                  </td>
                  {/* Who travelled, and what the booking was — the same one-line description
                      the billing line and the invoice will carry. */}
                  <td className="px-3 py-2 text-slate-700 max-w-55">
                    <div className="truncate" title={r.passenger_raw ?? r.passenger ?? undefined}>{r.passenger || "—"}</div>
                    {r.service_summary && (
                      <div className="truncate text-[10px] text-slate-400" title={r.service_summary}>{r.service_summary}</div>
                    )}
                  </td>
                  {/* Editable exactly where the party picker is: a billable row not yet in billing. */}
                  <td className="px-3 py-2">
                    <PaxCell key={`${r.id}-${r.pax_count}-${r.pax_source}`}
                      pax={r.pax_count} source={r.pax_source} inFile={r.pax_in_file}
                      label={r.passenger || "this row"}
                      editable={!out && !locked(r)} onSave={(pax) => setRowPax(r, pax)} />
                  </td>
                  <td className="px-3 py-2 text-slate-500 font-mono text-[11px] whitespace-nowrap truncate max-w-[150px]">
                    {r.booking_ref || <span className="text-slate-300">none</span>}
                  </td>
                  {/* "—" on a hotel row is the point, not a gap: this type exists because
                      those rows have no PNR and the flight-shaped importers refused them. */}
                  <td className="px-3 py-2 text-slate-500 font-mono text-[11px]">{r.pnr || "—"}</td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDate(r.booked_date)}</td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDate(r.travel_date)}</td>
                  {/* The vendor's own status — Pending and Cancelled are WHY two of the
                      exclusions fire, so showing it makes the verdict explicable. TBO ships no
                      status column at all, so the verdict itself is the tooltip. */}
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap"
                      title={KIND_LABEL[r.bill_kind ?? ""] ?? undefined}>
                    {r.booking_status || "—"}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${(r.amount ?? 0) < 0 ? "text-red-600" : "text-slate-700"}`}>
                    {r.amount == null ? (
                      // A cell that would not parse. Shown as unknown rather than zero — a
                      // total silently short by one line is the failure to avoid.
                      <span className="text-amber-600" title="This row's amount could not be read from the file.">—</span>
                    ) : inr(r.amount)}
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
                    {out ? (
                      // The reason travels as the tooltip, so a dimmed row is never mute.
                      <span className="text-[11px] text-slate-400" title={r.bill_match_reason ?? undefined}>
                        Not billed from here
                      </span>
                    ) : (
                      <LccPartyPicker
                        size="sm"
                        options={parties}
                        disabled={locked(r)}
                        // WHO FLEW, whenever the row names anyone — a row billed to an
                        // employer still knows its passenger.
                        value={r.bill_customer_id ?? r.bill_corporate_id}
                        // Ids repeat across the two masters, so name the list this id
                        // belongs to or corporate #7 answers for customer #7.
                        valueKind={r.bill_customer_id ? "customer" : "corporate"}
                        onChange={(opt) => setRowParty(r, opt)}
                        placeholder="Pick a party…"
                      />
                    )}
                  </td>

                  {/* WHO PAYS. Separate from who flew because they are separate answers. */}
                  <td className="px-3 py-2">
                    {out ? (
                      <span className="text-[11px] text-slate-400">—</span>
                    ) : !r.bill_customer_id ? (
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
                            ? "The company pays — this booking shows in Corporate Billing"
                            : "The passenger pays — this booking shows in Customer Billing"}
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

      {/* Two sections, because the two are different problems. "No party" is fixable with a
          picker. "Not sent to billing" is not fixable and is not meant to be — it is
          reported so a five-row file billing two of them says so out loud, WITH the money. */}
      {showGaps && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
             onClick={() => setShowGaps(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-2.5 px-5 pt-5 pb-3">
              <Info className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-sm font-semibold text-slate-800">Why these rows aren&apos;t billed</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Grouped by the reason. The first list is fixable with a party; the second is not.
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
                      <th className="text-right px-4 py-2 font-semibold">Rows</th>
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
              {gaps.excluded.length > 0 && (
                <>
                  <div className="bg-slate-50 border-y border-slate-200 px-4 py-2.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      Not sent to billing
                    </p>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      These are real statement lines. They are stored, searchable and exportable
                      from the upload — they are simply not billed: nothing has settled, the
                      vendor refunded all of it, or there is no category to price them under.
                    </p>
                  </div>
                  <table className="w-full text-xs">
                    <thead className="bg-white border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="text-left px-4 py-2 font-semibold">Category</th>
                        <th className="text-left px-4 py-2 font-semibold">Why</th>
                        <th className="text-right px-4 py-2 font-semibold">Rows</th>
                        {/* The load-bearing column: a count alone lets a five-figure sum
                            hide behind the word "1". */}
                        <th className="text-right px-4 py-2 font-semibold">Amount</th>
                        <th className="text-left px-4 py-2 font-semibold">For example</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {gaps.excluded.map((g, i) => (
                        <tr key={i}>
                          <td className="px-4 py-2">
                            {/* The file's own product text — an uncategorised row has no slug
                                to colour, and "Visa" is exactly what the user needs to read. */}
                            <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${
                              g.product ? "bg-slate-100 text-slate-600 border-slate-200" : "bg-red-50 text-red-700 border-red-200"}`}>
                              {g.product || "No product"}
                            </span>
                          </td>
                          <td className="px-4 py-2 text-slate-600">{g.reason ?? "—"}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-slate-700">{g.count.toLocaleString()}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-slate-700">{inr(g.amount)}</td>
                          <td className="px-4 py-2 text-slate-400 font-mono truncate max-w-[220px]">{g.sample_refs.join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
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
