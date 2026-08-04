"use client";

import { AlertCircle, RefreshCw, Split } from "lucide-react";
import { inr, type TicketRow } from "@/lib/ticketFields";

const MONEY_COLS: { key: keyof TicketRow; label: string }[] = [
  { key: "sell_fare",   label: "Sell Fare" },
  { key: "sell_tax",    label: "Sell Tax" },
  { key: "sell_tax_yq", label: "Tax YQ" },
  { key: "sale_yr",     label: "Sale YR" },
];

/**
 * Shows what the server will actually save for the ticket being punched.
 *
 * A multi-sector B2B ticket is stored as one row per leg with the fare columns
 * divided, so "one ticket" and "one row" are not the same thing. Surfacing that
 * before saving is the whole point — the upload flow shows it in the review grid,
 * and manual entry would otherwise have no equivalent.
 */
export default function LegPreview({
  rows, original, loading, error,
}: {
  rows: TicketRow[];
  /** Pre-split values, for showing what each leg was divided from. */
  original: Partial<Record<keyof TicketRow, number | null>>;
  loading?: boolean;
  error?: string | null;
}) {
  if (error) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-[11px] text-red-700">
        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
        {error}
      </div>
    );
  }

  if (rows.length === 0) return null;

  if (rows.length === 1) {
    return (
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 border border-gray-200 text-[11px] text-gray-500 ${loading ? "opacity-50" : ""}`}>
        {loading
          ? <RefreshCw className="w-3.5 h-3.5 shrink-0 animate-spin text-blue-400" />
          : <span className="w-1.5 h-1.5 rounded-full bg-gray-300 shrink-0" />}
        Single leg — saved as 1 row.
      </div>
    );
  }

  const n = rows.length;

  return (
    <div className={`rounded-lg border border-amber-200 bg-amber-50/60 overflow-hidden transition-opacity ${loading ? "opacity-50" : ""}`}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-amber-200">
        {loading
          ? <RefreshCw className="w-3.5 h-3.5 text-amber-600 shrink-0 animate-spin" />
          : <Split className="w-3.5 h-3.5 text-amber-600 shrink-0" />}
        <p className="text-[11px] font-semibold text-amber-800">
          Multi-sector — this ticket will be saved as {n} rows
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse">
          <thead>
            <tr className="border-b border-amber-200/70">
              <th className="px-3 py-1.5 text-left text-[10px] font-semibold text-amber-700 uppercase tracking-wide">Leg</th>
              <th className="px-3 py-1.5 text-left text-[10px] font-semibold text-amber-700 uppercase tracking-wide">Sector</th>
              <th className="px-3 py-1.5 text-left text-[10px] font-semibold text-amber-700 uppercase tracking-wide">Class</th>
              {MONEY_COLS.map((c) => (
                <th key={c.key} className="px-3 py-1.5 text-right text-[10px] font-semibold text-amber-700 uppercase tracking-wide">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-amber-100/70 last:border-0">
                <td className="px-3 py-1.5 text-[11px] text-amber-700/70">{i + 1}</td>
                <td className="px-3 py-1.5 text-[11px] font-medium text-gray-800 font-mono">{r.sector ?? "—"}</td>
                <td className="px-3 py-1.5 text-[11px] text-gray-700">{r.booking_class ?? <span className="text-gray-300">—</span>}</td>
                {MONEY_COLS.map((c) => {
                  const v = r[c.key] as number | null | undefined;
                  const from = original[c.key];
                  return (
                    <td key={c.key} className="px-3 py-1.5 text-right whitespace-nowrap">
                      <span className="text-[11px] font-medium text-gray-800 tabular-nums">{inr(v)}</span>
                      {v != null && from != null && (
                        <span className="block text-[9px] text-gray-400 tabular-nums">from {inr(from)}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="px-3 py-1.5 text-[10px] text-amber-700/80 border-t border-amber-200/70">
        Sell fare, sell tax, tax YQ and sale YR are divided by {n} and rounded to 2 decimals,
        so the legs may not re-sum to the original to the paisa.
      </p>
    </div>
  );
}
