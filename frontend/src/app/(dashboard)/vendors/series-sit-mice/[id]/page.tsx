"use client";

/**
 * One contract, end to end.
 *
 * `params` is a Promise in this version of Next and is unwrapped with React's `use()` —
 * see node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/dynamic-routes.md.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import {
  ArrowLeft, CalendarClock, Check, Loader2, Plus, RefreshCw, TriangleAlert,
} from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import InventoryTab from "@/components/vendors/series/InventoryTab";
import MoneyTab from "@/components/vendors/series/MoneyTab";
import TermsTab from "@/components/vendors/series/TermsTab";
import DocumentsCard from "@/components/vendors/series/DocumentsCard";
import { SMALL_INPUT } from "@/components/vendors/series/editors";
import {
  ANCHOR_LABEL, API_BASE, CABIN_LABEL, CONTRACT_STATUS_LABEL, CONTRACT_STATUS_STYLE,
  CONTRACT_TYPE_LABEL, DEADLINE_ANCHORS, DEADLINE_TYPE_LABEL, MANUAL_DEADLINE_TYPES,
  MATCH_STATUS_LABEL, MATCH_STATUS_STYLE, URGENCY_STYLE,
  type ContractDetail, type Deadline, inr, relativeDays,
} from "@/lib/series";

const TABS = ["Inventory", "Money", "Terms", "Deadlines"] as const;

export default function ContractDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [contract, setContract] = useState<ContractDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Inventory");
  const [matching, setMatching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const { data } = await api.get<ContractDetail>(`${API_BASE}/${id}`);
      setContract(data);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  /** Re-read without the full-page loader — for changes made from a card on this page. */
  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<ContractDetail>(`${API_BASE}/${id}`);
      setContract(data);
    } catch (e) {
      toast.error(apiError(e));
    }
  }, [id]);

  const rematch = async () => {
    setMatching(true);
    try {
      await api.post(`${API_BASE}/match`, null, { params: { contract_id: id } });
      await load();
      toast.success("Rolled up from the tickets on this contract's PNRs");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setMatching(false);
    }
  };

  if (loading) {
    return (
      <div className="py-24 text-center text-xs text-gray-400">
        <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading contract…
      </div>
    );
  }
  if (error || !contract) {
    return (
      <div className="py-24 text-center">
        <p className="text-sm text-red-500">{error || "Contract not found"}</p>
        <Link href="/vendors/series-sit-mice" className="text-xs text-[#1e3a5f] font-semibold mt-3 inline-block">
          Back to contracts
        </Link>
      </div>
    );
  }

  const c = contract;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <button
            onClick={() => router.push("/vendors/series-sit-mice")}
            className="flex items-center gap-1 text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-1 hover:text-gray-600"
          >
            <ArrowLeft className="w-3 h-3" /> Series / SIT / MICE / Group
          </button>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold text-gray-900 font-mono">
              {c.contract_number ?? `Contract #${c.id}`}
            </h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-600">
              {CONTRACT_TYPE_LABEL[c.contract_type ?? ""] ?? c.contract_type}
            </span>
            {c.status && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                CONTRACT_STATUS_STYLE[c.status] ?? CONTRACT_STATUS_STYLE.draft
              }`}>
                {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
              </span>
            )}
            {c.match_status && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                MATCH_STATUS_STYLE[c.match_status] ?? MATCH_STATUS_STYLE.pending
              }`}>
                {MATCH_STATUS_LABEL[c.match_status] ?? c.match_status}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {[
              c.group_name,
              c.group_reference,
              c.agent_name ?? c.airline_name,
              c.cabin ? CABIN_LABEL[c.cabin] ?? c.cabin : null,
              c.travel_from ? `travel ${c.travel_from}${c.travel_to && c.travel_to !== c.travel_from ? ` – ${c.travel_to}` : ""}` : null,
            ].filter(Boolean).join(" · ")}
          </p>
          <p className="text-[11px] text-gray-400 mt-0.5">
            {[
              c.minimum_pax ? `min ${c.minimum_pax} pax` : null,
              c.materialization_floor_pct != null ? `${c.materialization_floor_pct}% materialisation` : null,
              c.foc_per_paid ? `FOC 1 per ${c.foc_per_paid}` : null,
              c.baggage_allowance ? `baggage ${c.baggage_allowance}` : null,
              c.event_name,
              c.supplier_ref ? `supplier ref ${c.supplier_ref}` : null,
              c.option_expires_on ? `offer valid until ${c.option_expires_on}` : null,
            ].filter(Boolean).join(" · ")}
          </p>
        </div>

        <button
          onClick={rematch}
          disabled={matching}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${matching ? "animate-spin" : ""}`} /> Re-match tickets
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Tile label="Cost" value={inr(c.contract_cost)} hint={`${c.seats_allocated} seats`} />
        <Tile label="Issued" value={inr(c.amount_issued)} hint={`${c.seats_ticketed} ticketed`} />
        <Tile
          label="Margin"
          value={inr(c.margin)}
          hint="sell − cost − penalties"
          tone={c.margin > 0 ? "good" : c.margin < 0 ? "bad" : undefined}
        />
        <Tile
          label="Outstanding"
          value={inr(c.amount_due)}
          hint={c.overdue_count ? `${c.overdue_count} overdue` : "on schedule"}
          tone={c.overdue_count ? "bad" : undefined}
        />
        <Tile
          label="Next deadline"
          value={
            c.next_deadline
              ? DEADLINE_TYPE_LABEL[c.next_deadline.deadline_type ?? ""] ?? c.next_deadline.deadline_type ?? "—"
              : "—"
          }
          hint={c.next_deadline ? relativeDays(c.next_deadline.days_remaining) : "nothing pending"}
          tone={c.next_deadline?.urgency === "overdue" ? "bad" : undefined}
        />
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3.5 py-2 text-xs font-semibold border-b-2 -mb-px ${
              tab === t
                ? "border-[#1e3a5f] text-[#1e3a5f]"
                : "border-transparent text-gray-400 hover:text-gray-600"
            }`}
          >
            {t}
            {t === "Terms" && c.terms.length > 0 && (
              <span className="ml-1 text-[10px] font-normal text-gray-400">{c.terms.length}</span>
            )}
            {t === "Deadlines" && c.deadlines.some((d) => d.urgency === "overdue") && (
              <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-red-500 align-middle" />
            )}
          </button>
        ))}
      </div>

      {tab === "Inventory" && <InventoryTab contract={c} onChanged={setContract} />}
      {tab === "Money" && <MoneyTab contract={c} onChanged={setContract} />}
      {tab === "Terms" && <TermsTab contract={c} onChanged={setContract} />}
      {tab === "Deadlines" && <DeadlinesTab contract={c} onChanged={setContract} />}

      <DocumentsCard contract={c} onChanged={refresh} />

      {c.notes && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-3">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Notes</p>
          <p className="text-xs text-gray-600 whitespace-pre-wrap">{c.notes}</p>
        </div>
      )}
    </div>
  );
}

