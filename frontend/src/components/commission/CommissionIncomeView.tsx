"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  RefreshCw, Calculator, Clock, CheckCircle2, XCircle, MinusCircle, AlertTriangle,
} from "lucide-react";
import api from "@/lib/api";
import type { CommissionSource } from "@/lib/commissionSources";
import CommissionStatementDetail from "./CommissionStatementDetail";
import { CommissionStatement, inr } from "./types";

const RUNNING = ["queued", "processing"];

function StatusBadge({ s }: { s: CommissionStatement }) {
  const map: Record<string, { cls: string; icon: React.ReactNode; label: string }> = {
    completed:  { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", icon: <CheckCircle2 className="w-3 h-3" />, label: "Calculated" },
    processing: { cls: "bg-blue-50 text-blue-700 border-blue-200",          icon: <Clock className="w-3 h-3" />,       label: `Running ${s.progress_pct}%` },
    queued:     { cls: "bg-blue-50 text-blue-700 border-blue-200",          icon: <Clock className="w-3 h-3" />,       label: "Queued" },
    failed:     { cls: "bg-red-50 text-red-700 border-red-200",             icon: <XCircle className="w-3 h-3" />,     label: "Failed" },
    idle:       { cls: "bg-slate-100 text-slate-500 border-slate-200",      icon: <MinusCircle className="w-3 h-3" />, label: "Not run" },
  };
  const m = map[s.status] ?? map.idle;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${m.cls}`}>
      {m.icon} {m.label}
    </span>
  );
}

export default function CommissionIncomeView({ source }: { source: CommissionSource }) {
  const [statements, setStatements] = useState<CommissionStatement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CommissionStatement | null>(null);

  const fetchStatements = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<CommissionStatement[]>(`${source.apiBase}/statements`);
      setStatements(data);
    } catch { setError(`Failed to load ${source.statementNoun}s.`); }
    finally { setLoading(false); }
  }, [source]);
  useEffect(() => { fetchStatements(); }, [fetchStatements]);

  // Keep the list live while any statement is calculating.
  useEffect(() => {
    if (!statements.some((s) => RUNNING.includes(s.status))) return;
    const t = setInterval(fetchStatements, 4000);
    return () => clearInterval(t);
  }, [statements, fetchStatements]);

  if (selected) {
    return (
      <CommissionStatementDetail
        source={source}
        statement={selected}
        onBack={() => { setSelected(null); fetchStatements(); }}
      />
    );
  }

  // Statement · [Agency|Airline] · Period · Rows · Status · Matched · [Needs TGQ] ·
  // Unmatched · IATA · Estimated · [Variance] · Actions. Computed, because the two
  // literals this replaced had to be re-counted by hand every time a column moved.
  const cols = 10 + (source.showsEnrichment ? 1 : 0) + (source.showsVariance ? 1 : 0);

  return (
    <div>
      <div className="flex items-center justify-end mb-3">
        <button onClick={fetchStatements}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400 whitespace-nowrap">
                <th className="text-left px-3 py-2.5 font-semibold">Statement</th>
                <th className="text-left px-3 py-2.5 font-semibold">
                  {source.showsAgency ? "Agency" : "Airline"}
                </th>
                <th className="text-left px-3 py-2.5 font-semibold">Period</th>
                <th className="text-right px-3 py-2.5 font-semibold">Rows</th>
                <th className="text-center px-3 py-2.5 font-semibold">Status</th>
                <th className="text-right px-3 py-2.5 font-semibold">Matched</th>
                {/* Without this the biggest population on a BSP statement is invisible
                    from the picker: 9,021 rows that matched a deal but could not be
                    verified read as neither matched nor unmatched. */}
                {source.showsEnrichment && (
                  <th className="text-right px-3 py-2.5 font-semibold text-amber-700">Needs TGQ</th>
                )}
                <th className="text-right px-3 py-2.5 font-semibold">Unmatched</th>
                <th className="text-right px-3 py-2.5 font-semibold text-teal-600">IATA comm</th>
                <th className="text-right px-3 py-2.5 font-semibold text-emerald-700">Estimated commission</th>
                {source.showsVariance && (
                  <th className="text-right px-3 py-2.5 font-semibold text-amber-700"
                      title="What your deals say you should have earned, minus what the consolidator actually paid. Positive means they owe you.">
                    Variance
                  </th>
                )}
                <th className="text-right px-3 py-2.5 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={cols} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={cols} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : statements.length === 0 ? (
                <tr><td colSpan={cols} className="px-3 py-12 text-center text-sm text-slate-400">
                  No {source.statementNoun}s yet — upload one under{" "}
                  <Link href={source.uploadHref} className="text-blue-600 hover:underline">
                    {source.uploadLabel}
                  </Link>{" "}first.
                </td></tr>
              ) : statements.map((s) => (
                <tr key={s.batch_id} className="border-b border-slate-100 hover:bg-slate-50/60 whitespace-nowrap">
                  <td className="px-3 py-2 text-slate-700 font-medium max-w-[260px] truncate" title={s.statement_name || s.batch_id}>
                    {s.statement_name || s.batch_id}
                    {s.parse_status !== "completed" && (
                      <span className="ml-2 text-[10px] text-orange-500">parsing {s.parse_status}</span>
                    )}
                  </td>
                  {source.showsAgency ? (
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {s.supplier_name ? (
                        <>
                          {s.supplier_name}
                          {(s.supplier_branch || s.supplier_code) && (
                            <span className="text-slate-400">
                              {" · "}{[s.supplier_branch, s.supplier_code].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </>
                      ) : (
                        // Listed but not runnable: with no consolidator there is no B2B
                        // deal to price it against, and saying so here beats failing later.
                        <span className="inline-flex items-center gap-1 text-amber-600"
                              title={s.blocked_reason ?? undefined}>
                          <AlertTriangle className="w-3 h-3" /> No agency
                        </span>
                      )}
                    </td>
                  ) : (
                    <td className="px-3 py-2 text-xs text-slate-600">{s.airline_name || s.airline_code || "—"}</td>
                  )}
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {s.period_from || "—"}{s.period_to ? ` → ${s.period_to}` : ""}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600">{s.row_count.toLocaleString("en-IN")}</td>
                  <td className="px-3 py-2 text-center"><StatusBadge s={s} /></td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600">{s.matched_rows.toLocaleString("en-IN")}</td>
                  {source.showsEnrichment && (
                    <td
                      className="px-3 py-2 text-right tabular-nums text-amber-700"
                      title="Matched a deal, but it pays only on a cabin class, travel window or route this statement does not print — upload the matching TGQ HMPR and re-run."
                    >
                      {s.needs_data_rows.toLocaleString("en-IN")}
                    </td>
                  )}
                  <td className="px-3 py-2 text-right tabular-nums text-orange-600">{(s.unmatched_rows + s.needs_data_rows).toLocaleString("en-IN")}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-teal-700">
                    {s.iata_total != null ? `₹${inr(s.iata_total)}` : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-emerald-700">
                    {s.total_incentive != null ? `₹${inr(s.total_incentive)}` : <span className="text-slate-300">—</span>}
                  </td>
                  {source.showsVariance && (
                    <td className="px-3 py-2 text-right tabular-nums font-semibold">
                      {s.variance_total == null ? <span className="text-slate-300">—</span>
                        : s.variance_total > 0
                          ? <span className="text-amber-700" title="They paid you less than your deals say">
                              ₹{inr(s.variance_total)}
                            </span>
                          : s.variance_total < 0
                            ? <span className="text-slate-500" title="They paid you more than your deals say">
                                −₹{inr(Math.abs(s.variance_total))}
                              </span>
                            : <span className="text-slate-400">₹0.00</span>}
                    </td>
                  )}
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => setSelected(s)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline">
                      <Calculator className="w-3.5 h-3.5" /> Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
