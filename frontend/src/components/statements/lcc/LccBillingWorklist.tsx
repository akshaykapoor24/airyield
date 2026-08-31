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
// Bucket chips + reason grouping follow the deal-upload review table and the BSP
// commission gaps tab — the reason strings are identical per gap type on purpose, so
// 108 passengers collapse into a handful of groups instead of 108 rows of one.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Loader2, RefreshCw, Send,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import LccPartyPicker, { PartyOption } from "./LccPartyPicker";

const PAGE = 50;

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
};

type Gap = { status: string; reason: string | null; count: number; sample_passengers: string[] };

type Summary = {
  billable_rows: number; resolved_rows: number; unresolved_rows: number;
  summary: Record<string, number>; customers_in_scope: number;
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
const KIND_LABEL: Record<string, string> = { sale: "Charge", refund: "Credit", payment: "Payment" };

const inr = (n: number | null) =>
  n == null ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

function fmtDate(s: string | null) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(); } catch { return s; }
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
  apiBase, batchId, fileName, onBack, onChanged,
}: {
  apiBase: string;
  batchId: string;
  fileName: string | null;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [parties, setParties] = useState<PartyOption[]>([]);
  const [defaultPick, setDefaultPick] = useState<number | null>(null);
  const [defaultKind, setDefaultKind] = useState<"customer" | "corporate" | null>(null);

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

  const load = useCallback(async (off = 0, status = filter) => {
    setLoading(true);
    try {
      const [rowsRes, gapsRes] = await Promise.all([
        api.get<{ total: number; rows: Row[] }>(`${apiBase}/batches/${batchId}/billing-rows`,
          { params: { offset: off, limit: PAGE, ...(status ? { status } : {}) } }),
        api.get<Gap[]>(`${apiBase}/batches/${batchId}/billing-gaps`),
      ]);
      setRows(rowsRes.data.rows); setTotal(rowsRes.data.total); setOffset(off);
      setGaps(gapsRes.data);
    } catch { toast.error("Failed to load the worklist."); }
    finally { setLoading(false); }
  }, [apiBase, batchId, filter]);

  const resolve = useCallback(async () => {
    setBusy("resolve");
    try {
      const { data } = await api.post<Summary>(`${apiBase}/batches/${batchId}/resolve-customers`, {});
      setSummary(data);
      toast.success(`${data.resolved_rows.toLocaleString()} of ${data.billable_rows.toLocaleString()} rows have a party.`);
      await load(0);
      onChanged();
    } catch { toast.error("Could not resolve customers."); }
    finally { setBusy(null); }
  }, [apiBase, batchId, load, onChanged]);

  // Match once when the worklist opens. A ref guard rather than an empty dep array,
  // so `resolve` stays in the dependency list without re-running on every reload.
  const matchedOnMount = useRef(false);
  useEffect(() => {
    if (matchedOnMount.current) return;
    matchedOnMount.current = true;
    resolve();
  }, [resolve]);

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
      await Promise.all([load(offset), resolve()]);
    } catch { toast.error("Could not set the default party."); }
    finally { setBusy(null); }
  };

  const setRowParty = async (row: Row, opt: PartyOption | null) => {
    try {
      await api.patch(`${apiBase}/rows/${row.id}/billing-party`, opt
        ? (opt.kind === "corporate"
            ? { customer_type: "corporate", corporate_id: opt.value }
            : { customer_type: "direct", customer_id: opt.value })
        : {});
      await load(offset);
      onChanged();
    } catch { toast.error("Could not set the party for this row."); }
  };

  const sendToBilling = async () => {
    setBusy("send");
    try {
      const { data } = await api.post<{ created: number; updated: number; deleted: number; skipped_billed: number }>(
        `${apiBase}/batches/${batchId}/send-to-billing`);
      const bits = [
        data.created ? `${data.created} added` : null,
        data.updated ? `${data.updated} updated` : null,
        data.deleted ? `${data.deleted} removed` : null,
        data.skipped_billed ? `${data.skipped_billed} already billed, left alone` : null,
      ].filter(Boolean);
      toast.success(`Sent to billing — ${bits.join(", ") || "nothing to do"}.`);
      await load(offset);
      onChanged();
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Could not send to billing.");
    } finally { setBusy(null); }
  };

  const s = summary?.summary ?? {};
  const needALook = (s.ambiguous ?? 0) + (s.initials_only ?? 0);
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + rows.length, total);
  const projected = useMemo(() => rows.filter((r) => r.projected_ticket_id).length, [rows]);

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
          <button onClick={sendToBilling} disabled={!!busy || !summary?.resolved_rows}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {busy === "send" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Send to billing
          </button>
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
        <Chip label="Payments excluded" value={s.excluded ?? 0} tone="bg-slate-50 border-slate-200 text-slate-400"
              hint="Money moved between accounts with no fare on the row — nothing to bill." />
      </div>

      {summary && summary.customers_in_scope === 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>Your Customer master is empty, so no passenger can match. Add customers under
            User master → Employee Master, or bill the whole upload to one party below.</span>
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

      {gaps.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white mb-3 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-semibold">Status</th>
                <th className="text-left px-3 py-2 font-semibold">Why</th>
                <th className="text-right px-3 py-2 font-semibold">Rows</th>
                <th className="text-left px-3 py-2 font-semibold">For example</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {gaps.map((g, i) => (
                <tr key={i}>
                  <td className="px-3 py-2">
                    <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${STATUS_STYLE[g.status] ?? STATUS_STYLE.unresolved}`}>
                      {STATUS_LABEL[g.status] ?? g.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{g.reason ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">{g.count.toLocaleString()}</td>
                  <td className="px-3 py-2 text-slate-400 truncate max-w-[280px]">{g.sample_passengers.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <select value={filter} onChange={(e) => { setFilter(e.target.value); load(0, e.target.value); }}
          className="px-2 py-1.5 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
          <option value="">All rows</option>
          <option value="unresolved">No match</option>
          <option value="ambiguous">Several match</option>
          <option value="initials_only">Initials only</option>
          <option value="defaulted">Default party</option>
          <option value="overridden">Set by you</option>
          <option value="resolved">Matched</option>
          <option value="excluded">Payment movements</option>
        </select>
        {projected > 0 && (
          <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600">
            <CheckCircle2 className="w-3.5 h-3.5" /> {projected} of the rows on this page are in billing
          </span>
        )}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="text-left px-3 py-2.5 font-semibold">Passenger</th>
                <th className="text-left px-3 py-2.5 font-semibold">PNR</th>
                <th className="text-left px-3 py-2.5 font-semibold">Date</th>
                <th className="text-left px-3 py-2.5 font-semibold">Kind</th>
                <th className="text-right px-3 py-2.5 font-semibold">Amount</th>
                <th className="text-left px-3 py-2.5 font-semibold">Status</th>
                <th className="text-left px-3 py-2.5 font-semibold w-[260px]">Bill to</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr><td colSpan={7} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={7} className="px-3 py-10 text-center text-slate-400">No rows in this bucket.</td></tr>
              ) : rows.map((r) => (
                <tr key={r.id} className={`hover:bg-slate-50/60 ${r.bill_kind === "payment" ? "opacity-55" : ""}`}>
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
              ))}
            </tbody>
          </table>
        </div>
        {total > 0 && (
          <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500">
            <span>Showing {start.toLocaleString()}–{end.toLocaleString()} of {total.toLocaleString()}</span>
            <div className="flex items-center gap-1">
              <button disabled={offset === 0 || loading} onClick={() => load(Math.max(0, offset - PAGE))}
                className="px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Prev</button>
              <button disabled={offset + PAGE >= total || loading} onClick={() => load(offset + PAGE)}
                className="px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
