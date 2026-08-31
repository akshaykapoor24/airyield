"use client";

import Link from "next/link";
import { ExternalLink, X } from "lucide-react";
import StatusBadge from "@/components/dashboard/StatusBadge";
import { STATUS, type AccrualRow } from "@/lib/accrual";
import { inr, monthLabel, pct, rupees } from "@/lib/money";

/**
 * Why this row produced this number.
 *
 * The grid shows the answer; this shows the working — month by month, with the
 * deflator and rate that were applied and where each came from. Without it a
 * disputed accrual means re-deriving the arithmetic by hand, which is exactly the
 * situation the spreadsheet leaves people in.
 */
export default function AccrualRowDrawer({
  row,
  months,
  periodLabel,
  onClose,
}: {
  row: AccrualRow;
  months: string[];
  periodLabel: string;
  onClose: () => void;
}) {
  const SRC: Record<string, string> = {
    derived: "from statements",
    manual: "typed in",
    pooled: "not attributed",
    none: "no data",
  };

  return (
    <>
      <div
        className="fixed inset-0 bg-slate-900/20 z-40"
        onClick={onClose}
        aria-hidden
      />
      <aside className="fixed right-0 top-0 h-screen w-full max-w-lg bg-white z-50 shadow-2xl flex flex-col">
        <header className="px-5 py-4 border-b border-gray-100 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
              {periodLabel} · {row.deal_no ?? "No deal"}
            </p>
            <h2 className="text-lg font-bold text-gray-900 truncate">{row.airline_name}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {[row.entity, row.channel, row.lob].filter(Boolean).join(" · ")} ·{" "}
              {row.plb_period_label}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 shrink-0"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200 p-4">
            <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
              PLB accrued
            </p>
            <p className="text-3xl font-semibold text-gray-900 mt-1">{rupees(row.accrual)}</p>
            <p className="text-xs text-gray-500 mt-2">
              {rupees(row.flown_total)} flown × {pct(row.deflator_pct)} deflator ×{" "}
              {pct(row.plb_rate_pct)} rate
            </p>
            {row.accrual_at_risk !== 0 && (
              <p className="text-xs text-red-700 mt-2 font-medium">
                {rupees(Math.abs(row.accrual_at_risk))} of this rests on months the PLB period
                does not cover.
              </p>
            )}
          </div>

          {row.status_flags.filter((f) => f !== "OK").length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
                Needs attention
              </h3>
              <ul className="space-y-2">
                {row.status_flags.filter((f) => f !== "OK").map((f, i) => (
                  <li key={f} className="flex gap-2.5 items-start">
                    <StatusBadge code={f} />
                    <p className="text-xs text-gray-600 flex-1">
                      {row.reasons[i] ?? STATUS[f].blurb}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
              Month by month
            </h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="text-left pb-1.5 font-semibold">Month</th>
                  <th className="text-right pb-1.5 font-semibold">Flown</th>
                  <th className="text-right pb-1.5 font-semibold">Deflator</th>
                  <th className="text-right pb-1.5 font-semibold">Commissionable</th>
                  <th className="text-right pb-1.5 font-semibold">Accrued</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {months.map((ym) => {
                  const c = row.months[ym];
                  if (!c) return null;
                  return (
                    <tr key={ym} className={c.in_period ? "" : "bg-red-50/40"}>
                      <td className="py-1.5">
                        <span className="font-medium text-gray-800">{monthLabel(ym)}</span>
                        <span className="block text-[10px] text-gray-400">
                          {SRC[c.source]}
                          {c.source === "derived" && (c.confirmed ? " · confirmed" : " · provisional")}
                          {!c.in_period && " · outside period"}
                        </span>
                      </td>
                      <td className="text-right tabular-nums text-gray-700">{inr(c.flown)}</td>
                      <td className="text-right tabular-nums text-gray-500">
                        {c.deflator_pct.toFixed(2)}%
                      </td>
                      <td className="text-right tabular-nums text-gray-700">
                        {inr(c.commissionable)}
                      </td>
                      <td className="text-right tabular-nums font-semibold text-gray-900">
                        {inr((c.commissionable * row.plb_rate_pct) / 100)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section>
            <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
              How the rate was resolved
            </h3>
            <p className="text-xs text-gray-600 bg-gray-50 rounded-lg p-3 ring-1 ring-gray-100">
              {row.plb_rate_explain || "—"}
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3 text-xs">
              <div>
                <dt className="text-gray-400">Commission base</dt>
                <dd className="text-gray-800 font-medium">{row.basis_label}</dd>
              </div>
              <div>
                <dt className="text-gray-400">Deflator source</dt>
                <dd className="text-gray-800 font-medium capitalize">{row.deflator_source}</dd>
              </div>
              <div>
                <dt className="text-gray-400">Rate source</dt>
                <dd className="text-gray-800 font-medium capitalize">{row.plb_rate_source}</dd>
              </div>
              <div>
                <dt className="text-gray-400">Airline confirmed through</dt>
                <dd className="text-gray-800 font-medium">
                  {row.flown_confirmed_through
                    ? monthLabel(row.flown_confirmed_through.slice(0, 7))
                    : "not set"}
                </dd>
              </div>
            </dl>
          </section>
        </div>

        {row.deal_id != null && (
          <footer className="px-5 py-3 border-t border-gray-100 flex gap-2">
            <Link
              href={`/deals?search=${encodeURIComponent(row.airline_name)}`}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#1e3a5f] hover:underline"
            >
              Open the deal <ExternalLink className="w-3 h-3" aria-hidden />
            </Link>
            <Link
              href="/vendors/statements"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#1e3a5f] hover:underline ml-4"
            >
              Source statements <ExternalLink className="w-3 h-3" aria-hidden />
            </Link>
          </footer>
        )}
      </aside>
    </>
  );
}