function Tile({
  label, value, hint, tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "good" | "bad";
}) {
  const colour = tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-red-600" : "text-gray-900";
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-3">
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={`text-base font-bold tabular-nums ${colour}`}>{value}</p>
      {hint && <p className="text-[10px] text-gray-400">{hint}</p>}
    </div>
  );
}

function DeadlinesTab({
  contract, onChanged,
}: {
  contract: ContractDetail;
  onChanged: (c: ContractDetail) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({
    deadline_type: "NAME_LIST",
    anchor: "DEPARTURE",
    offset_days: "",
    stated_date: "",
    allocation_id: "",
  });

  const patch = async (d: Deadline, body: Record<string, unknown>) => {
    setBusy(true);
    try {
      const { data } = await api.patch<ContractDetail>(
        `${API_BASE}/${contract.id}/deadlines/${d.id}`, body,
      );
      onChanged(data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post<ContractDetail>(`${API_BASE}/${contract.id}/deadlines/regenerate`);
      onChanged(data);
      toast.success("Timeline rebuilt");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    if (!draft.offset_days && !draft.stated_date) {
      toast.error("Give it either an offset from an anchor or the date the contract printed.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post<ContractDetail>(`${API_BASE}/${contract.id}/deadlines`, {
        deadline_type: draft.deadline_type,
        anchor: draft.anchor,
        offset_days: draft.offset_days ? Number(draft.offset_days) : null,
        stated_date: draft.stated_date || null,
        allocation_id: draft.allocation_id ? Number(draft.allocation_id) : null,
      });
      onChanged(data);
      setAdding(false);
      setDraft({ ...draft, offset_days: "", stated_date: "" });
      toast.success("Deadline added");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  const sorted = [...contract.deadlines].sort((a, b) =>
    (a.effective_date ?? "9999").localeCompare(b.effective_date ?? "9999"),
  );

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
        <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Timeline</p>
        <button
          onClick={() => setAdding((v) => !v)}
          className="ml-auto flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg"
        >
          <Plus className="w-3 h-3" /> Add deadline
        </button>
        <button
          onClick={regenerate}
          disabled={busy}
          className="flex items-center gap-1 text-[11px] font-semibold text-gray-600 hover:bg-gray-50 px-2 py-1 rounded-lg disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${busy ? "animate-spin" : ""}`} /> Rebuild
        </button>
      </div>

      {adding && (
        <div className="px-4 py-3 bg-blue-50/40 border-b border-blue-100">
          <div className="grid grid-cols-[1fr_1fr_90px_140px_1fr_auto_auto] gap-2 items-end">
            <div>
              <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Type</label>
              <select
                value={draft.deadline_type}
                onChange={(e) => setDraft({ ...draft, deadline_type: e.target.value })}
                className={SMALL_INPUT}
              >
                {/* Payments, departure, offer expiry and penalty steps are generated. */}
                {MANUAL_DEADLINE_TYPES.map((t) => (
                  <option key={t} value={t}>{DEADLINE_TYPE_LABEL[t]}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Anchor</label>
              <select
                value={draft.anchor}
                onChange={(e) => setDraft({ ...draft, anchor: e.target.value })}
                className={SMALL_INPUT}
              >
                {DEADLINE_ANCHORS.map((a) => (
                  <option key={a} value={a}>{ANCHOR_LABEL[a]}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Days</label>
              <input
                type="number"
                min="0"
                value={draft.offset_days}
                onChange={(e) => setDraft({ ...draft, offset_days: e.target.value })}
                placeholder="30"
                className={SMALL_INPUT}
              />
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">
                Date on contract
              </label>
              <input
                type="date"
                value={draft.stated_date}
                onChange={(e) => setDraft({ ...draft, stated_date: e.target.value })}
                className={SMALL_INPUT}
              />
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">Departure</label>
              <select
                value={draft.allocation_id}
                onChange={(e) => setDraft({ ...draft, allocation_id: e.target.value })}
                className={SMALL_INPUT}
              >
                <option value="">Whole contract</option>
                {contract.allocations.map((a) => (
                  <option key={a.id} value={a.id}>{a.departure_date ?? a.allocation_ref}</option>
                ))}
              </select>
            </div>
            <button
              onClick={() => setAdding(false)}
              className="px-3 py-1.5 text-[11px] font-semibold text-gray-500 hover:bg-white rounded-lg"
            >
              Cancel
            </button>
            <button
              onClick={add}
              disabled={busy}
              className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-[11px] font-semibold px-3 py-1.5 rounded-lg disabled:opacity-60"
            >
              {busy && <Loader2 className="w-3 h-3 animate-spin" />} Add
            </button>
          </div>
          <p className="text-[10px] text-gray-400 mt-1.5">
            Give it an offset and it follows the departure date wherever that moves. Add the
            date the contract printed as well and that one is what gets acted on — with any
            disagreement between the two flagged rather than hidden.
          </p>
        </div>
      )}

      {sorted.length === 0 ? (
        <p className="text-xs text-gray-400 py-10 text-center">
          No deadlines yet. They are generated from the payment schedule and departures.
        </p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50">
              {["DEADLINE", "DATE", "RULE", "WHEN", "STATUS", ""].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((d) => (
              <tr key={d.id} className="border-b border-gray-50">
                <td className="px-3 py-2 text-[11px] text-gray-700">
                  {DEADLINE_TYPE_LABEL[d.deadline_type ?? ""] ?? d.deadline_type}
                  {d.action_required && (
                    <span className="block text-[9px] text-gray-400">{d.action_required}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-[11px] text-gray-700 whitespace-nowrap">
                  {d.effective_date ?? "—"}
                  {d.has_divergence && (
                    <span
                      className="ml-1.5 inline-flex items-center gap-0.5 text-[9px] text-amber-600"
                      title={`The contract states ${d.stated_date}, but ${d.offset_days} days before departure works out to ${d.computed_date}. The stated date is what the airline will enforce.`}
                    >
                      <TriangleAlert className="w-3 h-3" /> differs
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-[11px] text-gray-500 whitespace-nowrap">
                  {d.offset_hours
                    ? `${d.offset_hours}h ${ANCHOR_LABEL[d.anchor ?? ""] ?? ""}`
                    : d.offset_days != null
                      ? `${d.offset_days}d ${ANCHOR_LABEL[d.anchor ?? ""] ?? ""}`
                      : "stated on contract"}
                </td>
                <td className="px-3 py-2">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                    URGENCY_STYLE[d.urgency ?? "scheduled"]
                  }`}>
                    {relativeDays(d.days_remaining)}
                  </span>
                </td>
                <td className="px-3 py-2 text-[11px] text-gray-500 capitalize">{d.status ?? "open"}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {(d.status ?? "open") === "open" && d.deadline_type !== "DEPARTURE" && (
                    <>
                      <button
                        onClick={() => patch(d, { status: "met" })}
                        disabled={busy}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 hover:bg-emerald-50 px-2 py-1 rounded-lg disabled:opacity-50"
                      >
                        <Check className="w-3 h-3" /> Done
                      </button>
                      <button
                        onClick={() => patch(d, { status: "waived" })}
                        disabled={busy}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-gray-400 hover:bg-gray-50 px-2 py-1 rounded-lg disabled:opacity-50"
                      >
                        Waive
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="px-4 py-2 text-[10px] text-gray-400 border-t border-gray-100 flex items-center gap-1.5">
        <CalendarClock className="w-3 h-3" />
        Dates are stored; how late they are is worked out against today every time you open
        this. Marking one done keeps it done through a rebuild.
      </p>
    </div>
  );
}
