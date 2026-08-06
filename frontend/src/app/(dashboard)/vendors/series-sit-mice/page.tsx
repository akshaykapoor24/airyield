"use client";

import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Edit2, Layers, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import ContractModal, { type Contract } from "@/components/vendors/ContractModal";

const inr = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Colour the status so the list answers "where does this contract stand" at a glance. */
const STATUS_STYLE: Record<string, string> = {
  pending:     "bg-gray-50 text-gray-500 border-gray-200",
  partial:     "bg-amber-50 text-amber-700 border-amber-200",
  complete:    "bg-emerald-50 text-emerald-700 border-emerald-200",
  over_issued: "bg-red-50 text-red-700 border-red-200",
};
const STATUS_LABEL: Record<string, string> = {
  pending: "Pending", partial: "Partial", complete: "Complete", over_issued: "Over-issued",
};

const COLUMNS = [
  "TYPE", "AGENT", "AIRLINE", "PNR", "PAX", "TRAVEL", "TOTAL FARE",
  "TICKETS ISSUED", "TICKET NUMBERS", "AMOUNT ISSUED", "STATUS", "ACTIONS",
];

export default function SeriesSitMicePage() {
  const [rows, setRows] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  const [search, setSearch] = useState("");
  const [matching, setMatching] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<Contract | null>(null);
  // Gates the first list load behind the automatic match, so the page never
  // renders figures it is about to replace a moment later.
  const [matchedOnLoad, setMatchedOnLoad] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setListErr("");
    try {
      const { data } = await api.get<Contract[]>("/series-contracts/", { params: { search, limit: 500 } });
      setRows(data);
    } catch (e) {
      setListErr(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [search]);

  // Match once per page load, so opening the page always shows what has actually
  // ticketed rather than the last run's numbers. Silent and non-fatal: if it
  // fails the list still loads, and the Match tickets button is always there.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await api.post("/series-contracts/match");
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

  const remove = async (c: Contract) => {
    if (!confirm(`Delete the contract on PNR ${c.pnr_no}? This cannot be undone.`)) return;
    try {
      await api.delete(`/series-contracts/${c.id}`);
      setRows((prev) => prev.filter((r) => r.id !== c.id));
      toast.success("Contract deleted");
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const runMatch = async () => {
    setMatching(true);
    try {
      const { data } = await api.post<{ contracts: number; tickets_matched: number }>("/series-contracts/match");
      toast.success(
        `Matched ${data.tickets_matched} ticket${data.tickets_matched !== 1 ? "s" : ""} across ` +
        `${data.contracts} contract${data.contracts !== 1 ? "s" : ""}`,
      );
      fetchRows();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setMatching(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Vendors data</p>
          <h1 className="text-xl font-bold text-gray-900">Series / SIT / MICE</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {rows.length} block booking{rows.length !== 1 ? "s" : ""} — and how much of each has actually ticketed
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
            className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Contract
          </button>
        </div>
      </div>

      {/* contracts */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Series Contract</p>
          <div className="relative ml-auto w-64">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="PNR, agent, airline…"
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
                  <th key={i} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
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
                      {search ? "No contracts match that search" : "No contracts yet"}
                    </p>
                    <p className="text-xs text-gray-400 mt-1 mb-4">
                      Record a block booking — tickets issued on its PNR will roll up here.
                    </p>
                    {!search && (
                      <button
                        onClick={() => setShowAdd(true)}
                        className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
                      >
                        <Plus className="w-3.5 h-3.5" /> Add Contract
                      </button>
                    )}
                  </div>
                </td></tr>
              ) : rows.map((c, idx) => {
                const numbers = c.ticket_numbers ?? [];
                return (
                  <tr
                    key={c.id}
                    className={`border-b border-gray-50 hover:bg-blue-50/40 transition-colors ${
                      idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"
                    }`}
                  >
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{c.contract_type ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">
                      {c.agent_name ?? "—"}
                      {c.agent_type && <span className="block text-[9px] text-gray-400 uppercase">{c.agent_type}</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap">
                      {c.airline_code && <span className="font-mono text-gray-500 mr-1">{c.airline_code}</span>}
                      {c.airline_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-700">{c.pnr_no ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 tabular-nums">{c.pax_count ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500 whitespace-nowrap">
                      {c.date_of_travel ?? "—"}
                      {c.trip_type && (
                        <span className="block text-[9px] text-gray-400">
                          {c.trip_type === "RETURN" ? "Return" : "One way"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700 tabular-nums whitespace-nowrap">{inr(c.total_fare)}</td>
                    <td className="px-3 py-2 text-[11px] tabular-nums">
                      <span className="font-semibold text-gray-800">{c.tickets_issued}</span>
                      {c.pax_count ? <span className="text-gray-400"> / {c.pax_count}</span> : null}
                    </td>
                    <td className="px-3 py-2 min-w-[170px]">
                      {numbers.length === 0 ? (
                        <span className="text-[11px] text-gray-300">—</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {numbers.slice(0, 3).map((n) => (
                            <span key={n} className="inline-flex px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px] font-mono whitespace-nowrap">
                              {n}
                            </span>
                          ))}
                          {numbers.length > 3 && (
                            <span
                              className="inline-flex px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px] font-semibold"
                              title={numbers.join(", ")}
                            >
                              +{numbers.length - 3}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700 tabular-nums whitespace-nowrap">{inr(c.amount_issued)}</td>
                    <td className="px-3 py-2">
                      {c.match_status && (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                          STATUS_STYLE[c.match_status] ?? STATUS_STYLE.pending
                        }`}>
                          {STATUS_LABEL[c.match_status] ?? c.match_status}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditTarget(c)}
                          className="p-1.5 hover:bg-blue-50 rounded-lg"
                          title="Edit contract"
                        >
                          <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                        </button>
                        <button
                          onClick={() => remove(c)}
                          className="p-1.5 hover:bg-red-50 rounded-lg"
                          title="Delete contract"
                        >
                          <Trash2 className="w-3.5 h-3.5 text-red-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {rows.length > 0 && (
          <p className="px-4 py-2 text-[10px] text-gray-400 border-t border-gray-100">
            Tickets issued, ticket numbers and amount issued are matched from the contract&apos;s PNR. They
            refresh when this page loads and whenever tickets are saved — or press Match tickets to re-run now.
          </p>
        )}
      </div>

      {showAdd && (
        <ContractModal onClose={() => setShowAdd(false)} onSaved={fetchRows} />
      )}
      {editTarget && (
        <ContractModal contract={editTarget} onClose={() => setEditTarget(null)} onSaved={fetchRows} />
      )}
    </div>
  );
}
