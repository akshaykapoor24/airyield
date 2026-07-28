"use client";

import { CheckCircle2, XCircle } from "lucide-react";

type Line = {
  line: string;
  summary: number | string | null;
  detail: number | string | null;
  variance: number | string | null;
  ok: boolean;
};

const LABELS: Record<string, string> = {
  issues: "Issues",
  refunds: "Refunds",
  debit_memos: "Debit Memos",
  credit_memos: "Credit Memos",
  std_comm: "STD Commission",
  sup_comm: "SUP Commission",
  tax_on_comm: "Tax on Commission",
  balance_payable: "Balance Payable",
};

function inr(v: number | string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export default function BspComparisonPanel({
  matchStatus,
  lines,
}: {
  matchStatus: string;
  lines: Line[];
}) {
  const matched = matchStatus === "matched";
  return (
    <div>
      {/* Verdict */}
      <div
        className={`flex items-center gap-3 rounded-xl border px-4 py-3 mb-4 ${
          matched
            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
            : "border-red-200 bg-red-50 text-red-700"
        }`}
      >
        {matched ? <CheckCircle2 className="w-6 h-6" /> : <XCircle className="w-6 h-6" />}
        <div>
          <p className="text-sm font-bold">{matched ? "MATCHED" : "MISMATCH"}</p>
          <p className="text-xs opacity-80">
            {matched
              ? "Every grand-total line ties between the summary and the detailed statement."
              : "One or more grand-total lines differ — the detailed data was saved and flagged for review."}
          </p>
        </div>
      </div>

      {/* Per-line table */}
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
              <th className="text-left px-3 py-2 font-semibold">Line</th>
              <th className="text-right px-3 py-2 font-semibold">Summary</th>
              <th className="text-right px-3 py-2 font-semibold">Detailed</th>
              <th className="text-right px-3 py-2 font-semibold">Variance</th>
              <th className="text-center px-3 py-2 font-semibold">Match</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const anchor = l.line === "balance_payable";
              return (
                <tr key={l.line} className={`border-b border-slate-100 last:border-0 ${anchor ? "bg-blue-50/40 font-semibold" : ""}`}>
                  <td className="px-3 py-2 text-slate-700">{LABELS[l.line] ?? l.line}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">{inr(l.summary)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">{inr(l.detail)}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${l.ok ? "text-slate-400" : "text-red-600 font-semibold"}`}>
                    {inr(l.variance)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {l.ok ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 inline" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-500 inline" />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
