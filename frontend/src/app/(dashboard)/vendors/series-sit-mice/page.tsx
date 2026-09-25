"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import {
  AlertTriangle, CalendarClock, Layers, PencilLine, RefreshCw, Search, Sparkles, Trash2, Wallet,
} from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import ContractWizard from "@/components/vendors/series/ContractWizard";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import SeriesReminders from "@/components/vendors/series/SeriesReminders";
import {
  API_BASE, CONTRACT_STATUS_LABEL, CONTRACT_STATUS_STYLE, CONTRACT_TYPES,
  CONTRACT_TYPE_LABEL, MATCH_STATUS_LABEL, MATCH_STATUS_STYLE, URGENCY_STYLE,
  type ActionCenter, type Contract, type MatchResult,
  DEADLINE_TYPE_LABEL, inr, relativeDays,
} from "@/lib/series";

const COLUMNS = [
  "TYPE", "CONTRACT", "COUNTERPARTY", "TRAVEL", "DEPARTURES", "TICKETED",
  "COST", "ISSUED", "MARGIN", "NEXT DEADLINE", "DUE", "STATUS", "",
];

export default function SeriesSitMicePage() {
  const router = useRouter();
  const [rows, setRows] = useState<Contract[]>([]);
  const [actions, setActions] = useState<ActionCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [matching, setMatching] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [toDelete, setToDelete] = useState<Contract | null>(null);
  // Gates the first list load behind the automatic match, so the page never renders
  // figures it is about to replace a moment later.
  const [matchedOnLoad, setMatchedOnLoad] = useState(false);
  // Bumped after each list load. Loading the action centre is what raises due reminders
  // on the server, so the reminder strip re-reads after it.
  const [loadCount, setLoadCount] = useState(0);

  const fetchRows = useCallback(async () => {
    setLoading(true); setListErr("");
    try {
      const [list, centre] = await Promise.all([
        api.get<Contract[]>(`${API_BASE}/`, {
          params: { search, limit: 500, contract_type: kind || undefined },
        }),
        api.get<ActionCenter>(`${API_BASE}/action-center`),
      ]);
      setRows(list.data);
      setActions(centre.data);
    } catch (e) {
      setListErr(apiError(e));
    } finally {
      setLoading(false);
      setLoadCount((n) => n + 1);
    }
  }, [search, kind]);

  // Match once per page load, so opening the page shows what has actually ticketed
  // rather than the last run's numbers. Silent and non-fatal.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await api.post(`${API_BASE}/match`);
      } catch {
        /* the stored rollup is still shown; the button can retry */
      } finally {
        if (!cancelled) setMatchedOnLoad(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!matchedOnLoad) return;
    const t = setTimeout(fetchRows, 250);
    return () => clearTimeout(t);
  }, [fetchRows, matchedOnLoad]);

  // Runs inside ConfirmDialog: a failure keeps the dialog open with the error shown.
  const remove = async (c: Contract) => {
    await api.delete(`${API_BASE}/${c.id}`);
    setRows((prev) => prev.filter((r) => r.id !== c.id));
    toast.success("Contract deleted");
    fetchRows();
  };

  const runMatch = async () => {
    setMatching(true);
    try {
      const { data } = await api.post<MatchResult>(`${API_BASE}/match`);
      toast.success(
        `Matched ${data.tickets_matched} ticket${data.tickets_matched !== 1 ? "s" : ""} across ` +
        `${data.bookings} PNR${data.bookings !== 1 ? "s" : ""} on ` +
        `${data.contracts} contract${data.contracts !== 1 ? "s" : ""}`,
      );
      fetchRows();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setMatching(false);
    }
  };

  const urgentCount =
    (actions?.overdue.length ?? 0) + (actions?.today.length ?? 0) + (actions?.critical.length ?? 0);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">
            Vendors data
          </p>
          <h1 className="text-xl font-bold text-gray-900">Series / SIT / MICE / Group</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {rows.length} contract{rows.length !== 1 ? "s" : ""} — inventory, money and what is due next
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={runMatch}
            disabled={matching}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${matching ? "animate-spin" : ""}`} />
            Match tickets
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
          >
            <PencilLine className="w-3.5 h-3.5" /> Enter manually
          </button>
          <button
            onClick={() => router.push("/vendors/series-sit-mice/new")}
            className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
          >
            <Sparkles className="w-3.5 h-3.5" /> Upload contract
          </button>
        </div>
      </div>

      <SeriesReminders refreshKey={loadCount} />

      {/* What needs attention. Computed live on every load — there is no background job
          keeping a stored version of this up to date. */}
      {actions && (urgentCount > 0 || actions.below_materialization.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Tile
            icon={<CalendarClock className="w-4 h-4" />}
            tone={actions.overdue.length ? "red" : "amber"}
            value={urgentCount}
            label={actions.overdue.length ? `${actions.overdue.length} overdue, rest due within 3 days` : "due within 3 days"}
            title="Needs attention"
          />
          <Tile
            icon={<Wallet className="w-4 h-4" />}
            tone={actions.total_overdue_amount > 0 ? "red" : "gray"}
            value={inr(actions.total_overdue_amount)}
            label="overdue payments"
            title="Money late"
          />
          <Tile
            icon={<AlertTriangle className="w-4 h-4" />}
            tone={actions.below_materialization.length ? "amber" : "gray"}
            value={actions.below_materialization.length}
            label="departures below the materialisation floor"
            title="Under-materialised"
          />
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Contracts</p>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="ml-2 border border-gray-200 rounded-lg px-2 py-1.5 text-xs bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40"
          >
            <option value="">All types</option>
            {CONTRACT_TYPES.map((t) => (
              <option key={t} value={t}>{CONTRACT_TYPE_LABEL[t]}</option>
            ))}
          </select>
          <div className="relative ml-auto w-64">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Contract no., group, airline…"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-gray-50"
            />
          </div>
          <button
            onClick={fetchRows}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {COLUMNS.map((h, i) => (
                  <th
                    key={i}
                    className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-gray-400">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading contracts…
                </td></tr>
              ) : listErr ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-red-400">{listErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-16 text-center">
                  <div className="flex flex-col items-center justify-center text-center">
                    <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                      <Layers className="w-7 h-7 text-gray-300" />
                    </div>
                    <p className="text-sm font-medium text-gray-600">
                      {search || kind ? "No contracts match that filter" : "No contracts yet"}
                    </p>
                    <p className="text-xs text-gray-400 mt-1 mb-4">
                      Upload the airline&apos;s or supplier&apos;s contract PDF and it is read for you —
                      departures, fare, deposits, deadlines and cancellation terms.
                    </p>
                    {!search && !kind && (
                      <div className="flex gap-2">
                        <button
                          onClick={() => router.push("/vendors/series-sit-mice/new")}
                          className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
                        >
                          <Sparkles className="w-3.5 h-3.5" /> Upload contract
                        </button>
                        <button
                          onClick={() => setShowAdd(true)}
                          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
                        >
                          <PencilLine className="w-3.5 h-3.5" /> Enter manually
                        </button>
                      </div>
                    )}
                  </div>
                </td></tr>
              ) : rows.map((c, idx) => {
                const deadline = c.next_deadline;
                return (
                  <tr
                    key={c.id}
                    onClick={() => router.push(`/vendors/series-sit-mice/${c.id}`)}
                    className={`border-b border-gray-50 hover:bg-blue-50/40 transition-colors cursor-pointer ${
                      idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"
                    }`}
                  >
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800 whitespace-nowrap">
                      {CONTRACT_TYPE_LABEL[c.contract_type ?? ""] ?? c.contract_type ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-[11px] whitespace-nowrap">
                      <span className="font-mono text-gray-700">{c.contract_number ?? "—"}</span>
                      {c.group_name && (
                        <span className="block text-[9px] text-gray-400">{c.group_name}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">
                      {c.agent_name ?? c.airline_name ?? "—"}
                      {c.airline_code && (
                        <span className="block text-[9px] text-gray-400 font-mono">{c.airline_code}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-500 whitespace-nowrap">
                      {c.travel_from ?? "—"}
                      {c.travel_to && c.travel_to !== c.travel_from && (
                        <span className="block text-[9px] text-gray-400">to {c.travel_to}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 tabular-nums">
                      {c.allocations_count}
                    </td>
                    <td className="px-3 py-2 text-[11px] tabular-nums whitespace-nowrap">
                      <span className="font-semibold text-gray-800">{c.seats_ticketed}</span>
                      {c.seats_allocated ? <span className="text-gray-400"> / {c.seats_allocated}</span> : null}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 tabular-nums whitespace-nowrap">
                      {inr(c.contract_cost)}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700 tabular-nums whitespace-nowrap">
                      {inr(c.amount_issued)}
                    </td>
                    {/* Positive is money earned — the sell_reconciliation convention. */}
                    <td className={`px-3 py-2 text-[11px] tabular-nums whitespace-nowrap font-semibold ${
                      c.margin > 0 ? "text-emerald-600" : c.margin < 0 ? "text-red-600" : "text-gray-400"
                    }`}>
                      {inr(c.margin)}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {deadline ? (
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                            URGENCY_STYLE[deadline.urgency ?? "scheduled"]
                          }`}
                          title={deadline.action_required ?? ""}
                        >
                          {DEADLINE_TYPE_LABEL[deadline.deadline_type ?? ""] ?? deadline.deadline_type}
                          <span className="ml-1 font-normal opacity-80">
                            {relativeDays(deadline.days_remaining)}
                          </span>
                        </span>
                      ) : (
                        <span className="text-[11px] text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] tabular-nums whitespace-nowrap">
                      <span className={c.overdue_count ? "text-red-600 font-semibold" : "text-gray-600"}>
                        {inr(c.amount_due)}
                      </span>
                      {c.overdue_count > 0 && (
                        <span className="block text-[9px] text-red-400">
                          {c.overdue_count} overdue
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <div className="flex flex-col gap-0.5">
                        {c.status && (
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border w-fit ${
                            CONTRACT_STATUS_STYLE[c.status] ?? CONTRACT_STATUS_STYLE.draft
                          }`}>
                            {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
                          </span>
                        )}
                        {c.match_status && (
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border w-fit ${
                            MATCH_STATUS_STYLE[c.match_status] ?? MATCH_STATUS_STYLE.pending
                          }`}>
                            {MATCH_STATUS_LABEL[c.match_status] ?? c.match_status}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); setToDelete(c); }}
                        className="p-1.5 hover:bg-red-50 rounded-lg"
                        title="Delete contract"
                      >
                        <Trash2 className="w-3.5 h-3.5 text-red-400" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {rows.length > 0 && (
          <p className="px-4 py-2 text-[10px] text-gray-400 border-t border-gray-100">
            Ticketed, issued and margin are matched from each contract&apos;s PNRs and refresh
            when this page loads and whenever tickets are saved. Deadlines and overdue amounts
            are worked out against today&apos;s date every time you read them.
          </p>
        )}
      </div>

      {toDelete && (
        <ConfirmDialog
          title="Delete contract?"
          confirmLabel="Delete contract"
          onConfirm={() => remove(toDelete)}
          onClose={() => setToDelete(null)}
        >
          <p>
            <span className="font-semibold text-gray-900 font-mono">
              {toDelete.contract_number || toDelete.group_name || `#${toDelete.id}`}
            </span>
            {toDelete.group_name && toDelete.contract_number && <> · {toDelete.group_name}</>}
            {(toDelete.airline_name || toDelete.agent_name) && <> · {toDelete.airline_name || toDelete.agent_name}</>}
          </p>
          <p>
            Its {toDelete.allocations_count} departure{toDelete.allocations_count !== 1 ? "s" : ""}, PNRs,
            passengers, fares, payment schedule, deadlines, terms and uploaded documents are deleted
            with it. This cannot be undone.
          </p>
          {toDelete.amount_due > 0 && (
            <p className="text-amber-700">
              {inr(toDelete.amount_due)} is still outstanding on this contract.
            </p>
          )}
        </ConfirmDialog>
      )}

      {showAdd && (
        <ContractWizard
          onClose={() => setShowAdd(false)}
          onSaved={(id) => { setShowAdd(false); router.push(`/vendors/series-sit-mice/${id}`); }}
        />
      )}
    </div>
  );
}

function Tile({
  icon, value, label, title, tone,
}: {
  icon: React.ReactNode;
  value: React.ReactNode;
  label: string;
  title: string;
  tone: "red" | "amber" | "gray";
}) {
  const tones = {
    red: "border-red-100 bg-red-50/40 text-red-600",
    amber: "border-amber-100 bg-amber-50/40 text-amber-600",
    gray: "border-gray-100 bg-white text-gray-400",
  };
  return (
    <div className={`rounded-xl border shadow-sm px-4 py-3 ${tones[tone]}`}>
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <p className="text-[10px] font-semibold uppercase tracking-wide">{title}</p>
      </div>
      <p className="text-lg font-bold text-gray-900 tabular-nums">{value}</p>
      <p className="text-[10px] text-gray-400">{label}</p>
    </div>
  );
}
